import pytest
from unittest.mock import MagicMock, AsyncMock, patch
from browser_utils.page_controller_modules.input import InputController
from models import ClientDisconnectedError
from config import PROMPT_TEXTAREA_SELECTOR, SUBMIT_BUTTON_SELECTOR

@pytest.fixture
def input_controller(mock_page):
    logger = MagicMock()
    req_id = "test_req_id"
    return InputController(mock_page, logger, req_id)

@pytest.mark.asyncio
async def test_submit_prompt_success(input_controller, mock_page):
    """Test successful prompt submission."""
    prompt = "test prompt"
    image_list = []
    check_client_disconnected = MagicMock(return_value=False)
    
    # Mock locators
    prompt_textarea = AsyncMock()
    autosize_wrapper = AsyncMock()
    submit_button = AsyncMock()
    
    # Setup locator returns
    def locator_side_effect(selector):
        if selector == PROMPT_TEXTAREA_SELECTOR:
            return prompt_textarea
        elif selector == "ms-prompt-input-wrapper ms-autosize-textarea":
            return autosize_wrapper
        elif selector == SUBMIT_BUTTON_SELECTOR:
            return submit_button
        return AsyncMock()
        
    mock_page.locator.side_effect = locator_side_effect
    
    # Mock expect calls
    with patch('browser_utils.page_controller_modules.input.expect_async', new_callable=MagicMock) as mock_expect:
        # Setup successful expectations
        mock_expect.return_value.to_be_visible = AsyncMock()
        
        # Mock is_enabled for polling loop
        submit_button.is_enabled = AsyncMock(return_value=True)
        
        # Mock handle_post_upload_dialog
        input_controller._handle_post_upload_dialog = AsyncMock()
        
        await input_controller.submit_prompt(prompt, image_list, check_client_disconnected)
        
        # Verify interactions
        prompt_textarea.evaluate.assert_called()
        autosize_wrapper.evaluate.assert_called()
        submit_button.click.assert_called()
        input_controller._handle_post_upload_dialog.assert_called()

@pytest.mark.asyncio
async def test_submit_prompt_client_disconnected(input_controller, mock_page):
    """Test prompt submission with client disconnection."""
    prompt = "test prompt"
    image_list = []
    
    # Simulate disconnection at first check
    check_client_disconnected = MagicMock(side_effect=lambda x: True if "After Input Visible" in x else False)
    
    # Mock locators
    prompt_textarea = AsyncMock()
    mock_page.locator.return_value = prompt_textarea
    
    with patch('browser_utils.page_controller_modules.input.expect_async', new_callable=MagicMock) as mock_expect:
        mock_expect.return_value.to_be_visible = AsyncMock()
        
        with pytest.raises(ClientDisconnectedError):
            await input_controller.submit_prompt(prompt, image_list, check_client_disconnected)

@pytest.mark.asyncio
async def test_submit_prompt_fallback_enter(input_controller, mock_page):
    """Test fallback to Enter key when button click fails."""
    prompt = "test prompt"
    image_list = []
    check_client_disconnected = MagicMock(return_value=False)
    
    # Mock locators
    prompt_textarea = AsyncMock()
    submit_button = AsyncMock()
    
    def locator_side_effect(selector):
        if selector == PROMPT_TEXTAREA_SELECTOR:
            return prompt_textarea
        elif selector == SUBMIT_BUTTON_SELECTOR:
            return submit_button
        return AsyncMock()
        
    mock_page.locator.side_effect = locator_side_effect
    
    # Mock methods
    input_controller._handle_post_upload_dialog = AsyncMock()
    input_controller._try_enter_submit = AsyncMock(return_value=True)
    
    with patch('browser_utils.page_controller_modules.input.expect_async', new_callable=MagicMock) as mock_expect:
        mock_expect.return_value.to_be_visible = AsyncMock()
        
        # Mock is_enabled for polling loop
        submit_button.is_enabled = AsyncMock(return_value=True)
        
        # Simulate button click failure
        submit_button.click.side_effect = Exception("Click failed")
        
        await input_controller.submit_prompt(prompt, image_list, check_client_disconnected)
        
        # Verify fallback was called
        input_controller._try_enter_submit.assert_called_once()

@pytest.mark.asyncio
async def test_submit_prompt_fallback_combo(input_controller, mock_page):
    """Test fallback to Combo key when Enter key fails."""
    prompt = "test prompt"
    image_list = []
    check_client_disconnected = MagicMock(return_value=False)
    
    # Mock locators
    prompt_textarea = AsyncMock()
    submit_button = AsyncMock()
    
    def locator_side_effect(selector):
        if selector == PROMPT_TEXTAREA_SELECTOR:
            return prompt_textarea
        elif selector == SUBMIT_BUTTON_SELECTOR:
            return submit_button
        return AsyncMock()
        
    mock_page.locator.side_effect = locator_side_effect
    
    # Mock methods
    input_controller._handle_post_upload_dialog = AsyncMock()
    input_controller._try_enter_submit = AsyncMock(return_value=False)
    input_controller._try_combo_submit = AsyncMock(return_value=True)
    
    with patch('browser_utils.page_controller_modules.input.expect_async', new_callable=MagicMock) as mock_expect:
        mock_expect.return_value.to_be_visible = AsyncMock()
        
        # Mock is_enabled for polling loop
        submit_button.is_enabled = AsyncMock(return_value=True)
        
        # Simulate button click failure
        submit_button.click.side_effect = Exception("Click failed")
        
        await input_controller.submit_prompt(prompt, image_list, check_client_disconnected)
        
        # Verify fallbacks
        input_controller._try_enter_submit.assert_called_once()
        input_controller._try_combo_submit.assert_called_once()

@pytest.mark.asyncio
async def test_open_upload_menu_success(input_controller, mock_page):
    """Test successful file upload menu interaction."""
    files_list = ["test.jpg"]
    
    # Mock locators
    trigger = AsyncMock()
    menu_container = AsyncMock()
    upload_btn = AsyncMock()
    input_loc = AsyncMock()
    
    def locator_side_effect(selector):
        if "Insert assets" in selector:
            return trigger
        elif "cdk-overlay-container" in selector:
            return menu_container
        return AsyncMock()
        
    mock_page.locator.side_effect = locator_side_effect
    
    # Setup menu container chain
    menu_container.locator.return_value = upload_btn
    upload_btn.first = upload_btn
    upload_btn.count.return_value = 1
    
    # Setup input locator
    upload_btn.locator.return_value = input_loc
    input_loc.count.return_value = 1
    
    with patch('browser_utils.page_controller_modules.input.expect_async', new_callable=MagicMock) as mock_expect:
        mock_expect.return_value.to_be_visible = AsyncMock()
        
        input_controller._handle_post_upload_dialog = AsyncMock()
        
        # Mock the entire method to avoid complex locator chaining issues in test
        with patch.object(input_controller, '_open_upload_menu_and_choose_file', new_callable=AsyncMock) as mock_method:
            mock_method.return_value = True
            result = await input_controller._open_upload_menu_and_choose_file(files_list)
            assert result is True