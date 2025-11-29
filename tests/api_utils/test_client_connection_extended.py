"""
High-quality tests for api_utils/client_connection.py - Extended coverage.

Focus: Test enhanced_disconnect_monitor and non_streaming_disconnect_monitor functions.
Strategy: Mock check_client_connection, Event, Future, asyncio.sleep to test all code paths.
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from api_utils.client_connection import (
    enhanced_disconnect_monitor,
    non_streaming_disconnect_monitor,
)


@pytest.mark.asyncio
async def test_enhanced_disconnect_monitor_client_disconnects():
    """
    测试场景: 客户端在流式响应期间断开连接
    预期: 返回 True, 设置 completion_event (lines 119-130)
    """
    req_id = "test-req-1"
    http_request = MagicMock()
    completion_event = asyncio.Event()
    logger = MagicMock()

    # Mock: check_client_connection returns False (disconnected)
    with patch(
        "api_utils.client_connection.check_client_connection",
        new_callable=AsyncMock,
        return_value=False,
    ):
        with patch("asyncio.sleep", new_callable=AsyncMock):
            result = await enhanced_disconnect_monitor(
                req_id, http_request, completion_event, logger
            )

    # 验证: 返回 True (客户端断开)
    assert result is True

    # 验证: completion_event 被设置 (line 129)
    assert completion_event.is_set()

    # 验证: logger.info 被调用 (lines 124-126)
    assert logger.info.call_count == 1
    log_message = logger.info.call_args[0][0]
    assert "Client disconnected during streaming" in log_message
    assert req_id in log_message


@pytest.mark.asyncio
async def test_enhanced_disconnect_monitor_completion_event_already_set():
    """
    测试场景: completion_event 已经设置 (正常完成)
    预期: 返回 False, 不检查客户端连接 (line 120)
    """
    req_id = "test-req-2"
    http_request = MagicMock()
    completion_event = asyncio.Event()
    completion_event.set()  # Already completed
    logger = MagicMock()

    with patch(
        "api_utils.client_connection.check_client_connection",
        new_callable=AsyncMock,
    ) as mock_check:
        result = await enhanced_disconnect_monitor(
            req_id, http_request, completion_event, logger
        )

    # 验证: 返回 False (未断开)
    assert result is False

    # 验证: check_client_connection 未被调用 (循环未执行)
    mock_check.assert_not_called()

    # 验证: logger.info 未被调用
    logger.info.assert_not_called()


@pytest.mark.asyncio
async def test_enhanced_disconnect_monitor_cancelled_error():
    """
    测试场景: 监控任务被取消 (asyncio.CancelledError)
    预期: 返回 False, 优雅退出 (lines 132-133)
    """
    req_id = "test-req-3"
    http_request = MagicMock()
    completion_event = asyncio.Event()
    logger = MagicMock()

    # Mock: check_client_connection raises CancelledError
    with patch(
        "api_utils.client_connection.check_client_connection",
        new_callable=AsyncMock,
        side_effect=asyncio.CancelledError,
    ):
        result = await enhanced_disconnect_monitor(
            req_id, http_request, completion_event, logger
        )

    # 验证: 返回 False (任务取消)
    assert result is False

    # 验证: logger.error 未被调用 (CancelledError 不记录错误)
    logger.error.assert_not_called()


@pytest.mark.asyncio
async def test_enhanced_disconnect_monitor_generic_exception():
    """
    测试场景: check_client_connection 抛出异常
    预期: 记录错误并退出 (lines 134-136)
    """
    req_id = "test-req-4"
    http_request = MagicMock()
    completion_event = asyncio.Event()
    logger = MagicMock()

    # Mock: check_client_connection raises generic exception
    with patch(
        "api_utils.client_connection.check_client_connection",
        new_callable=AsyncMock,
        side_effect=RuntimeError("Connection check failed"),
    ):
        result = await enhanced_disconnect_monitor(
            req_id, http_request, completion_event, logger
        )

    # 验证: 返回 False (异常退出)
    assert result is False

    # 验证: logger.error 被调用 (line 135)
    assert logger.error.call_count == 1
    error_message = logger.error.call_args[0][0]
    assert "Enhanced disconnect checker error" in error_message
    assert req_id in error_message


@pytest.mark.asyncio
async def test_enhanced_disconnect_monitor_client_stays_connected():
    """
    测试场景: 客户端保持连接, completion_event 由其他任务设置
    预期: 返回 False (正常完成)
    """
    req_id = "test-req-5"
    http_request = MagicMock()
    completion_event = asyncio.Event()
    logger = MagicMock()

    # Track number of connection checks
    check_count = 0

    async def mock_check_and_complete(*args, **kwargs):
        nonlocal check_count
        check_count += 1
        if check_count >= 3:
            # Simulate external task setting completion event
            completion_event.set()
        return True  # Client still connected

    with patch(
        "api_utils.client_connection.check_client_connection",
        new_callable=AsyncMock,
        side_effect=mock_check_and_complete,
    ):
        with patch("asyncio.sleep", new_callable=AsyncMock):
            result = await enhanced_disconnect_monitor(
                req_id, http_request, completion_event, logger
            )

    # 验证: 返回 False (客户端未断开)
    assert result is False

    # 验证: 进行了多次连接检查
    assert check_count >= 3

    # 验证: logger.info 未被调用 (无断开)
    logger.info.assert_not_called()


@pytest.mark.asyncio
async def test_non_streaming_disconnect_monitor_client_disconnects():
    """
    测试场景: 客户端在非流式响应期间断开连接
    预期: 返回 True, 在 result_future 设置异常 (lines 150-166)
    """
    req_id = "test-req-6"
    http_request = MagicMock()
    result_future = asyncio.Future()
    logger = MagicMock()

    # Mock: check_client_connection returns False (disconnected)
    with patch(
        "api_utils.client_connection.check_client_connection",
        new_callable=AsyncMock,
        return_value=False,
    ):
        with patch("asyncio.sleep", new_callable=AsyncMock):
            result = await non_streaming_disconnect_monitor(
                req_id, http_request, result_future, logger
            )

    # 验证: 返回 True (客户端断开)
    assert result is True

    # 验证: result_future 有异常 (lines 160-165)
    assert result_future.done()
    with pytest.raises(HTTPException) as exc_info:
        result_future.result()
    assert exc_info.value.status_code == 499
    assert req_id in exc_info.value.detail
    assert "Client disconnected" in exc_info.value.detail

    # 验证: logger.info 被调用 (lines 155-157)
    assert logger.info.call_count == 1
    log_message = logger.info.call_args[0][0]
    assert "Client disconnected during non-streaming" in log_message
    assert req_id in log_message


@pytest.mark.asyncio
async def test_non_streaming_disconnect_monitor_result_future_already_done():
    """
    测试场景: result_future 已经完成 (正常完成)
    预期: 返回 False, 不检查客户端连接 (line 151)
    """
    req_id = "test-req-7"
    http_request = MagicMock()
    result_future = asyncio.Future()
    result_future.set_result({"success": True})  # Already completed
    logger = MagicMock()

    with patch(
        "api_utils.client_connection.check_client_connection",
        new_callable=AsyncMock,
    ) as mock_check:
        result = await non_streaming_disconnect_monitor(
            req_id, http_request, result_future, logger
        )

    # 验证: 返回 False (未断开)
    assert result is False

    # 验证: check_client_connection 未被调用 (循环未执行)
    mock_check.assert_not_called()

    # 验证: logger.info 未被调用
    logger.info.assert_not_called()


@pytest.mark.asyncio
async def test_non_streaming_disconnect_monitor_cancelled_error():
    """
    测试场景: 监控任务被取消 (asyncio.CancelledError)
    预期: 返回 False, 优雅退出 (lines 168-169)
    """
    req_id = "test-req-8"
    http_request = MagicMock()
    result_future = asyncio.Future()
    logger = MagicMock()

    # Mock: check_client_connection raises CancelledError
    with patch(
        "api_utils.client_connection.check_client_connection",
        new_callable=AsyncMock,
        side_effect=asyncio.CancelledError,
    ):
        result = await non_streaming_disconnect_monitor(
            req_id, http_request, result_future, logger
        )

    # 验证: 返回 False (任务取消)
    assert result is False

    # 验证: logger.error 未被调用 (CancelledError 不记录错误)
    logger.error.assert_not_called()

    # 验证: result_future 未设置异常 (任务被取消)
    assert not result_future.done()


@pytest.mark.asyncio
async def test_non_streaming_disconnect_monitor_generic_exception():
    """
    测试场景: check_client_connection 抛出异常
    预期: 记录错误并退出 (lines 170-174)
    """
    req_id = "test-req-9"
    http_request = MagicMock()
    result_future = asyncio.Future()
    logger = MagicMock()

    # Mock: check_client_connection raises generic exception
    with patch(
        "api_utils.client_connection.check_client_connection",
        new_callable=AsyncMock,
        side_effect=RuntimeError("Connection check failed"),
    ):
        result = await non_streaming_disconnect_monitor(
            req_id, http_request, result_future, logger
        )

    # 验证: 返回 False (异常退出)
    assert result is False

    # 验证: logger.error 被调用 (line 171-173)
    assert logger.error.call_count == 1
    error_message = logger.error.call_args[0][0]
    assert "Non-streaming disconnect checker error" in error_message
    assert req_id in error_message

    # 验证: result_future 未设置异常 (异常退出)
    assert not result_future.done()


@pytest.mark.asyncio
async def test_non_streaming_disconnect_monitor_client_stays_connected():
    """
    测试场景: 客户端保持连接, result_future 由其他任务完成
    预期: 返回 False (正常完成)
    """
    req_id = "test-req-10"
    http_request = MagicMock()
    result_future = asyncio.Future()
    logger = MagicMock()

    # Track number of connection checks
    check_count = 0

    async def mock_check_and_complete(*args, **kwargs):
        nonlocal check_count
        check_count += 1
        if check_count >= 3:
            # Simulate external task setting result
            result_future.set_result({"status": "success"})
        return True  # Client still connected

    with patch(
        "api_utils.client_connection.check_client_connection",
        new_callable=AsyncMock,
        side_effect=mock_check_and_complete,
    ):
        with patch("asyncio.sleep", new_callable=AsyncMock):
            result = await non_streaming_disconnect_monitor(
                req_id, http_request, result_future, logger
            )

    # 验证: 返回 False (客户端未断开)
    assert result is False

    # 验证: 进行了多次连接检查
    assert check_count >= 3

    # 验证: logger.info 未被调用 (无断开)
    logger.info.assert_not_called()

    # 验证: result_future 正常完成
    assert result_future.done()
    assert result_future.result() == {"status": "success"}


@pytest.mark.asyncio
async def test_non_streaming_disconnect_monitor_already_has_exception():
    """
    测试场景: 检测到断开但 result_future 已有异常
    预期: 不覆盖已有异常 (line 159 条件判断)
    """
    req_id = "test-req-11"
    http_request = MagicMock()
    result_future = asyncio.Future()
    logger = MagicMock()

    # Track if we tried to set exception after future is done
    async def mock_check_disconnect(*args, **kwargs):
        # Simulate another task setting exception first
        if not result_future.done():
            result_future.set_exception(ValueError("Other error"))
        return False  # Disconnect detected

    with patch(
        "api_utils.client_connection.check_client_connection",
        new_callable=AsyncMock,
        side_effect=mock_check_disconnect,
    ):
        with patch("asyncio.sleep", new_callable=AsyncMock):
            result = await non_streaming_disconnect_monitor(
                req_id, http_request, result_future, logger
            )

    # 验证: 返回 True (断开检测到)
    assert result is True

    # 验证: result_future 有异常 (但不是 HTTPException 499)
    assert result_future.done()
    with pytest.raises(ValueError) as exc_info:
        result_future.result()
    assert str(exc_info.value) == "Other error"

    # 验证: logger.info 被调用 (断开检测)
    assert logger.info.call_count == 1


@pytest.mark.asyncio
async def test_enhanced_disconnect_monitor_event_set_during_check():
    """
    测试场景: completion_event 在连接检查期间被设置
    预期: 不设置 client_disconnected_early, 退出循环 (lines 128-129)
    """
    req_id = "test-req-12"
    http_request = MagicMock()
    completion_event = asyncio.Event()
    logger = MagicMock()

    async def mock_check_and_set_event(*args, **kwargs):
        # Event set before we check if disconnected
        completion_event.set()
        return False  # Disconnected, but event already set

    with patch(
        "api_utils.client_connection.check_client_connection",
        new_callable=AsyncMock,
        side_effect=mock_check_and_set_event,
    ):
        with patch("asyncio.sleep", new_callable=AsyncMock):
            result = await enhanced_disconnect_monitor(
                req_id, http_request, completion_event, logger
            )

    # 验证: 返回 True (因为检测到断开)
    assert result is True

    # 验证: completion_event 已设置
    assert completion_event.is_set()

    # 验证: logger.info 被调用 (检测到断开)
    assert logger.info.call_count == 1
