"""
Tests for launcher/process.py - CamoufoxProcessManager.

These tests verify the process lifecycle management including cleanup behavior
which is critical for preventing zombie processes and Ctrl+C hang issues.
"""

import os
import signal
import subprocess
import sys
from unittest.mock import MagicMock, patch

import pytest

from launcher.process import (
    CamoufoxProcessManager,
    _enqueue_output,
    build_launch_command,
)


class TestBuildLaunchCommand:
    """Tests for the build_launch_command pure function."""

    @patch("launcher.process.PYTHON_EXECUTABLE", "python_test_exe")
    @patch("sys.argv", ["script_name.py"])
    def test_build_launch_command_basic(self):
        """Verify basic command construction without optional args."""
        cmd = build_launch_command(
            final_launch_mode="headless",
            effective_active_auth_json_path=None,
            simulated_os_for_camoufox="linux",
            camoufox_debug_port=1234,
            internal_camoufox_proxy=None,
        )

        assert cmd == [
            "python_test_exe",
            "-u",
            "script_name.py",
            "--internal-launch-mode",
            "headless",
            "--internal-camoufox-os",
            "linux",
            "--internal-camoufox-port",
            "1234",
        ]

    @patch("launcher.process.PYTHON_EXECUTABLE", "python_test_exe")
    @patch("sys.argv", ["script_name.py"])
    def test_build_launch_command_with_all_options(self):
        """Verify command construction with all optional args provided."""
        cmd = build_launch_command(
            final_launch_mode="debug",
            effective_active_auth_json_path="/path/to/auth.json",
            simulated_os_for_camoufox="windows",
            camoufox_debug_port=9222,
            internal_camoufox_proxy="http://proxy:8080",
        )

        expected_cmd = [
            "python_test_exe",
            "-u",
            "script_name.py",
            "--internal-launch-mode",
            "debug",
            "--internal-auth-file",
            "/path/to/auth.json",
            "--internal-camoufox-os",
            "windows",
            "--internal-camoufox-port",
            "9222",
            "--internal-camoufox-proxy",
            "http://proxy:8080",
        ]
        assert cmd == expected_cmd


class TestCamoufoxProcessManagerCleanup:
    """Tests for CamoufoxProcessManager.cleanup() method."""

    def test_cleanup_terminates_running_process(self):
        """Verify cleanup terminates a running process.

        Regression test: Ensures the cleanup method properly terminates
        the internal Camoufox process when it's still running.
        """
        manager = CamoufoxProcessManager()

        # Mock a running process
        mock_process = MagicMock()
        mock_process.poll.return_value = None  # Process is still running
        mock_process.pid = 12345
        mock_process.stdout = MagicMock()
        mock_process.stderr = MagicMock()
        mock_process.stdout.closed = False
        mock_process.stderr.closed = False

        manager.camoufox_proc = mock_process

        with patch.object(os, "getpgid", return_value=12345):
            with patch.object(os, "killpg") as mock_killpg:
                manager.cleanup()

                # Verify SIGTERM was sent to process group
                mock_killpg.assert_called()

        # Verify process reference is cleared
        assert manager.camoufox_proc is None

    def test_cleanup_uses_sigterm_then_sigkill_on_timeout(self):
        """Verify Unix SIGTERM → SIGKILL escalation pattern.

        Regression test: If SIGTERM times out, the cleanup should escalate
        to SIGKILL to ensure the process is terminated.
        """
        if sys.platform == "win32":
            pytest.skip("Unix-only test")

        manager = CamoufoxProcessManager()

        # Mock a process that doesn't respond to SIGTERM
        mock_process = MagicMock()
        mock_process.poll.return_value = None  # Process is still running
        mock_process.pid = 12345
        mock_process.wait.side_effect = subprocess.TimeoutExpired(cmd="test", timeout=5)
        mock_process.stdout = MagicMock()
        mock_process.stderr = MagicMock()
        mock_process.stdout.closed = False
        mock_process.stderr.closed = False

        manager.camoufox_proc = mock_process

        with (
            patch.object(os, "getpgid", return_value=12345),
            patch.object(os, "killpg") as mock_killpg,
        ):
            manager.cleanup()

            # Verify killpg was called at least twice (SIGTERM, then SIGKILL)
            assert mock_killpg.call_count >= 2
            # First call should be SIGTERM
            first_call = mock_killpg.call_args_list[0]
            assert first_call[0][1] == signal.SIGTERM
            # Second call should be SIGKILL
            second_call = mock_killpg.call_args_list[1]
            assert second_call[0][1] == signal.SIGKILL

    def test_cleanup_handles_process_already_exited(self):
        """Verify cleanup handles already-exited process gracefully.

        Regression test: Ensures cleanup doesn't error if the process
        has already exited before cleanup is called.
        """
        manager = CamoufoxProcessManager()

        # Mock a process that has already exited
        mock_process = MagicMock()
        mock_process.poll.return_value = 0  # Process has exited with code 0
        mock_process.pid = 12345

        manager.camoufox_proc = mock_process

        # Should not raise exception
        manager.cleanup()

        # Verify process reference is cleared
        assert manager.camoufox_proc is None

    def test_cleanup_closes_streams(self):
        """Verify stdout/stderr streams are closed during cleanup.

        Regression test: Ensures streams are properly closed to prevent
        resource leaks.
        """
        manager = CamoufoxProcessManager()

        # Mock a running process with open streams
        mock_process = MagicMock()
        mock_process.poll.return_value = None
        mock_process.pid = 12345

        mock_stdout = MagicMock()
        mock_stdout.closed = False
        mock_stderr = MagicMock()
        mock_stderr.closed = False

        mock_process.stdout = mock_stdout
        mock_process.stderr = mock_stderr

        manager.camoufox_proc = mock_process

        with (
            patch.object(os, "getpgid", return_value=12345),
            patch.object(os, "killpg"),
        ):
            manager.cleanup()

        # Verify streams were closed
        mock_stdout.close.assert_called_once()
        mock_stderr.close.assert_called_once()

    @pytest.mark.skipif(sys.platform != "win32", reason="Windows-only test")
    def test_cleanup_uses_taskkill_on_windows(self):
        """Verify Windows uses taskkill for process termination.

        Regression test: Windows doesn't have SIGTERM/SIGKILL, so we must
        use taskkill /F /T to terminate the process tree.
        """
        manager = CamoufoxProcessManager()

        # Mock a running process
        mock_process = MagicMock()
        mock_process.poll.return_value = None
        mock_process.pid = 12345
        mock_process.stdout = MagicMock()
        mock_process.stderr = MagicMock()
        mock_process.stdout.closed = False
        mock_process.stderr.closed = False

        manager.camoufox_proc = mock_process

        with patch("subprocess.run") as mock_run:
            mock_run.return_value.returncode = 0
            manager.cleanup()

            # Verify taskkill was called with /F (force) and /T (tree)
            mock_run.assert_called_once()
            call_args = mock_run.call_args[0][0]
            assert "taskkill" in call_args
            assert "/F" in call_args
            assert "/T" in call_args
            assert str(12345) in call_args

    def test_cleanup_no_process_does_not_error(self):
        """Verify cleanup handles case where process was never started.

        Regression test: Ensures cleanup doesn't fail when called before
        any process was started (e.g., during early startup failure).
        """
        manager = CamoufoxProcessManager()

        # No process was ever started
        assert manager.camoufox_proc is None

        # Should not raise exception
        manager.cleanup()

        # Still None
        assert manager.camoufox_proc is None


class TestEnqueueOutput:
    """Tests for the _enqueue_output helper function."""

    def test_enqueue_output_reads_lines(self):
        """Verify _enqueue_output properly enqueues lines from stream."""
        import queue

        mock_stream = MagicMock()
        # Simulate reading two lines then empty (EOF)
        mock_stream.readline.side_effect = [
            b"line 1\n",
            b"line 2\n",
            b"",  # EOF
        ]
        mock_stream.closed = False

        output_queue = queue.Queue()

        _enqueue_output(mock_stream, "stdout", output_queue, "test-pid")

        # Should have 2 lines + 1 EOF marker (None)
        results = []
        while not output_queue.empty():
            results.append(output_queue.get_nowait())

        assert len(results) == 3
        assert results[0] == ("stdout", "line 1\n")
        assert results[1] == ("stdout", "line 2\n")
        assert results[2] == ("stdout", None)  # EOF marker

    def test_enqueue_output_handles_decode_error(self):
        """Verify _enqueue_output handles invalid UTF-8 gracefully."""
        import queue

        mock_stream = MagicMock()
        # Invalid UTF-8 sequence
        mock_stream.readline.side_effect = [
            b"\xff\xfe invalid utf8",
            b"",  # EOF
        ]
        mock_stream.closed = False

        output_queue = queue.Queue()

        # Should not raise exception
        _enqueue_output(mock_stream, "stderr", output_queue, "test-pid")

        # Should still produce output (with replacement characters)
        results = []
        while not output_queue.empty():
            results.append(output_queue.get_nowait())

        assert len(results) == 2  # 1 line + EOF marker

    def test_enqueue_output_handles_value_error(self):
        """Verify _enqueue_output handles ValueError when stream is closed.

        This can happen if the stream is closed by another thread while
        we're still trying to read from it.
        """
        import queue

        mock_stream = MagicMock()
        # Simulate ValueError when stream is closed during read
        mock_stream.readline.side_effect = [
            b"line 1\n",
            ValueError("I/O operation on closed file"),
        ]
        mock_stream.closed = True  # Stream becomes closed

        output_queue = queue.Queue()

        # Should not raise exception - ValueError is caught
        _enqueue_output(mock_stream, "stdout", output_queue, "test-pid")

        results = []
        while not output_queue.empty():
            results.append(output_queue.get_nowait())

        # Should have 1 line + 1 EOF marker
        assert len(results) == 2
        assert results[0] == ("stdout", "line 1\n")
        assert results[1] == ("stdout", None)  # EOF marker from finally block

    def test_enqueue_output_handles_unexpected_exception(self):
        """Verify _enqueue_output handles unexpected exceptions gracefully.

        This tests the generic Exception handler for errors that are neither
        ValueError nor decode errors (e.g., OS-level IO errors).
        """
        import queue

        mock_stream = MagicMock()
        # Simulate an unexpected exception during reading
        mock_stream.readline.side_effect = [
            b"line 1\n",
            OSError("Unexpected I/O error"),
        ]
        mock_stream.closed = False

        output_queue = queue.Queue()

        # Should not raise exception - Exception is caught and logged
        _enqueue_output(mock_stream, "stderr", output_queue, "test-pid")

        results = []
        while not output_queue.empty():
            results.append(output_queue.get_nowait())

        # Should have 1 line + 1 EOF marker
        assert len(results) == 2
        assert results[0] == ("stderr", "line 1\n")
        assert results[1] == ("stderr", None)  # EOF marker from finally block

    def test_enqueue_output_closes_stream_in_finally(self):
        """Verify _enqueue_output closes the stream in finally block.

        Even after errors, the stream should be properly closed to prevent
        resource leaks.
        """
        import queue

        mock_stream = MagicMock()
        mock_stream.readline.return_value = b""  # EOF immediately
        mock_stream.closed = False

        output_queue = queue.Queue()

        _enqueue_output(mock_stream, "stdout", output_queue, "test-pid")

        # Stream should be closed
        mock_stream.close.assert_called_once()

    def test_enqueue_output_handles_close_exception(self):
        """Verify _enqueue_output handles exceptions during stream close.

        If closing the stream fails, it should be silently ignored to
        prevent masking the original error.
        """
        import queue

        mock_stream = MagicMock()
        mock_stream.readline.return_value = b""  # EOF immediately
        mock_stream.closed = False
        mock_stream.close.side_effect = OSError("Close failed")

        output_queue = queue.Queue()

        # Should not raise exception even if close fails
        _enqueue_output(mock_stream, "stdout", output_queue, "test-pid")

        # Should still have EOF marker
        results = []
        while not output_queue.empty():
            results.append(output_queue.get_nowait())

        assert len(results) == 1
        assert results[0] == ("stdout", None)


class TestCamoufoxProcessManagerInterface:
    """Structural tests for CamoufoxProcessManager.

    NOTE: The CamoufoxProcessManager.start() method is marked with `# pragma: no cover`
    because it is inherently difficult to unit test:
    - It spawns real subprocesses (subprocess.Popen)
    - It creates threads for stdout/stderr reading
    - It has timeout-based loops waiting for WebSocket endpoint output
    - It interacts with the real filesystem and network

    The testable logic (build_launch_command, _enqueue_output, cleanup) has been
    extracted into separate functions/methods that ARE tested. The start() method
    is verified through:
    - Integration tests that verify end-to-end browser initialization
    - Manual testing during development
    - Structural tests below that verify the interface contract
    """

    def test_manager_has_required_interface(self):
        """Verify CamoufoxProcessManager exposes required interface.

        This structural test ensures that any refactoring maintains the
        expected public interface. If these attributes are removed or renamed,
        the test will fail, alerting developers to update dependent code.
        """
        manager = CamoufoxProcessManager()

        # Required attributes
        assert hasattr(manager, "camoufox_proc"), "Missing camoufox_proc attribute"
        assert hasattr(manager, "captured_ws_endpoint"), (
            "Missing captured_ws_endpoint attribute"
        )

        # Required methods
        assert callable(getattr(manager, "start", None)), "Missing start() method"
        assert callable(getattr(manager, "cleanup", None)), "Missing cleanup() method"

        # Initial state
        assert manager.camoufox_proc is None, "camoufox_proc should initially be None"
        assert manager.captured_ws_endpoint is None, (
            "captured_ws_endpoint should initially be None"
        )

    def test_build_launch_command_is_pure(self):
        """Verify build_launch_command is importable and callable.

        This function is the extracted pure logic from start() that IS unit-testable.
        The actual tests for build_launch_command are in TestBuildLaunchCommand.
        """
        assert callable(build_launch_command)

    def test_enqueue_output_is_importable(self):
        """Verify _enqueue_output is importable for threading.

        The actual tests for _enqueue_output are in TestEnqueueOutput.
        This just verifies it's accessible from the module.
        """
        assert callable(_enqueue_output)
