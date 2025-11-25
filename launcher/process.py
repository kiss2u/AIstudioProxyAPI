import os
import sys
import time
import signal
import subprocess
import threading
import queue
import logging
from launcher.config import PYTHON_EXECUTABLE, ENDPOINT_CAPTURE_TIMEOUT, ws_regex

logger = logging.getLogger("CamoufoxLauncher")

def _enqueue_output(stream, stream_name, output_queue, process_pid_for_log="<未知PID>"):
    log_prefix = f"[读取线程-{stream_name}-PID:{process_pid_for_log}]"
    try:
        for line_bytes in iter(stream.readline, b''):
            if not line_bytes:
                break
            try:
                line_str = line_bytes.decode('utf-8', errors='replace')
                output_queue.put((stream_name, line_str))
            except Exception as decode_err:
                logger.warning(f"{log_prefix} 解码错误: {decode_err}。原始数据 (前100字节): {line_bytes[:100]}")
                output_queue.put((stream_name, f"[解码错误: {decode_err}] {line_bytes[:100]}...\n"))
    except ValueError:
        logger.debug(f"{log_prefix} ValueError (流可能已关闭)。")
    except Exception as e:
        logger.error(f"{log_prefix} 读取流时发生意外错误: {e}", exc_info=True)
    finally:
        output_queue.put((stream_name, None))
        if hasattr(stream, 'close') and not stream.closed:
            try:
                stream.close()
            except Exception:
                pass
        logger.debug(f"{log_prefix} 线程退出。")

class CamoufoxProcessManager:
    def __init__(self):
        self.camoufox_proc = None
        self.captured_ws_endpoint = None

    def start(self, final_launch_mode, effective_active_auth_json_path, simulated_os_for_camoufox, args):
        # 构建 Camoufox 内部启动命令 (from dev)
        camoufox_internal_cmd_args = [
            PYTHON_EXECUTABLE, '-u', sys.argv[0], # Use sys.argv[0] to refer to the main script
            '--internal-launch-mode', final_launch_mode
        ]
        if effective_active_auth_json_path:
            camoufox_internal_cmd_args.extend(['--internal-auth-file', effective_active_auth_json_path])

        camoufox_internal_cmd_args.extend(['--internal-camoufox-os', simulated_os_for_camoufox])
        camoufox_internal_cmd_args.extend(['--internal-camoufox-port', str(args.camoufox_debug_port)])

        # 修复：传递代理参数到内部Camoufox进程
        if args.internal_camoufox_proxy is not None:
            camoufox_internal_cmd_args.extend(['--internal-camoufox-proxy', args.internal_camoufox_proxy])

        camoufox_popen_kwargs = {'stdout': subprocess.PIPE, 'stderr': subprocess.PIPE, 'env': os.environ.copy()}
        camoufox_popen_kwargs['env']['PYTHONIOENCODING'] = 'utf-8'
        if sys.platform != "win32" and final_launch_mode != 'debug':
            camoufox_popen_kwargs['start_new_session'] = True
        elif sys.platform == "win32" and (final_launch_mode == 'headless' or final_launch_mode == 'virtual_headless'):
             camoufox_popen_kwargs['creationflags'] = subprocess.CREATE_NO_WINDOW


        try:
            logger.info(f"  将执行 Camoufox 内部启动命令: {' '.join(camoufox_internal_cmd_args)}")
            self.camoufox_proc = subprocess.Popen(camoufox_internal_cmd_args, **camoufox_popen_kwargs)
            logger.info(f"  Camoufox 内部进程已启动 (PID: {self.camoufox_proc.pid})。正在等待 WebSocket 端点输出 (最长 {ENDPOINT_CAPTURE_TIMEOUT} 秒)...")

            camoufox_output_q = queue.Queue()
            camoufox_stdout_reader = threading.Thread(target=_enqueue_output, args=(self.camoufox_proc.stdout, "stdout", camoufox_output_q, self.camoufox_proc.pid), daemon=True)
            camoufox_stderr_reader = threading.Thread(target=_enqueue_output, args=(self.camoufox_proc.stderr, "stderr", camoufox_output_q, self.camoufox_proc.pid), daemon=True)
            camoufox_stdout_reader.start()
            camoufox_stderr_reader.start()

            ws_capture_start_time = time.time()
            camoufox_ended_streams_count = 0
            while time.time() - ws_capture_start_time < ENDPOINT_CAPTURE_TIMEOUT:
                if self.camoufox_proc.poll() is not None:
                    logger.error(f"  Camoufox 内部进程 (PID: {self.camoufox_proc.pid}) 在等待 WebSocket 端点期间已意外退出，退出码: {self.camoufox_proc.poll()}。")
                    break
                try:
                    stream_name, line_from_camoufox = camoufox_output_q.get(timeout=0.2)
                    if line_from_camoufox is None:
                        camoufox_ended_streams_count += 1
                        logger.debug(f"  [InternalCamoufox-{stream_name}-PID:{self.camoufox_proc.pid}] 输出流已关闭 (EOF)。")
                        if camoufox_ended_streams_count >= 2:
                            logger.info(f"  Camoufox 内部进程 (PID: {self.camoufox_proc.pid}) 的所有输出流均已关闭。")
                            break
                        continue

                    log_line_content = f"[InternalCamoufox-{stream_name}-PID:{self.camoufox_proc.pid}]: {line_from_camoufox.rstrip()}"
                    if stream_name == "stderr" or "ERROR" in line_from_camoufox.upper() or "❌" in line_from_camoufox:
                        logger.warning(log_line_content)
                    else:
                        logger.info(log_line_content)

                    ws_match = ws_regex.search(line_from_camoufox)
                    if ws_match:
                        self.captured_ws_endpoint = ws_match.group(1)
                        logger.info(f"  ✅ 成功从 Camoufox 内部进程捕获到 WebSocket 端点: {self.captured_ws_endpoint[:40]}...")
                        break
                except queue.Empty:
                    continue

            if camoufox_stdout_reader.is_alive(): camoufox_stdout_reader.join(timeout=1.0)
            if camoufox_stderr_reader.is_alive(): camoufox_stderr_reader.join(timeout=1.0)

            if not self.captured_ws_endpoint and (self.camoufox_proc and self.camoufox_proc.poll() is None):
                logger.error(f"  ❌ 未能在 {ENDPOINT_CAPTURE_TIMEOUT} 秒内从 Camoufox 内部进程 (PID: {self.camoufox_proc.pid}) 捕获到 WebSocket 端点。")
                logger.error("  Camoufox 内部进程仍在运行，但未输出预期的 WebSocket 端点。请检查其日志或行为。")
                self.cleanup()
                sys.exit(1)
            elif not self.captured_ws_endpoint and (self.camoufox_proc and self.camoufox_proc.poll() is not None):
                logger.error(f"  ❌ Camoufox 内部进程已退出，且未能捕获到 WebSocket 端点。")
                sys.exit(1)
            elif not self.captured_ws_endpoint:
                logger.error(f"  ❌ 未能捕获到 WebSocket 端点。")
                sys.exit(1)

        except Exception as e_launch_camoufox_internal:
            logger.critical(f"  ❌ 在内部启动 Camoufox 或捕获其 WebSocket 端点时发生致命错误: {e_launch_camoufox_internal}", exc_info=True)
            self.cleanup()
            sys.exit(1)
        
        return self.captured_ws_endpoint

    def cleanup(self):
        logger.info("--- 开始执行清理程序 (CamoufoxProcessManager) ---")
        if self.camoufox_proc and self.camoufox_proc.poll() is None:
            pid = self.camoufox_proc.pid
            logger.info(f"正在终止 Camoufox 内部子进程 (PID: {pid})...")
            try:
                if sys.platform != "win32" and hasattr(os, 'getpgid') and hasattr(os, 'killpg'):
                    try:
                        pgid = os.getpgid(pid)
                        logger.info(f"  向 Camoufox 进程组 (PGID: {pgid}) 发送 SIGTERM 信号...")
                        os.killpg(pgid, signal.SIGTERM)
                    except ProcessLookupError:
                        logger.info(f"  Camoufox 进程组 (PID: {pid}) 未找到，尝试直接终止进程...")
                        self.camoufox_proc.terminate()
                else:
                    if sys.platform == "win32":
                        logger.info(f"进程树 (PID: {pid}) 发送终止请求")
                        subprocess.call(['taskkill', '/T', '/PID', str(pid)])
                    else:
                        logger.info(f"  向 Camoufox (PID: {pid}) 发送 SIGTERM 信号...")
                        self.camoufox_proc.terminate()
                self.camoufox_proc.wait(timeout=5)
                logger.info(f"  ✓ Camoufox (PID: {pid}) 已通过 SIGTERM 成功终止。")
            except subprocess.TimeoutExpired:
                logger.warning(f"  ⚠️ Camoufox (PID: {pid}) SIGTERM 超时。正在发送 SIGKILL 强制终止...")
                if sys.platform != "win32" and hasattr(os, 'getpgid') and hasattr(os, 'killpg'):
                    try:
                        pgid = os.getpgid(pid)
                        logger.info(f"  向 Camoufox 进程组 (PGID: {pgid}) 发送 SIGKILL 信号...")
                        os.killpg(pgid, signal.SIGKILL)
                    except ProcessLookupError:
                        logger.info(f"  Camoufox 进程组 (PID: {pid}) 在 SIGKILL 时未找到，尝试直接强制终止...")
                        self.camoufox_proc.kill()
                else:
                    if sys.platform == "win32":
                        logger.info(f"  强制杀死 Camoufox 进程树 (PID: {pid})")
                        subprocess.call(['taskkill', '/F', '/T', '/PID', str(pid)])
                    else:
                        self.camoufox_proc.kill()
                try:
                    self.camoufox_proc.wait(timeout=2)
                    logger.info(f"  ✓ Camoufox (PID: {pid}) 已通过 SIGKILL 成功终止。")
                except Exception as e_kill:
                    logger.error(f"  ❌ 等待 Camoufox (PID: {pid}) SIGKILL 完成时出错: {e_kill}")
            except Exception as e_term:
                logger.error(f"  ❌ 终止 Camoufox (PID: {pid}) 时发生错误: {e_term}", exc_info=True)
            finally:
                if hasattr(self.camoufox_proc, 'stdout') and self.camoufox_proc.stdout and not self.camoufox_proc.stdout.closed:
                    self.camoufox_proc.stdout.close()
                if hasattr(self.camoufox_proc, 'stderr') and self.camoufox_proc.stderr and not self.camoufox_proc.stderr.closed:
                    self.camoufox_proc.stderr.close()
            self.camoufox_proc = None
        elif self.camoufox_proc:
            logger.info(f"Camoufox 内部子进程 (PID: {self.camoufox_proc.pid if hasattr(self.camoufox_proc, 'pid') else 'N/A'}) 先前已自行结束，退出码: {self.camoufox_proc.poll()}。")
            self.camoufox_proc = None
        else:
            logger.info("Camoufox 内部子进程未运行或已清理。")
        logger.info("--- 清理程序执行完毕 (CamoufoxProcessManager) ---")