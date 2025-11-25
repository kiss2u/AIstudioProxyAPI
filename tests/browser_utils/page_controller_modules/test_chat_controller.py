import pytest
from unittest.mock import MagicMock, AsyncMock, patch, PropertyMock
from browser_utils.page_controller_modules.chat import ChatController
from models import ClientDisconnectedError
from config import CLEAR_CHAT_BUTTON_SELECTOR, CLEAR_CHAT_CONFIRM_BUTTON_SELECTOR, OVERLAY_SELECTOR, SUBMIT_BUTTON_SELECTOR

@pytest.fixture
def mock_controller(mock_page):
    logger = MagicMock()
    controller = ChatController(mock_page, logger, "req_123")
    return controller

@pytest.mark.asyncio
async def test_clear_chat_history_success(mock_controller, mock_page):
    # Mock locators
    submit_btn = AsyncMock()
    clear_btn = AsyncMock()
    confirm_btn = AsyncMock()
    overlay = AsyncMock()
    
    # Ensure overlay is not visible initially so it clicks the clear button
    # Use side_effect to ensure it returns False when awaited
    overlay.is_visible.side_effect = [False]

    mock_page.locator.side_effect = lambda s: {
        SUBMIT_BUTTON_SELECTOR: submit_btn,
        CLEAR_CHAT_BUTTON_SELECTOR: clear_btn,
        CLEAR_CHAT_CONFIRM_BUTTON_SELECTOR: confirm_btn,
        OVERLAY_SELECTOR: overlay,
        "ms-response-container": AsyncMock() # For verification
    }.get(s, AsyncMock())

    # Mock page.url as a property
    type(mock_page).url = PropertyMock(return_value="https://aistudio.google.com/prompts/123")

    # Mock expectations
    # We need to patch expect_async where it is used
    mock_expect = MagicMock()
    assertion_wrapper = MagicMock()
    assertion_wrapper.to_be_enabled = AsyncMock()
    assertion_wrapper.to_be_disabled = AsyncMock()
    assertion_wrapper.to_be_visible = AsyncMock()
    assertion_wrapper.to_be_hidden = AsyncMock()
    mock_expect.return_value = assertion_wrapper

    with patch("browser_utils.page_controller_modules.chat.expect_async", mock_expect):
        # Mock enable_temporary_chat_mode
        with patch("browser_utils.page_controller_modules.chat.enable_temporary_chat_mode", new_callable=AsyncMock) as mock_enable_temp:
            # Mock _dismiss_backdrops to avoid errors
            mock_controller._dismiss_backdrops = AsyncMock()
            
            # Mock _check_disconnect to avoid errors
            mock_controller._check_disconnect = AsyncMock()

            await mock_controller.clear_chat_history(MagicMock(return_value=False))

            # Verify flow
            # Since we configured overlay.is_visible to return False, clear_btn should be clicked
            clear_btn.click.assert_called()
            
            # And then confirm_btn should be clicked
            confirm_btn.click.assert_called()
            
            mock_enable_temp.assert_called_once()

@pytest.mark.asyncio
async def test_clear_chat_history_new_chat_url(mock_controller, mock_page):
    # Mock URL to be new chat
    # Ensure url is a string property, not a mock that needs awaiting or calling
    type(mock_page).url = PropertyMock(return_value="https://aistudio.google.com/prompts/new_chat")
    
    # Mock locators
    clear_btn = AsyncMock()
    mock_page.locator.return_value = clear_btn
    
    # Mock expect to fail (button not enabled)
    # We need to patch expect_async where it is imported in the module under test
    with patch("browser_utils.page_controller_modules.chat.expect_async", side_effect=Exception("Not enabled")):
        await mock_controller.clear_chat_history(MagicMock(return_value=False))
        
        # Should log info about skipping
        mock_controller.logger.info.assert_any_call(
            f'[{mock_controller.req_id}] "清空聊天"按钮不可用 (预期，因为在 new_chat 页面)。跳过清空操作。'
        )

@pytest.mark.asyncio
async def test_clear_chat_history_client_disconnected(mock_controller):
    check_disconnect = MagicMock(return_value=True)
    
    with pytest.raises(ClientDisconnectedError):
        await mock_controller.clear_chat_history(check_disconnect)

@pytest.mark.asyncio
async def test_execute_chat_clear_overlay_visible(mock_controller, mock_page):
    # Mock overlay visible
    overlay = AsyncMock()
    overlay.is_visible.return_value = True
    confirm_btn = AsyncMock()
    
    mock_page.locator.side_effect = lambda s: {
        ".cdk-overlay-container": overlay,
        "button[data-test-id='confirm-button']": confirm_btn
    }.get(s, AsyncMock())
    
    # Mock expect_async
    mock_expect = MagicMock()
    assertion_wrapper = MagicMock()
    assertion_wrapper.to_be_hidden = AsyncMock()
    mock_expect.return_value = assertion_wrapper

    with patch("browser_utils.page_controller_modules.chat.expect_async", mock_expect):
        await mock_controller._execute_chat_clear(
            AsyncMock(), confirm_btn, overlay, MagicMock(return_value=False)
        )
        
        confirm_btn.click.assert_called()

@pytest.mark.asyncio
async def test_verify_chat_cleared_success(mock_controller, mock_page):
    last_container = AsyncMock()
    mock_page.locator.return_value.last = last_container
    
    # Mock expect_async to return an object with to_be_hidden method
    mock_expect_func = MagicMock()
    assertion_wrapper = MagicMock()
    assertion_wrapper.to_be_hidden = AsyncMock()
    mock_expect_func.return_value = assertion_wrapper

    with patch("browser_utils.page_controller_modules.chat.expect_async", mock_expect_func):
        await mock_controller._verify_chat_cleared(MagicMock(return_value=False))
        mock_expect_func.assert_called_with(last_container)
        assertion_wrapper.to_be_hidden.assert_called()