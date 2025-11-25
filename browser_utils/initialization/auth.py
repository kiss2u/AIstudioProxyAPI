# --- browser_utils/initialization/auth.py ---
import asyncio
import os
import time
import logging
from playwright.async_api import BrowserContext as AsyncBrowserContext

from config import (
    USER_INPUT_START_MARKER_SERVER,
    USER_INPUT_END_MARKER_SERVER,
    AUTO_CONFIRM_LOGIN,
    AUTO_SAVE_AUTH,
    AUTH_SAVE_TIMEOUT,
    SAVED_AUTH_DIR,
)

logger = logging.getLogger("AIStudioProxyServer")

async def wait_for_model_list_and_handle_auth_save(temp_context, launch_mode, loop):
    """等待模型列表响应并处理认证保存"""
    import server

    # 等待模型列表响应，确认登录成功
    logger.info("   等待模型列表响应以确认登录成功...")
    try:
        # 等待模型列表事件，最多等待30秒
        await asyncio.wait_for(server.model_list_fetch_event.wait(), timeout=30.0)
        logger.info("   ✅ 检测到模型列表响应，登录确认成功！")
    except asyncio.TimeoutError:
        logger.warning("   ⚠️ 等待模型列表响应超时，但继续处理认证保存...")

    # 检查是否有预设的文件名用于保存
    save_auth_filename = os.environ.get('SAVE_AUTH_FILENAME', '').strip()
    if save_auth_filename:
        logger.info(f"   检测到 SAVE_AUTH_FILENAME 环境变量: '{save_auth_filename}'。将自动保存认证文件。")
        await _handle_auth_file_save_with_filename(temp_context, save_auth_filename)
        return

    # If not auto-saving, proceed with interactive prompts
    await _interactive_auth_save(temp_context, launch_mode, loop)


async def _interactive_auth_save(temp_context, launch_mode, loop):
    """处理认证文件保存的交互式提示"""
    # 检查是否启用自动确认
    if AUTO_CONFIRM_LOGIN:
        print("\n" + "="*50, flush=True)
        print("   ✅ 登录成功！检测到模型列表响应。", flush=True)
        print("   🤖 自动确认模式已启用，将自动保存认证状态...", flush=True)

        # 自动保存认证状态
        await _handle_auth_file_save_auto(temp_context)
        print("="*50 + "\n", flush=True)
        return

    # 手动确认模式
    print("\n" + "="*50, flush=True)
    print("   【用户交互】需要您的输入!", flush=True)
    print("   ✅ 登录成功！检测到模型列表响应。", flush=True)

    should_save_auth_choice = ''
    if AUTO_SAVE_AUTH and launch_mode == 'debug':
        logger.info("   自动保存认证模式已启用，将自动保存认证状态...")
        should_save_auth_choice = 'y'
    else:
        save_auth_prompt = "   是否要将当前的浏览器认证状态保存到文件？ (y/N): "
        print(USER_INPUT_START_MARKER_SERVER, flush=True)
        try:
            auth_save_input_future = loop.run_in_executor(None, input, save_auth_prompt)
            should_save_auth_choice = await asyncio.wait_for(auth_save_input_future, timeout=AUTH_SAVE_TIMEOUT)
        except asyncio.TimeoutError:
            print(f"   输入等待超时({AUTH_SAVE_TIMEOUT}秒)。默认不保存认证状态。", flush=True)
            should_save_auth_choice = 'n'
        finally:
            print(USER_INPUT_END_MARKER_SERVER, flush=True)

    if should_save_auth_choice.strip().lower() == 'y':
        await _handle_auth_file_save(temp_context, loop)
    else:
        print("   好的，不保存认证状态。", flush=True)

    print("="*50 + "\n", flush=True)


async def _handle_auth_file_save(temp_context, loop):
    """处理认证文件保存（手动模式）"""
    os.makedirs(SAVED_AUTH_DIR, exist_ok=True)
    default_auth_filename = f"auth_state_{int(time.time())}.json"

    print(USER_INPUT_START_MARKER_SERVER, flush=True)
    filename_prompt_str = f"   请输入保存的文件名 (默认为: {default_auth_filename}，输入 'cancel' 取消保存): "
    chosen_auth_filename = ''

    try:
        filename_input_future = loop.run_in_executor(None, input, filename_prompt_str)
        chosen_auth_filename = await asyncio.wait_for(filename_input_future, timeout=AUTH_SAVE_TIMEOUT)
    except asyncio.TimeoutError:
        print(f"   输入文件名等待超时({AUTH_SAVE_TIMEOUT}秒)。将使用默认文件名: {default_auth_filename}", flush=True)
        chosen_auth_filename = default_auth_filename
    finally:
        print(USER_INPUT_END_MARKER_SERVER, flush=True)

    if chosen_auth_filename.strip().lower() == 'cancel':
        print("   用户选择取消保存认证状态。", flush=True)
        return

    final_auth_filename = chosen_auth_filename.strip() or default_auth_filename
    if not final_auth_filename.endswith(".json"):
        final_auth_filename += ".json"

    auth_save_path = os.path.join(SAVED_AUTH_DIR, final_auth_filename)

    try:
        await temp_context.storage_state(path=auth_save_path)
        logger.info(f"   认证状态已成功保存到: {auth_save_path}")
        print(f"   ✅ 认证状态已成功保存到: {auth_save_path}", flush=True)
    except Exception as save_state_err:
        logger.error(f"   ❌ 保存认证状态失败: {save_state_err}", exc_info=True)
        print(f"   ❌ 保存认证状态失败: {save_state_err}", flush=True)


async def _handle_auth_file_save_with_filename(temp_context, filename: str):
    """处理认证文件保存（使用提供的文件名）"""
    os.makedirs(SAVED_AUTH_DIR, exist_ok=True)

    # Clean the filename and add .json if needed
    final_auth_filename = filename.strip()
    if not final_auth_filename.endswith(".json"):
        final_auth_filename += ".json"

    auth_save_path = os.path.join(SAVED_AUTH_DIR, final_auth_filename)

    try:
        await temp_context.storage_state(path=auth_save_path)
        print(f"   ✅ 认证状态已自动保存到: {auth_save_path}", flush=True)
        logger.info(f"   自动保存认证状态成功: {auth_save_path}")
    except Exception as save_state_err:
        logger.error(f"   ❌ 自动保存认证状态失败: {save_state_err}", exc_info=True)
        print(f"   ❌ 自动保存认证状态失败: {save_state_err}", flush=True)


async def _handle_auth_file_save_auto(temp_context):
    """处理认证文件保存（自动模式）"""
    os.makedirs(SAVED_AUTH_DIR, exist_ok=True)

    # 生成基于时间戳的文件名
    timestamp = int(time.time())
    auto_auth_filename = f"auth_auto_{timestamp}.json"
    auth_save_path = os.path.join(SAVED_AUTH_DIR, auto_auth_filename)

    try:
        await temp_context.storage_state(path=auth_save_path)
        logger.info(f"   认证状态已成功保存到: {auth_save_path}")
        print(f"   ✅ 认证状态已成功保存到: {auth_save_path}", flush=True)
    except Exception as save_state_err:
        logger.error(f"   ❌ 自动保存认证状态失败: {save_state_err}", exc_info=True)
        print(f"   ❌ 自动保存认证状态失败: {save_state_err}", flush=True)