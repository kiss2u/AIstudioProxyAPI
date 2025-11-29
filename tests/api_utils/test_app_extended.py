"""
Extended tests for api_utils/app.py - Coverage completion.

Focus: Cover the last 2 uncovered lines (86, 265).
Strategy: Test edge cases for proxy settings and middleware path matching.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from api_utils.app import APIKeyAuthMiddleware, _initialize_proxy_settings
from api_utils.server_state import state


@pytest.fixture(autouse=True)
def reset_state():
    """Reset server state before each test."""
    state.reset()
    yield
    state.reset()


def test_initialize_proxy_settings_no_proxy_configured():
    """
    测试场景: 完全没有配置任何代理
    预期: 记录 "No proxy configured" 日志 (line 86)
    """
    state.PLAYWRIGHT_PROXY_SETTINGS = None
    mock_logger = MagicMock()
    state.logger = mock_logger

    with (
        patch("api_utils.app.get_environment_variable") as mock_get_env,
        patch("api_utils.app.NO_PROXY_ENV", None),
    ):
        # 返回 None 表示没有配置任何代理
        mock_get_env.side_effect = lambda key, default=None: {
            "STREAM_PORT": "0",
            "UNIFIED_PROXY_CONFIG": None,
            "HTTPS_PROXY": None,
            "HTTP_PROXY": None,
        }.get(key, default)

        _initialize_proxy_settings()

    # 验证: PLAYWRIGHT_PROXY_SETTINGS 应该为 None
    assert state.PLAYWRIGHT_PROXY_SETTINGS is None

    # 验证: 记录了 "No proxy configured" 日志 (line 86)
    mock_logger.info.assert_any_call("No proxy configured for Playwright.")


@pytest.mark.asyncio
async def test_api_key_auth_middleware_excluded_path_subpath():
    """
    测试场景: 请求路径是排除路径的子路径,且以 /v1/ 开头
    预期: 绕过认证,调用 call_next (line 265)

    注意: 为了触发 line 265,路径必须:
    1. 以 /v1/ 开头 (通过 line 257-258 检查)
    2. 匹配 excluded_paths 中的路径或其子路径 (触发 lines 261-265)
    """
    app = MagicMock()
    middleware = APIKeyAuthMiddleware(app)
    # 添加一个以 /v1/ 开头的排除路径
    middleware.excluded_paths.append("/v1/models")

    request = MagicMock()
    request.url.path = "/v1/models/abc"  # /v1/models 的子路径
    call_next = AsyncMock()
    call_next.return_value = MagicMock()  # Mock response

    # 即使配置了 API 密钥,排除路径的子路径也应该通过
    with patch("api_utils.auth_utils.API_KEYS", {"test-key": "user"}):
        response = await middleware.dispatch(request, call_next)

        # 验证: call_next 被调用 (line 265)
        call_next.assert_called_once_with(request)

        # 验证: 返回了 call_next 的响应
        assert response is not None
