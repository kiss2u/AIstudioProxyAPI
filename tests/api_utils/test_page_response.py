"""
High-quality tests for api_utils/page_response.py - Response element location.

Focus: Test locate_response_elements with success and error paths.
Strategy: Mock Playwright page and locators, test timeout and exception handling.
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException
from playwright.async_api import Error as PlaywrightAsyncError

from api_utils.page_response import locate_response_elements
from models.exceptions import ClientDisconnectedError


@pytest.mark.asyncio
async def test_locate_response_elements_success():
    """
    测试场景: 响应元素成功定位
    预期: 正常完成,记录两次 logger.info (lines 14, 22)
    """
    logger = MagicMock()
    page = MagicMock()
    check_client_disconnected = MagicMock()

    # Mock locator chain
    response_container_locator = MagicMock()
    response_element_locator = MagicMock()
    page.locator.return_value.last = response_container_locator
    response_container_locator.locator.return_value = response_element_locator

    # Mock expect_async to succeed immediately
    with patch("api_utils.page_response.expect_async") as mock_expect:
        mock_expect_result = AsyncMock()
        mock_expect_result.to_be_attached = AsyncMock()
        mock_expect.return_value = mock_expect_result

        await locate_response_elements(page, "req1", logger, check_client_disconnected)

        # 验证: logger.info 被调用两次 (lines 14, 22)
        assert logger.info.call_count == 2
        assert "[req1] 定位响应元素..." in logger.info.call_args_list[0][0][0]
        assert "[req1] 响应元素已定位。" in logger.info.call_args_list[1][0][0]

        # 验证: check_client_disconnected 被调用 (line 20)
        check_client_disconnected.assert_called_once_with(
            "After Response Container Attached: "
        )

        # 验证: expect_async 被调用两次 (container + element)
        assert mock_expect.call_count == 2
        assert mock_expect_result.to_be_attached.call_count == 2


@pytest.mark.asyncio
async def test_locate_response_elements_container_timeout():
    """
    测试场景: 响应容器定位超时 (PlaywrightAsyncError)
    预期: 抛出 HTTPException 502 (lines 23-26)
    """
    logger = MagicMock()
    page = MagicMock()
    check_client_disconnected = MagicMock()

    # Mock locator chain
    response_container_locator = MagicMock()
    page.locator.return_value.last = response_container_locator
    response_container_locator.locator.return_value = MagicMock()

    # Mock expect_async to raise PlaywrightAsyncError on first call
    with patch("api_utils.page_response.expect_async") as mock_expect:
        mock_expect_result = AsyncMock()
        mock_expect_result.to_be_attached = AsyncMock(
            side_effect=PlaywrightAsyncError("Timeout 20000ms exceeded")
        )
        mock_expect.return_value = mock_expect_result

        with pytest.raises(HTTPException) as exc_info:
            await locate_response_elements(
                page, "req1", logger, check_client_disconnected
            )

        # 验证: HTTPException status code 502 (upstream error)
        assert exc_info.value.status_code == 502
        # 验证: 错误消息包含 "定位AI Studio响应元素失败" (line 26)
        assert "定位AI Studio响应元素失败" in exc_info.value.detail
        assert "Timeout 20000ms exceeded" in exc_info.value.detail


@pytest.mark.asyncio
async def test_locate_response_elements_element_timeout():
    """
    测试场景: 响应文本元素定位超时 (asyncio.TimeoutError)
    预期: 抛出 HTTPException 502 (lines 23-26)
    """
    logger = MagicMock()
    page = MagicMock()
    check_client_disconnected = MagicMock()

    # Mock locator chain
    response_container_locator = MagicMock()
    response_element_locator = MagicMock()
    page.locator.return_value.last = response_container_locator
    response_container_locator.locator.return_value = response_element_locator

    # Mock expect_async: succeed on first call (container), fail on second (element)
    with patch("api_utils.page_response.expect_async") as mock_expect:
        mock_expect_result_container = AsyncMock()
        mock_expect_result_container.to_be_attached = AsyncMock()

        mock_expect_result_element = AsyncMock()
        mock_expect_result_element.to_be_attached = AsyncMock(
            side_effect=asyncio.TimeoutError("90000ms timeout")
        )

        # First call returns container result, second call returns element result
        mock_expect.side_effect = [
            mock_expect_result_container,
            mock_expect_result_element,
        ]

        with pytest.raises(HTTPException) as exc_info:
            await locate_response_elements(
                page, "req1", logger, check_client_disconnected
            )

        # 验证: HTTPException status code 502 (upstream error)
        assert exc_info.value.status_code == 502
        # 验证: 错误消息包含 "定位AI Studio响应元素失败" (line 26)
        assert "定位AI Studio响应元素失败" in exc_info.value.detail


@pytest.mark.asyncio
async def test_locate_response_elements_client_disconnected():
    """
    测试场景: 客户端在定位过程中断开连接
    预期: 抛出 HTTPException 500 (generic Exception handler wraps it)
    """
    logger = MagicMock()
    page = MagicMock()
    check_client_disconnected = MagicMock(
        side_effect=ClientDisconnectedError("Client disconnected")
    )

    # Mock locator chain
    response_container_locator = MagicMock()
    response_element_locator = MagicMock()
    page.locator.return_value.last = response_container_locator
    response_container_locator.locator.return_value = response_element_locator

    # Mock expect_async to succeed (但 check_client_disconnected 会先抛出异常)
    with patch("api_utils.page_response.expect_async") as mock_expect:
        mock_expect_result = AsyncMock()
        mock_expect_result.to_be_attached = AsyncMock()
        mock_expect.return_value = mock_expect_result

        with pytest.raises(HTTPException) as exc_info:
            await locate_response_elements(
                page, "req1", logger, check_client_disconnected
            )

        # 验证: HTTPException status code 500 (server error from generic handler)
        assert exc_info.value.status_code == 500
        # 验证: 错误消息包含 "定位响应元素时意外错误" (line 30)
        assert "定位响应元素时意外错误" in exc_info.value.detail
        # 验证: check_client_disconnected 被调用 (line 20)
        check_client_disconnected.assert_called_once()


@pytest.mark.asyncio
async def test_locate_response_elements_generic_exception():
    """
    测试场景: 意外错误 (非 Playwright/Timeout) 在 try 块内发生
    预期: 抛出 HTTPException 500 (lines 27-30)
    """
    logger = MagicMock()
    page = MagicMock()
    check_client_disconnected = MagicMock()

    # Mock locator chain
    response_container_locator = MagicMock()
    response_element_locator = MagicMock()
    page.locator.return_value.last = response_container_locator
    response_container_locator.locator.return_value = response_element_locator

    # Mock expect_async to raise generic exception (inside try block)
    with patch("api_utils.page_response.expect_async") as mock_expect:
        mock_expect.side_effect = ValueError("Unexpected validation error")

        with pytest.raises(HTTPException) as exc_info:
            await locate_response_elements(
                page, "req1", logger, check_client_disconnected
            )

        # 验证: HTTPException status code 500 (server error)
        assert exc_info.value.status_code == 500
        # 验证: 错误消息包含 "定位响应元素时意外错误" (line 30)
        assert "定位响应元素时意外错误" in exc_info.value.detail
        assert "Unexpected validation error" in exc_info.value.detail


@pytest.mark.asyncio
async def test_locate_response_elements_logger_messages():
    """
    测试场景: 验证完整的 logger 消息
    预期: 正确记录 req_id 和上下文信息
    """
    logger = MagicMock()
    page = MagicMock()
    check_client_disconnected = MagicMock()

    # Mock locator chain
    response_container_locator = MagicMock()
    response_element_locator = MagicMock()
    page.locator.return_value.last = response_container_locator
    response_container_locator.locator.return_value = response_element_locator

    # Mock expect_async
    with patch("api_utils.page_response.expect_async") as mock_expect:
        mock_expect_result = AsyncMock()
        mock_expect_result.to_be_attached = AsyncMock()
        mock_expect.return_value = mock_expect_result

        await locate_response_elements(
            page, "test-req-123", logger, check_client_disconnected
        )

        # 验证: logger.info 包含正确的 req_id
        first_log = logger.info.call_args_list[0][0][0]
        assert "[test-req-123]" in first_log
        assert "定位响应元素..." in first_log

        second_log = logger.info.call_args_list[1][0][0]
        assert "[test-req-123]" in second_log
        assert "响应元素已定位。" in second_log


@pytest.mark.asyncio
async def test_locate_response_elements_locator_chain():
    """
    测试场景: 验证正确的 locator 调用链
    预期: page.locator(SELECTOR).last.locator(TEXT_SELECTOR)
    """
    logger = MagicMock()
    page = MagicMock()
    check_client_disconnected = MagicMock()

    # Mock locator chain
    response_container_locator = MagicMock()
    response_element_locator = MagicMock()
    page.locator.return_value.last = response_container_locator
    response_container_locator.locator.return_value = response_element_locator

    # Mock expect_async
    with patch("api_utils.page_response.expect_async") as mock_expect:
        mock_expect_result = AsyncMock()
        mock_expect_result.to_be_attached = AsyncMock()
        mock_expect.return_value = mock_expect_result

        await locate_response_elements(page, "req1", logger, check_client_disconnected)

        # 验证: page.locator 被调用 (line 15)
        from config import RESPONSE_CONTAINER_SELECTOR

        page.locator.assert_called_once_with(RESPONSE_CONTAINER_SELECTOR)

        # 验证: response_container.locator 被调用 (line 16)
        from config import RESPONSE_TEXT_SELECTOR

        response_container_locator.locator.assert_called_once_with(
            RESPONSE_TEXT_SELECTOR
        )


@pytest.mark.asyncio
async def test_locate_response_elements_timeout_values():
    """
    测试场景: 验证超时参数传递正确
    预期: container=20000ms, element=90000ms (lines 19, 21)
    """
    logger = MagicMock()
    page = MagicMock()
    check_client_disconnected = MagicMock()

    # Mock locator chain
    response_container_locator = MagicMock()
    response_element_locator = MagicMock()
    page.locator.return_value.last = response_container_locator
    response_container_locator.locator.return_value = response_element_locator

    # Mock expect_async
    with patch("api_utils.page_response.expect_async") as mock_expect:
        mock_expect_result = AsyncMock()
        mock_expect_result.to_be_attached = AsyncMock()
        mock_expect.return_value = mock_expect_result

        await locate_response_elements(page, "req1", logger, check_client_disconnected)

        # 验证: to_be_attached 被调用两次,超时参数正确
        calls = mock_expect_result.to_be_attached.call_args_list
        assert calls[0][1]["timeout"] == 20000  # Container timeout
        assert calls[1][1]["timeout"] == 90000  # Element timeout
