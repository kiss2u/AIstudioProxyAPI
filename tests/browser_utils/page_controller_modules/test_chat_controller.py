from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from playwright.async_api import TimeoutError

from browser_utils.page_controller_modules.chat import ChatController

# Mock config constants
CONSTANTS = {
    "CLEAR_CHAT_BUTTON_SELECTOR": "button.clear",
    "CLEAR_CHAT_CONFIRM_BUTTON_SELECTOR": "button.confirm",
    "CLEAR_CHAT_VERIFY_TIMEOUT_MS": 1000,
    "CLICK_TIMEOUT_MS": 1000,
    "OVERLAY_SELECTOR": "div.overlay",
    "RESPONSE_CONTAINER_SELECTOR": "div.response",
    "SUBMIT_BUTTON_SELECTOR": "button.submit",
    "WAIT_FOR_ELEMENT_TIMEOUT_MS": 1000,
}


@pytest.fixture(autouse=True)
def mock_constants():
    with patch.multiple("browser_utils.page_controller_modules.chat", **CONSTANTS):
        yield


@pytest.fixture
def mock_page_controller():
    controller = MagicMock()
    controller.page = MagicMock()
    controller.logger = MagicMock()
    controller.req_id = "test-req-id"
    # Setup page methods as AsyncMock
    controller.page.locator = MagicMock()
    controller.page.keyboard = MagicMock()
    controller.page.keyboard.press = AsyncMock()
    controller._check_disconnect = AsyncMock()
    return controller


@pytest.fixture
def chat_controller(mock_page_controller):
    # The BaseController __init__ requires (page, logger, req_id)
    # We'll just pass mock objects from mock_page_controller
    return ChatController(
        mock_page_controller.page,
        mock_page_controller.logger,
        mock_page_controller.req_id,
    )


@pytest.fixture
def mock_expect_async():
    with patch("browser_utils.page_controller_modules.chat.expect_async") as mock:
        # Create a mock object that supports .to_be_enabled(), .to_be_disabled(), etc.
        # These methods should return an awaitable (AsyncMock)
        assertion_mock = MagicMock()
        assertion_mock.to_be_enabled = AsyncMock()
        assertion_mock.to_be_disabled = AsyncMock()
        assertion_mock.to_be_visible = AsyncMock()
        assertion_mock.to_be_hidden = AsyncMock()

        mock.return_value = assertion_mock
        yield mock


@pytest.fixture
def mock_enable_temp_chat():
    with patch(
        "browser_utils.page_controller_modules.chat.enable_temporary_chat_mode",
        new_callable=AsyncMock,
    ) as mock:
        yield mock


@pytest.fixture
def mock_save_snapshot():
    with patch(
        "browser_utils.page_controller_modules.chat.save_error_snapshot",
        new_callable=AsyncMock,
    ) as mock:
        yield mock


@pytest.mark.asyncio
@pytest.mark.timeout(5)
async def test_clear_chat_history_success(
    chat_controller, mock_page_controller, mock_expect_async, mock_enable_temp_chat
):
    """Test successful chat clearing flow."""
    mock_check_disconnect = MagicMock(return_value=False)

    # Setup locators
    submit_btn = MagicMock()
    submit_btn.click = AsyncMock()
    clear_btn = MagicMock()
    clear_btn.click = AsyncMock()
    clear_btn.scroll_into_view_if_needed = AsyncMock()
    confirm_btn = MagicMock()
    confirm_btn.click = AsyncMock()
    confirm_btn.scroll_into_view_if_needed = AsyncMock()
    overlay = MagicMock()
    overlay.is_visible = AsyncMock(return_value=False)
    response_container = MagicMock()

    # Mock locator calls
    def locator_side_effect(selector):
        if selector == CONSTANTS["SUBMIT_BUTTON_SELECTOR"]:
            return submit_btn
        elif selector == CONSTANTS["CLEAR_CHAT_BUTTON_SELECTOR"]:
            return clear_btn
        elif selector == CONSTANTS["CLEAR_CHAT_CONFIRM_BUTTON_SELECTOR"]:
            return confirm_btn
        elif selector == CONSTANTS["OVERLAY_SELECTOR"]:
            return overlay
        elif selector == CONSTANTS["RESPONSE_CONTAINER_SELECTOR"]:
            return response_container
        return MagicMock()

    mock_page_controller.page.locator.side_effect = locator_side_effect

    # Mock response container .last
    response_container.last = response_container

    # Mock url
    mock_page_controller.page.url = "https://example.com/c/123"

    # Mock _execute_chat_clear and _verify_chat_cleared to simplify main flow test
    # (We will test them separately, but here we want to ensure they are called)
    with (
        patch.object(
            chat_controller, "_execute_chat_clear", new_callable=AsyncMock
        ) as mock_exec,
        patch.object(
            chat_controller, "_verify_chat_cleared", new_callable=AsyncMock
        ) as mock_verify,
    ):
        await chat_controller.clear_chat_history(mock_check_disconnect)

        # Verify submit button flow
        assert submit_btn.click.called

        # Verify clear execution
        mock_exec.assert_awaited_once()
        mock_verify.assert_awaited_once()
        mock_enable_temp_chat.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.timeout(5)
async def test_clear_chat_history_new_chat_skip(
    chat_controller, mock_page_controller, mock_expect_async
):
    """Test that clear chat is skipped if already on new_chat page."""
    mock_check_disconnect = MagicMock(return_value=False)

    # Mock submit button check passes
    submit_btn = MagicMock()
    submit_btn.click = AsyncMock()
    mock_page_controller.page.locator.return_value = submit_btn

    # Mock clear button check fails (not enabled)
    mock_expect_async.return_value.to_be_enabled.side_effect = Exception("Not enabled")

    # Mock URL to be new_chat
    mock_page_controller.page.url = "https://example.com/prompts/new_chat"

    with patch.object(
        chat_controller, "_execute_chat_clear", new_callable=AsyncMock
    ) as mock_exec:
        await chat_controller.clear_chat_history(mock_check_disconnect)

        # Should catch exception, log info, and NOT call execute
        mock_exec.assert_not_called()
        # Verify we logged the skip message
        # We can't easily check log message content with MagicMock unless we configure it,
        # but we verify the flow didn't proceed.


@pytest.mark.asyncio
@pytest.mark.timeout(5)
async def test_execute_chat_clear_overlay_visible(
    chat_controller, mock_page_controller
):
    """Test _execute_chat_clear when overlay is initially visible."""
    mock_check_disconnect = MagicMock(return_value=False)

    clear_btn = MagicMock()
    confirm_btn = MagicMock()
    confirm_btn.click = AsyncMock()
    overlay = MagicMock()
    overlay.is_visible = AsyncMock(return_value=True)  # Visible!

    # Setup expect_async mock for disappear check
    with patch(
        "browser_utils.page_controller_modules.chat.expect_async"
    ) as mock_expect:
        mock_expect.return_value.to_be_hidden = AsyncMock()

        await chat_controller._execute_chat_clear(
            clear_btn, confirm_btn, overlay, mock_check_disconnect
        )

        # Should click confirm directly
        confirm_btn.click.assert_awaited()
        clear_btn.click.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.timeout(5)
async def test_execute_chat_clear_overlay_hidden_initially(
    chat_controller, mock_page_controller
):
    """Test _execute_chat_clear when overlay is initially hidden."""
    mock_check_disconnect = MagicMock(return_value=False)

    clear_btn = MagicMock()
    clear_btn.click = AsyncMock()
    clear_btn.scroll_into_view_if_needed = AsyncMock()

    confirm_btn = MagicMock()
    confirm_btn.click = AsyncMock()
    confirm_btn.scroll_into_view_if_needed = AsyncMock()

    overlay = MagicMock()
    overlay.is_visible = AsyncMock(return_value=False)  # Hidden initially

    with patch(
        "browser_utils.page_controller_modules.chat.expect_async"
    ) as mock_expect:
        mock_expect.return_value.to_be_visible = AsyncMock()  # Overlay appears
        mock_expect.return_value.to_be_hidden = AsyncMock()  # Overlay disappears

        with patch.object(
            chat_controller, "_dismiss_backdrops", new_callable=AsyncMock
        ):
            await chat_controller._execute_chat_clear(
                clear_btn, confirm_btn, overlay, mock_check_disconnect
            )

            # Should click clear first
            clear_btn.click.assert_awaited()
            # Then check overlay visible
            mock_expect.return_value.to_be_visible.assert_awaited()
            # Then click confirm
            confirm_btn.click.assert_awaited()


@pytest.mark.asyncio
@pytest.mark.timeout(5)
async def test_dismiss_backdrops(chat_controller, mock_page_controller):
    """Test _dismiss_backdrops logic."""
    backdrop = MagicMock()
    # First call returns count 1 (exists), second call returns 0 (gone)
    backdrop.count = AsyncMock(side_effect=[1, 0])

    mock_page_controller.page.locator.return_value = backdrop

    with patch(
        "browser_utils.page_controller_modules.chat.expect_async"
    ) as mock_expect:
        mock_expect.return_value.to_be_hidden = AsyncMock()

        await chat_controller._dismiss_backdrops()

        # Should have pressed Escape
        mock_page_controller.page.keyboard.press.assert_awaited_with("Escape")
        # Should have checked hidden
        mock_expect.return_value.to_be_hidden.assert_awaited()


@pytest.mark.asyncio
@pytest.mark.timeout(5)
async def test_verify_chat_cleared_success(chat_controller, mock_page_controller):
    """Test _verify_chat_cleared success."""
    mock_check_disconnect = MagicMock(return_value=False)

    response_container = MagicMock()
    response_container.last = response_container
    mock_page_controller.page.locator.return_value = response_container

    with patch(
        "browser_utils.page_controller_modules.chat.expect_async"
    ) as mock_expect:
        mock_expect.return_value.to_be_hidden = AsyncMock()

        await chat_controller._verify_chat_cleared(mock_check_disconnect)

        mock_expect.return_value.to_be_hidden.assert_awaited()


@pytest.mark.asyncio
@pytest.mark.timeout(5)
async def test_verify_chat_cleared_failure(chat_controller, mock_page_controller):
    """Test _verify_chat_cleared failure (should log warning but not raise)."""
    mock_check_disconnect = MagicMock(return_value=False)

    response_container = MagicMock()
    response_container.last = response_container
    mock_page_controller.page.locator.return_value = response_container

    with patch(
        "browser_utils.page_controller_modules.chat.expect_async"
    ) as mock_expect:
        mock_expect.return_value.to_be_hidden = AsyncMock(
            side_effect=Exception("Still visible")
        )

        # Should not raise exception
        await chat_controller._verify_chat_cleared(mock_check_disconnect)

        # Verify warning logged
        mock_page_controller.logger.warning.assert_called()


@pytest.mark.asyncio
@pytest.mark.timeout(5)
async def test_execute_chat_clear_retries(chat_controller, mock_page_controller):
    """Test _execute_chat_clear retries and force clicks."""
    mock_check_disconnect = MagicMock(return_value=False)

    clear_btn = MagicMock()
    # First click fails, second (force) succeeds
    clear_btn.click = AsyncMock(side_effect=[Exception("Click failed"), None])
    clear_btn.scroll_into_view_if_needed = AsyncMock()

    confirm_btn = MagicMock()
    confirm_btn.click = AsyncMock()

    overlay = MagicMock()
    overlay.is_visible = AsyncMock(return_value=False)

    with patch(
        "browser_utils.page_controller_modules.chat.expect_async"
    ) as mock_expect:
        mock_expect.return_value.to_be_visible = AsyncMock()
        mock_expect.return_value.to_be_hidden = AsyncMock()

        with patch.object(
            chat_controller, "_dismiss_backdrops", new_callable=AsyncMock
        ) as mock_dismiss:
            await chat_controller._execute_chat_clear(
                clear_btn, confirm_btn, overlay, mock_check_disconnect
            )

            # Verify retry logic
            assert clear_btn.click.call_count == 2
            # Check second call had force=True
            call_args = clear_btn.click.call_args_list[1]
            assert call_args.kwargs.get("force") is True
            # Check dismiss backdrops called
            mock_dismiss.assert_awaited()


@pytest.mark.asyncio
@pytest.mark.timeout(5)
async def test_execute_chat_clear_wait_disappear_timeout(
    chat_controller, mock_page_controller
):
    """Test _execute_chat_clear timeout waiting for dialog to disappear."""
    mock_check_disconnect = MagicMock(return_value=False)

    clear_btn = MagicMock()
    clear_btn.click = AsyncMock()
    confirm_btn = MagicMock()
    confirm_btn.click = AsyncMock()
    overlay = MagicMock()
    overlay.is_visible = AsyncMock(return_value=True)

    with patch(
        "browser_utils.page_controller_modules.chat.expect_async"
    ) as mock_expect:
        # to_be_hidden always raises TimeoutError
        mock_expect.return_value.to_be_hidden = AsyncMock(
            side_effect=TimeoutError("Timeout")
        )

        with pytest.raises(Exception) as excinfo:
            await chat_controller._execute_chat_clear(
                clear_btn, confirm_btn, overlay, mock_check_disconnect
            )

        assert "达到最大重试次数" in str(excinfo.value)
