import json
from asyncio import Event
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from api_utils.response_generators import (
    gen_sse_from_aux_stream,
    gen_sse_from_playwright,
)
from models import ChatCompletionRequest, ClientDisconnectedError


@pytest.fixture
def mock_request():
    req = MagicMock(spec=ChatCompletionRequest)
    req.messages = [MagicMock(model_dump=lambda: {"role": "user", "content": "hi"})]
    return req


@pytest.fixture
def mock_event():
    return Event()


@pytest.fixture
def mock_check_disconnect():
    return MagicMock()


@pytest.mark.asyncio
async def test_gen_sse_from_aux_stream_basic_flow(
    mock_request, mock_event, mock_check_disconnect
):
    """Test basic flow with body content and completion."""
    req_id = "test_req"
    model_name = "test-model"

    # Mock data stream
    stream_data = [
        json.dumps({"body": "Hello", "reason": "", "done": False}),
        json.dumps({"body": "Hello World", "reason": "", "done": False}),
        json.dumps({"body": "Hello World", "reason": "", "done": True}),
    ]

    async def mock_stream_gen(rid):
        for item in stream_data:
            yield item

    with (
        patch(
            "api_utils.response_generators.use_stream_response",
            side_effect=mock_stream_gen,
        ),
        patch(
            "api_utils.response_generators.calculate_usage_stats",
            return_value={"total_tokens": 10},
        ),
    ):
        chunks = []
        async for chunk in gen_sse_from_aux_stream(
            req_id, mock_request, model_name, mock_check_disconnect, mock_event
        ):
            chunks.append(chunk)

    # Verify chunks
    # We expect:
    # 1. Chunk with "Hello"
    # 2. Chunk with " World"
    # 3. Stop chunk (finish_reason="stop")
    # 4. Usage chunk
    # 5. [DONE]

    assert len(chunks) >= 3
    assert "Hello" in chunks[0]
    assert "World" in chunks[1]
    assert "[DONE]" in chunks[-1]
    assert mock_event.is_set()


@pytest.mark.asyncio
async def test_gen_sse_from_aux_stream_reasoning(
    mock_request, mock_event, mock_check_disconnect
):
    """Test flow with reasoning content."""
    req_id = "test_req_reason"

    stream_data = [
        {"reason": "Thinking...", "body": "", "done": False},
        {"reason": "Thinking... Done.", "body": "", "done": False},
        {"reason": "", "body": "Answer", "done": True},
    ]

    async def mock_stream_gen(rid):
        for item in stream_data:
            yield item

    with (
        patch(
            "api_utils.response_generators.use_stream_response",
            side_effect=mock_stream_gen,
        ),
        patch(
            "api_utils.response_generators.calculate_usage_stats",
            return_value={"total_tokens": 10},
        ),
    ):
        chunks = []
        async for chunk in gen_sse_from_aux_stream(
            req_id, mock_request, "model", mock_check_disconnect, mock_event
        ):
            chunks.append(chunk)

    # First chunk should have reasoning_content "Thinking..."
    # Second chunk should have delta reasoning_content " Done." (diff)

    chunk1_data = json.loads(chunks[0].replace("data: ", "").strip())
    assert chunk1_data["choices"][0]["delta"]["reasoning_content"] == "Thinking..."

    chunk2_data = json.loads(chunks[1].replace("data: ", "").strip())
    assert chunk2_data["choices"][0]["delta"]["reasoning_content"] == " Done."


@pytest.mark.asyncio
async def test_gen_sse_from_aux_stream_tool_calls(
    mock_request, mock_event, mock_check_disconnect
):
    """Test flow with tool calls."""
    req_id = "test_req_tool"

    function_data = [{"name": "get_weather", "params": {"location": "NYC"}}]

    stream_data = [{"body": "", "reason": "", "done": True, "function": function_data}]

    async def mock_stream_gen(rid):
        for item in stream_data:
            yield item

    with (
        patch(
            "api_utils.response_generators.use_stream_response",
            side_effect=mock_stream_gen,
        ),
        patch(
            "api_utils.response_generators.calculate_usage_stats",
            return_value={"total_tokens": 10},
        ),
        patch("api_utils.response_generators.random_id", return_value="123"),
    ):
        chunks = []
        async for chunk in gen_sse_from_aux_stream(
            req_id, mock_request, "model", mock_check_disconnect, mock_event
        ):
            chunks.append(chunk)

    # Check for tool call chunk
    found_tool = False
    for chunk in chunks:
        if "[DONE]" in chunk:
            continue
        data = json.loads(chunk.replace("data: ", "").strip())
        delta = data["choices"][0]["delta"]
        if "tool_calls" in delta:
            found_tool = True
            tool = delta["tool_calls"][0]
            assert tool["function"]["name"] == "get_weather"
            assert "NYC" in tool["function"]["arguments"]
            assert data["choices"][0]["finish_reason"] == "tool_calls"

    assert found_tool


@pytest.mark.asyncio
async def test_gen_sse_from_aux_stream_disconnect(mock_request, mock_event):
    """Test client disconnect handling."""
    req_id = "test_req_disc"

    # Mock disconnect checker to raise error on second call
    mock_check = MagicMock()
    mock_check.side_effect = [None, ClientDisconnectedError("Disconnected")]

    stream_data = [{"body": "1"}, {"body": "2"}]  # infinite stream effectively

    async def mock_stream_gen(rid):
        for item in stream_data:
            yield item

    with patch(
        "api_utils.response_generators.use_stream_response", side_effect=mock_stream_gen
    ):
        chunks = []
        async for chunk in gen_sse_from_aux_stream(
            req_id, mock_request, "model", mock_check, mock_event
        ):
            chunks.append(chunk)

    # Should stop early and set event
    assert mock_event.is_set()
    # Should contain logs about disconnect (verified via coverage/logic)


@pytest.mark.asyncio
async def test_gen_sse_from_aux_stream_invalid_json(
    mock_request, mock_event, mock_check_disconnect
):
    """Test handling of invalid JSON in stream."""
    req_id = "test_req_invalid"

    stream_data = ["invalid json", json.dumps({"body": "Valid"})]

    async def mock_stream_gen(rid):
        for item in stream_data:
            yield item

    with patch(
        "api_utils.response_generators.use_stream_response", side_effect=mock_stream_gen
    ):
        chunks = []
        async for chunk in gen_sse_from_aux_stream(
            req_id, mock_request, "model", mock_check_disconnect, mock_event
        ):
            chunks.append(chunk)

    # Should skip invalid and process valid
    assert len(chunks) >= 1
    assert "Valid" in chunks[0]


@pytest.mark.asyncio
async def test_gen_sse_from_playwright_success(
    mock_request, mock_event, mock_check_disconnect
):
    """Test success flow for Playwright generator."""
    req_id = "test_req_pw"
    mock_page = AsyncMock()
    mock_logger = MagicMock()

    with (
        patch("browser_utils.page_controller.PageController") as MockPC,
        patch(
            "api_utils.response_generators.calculate_usage_stats",
            return_value={"tokens": 5},
        ),
    ):
        instance = MockPC.return_value
        instance.get_response = AsyncMock(return_value="Line 1\nLine 2")

        chunks = []
        async for chunk in gen_sse_from_playwright(
            mock_page,
            mock_logger,
            req_id,
            "model",
            mock_request,
            mock_check_disconnect,
            mock_event,
        ):
            chunks.append(chunk)

    # Should chunk the response
    # "Line 1" -> chunks (size 5) -> "Line ", "1"
    # "\n"
    # "Line 2" -> "Line ", "2"
    # Stop chunk

    content_parts = []
    for c in chunks:
        if "[DONE]" in c:
            continue
        try:
            data = json.loads(c.replace("data: ", "").strip())
            if "choices" in data and len(data["choices"]) > 0:
                delta = data["choices"][0].get("delta", {})
                if "content" in delta and delta["content"]:
                    content_parts.append(delta["content"])
        except json.JSONDecodeError:
            continue

    content = "".join(content_parts)

    assert "Line 1\nLine 2" in content
    assert mock_event.is_set()


@pytest.mark.asyncio
async def test_gen_sse_from_playwright_exception(
    mock_request, mock_event, mock_check_disconnect
):
    """Test exception handling in Playwright generator."""
    req_id = "test_req_pw_err"
    mock_page = AsyncMock()
    mock_logger = MagicMock()

    with patch("browser_utils.page_controller.PageController") as MockPC:
        instance = MockPC.return_value
        instance.get_response = AsyncMock(side_effect=Exception("Page Error"))

        chunks = []
        async for chunk in gen_sse_from_playwright(
            mock_page,
            mock_logger,
            req_id,
            "model",
            mock_request,
            mock_check_disconnect,
            mock_event,
        ):
            chunks.append(chunk)

    # Should yield error chunk
    error_chunk_str = chunks[0].replace("data: ", "").strip()
    error_chunk = json.loads(error_chunk_str)
    content = error_chunk["choices"][0]["delta"]["content"]
    assert "[错误: Page Error]" in content
    assert mock_event.is_set()
