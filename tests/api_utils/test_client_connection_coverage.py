"""
Extended tests for api_utils/client_connection.py - Final coverage completion.

Focus: Cover the last 6 uncovered lines (43, 46-47, 83, 86, 107).
Strategy: Test edge cases in check_client_connection, connected monitoring, and check helper.
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import Request

from api_utils.client_connection import (
    check_client_connection,
    setup_disconnect_monitoring,
)


@pytest.mark.asyncio
async def test_check_client_connection_via_is_disconnected():
    """
    测试场景: _receive 超时,但 is_disconnected() 返回 True
    预期: 返回 False (line 43)
    """
    req_id = "test_req"
    request = MagicMock(spec=Request)

    # _receive 不立即返回断开消息,而是超时
    async def mock_receive():
        await asyncio.sleep(1)  # Will timeout in check
        return {"type": "http.request"}

    request._receive = mock_receive
    # is_disconnected() 返回 True
    request.is_disconnected = AsyncMock(return_value=True)

    # 执行
    result = await check_client_connection(req_id, request)

    # 验证: 返回 False (line 43 执行)
    assert result is False


@pytest.mark.asyncio
async def test_check_client_connection_outer_exception():
    """
    测试场景: is_disconnected() 抛出异常
    预期: 返回 False (lines 46-47)
    """
    req_id = "test_req"
    request = MagicMock(spec=Request)

    # _receive 超时
    async def mock_receive():
        await asyncio.sleep(1)
        return {"type": "http.request"}

    request._receive = mock_receive
    # is_disconnected() 抛出异常
    request.is_disconnected = AsyncMock(side_effect=Exception("is_disconnected error"))

    # 执行
    result = await check_client_connection(req_id, request)

    # 验证: 返回 False (lines 46-47 执行)
    assert result is False


@pytest.mark.asyncio
async def test_setup_disconnect_monitoring_client_stays_connected():
    """
    测试场景: 客户端保持连接,result_future 由其他任务完成
    预期: 监控任务正常循环,执行 sleep (line 83)
    """
    req_id = "test_req"
    request = MagicMock(spec=Request)
    result_future = asyncio.Future()

    # Track check calls
    check_count = 0

    async def mock_check_connected(*args, **kwargs):
        nonlocal check_count
        check_count += 1
        if check_count >= 3:
            # Complete the future to stop the loop
            if not result_future.done():
                result_future.set_result({"status": "success"})
        return True  # Client stays connected

    with patch(
        "api_utils.client_connection.check_client_connection",
        new_callable=AsyncMock,
        side_effect=mock_check_connected,
    ):
        event, task, check_func = await setup_disconnect_monitoring(
            req_id, request, result_future
        )

        # Wait for multiple checks
        await asyncio.sleep(1.2)  # Allow 3+ checks (0.3s sleep each)

        # 验证: 进行了多次检查 (line 83 executed multiple times)
        assert check_count >= 3

        # 验证: future 正常完成
        assert result_future.done()
        assert result_future.result() == {"status": "success"}

        # 验证: event 未设置 (无断开)
        assert not event.is_set()

        # Cleanup
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass


@pytest.mark.asyncio
async def test_setup_disconnect_monitoring_task_cancelled():
    """
    测试场景: 监控任务被取消
    预期: CancelledError 被捕获,任务优雅退出 (line 86)
    """
    req_id = "test_req"
    request = MagicMock(spec=Request)
    result_future = asyncio.Future()

    # Mock check to return True (connected), so it enters the sleep
    with patch(
        "api_utils.client_connection.check_client_connection",
        new_callable=AsyncMock,
        return_value=True,
    ):
        event, task, check_func = await setup_disconnect_monitoring(
            req_id, request, result_future
        )

        # Give it time to start one check cycle
        await asyncio.sleep(0.1)

        # 执行: 取消任务
        task.cancel()

        # 验证: 任务被取消 (line 86 executed)
        # 任务会捕获 CancelledError 并优雅退出,不会重新抛出
        try:
            await task
        except asyncio.CancelledError:
            # If it does raise, that's also fine
            pass

        # 验证: 任务已完成
        assert task.done()

        # 验证: event 未设置 (任务被取消,不是断开)
        assert not event.is_set()


@pytest.mark.asyncio
async def test_check_client_disconnected_not_disconnected():
    """
    测试场景: 调用 check_client_disconnected() 但事件未设置
    预期: 返回 False,不抛出异常 (line 107)
    """
    req_id = "test_req"
    request = MagicMock(spec=Request)
    result_future = asyncio.Future()

    # Mock check to keep client connected
    with patch(
        "api_utils.client_connection.check_client_connection",
        new_callable=AsyncMock,
        return_value=True,
    ):
        event, task, check_func = await setup_disconnect_monitoring(
            req_id, request, result_future
        )

        # Wait a bit but don't let it disconnect
        await asyncio.sleep(0.1)

        # 执行: 调用 check 函数
        result = check_func("test_stage")

        # 验证: 返回 False (line 107), 不抛出异常
        assert result is False

        # 验证: event 未设置
        assert not event.is_set()

        # Cleanup
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
