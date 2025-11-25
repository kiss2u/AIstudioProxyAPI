import pytest
import unittest.mock
from unittest.mock import MagicMock, AsyncMock, patch
from browser_utils.page_controller_modules.thinking import ThinkingController

@pytest.fixture
def mock_controller(mock_page):
    logger = MagicMock()
    controller = ThinkingController(mock_page, logger, "req_123")
    return controller

@pytest.mark.asyncio
async def test_handle_thinking_budget_disabled(mock_controller):
    # Mock helper methods
    mock_controller._uses_thinking_level = MagicMock(return_value=False)
    mock_controller._model_has_main_thinking_toggle = MagicMock(return_value=True)
    mock_controller._control_thinking_mode_toggle = AsyncMock(return_value=True)
    mock_controller._control_thinking_budget_toggle = AsyncMock()
    
    # Use 0 to disable thinking mode
    request_params = {"reasoning_effort": 0}
    await mock_controller._handle_thinking_budget(request_params, "gemini-2.0-flash", AsyncMock())
    
    mock_controller._control_thinking_mode_toggle.assert_called_with(
        should_be_enabled=False,
        check_client_disconnected=unittest.mock.ANY
    )
    # If thinking is disabled, we also ensure budget toggle is off (for compatibility)
    mock_controller._control_thinking_budget_toggle.assert_called_with(
        should_be_checked=False,
        check_client_disconnected=unittest.mock.ANY
    )

@pytest.mark.asyncio
async def test_handle_thinking_budget_enabled_with_budget(mock_controller):
    # Mock helper methods
    mock_controller._uses_thinking_level = MagicMock(return_value=False)
    mock_controller._model_has_main_thinking_toggle = MagicMock(return_value=True)
    mock_controller._control_thinking_mode_toggle = AsyncMock(return_value=True)
    mock_controller._control_thinking_budget_toggle = AsyncMock()
    mock_controller._set_thinking_budget_value = AsyncMock()
    
    request_params = {"reasoning_effort": 1000}
    await mock_controller._handle_thinking_budget(request_params, "gemini-2.0-flash", AsyncMock())
    
    mock_controller._control_thinking_mode_toggle.assert_called_with(
        should_be_enabled=True,
        check_client_disconnected=unittest.mock.ANY
    )
    mock_controller._control_thinking_budget_toggle.assert_called_with(
        should_be_checked=True,
        check_client_disconnected=unittest.mock.ANY
    )
    # The code calls _set_thinking_budget_value(value_to_set, check_client_disconnected)
    # The assertion failed because it expected keyword arg check_client_disconnected but got positional or vice versa?
    # The error message said: Expected: mock(1000, check_client_disconnected=<ANY>), Actual: mock(1000, <AsyncMock ...>)
    # This means it was called with positional arguments.
    mock_controller._set_thinking_budget_value.assert_called_with(
        1000,
        unittest.mock.ANY
    )

@pytest.mark.asyncio
async def test_handle_thinking_budget_gemini_3_pro(mock_controller):
    # Mock helper methods
    mock_controller._uses_thinking_level = MagicMock(return_value=True)
    mock_controller._has_thinking_dropdown = AsyncMock(return_value=True)
    mock_controller._model_has_main_thinking_toggle = MagicMock(return_value=True)
    mock_controller._control_thinking_mode_toggle = AsyncMock(return_value=True)
    mock_controller._set_thinking_level = AsyncMock()
    
    request_params = {"reasoning_effort": "high"}
    await mock_controller._handle_thinking_budget(request_params, "gemini-3-pro", AsyncMock())
    
    mock_controller._control_thinking_mode_toggle.assert_called_with(
        should_be_enabled=True,
        check_client_disconnected=unittest.mock.ANY
    )
    mock_controller._set_thinking_level.assert_called_with(
        "high",
        unittest.mock.ANY
    )

@pytest.mark.asyncio
async def test_control_thinking_mode_toggle(mock_controller, mock_page):
    toggle = AsyncMock()
    # First call returns "false" (current state), second call returns "true" (after click)
    toggle.get_attribute.side_effect = ["false", "true"]
    mock_page.locator.return_value = toggle
    
    # expect_async must be a MagicMock returning an object with AsyncMock methods
    mock_expect = MagicMock()
    assertion_wrapper = MagicMock()
    assertion_wrapper.to_be_visible = AsyncMock()
    mock_expect.return_value = assertion_wrapper

    with patch("browser_utils.page_controller_modules.thinking.expect_async", mock_expect):
        # Mock _check_disconnect to avoid errors
        mock_controller._check_disconnect = AsyncMock()
        
        result = await mock_controller._control_thinking_mode_toggle(True, AsyncMock())
    
    assert result is True
    toggle.click.assert_called()

@pytest.mark.asyncio
async def test_set_thinking_budget_value(mock_controller, mock_page):
    input_el = AsyncMock()
    mock_page.locator.return_value = input_el
    
    # expect_async must be a MagicMock returning an object with AsyncMock methods
    mock_expect = MagicMock()
    assertion_wrapper = MagicMock()
    assertion_wrapper.to_be_visible = AsyncMock()
    assertion_wrapper.to_have_value = AsyncMock()
    mock_expect.return_value = assertion_wrapper

    with patch("browser_utils.page_controller_modules.thinking.expect_async", mock_expect):
        # Mock _check_disconnect to avoid errors
        mock_controller._check_disconnect = AsyncMock()
        
        await mock_controller._set_thinking_budget_value(5000, AsyncMock())
        
        input_el.fill.assert_called_with("5000", timeout=5000)
        mock_page.evaluate.assert_called()