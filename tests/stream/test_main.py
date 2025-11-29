"""
Tests for stream/main.py - Entry point coverage.

Focus: Cover line 129 (__name__ == "__main__" block).
Strategy: Use runpy to execute module as __main__.
"""

import runpy
import sys
from unittest.mock import AsyncMock, MagicMock, patch


def test_main_module_as_main():
    """
    测试场景: 以 __main__ 模式执行模块
    预期: 覆盖 line 129 (if __name__ == "__main__")
    """
    # Mock ProxyServer to avoid actually starting the proxy
    with (
        patch("stream.main.ProxyServer") as mock_proxy_class,
        patch("stream.main.parse_args") as mock_parse,
        patch("stream.main.asyncio.run") as mock_asyncio_run,
    ):
        mock_proxy = AsyncMock()
        mock_proxy.start = AsyncMock()
        mock_proxy_class.return_value = mock_proxy

        # Provide test arguments
        mock_args = MagicMock()
        mock_args.host = "127.0.0.1"
        mock_args.port = 3120
        mock_args.domains = ["*.google.com"]
        mock_args.proxy = None
        mock_parse.return_value = mock_args

        # Temporarily replace sys.argv to avoid argument parsing errors
        original_argv = sys.argv
        try:
            sys.argv = ["stream.main"]

            # Execute module as __main__ (covers line 129)
            runpy.run_module("stream.main", run_name="__main__")

            # Verify asyncio.run was called with main() (line 129)
            mock_asyncio_run.assert_called_once()
        finally:
            sys.argv = original_argv
