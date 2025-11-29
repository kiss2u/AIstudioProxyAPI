import base64
import json
import queue
from unittest.mock import AsyncMock, MagicMock, mock_open, patch

import pytest

from api_utils.utils_ext.files import (
    _extension_for_mime,
    extract_data_url_to_local,
    save_blob_to_local,
)
from api_utils.utils_ext.helper import use_helper_get_response
from api_utils.utils_ext.stream import clear_stream_queue, use_stream_response
from api_utils.utils_ext.tokens import calculate_usage_stats, estimate_tokens
from api_utils.utils_ext.validation import validate_chat_request
from models import Message

# --- tokens.py tests ---


def test_estimate_tokens():
    assert estimate_tokens("") == 0
    assert estimate_tokens(None) == 0

    # English: 1 char = 0.25 tokens -> 4 chars = 1 token
    assert estimate_tokens("abcd") == 1

    # Chinese: 1 char = 0.66 tokens -> 3 chars = 2 tokens (approx)
    # Actually logic is: chinese_tokens = chars / 1.5
    # "你好" (2 chars) -> 2/1.5 = 1.33 -> 1 token
    # "你好吗" (3 chars) -> 3/1.5 = 2.0 -> 2 tokens
    assert estimate_tokens("你好吗") == 2

    # Mixed
    # "hi你好" -> 2 eng + 2 chi
    # eng: 2/4 = 0.5
    # chi: 2/1.5 = 1.33
    # total: 1.83 -> 1 token
    assert estimate_tokens("hi你好") == 1


def test_calculate_usage_stats():
    messages = [
        {"role": "user", "content": "hello"},
        {"role": "assistant", "content": "hi"},
    ]
    response = "response"
    reasoning = "reasoning"

    stats = calculate_usage_stats(messages, response, reasoning)

    assert "prompt_tokens" in stats
    assert "completion_tokens" in stats
    assert "total_tokens" in stats
    assert stats["total_tokens"] == stats["prompt_tokens"] + stats["completion_tokens"]


# --- validation.py tests ---


def test_validate_chat_request_valid():
    messages = [
        Message(role="system", content="sys"),
        Message(role="user", content="user"),
    ]
    result = validate_chat_request(messages, "req1")
    assert result["error"] is None


def test_validate_chat_request_empty():
    with pytest.raises(ValueError, match="数组缺失或为空"):
        validate_chat_request([], "req1")


def test_validate_chat_request_only_system():
    messages = [Message(role="system", content="sys")]
    with pytest.raises(ValueError, match="所有消息都是系统消息"):
        validate_chat_request(messages, "req1")


# --- files.py tests ---


def test_extension_for_mime():
    assert _extension_for_mime("image/png") == ".png"
    assert _extension_for_mime("application/unknown") == ".unknown"
    assert _extension_for_mime("plain") == ".bin"
    assert _extension_for_mime(None) == ".bin"


def test_extract_data_url_to_local_success():
    data = b"hello world"
    b64_data = base64.b64encode(data).decode()
    data_url = f"data:text/plain;base64,{b64_data}"

    with (
        patch("server.logger"),
        patch("config.UPLOAD_FILES_DIR", "/tmp/uploads"),
        patch("os.makedirs"),
        patch("os.path.exists", return_value=False),
        patch("builtins.open", mock_open()) as mock_file,
    ):
        path = extract_data_url_to_local(data_url, "req1")

        assert path is not None
        assert path.endswith(".txt")
        mock_file().write.assert_called_with(data)


def test_extract_data_url_to_local_invalid_format():
    with patch("server.logger") as mock_logger:
        assert extract_data_url_to_local("invalid-url") is None
        mock_logger.error.assert_called()


def test_extract_data_url_to_local_bad_b64():
    with (
        patch("server.logger") as mock_logger,
        patch("base64.b64decode", side_effect=base64.binascii.Error("Invalid")),
    ):
        assert extract_data_url_to_local("data:text/plain;base64,!!!") is None
        mock_logger.error.assert_called()


def test_extract_data_url_to_local_exists():
    data_url = "data:text/plain;base64,AAAA"
    with (
        patch("server.logger"),
        patch("config.UPLOAD_FILES_DIR", "/tmp/uploads"),
        patch("os.makedirs"),
        patch("os.path.exists", return_value=True),
    ):
        path = extract_data_url_to_local(data_url)
        assert path is not None


def test_save_blob_to_local():
    data = b"test"
    with (
        patch("server.logger"),
        patch("config.UPLOAD_FILES_DIR", "/tmp/uploads"),
        patch("os.makedirs"),
        patch("os.path.exists", return_value=False),
        patch("builtins.open", mock_open()),
    ):
        # Test with mime
        path = save_blob_to_local(data, mime_type="image/png")
        assert path.endswith(".png")

        # Test with ext
        path = save_blob_to_local(data, fmt_ext=".jpg")
        assert path.endswith(".jpg")

        # Test fallback
        path = save_blob_to_local(data)
        assert path.endswith(".bin")


# --- helper.py tests ---


@pytest.mark.asyncio
async def test_use_helper_get_response_success():
    with patch("server.logger"), patch("aiohttp.ClientSession") as MockSession:

        async def mock_iter_chunked(n):
            yield b"chunk1"
            yield b"chunk2"

        mock_resp = AsyncMock()
        mock_resp.status = 200
        mock_resp.content.iter_chunked = MagicMock(side_effect=mock_iter_chunked)

        # session.get is NOT awaited, it returns a context manager immediately.
        # AsyncMock method would return a coroutine. So we use MagicMock for .get
        mock_session = AsyncMock()
        mock_session.get = MagicMock()
        mock_session.get.return_value.__aenter__.return_value = mock_resp

        # ClientSession() returns a context manager.
        # We ensure the context manager returns our mock_session
        MockSession.return_value.__aenter__.return_value = mock_session

        chunks = []
        async for chunk in use_helper_get_response("http://helper", "sap"):
            chunks.append(chunk)

        assert chunks == ["chunk1", "chunk2"]


@pytest.mark.asyncio
async def test_use_helper_get_response_error():
    with (
        patch("server.logger") as mock_logger,
        patch("aiohttp.ClientSession") as MockSession,
    ):
        mock_resp = AsyncMock()
        mock_resp.status = 500

        mock_session = AsyncMock()
        mock_session.get = MagicMock()
        mock_session.get.return_value.__aenter__.return_value = mock_resp

        MockSession.return_value.__aenter__.return_value = mock_session

        chunks = []
        async for chunk in use_helper_get_response("http://helper", "sap"):
            chunks.append(chunk)

        assert len(chunks) == 0
        mock_logger.error.assert_called()


@pytest.mark.asyncio
async def test_use_helper_get_response_exception():
    with (
        patch("server.logger") as mock_logger,
        patch("aiohttp.ClientSession", side_effect=Exception("Network Error")),
    ):
        chunks = []
        async for chunk in use_helper_get_response("http://helper", "sap"):
            chunks.append(chunk)

        assert len(chunks) == 0
        mock_logger.error.assert_called()


# --- stream.py tests ---


@pytest.mark.asyncio
async def test_use_stream_response_success():
    # Setup queue data
    q_data = [
        json.dumps({"body": "chunk1", "done": False}),
        json.dumps({"body": "chunk2", "done": True}),
    ]

    mock_queue = MagicMock()
    mock_queue.get_nowait.side_effect = q_data + [queue.Empty()]

    with patch("server.STREAM_QUEUE", mock_queue), patch("server.logger"):
        chunks = []
        async for chunk in use_stream_response("req1"):
            chunks.append(chunk)

        assert len(chunks) == 2
        assert chunks[0]["body"] == "chunk1"
        assert chunks[1]["done"] is True


@pytest.mark.asyncio
async def test_use_stream_response_queue_none():
    with patch("server.STREAM_QUEUE", None), patch("server.logger") as mock_logger:
        chunks = []
        async for chunk in use_stream_response("req1"):
            chunks.append(chunk)

        assert len(chunks) == 0
        mock_logger.warning.assert_called_with(
            "[req1] STREAM_QUEUE is None, 无法使用流响应"
        )


@pytest.mark.asyncio
async def test_use_stream_response_timeout():
    # Simulate queue empty until timeout
    mock_queue = MagicMock()
    mock_queue.get_nowait.side_effect = queue.Empty

    with (
        patch("server.STREAM_QUEUE", mock_queue),
        patch("server.logger"),
        patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep,
    ):
        chunks = []
        async for chunk in use_stream_response("req1"):
            chunks.append(chunk)

        # Should yield timeout error
        assert len(chunks) == 1
        assert chunks[0]["reason"] == "internal_timeout"
        assert chunks[0]["done"] is True
        # Should have slept around 299 times (300 retries, sleep after each fail except last check)
        assert mock_sleep.call_count >= 299


@pytest.mark.asyncio
async def test_use_stream_response_mixed_types():
    # Test non-JSON string and dictionary data
    q_data = [
        "not-json",  # Should trigger JSONDecodeError path
        {"body": "dict-body", "done": False},  # Dictionary directly
        json.dumps({"body": "final", "done": True}),
    ]

    mock_queue = MagicMock()
    mock_queue.get_nowait.side_effect = q_data

    with patch("server.STREAM_QUEUE", mock_queue), patch("server.logger"):
        chunks = []
        async for chunk in use_stream_response("req1"):
            chunks.append(chunk)

        assert len(chunks) == 3
        assert chunks[0] == "not-json"
        assert chunks[1]["body"] == "dict-body"
        assert chunks[2]["done"] is True


@pytest.mark.asyncio
async def test_use_stream_response_ignore_stale_done():
    # First item is done=True with no content (stale), should be ignored
    # Second item is real content
    # Third item is real done
    q_data = [
        json.dumps({"done": True, "body": "", "reason": ""}),
        json.dumps({"body": "real content", "done": False}),
        json.dumps({"done": True, "body": "", "reason": ""}),
    ]

    mock_queue = MagicMock()
    mock_queue.get_nowait.side_effect = q_data

    with patch("server.STREAM_QUEUE", mock_queue), patch("server.logger"):
        chunks = []
        async for chunk in use_stream_response("req1"):
            chunks.append(chunk)

        # Should contain 2 items: real content and final done. Stale done ignored.
        assert len(chunks) == 2
        assert chunks[0]["body"] == "real content"
        assert chunks[1]["done"] is True


@pytest.mark.asyncio
async def test_clear_stream_queue():
    mock_queue = MagicMock()
    # 2 items then Empty
    mock_queue.get_nowait.side_effect = ["item1", "item2", queue.Empty]

    with (
        patch("server.STREAM_QUEUE", mock_queue),
        patch("server.logger") as mock_logger,
    ):
        await clear_stream_queue()

        assert mock_queue.get_nowait.call_count == 3
        # Should log that it cleared items
        warning_calls = mock_logger.warning.call_args_list
        assert len(warning_calls) > 0
        assert "共清理了 2 个残留项目" in warning_calls[0][0][0]


@pytest.mark.asyncio
async def test_clear_stream_queue_none():
    with patch("server.STREAM_QUEUE", None), patch("server.logger") as mock_logger:
        await clear_stream_queue()
        mock_logger.info.assert_called_with("流队列未初始化或已被禁用，跳过清空操作。")
