"""
High-quality tests for api_utils/context_init.py - Request context initialization.

Focus: Test initialize_request_context with various request configurations.
Strategy: Mock server module globals, verify context dictionary construction.
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from api_utils.context_init import initialize_request_context
from models import ChatCompletionRequest


@pytest.fixture
def mock_server_state():
    """Mock server module globals."""
    return {
        "current_ai_studio_model_id": "gemini-1.5-pro",
        "is_page_ready": True,
        "logger": MagicMock(),
        "model_switching_lock": AsyncMock(spec=asyncio.Lock),
        "page_instance": MagicMock(),
        "page_params_cache": {"temperature": 1.0},
        "params_cache_lock": AsyncMock(spec=asyncio.Lock),
        "parsed_model_list": [{"id": "gemini-1.5-pro", "object": "model"}],
    }


@pytest.mark.asyncio
async def test_initialize_request_context_streaming_request(mock_server_state):
    """
    测试场景: 流式请求初始化
    预期: is_streaming=True, 所有字段正确填充 (lines 25-39)
    """
    request = ChatCompletionRequest(
        model="gemini-1.5-pro",
        messages=[{"role": "user", "content": "Hello"}],
        stream=True,
    )

    with patch.dict("sys.modules", {"server": MagicMock(**mock_server_state)}):
        from server import logger

        context = await initialize_request_context("req1", request)

        # 验证: logger.info 被调用两次 (lines 20-23)
        assert logger.info.call_count == 2
        assert "[req1] 开始处理请求..." in logger.info.call_args_list[0][0][0]
        assert (
            "[req1]   请求参数 - Model: gemini-1.5-pro, Stream: True"
            in logger.info.call_args_list[1][0][0]
        )

        # 验证: context 字典包含所有必需字段
        assert context["logger"] == logger
        assert context["page"] == mock_server_state["page_instance"]
        assert context["is_page_ready"] is True
        assert context["parsed_model_list"] == mock_server_state["parsed_model_list"]
        assert context["current_ai_studio_model_id"] == "gemini-1.5-pro"
        assert (
            context["model_switching_lock"] == mock_server_state["model_switching_lock"]
        )
        assert context["page_params_cache"] == {"temperature": 1.0}
        assert context["params_cache_lock"] == mock_server_state["params_cache_lock"]
        assert context["is_streaming"] is True  # From request.stream
        assert context["model_actually_switched"] is False
        assert context["requested_model"] == "gemini-1.5-pro"
        assert context["model_id_to_use"] is None
        assert context["needs_model_switching"] is False


@pytest.mark.asyncio
async def test_initialize_request_context_non_streaming_request(mock_server_state):
    """
    测试场景: 非流式请求初始化
    预期: is_streaming=False (line 34)
    """
    request = ChatCompletionRequest(
        model="gemini-1.5-flash",
        messages=[{"role": "user", "content": "Test"}],
        stream=False,
    )

    with patch.dict("sys.modules", {"server": MagicMock(**mock_server_state)}):
        from server import logger

        context = await initialize_request_context("req2", request)

        # 验证: is_streaming=False
        assert context["is_streaming"] is False
        assert context["requested_model"] == "gemini-1.5-flash"

        # 验证: logger 记录了正确的请求参数
        log_message = logger.info.call_args_list[1][0][0]
        assert "Stream: False" in log_message


@pytest.mark.asyncio
async def test_initialize_request_context_different_model(mock_server_state):
    """
    测试场景: 使用不同的模型名称
    预期: requested_model 正确设置 (line 36)
    """
    request = ChatCompletionRequest(
        model="gemini-2.0-flash-thinking-exp",
        messages=[{"role": "user", "content": "Think"}],
        stream=True,
    )

    with patch.dict("sys.modules", {"server": MagicMock(**mock_server_state)}):
        from server import logger

        context = await initialize_request_context("req3", request)

        # 验证: requested_model 正确
        assert context["requested_model"] == "gemini-2.0-flash-thinking-exp"

        # 验证: logger 记录了模型名称
        log_message = logger.info.call_args_list[1][0][0]
        assert "Model: gemini-2.0-flash-thinking-exp" in log_message


@pytest.mark.asyncio
async def test_initialize_request_context_page_not_ready(mock_server_state):
    """
    测试场景: 页面未准备好
    预期: is_page_ready=False (line 28)
    """
    mock_server_state["is_page_ready"] = False

    request = ChatCompletionRequest(
        model="gemini-1.5-pro", messages=[{"role": "user", "content": "Test"}]
    )

    with patch.dict("sys.modules", {"server": MagicMock(**mock_server_state)}):
        context = await initialize_request_context("req4", request)

        # 验证: is_page_ready=False
        assert context["is_page_ready"] is False


@pytest.mark.asyncio
async def test_initialize_request_context_none_current_model(mock_server_state):
    """
    测试场景: 当前模型 ID 为 None (初始状态)
    预期: current_ai_studio_model_id=None (line 30)
    """
    mock_server_state["current_ai_studio_model_id"] = None

    request = ChatCompletionRequest(
        model="gemini-1.5-pro", messages=[{"role": "user", "content": "Test"}]
    )

    with patch.dict("sys.modules", {"server": MagicMock(**mock_server_state)}):
        context = await initialize_request_context("req5", request)

        # 验证: current_ai_studio_model_id=None
        assert context["current_ai_studio_model_id"] is None


@pytest.mark.asyncio
async def test_initialize_request_context_empty_params_cache(mock_server_state):
    """
    测试场景: 参数缓存为空
    预期: page_params_cache={} (line 32)
    """
    mock_server_state["page_params_cache"] = {}

    request = ChatCompletionRequest(
        model="gemini-1.5-pro", messages=[{"role": "user", "content": "Test"}]
    )

    with patch.dict("sys.modules", {"server": MagicMock(**mock_server_state)}):
        context = await initialize_request_context("req6", request)

        # 验证: page_params_cache 为空字典
        assert context["page_params_cache"] == {}


@pytest.mark.asyncio
async def test_initialize_request_context_empty_model_list(mock_server_state):
    """
    测试场景: 模型列表为空 (页面加载失败时)
    预期: parsed_model_list=[] (line 29)
    """
    mock_server_state["parsed_model_list"] = []

    request = ChatCompletionRequest(
        model="gemini-1.5-pro", messages=[{"role": "user", "content": "Test"}]
    )

    with patch.dict("sys.modules", {"server": MagicMock(**mock_server_state)}):
        context = await initialize_request_context("req7", request)

        # 验证: parsed_model_list 为空列表
        assert context["parsed_model_list"] == []


@pytest.mark.asyncio
async def test_initialize_request_context_logger_format(mock_server_state):
    """
    测试场景: 验证 logger 消息格式
    预期: 包含 req_id、model、stream 参数 (lines 20-23)
    """
    request = ChatCompletionRequest(
        model="test-model-123",
        messages=[{"role": "user", "content": "Hello"}],
        stream=True,
    )

    with patch.dict("sys.modules", {"server": MagicMock(**mock_server_state)}):
        from server import logger

        await initialize_request_context("test-req-abc", request)

        # 验证: 第一条日志包含 req_id
        first_log = logger.info.call_args_list[0][0][0]
        assert "[test-req-abc]" in first_log
        assert "开始处理请求..." in first_log

        # 验证: 第二条日志包含请求参数
        second_log = logger.info.call_args_list[1][0][0]
        assert "[test-req-abc]" in second_log
        assert "Model: test-model-123" in second_log
        assert "Stream: True" in second_log


@pytest.mark.asyncio
async def test_initialize_request_context_all_default_flags(mock_server_state):
    """
    测试场景: 验证所有默认标志位
    预期: model_actually_switched=False, model_id_to_use=None, needs_model_switching=False
    """
    request = ChatCompletionRequest(
        model="gemini-1.5-pro", messages=[{"role": "user", "content": "Test"}]
    )

    with patch.dict("sys.modules", {"server": MagicMock(**mock_server_state)}):
        context = await initialize_request_context("req8", request)

        # 验证: 所有默认标志位正确 (lines 35, 37-38)
        assert context["model_actually_switched"] is False
        assert context["model_id_to_use"] is None
        assert context["needs_model_switching"] is False


@pytest.mark.asyncio
async def test_initialize_request_context_return_type(mock_server_state):
    """
    测试场景: 验证返回类型
    预期: 返回 dict (RequestContext 是 TypedDict)
    """
    request = ChatCompletionRequest(
        model="gemini-1.5-pro", messages=[{"role": "user", "content": "Test"}]
    )

    with patch.dict("sys.modules", {"server": MagicMock(**mock_server_state)}):
        context = await initialize_request_context("req9", request)

        # 验证: 返回类型是字典
        assert isinstance(context, dict)

        # 验证: 包含所有必需的键
        required_keys = [
            "logger",
            "page",
            "is_page_ready",
            "parsed_model_list",
            "current_ai_studio_model_id",
            "model_switching_lock",
            "page_params_cache",
            "params_cache_lock",
            "is_streaming",
            "model_actually_switched",
            "requested_model",
            "model_id_to_use",
            "needs_model_switching",
        ]

        for key in required_keys:
            assert key in context, f"Missing key: {key}"
