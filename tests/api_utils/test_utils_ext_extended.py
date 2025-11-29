"""
Extended tests for api_utils/utils_ext/stream.py - Edge case coverage.

Focus: Cover uncovered error paths, exception handling, and edge cases.
Strategy: Test None signal, error detection, dict stale data, exceptions.
"""

import json
import queue
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from api_utils.utils_ext.stream import clear_stream_queue, use_stream_response
from models.exceptions import QuotaExceededError, UpstreamError


@pytest.mark.asyncio
async def test_use_stream_response_none_signal():
    """
    测试场景: 接收到 None 作为流结束信号
    预期: 正常结束,不返回任何内容 (lines 28-30)
    """
    mock_queue = MagicMock()
    mock_queue.get_nowait.side_effect = [None]  # None 是结束信号

    with patch("server.STREAM_QUEUE", mock_queue), patch("server.logger"):
        chunks = []
        async for chunk in use_stream_response("req1"):
            chunks.append(chunk)

        assert len(chunks) == 0  # None 信号不产生任何输出


@pytest.mark.asyncio
async def test_use_stream_response_quota_exceeded_error():
    """
    测试场景: 接收到 quota 错误信号 (status 429)
    预期: 抛出 QuotaExceededError (lines 44-65)
    """
    error_data = json.dumps(
        {"error": True, "status": 429, "message": "Quota exceeded for this project"}
    )

    mock_queue = MagicMock()
    mock_queue.get_nowait.side_effect = [error_data]

    with patch("server.STREAM_QUEUE", mock_queue), patch("server.logger"):
        with pytest.raises(QuotaExceededError) as exc_info:
            async for chunk in use_stream_response("req1"):
                pass

        assert "AI Studio quota exceeded" in str(exc_info.value)
        assert exc_info.value.req_id == "req1"


@pytest.mark.asyncio
async def test_use_stream_response_quota_error_by_message():
    """
    测试场景: 错误信息包含 "quota" 关键字
    预期: 抛出 QuotaExceededError (lines 58-65)
    """
    error_data = json.dumps(
        {"error": True, "status": 500, "message": "Your project quota has been reached"}
    )

    mock_queue = MagicMock()
    mock_queue.get_nowait.side_effect = [error_data]

    with patch("server.STREAM_QUEUE", mock_queue), patch("server.logger"):
        with pytest.raises(QuotaExceededError):
            async for chunk in use_stream_response("req1"):
                pass


@pytest.mark.asyncio
async def test_use_stream_response_upstream_error():
    """
    测试场景: 接收到非 quota 的上游错误 (status 500)
    预期: 抛出 UpstreamError (lines 66-74)
    """
    error_data = json.dumps(
        {"error": True, "status": 500, "message": "Internal server error"}
    )

    mock_queue = MagicMock()
    mock_queue.get_nowait.side_effect = [error_data]

    with patch("server.STREAM_QUEUE", mock_queue), patch("server.logger"):
        with pytest.raises(UpstreamError) as exc_info:
            async for chunk in use_stream_response("req1"):
                pass

        assert "AI Studio error" in str(exc_info.value)
        # status_code is stored in context dict, not direct attribute
        assert exc_info.value.context.get("status_code") == 500


@pytest.mark.asyncio
async def test_use_stream_response_dict_with_stale_done():
    """
    测试场景: 字典格式数据,第一个是 stale done (无内容)
    预期: Yields stale done, continues instead of breaking (lines 116-129)
    Note: Dict format ALWAYS yields first (line 109), then checks stale.
    """
    q_data = [
        {"done": True, "body": "", "reason": ""},  # Stale done (dict format)
        {"body": "real content", "done": False},  # Real data
        {"done": True, "body": "final", "reason": ""},  # Real done
    ]

    mock_queue = MagicMock()
    mock_queue.get_nowait.side_effect = q_data

    with (
        patch("server.STREAM_QUEUE", mock_queue),
        patch("server.logger") as mock_logger,
    ):
        chunks = []
        async for chunk in use_stream_response("req1"):
            chunks.append(chunk)

        # Dict always yields first, so all 3 chunks yielded
        # But stale detection prevents breaking on first done
        assert len(chunks) == 3
        assert chunks[0]["done"] is True  # Stale done yielded
        assert chunks[1]["body"] == "real content"
        assert chunks[2]["done"] is True  # Real done

        # Verify stale warning was logged (line 124)
        warning_calls = [
            c for c in mock_logger.warning.call_args_list if "STALE DATA" in str(c)
        ]
        assert len(warning_calls) > 0


@pytest.mark.asyncio
async def test_use_stream_response_timeout_after_data():
    """
    测试场景: 接收部分数据后超时
    预期: 记录警告并返回超时信号 (line 144)
    """
    q_data = [
        json.dumps({"body": "some data", "done": False}),
    ] + [queue.Empty] * 301  # 先收到数据,然后一直空

    mock_queue = MagicMock()
    mock_queue.get_nowait.side_effect = q_data

    with (
        patch("server.STREAM_QUEUE", mock_queue),
        patch("server.logger") as mock_logger,
        patch("asyncio.sleep", new_callable=AsyncMock),
    ):
        chunks = []
        async for chunk in use_stream_response("req1"):
            chunks.append(chunk)

        # Should have data chunk + timeout chunk
        assert len(chunks) == 2
        assert chunks[0]["body"] == "some data"
        assert chunks[1]["reason"] == "internal_timeout"

        # Verify warning was logged (line 144)
        warning_calls = [
            c
            for c in mock_logger.warning.call_args_list
            if "空读取次数达到上限" in str(c)
        ]
        assert len(warning_calls) > 0


@pytest.mark.asyncio
async def test_use_stream_response_generic_exception():
    """
    测试场景: 在处理过程中发生异常
    预期: 记录错误并重新抛出 (lines 156-158)
    """
    mock_queue = MagicMock()
    mock_queue.get_nowait.side_effect = RuntimeError("Unexpected error")

    with (
        patch("server.STREAM_QUEUE", mock_queue),
        patch("server.logger") as mock_logger,
    ):
        with pytest.raises(RuntimeError, match="Unexpected error"):
            async for chunk in use_stream_response("req1"):
                pass

        # Verify error was logged (line 157)
        error_calls = [
            c for c in mock_logger.error.call_args_list if "使用流响应时出错" in str(c)
        ]
        assert len(error_calls) > 0


@pytest.mark.asyncio
async def test_clear_stream_queue_exception_during_clear():
    """
    测试场景: 清空队列时发生异常
    预期: 记录错误并停止清空 (lines 189-194)
    """
    mock_queue = MagicMock()
    # Get 2 items, then raise exception
    mock_queue.get_nowait.side_effect = ["item1", "item2", RuntimeError("Queue error")]

    with (
        patch("server.STREAM_QUEUE", mock_queue),
        patch("server.logger") as mock_logger,
    ):
        await clear_stream_queue()

        # Should have gotten 2 items before exception
        assert mock_queue.get_nowait.call_count == 3

        # Verify error was logged (line 190-193)
        error_calls = [
            c
            for c in mock_logger.error.call_args_list
            if "清空流式队列时发生意外错误" in str(c)
        ]
        assert len(error_calls) > 0
        assert "已清空2项" in error_calls[0][0][0]


@pytest.mark.asyncio
async def test_clear_stream_queue_empty_queue():
    """
    测试场景: 清空一个空队列
    预期: 记录信息日志 (line 201)
    """
    mock_queue = MagicMock()
    mock_queue.get_nowait.side_effect = [queue.Empty]  # Immediately empty

    with (
        patch("server.STREAM_QUEUE", mock_queue),
        patch("server.logger") as mock_logger,
    ):
        await clear_stream_queue()

        # Verify info log for empty queue (line 201)
        info_calls = [
            c for c in mock_logger.info.call_args_list if "队列为空" in str(c)
        ]
        assert len(info_calls) > 0
