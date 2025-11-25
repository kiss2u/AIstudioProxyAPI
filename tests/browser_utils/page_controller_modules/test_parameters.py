import pytest
import asyncio
from unittest.mock import MagicMock, AsyncMock, patch, call
from browser_utils.page_controller_modules.parameters import ParameterController
from models import ClientDisconnectedError
from config import (
    DEFAULT_TEMPERATURE,
    DEFAULT_MAX_OUTPUT_TOKENS,
    DEFAULT_STOP_SEQUENCES,
    DEFAULT_TOP_P,
    TEMPERATURE_INPUT_SELECTOR,
    MAX_OUTPUT_TOKENS_SELECTOR,
    STOP_SEQUENCE_INPUT_SELECTOR,
    MAT_CHIP_REMOVE_BUTTON_SELECTOR,
    TOP_P_INPUT_SELECTOR,
    USE_URL_CONTEXT_SELECTOR,
    GROUNDING_WITH_GOOGLE_SEARCH_TOGGLE_SELECTOR,
)

@pytest.fixture
def mock_page():
    page = AsyncMock()
    page.locator = MagicMock()
    # Setup default locator behavior to return an AsyncMock that can be awaited/called
    locator_mock = AsyncMock()
    locator_mock.input_value.return_value = "0.5"
    locator_mock.get_attribute.return_value = "false"
    locator_mock.count.return_value = 0
    page.locator.return_value = locator_mock
    return page

@pytest.fixture
def mock_logger():
    return MagicMock()

@pytest.fixture
def controller(mock_page, mock_logger):
    return ParameterController(mock_page, mock_logger, "test_req_id")

@pytest.fixture
def mock_check_disconnect():
    return MagicMock(return_value=False)

@pytest.fixture
def mock_lock():
    return asyncio.Lock()

@pytest.fixture(autouse=True)
def mock_expect_async():
    with patch("browser_utils.page_controller_modules.parameters.expect_async") as mock:
        mock.return_value.to_be_visible = AsyncMock()
        mock.return_value.to_have_class = AsyncMock()
        yield mock

@pytest.fixture(autouse=True)
def mock_save_snapshot():
    with patch("browser_utils.operations.save_error_snapshot", new_callable=AsyncMock) as mock:
        yield mock

@pytest.mark.asyncio
async def test_adjust_temperature_cache_hit(controller, mock_lock, mock_check_disconnect, mock_page):
    page_params_cache = {"temperature": 0.7}
    
    await controller._adjust_temperature(
        0.7, page_params_cache, mock_lock, mock_check_disconnect
    )
    
    # Should not interact with page
    mock_page.locator.assert_not_called()
    assert page_params_cache["temperature"] == 0.7

@pytest.mark.asyncio
async def test_adjust_temperature_update_success(controller, mock_lock, mock_check_disconnect, mock_page):
    page_params_cache = {"temperature": 0.5}
    target_temp = 0.8
    
    # Mock locator interactions
    temp_locator = AsyncMock()
    # First read: 0.5, Second read (after update): 0.8
    temp_locator.input_value.side_effect = ["0.5", "0.8"]
    mock_page.locator.return_value = temp_locator
    
    await controller._adjust_temperature(
        target_temp, page_params_cache, mock_lock, mock_check_disconnect
    )
    
    mock_page.locator.assert_called_with(TEMPERATURE_INPUT_SELECTOR)
    temp_locator.fill.assert_called_with(str(target_temp), timeout=5000)
    assert page_params_cache["temperature"] == target_temp

@pytest.mark.asyncio
async def test_adjust_temperature_verify_fail(controller, mock_lock, mock_check_disconnect, mock_page, mock_save_snapshot):
    page_params_cache = {}
    target_temp = 0.8
    
    temp_locator = AsyncMock()
    # First read: 0.5, Second read (after update): 0.5 (update failed)
    temp_locator.input_value.side_effect = ["0.5", "0.5"]
    mock_page.locator.return_value = temp_locator
    
    await controller._adjust_temperature(
        target_temp, page_params_cache, mock_lock, mock_check_disconnect
    )
    
    assert "temperature" not in page_params_cache
    mock_save_snapshot.assert_called()

@pytest.mark.asyncio
async def test_adjust_temperature_value_error(controller, mock_lock, mock_check_disconnect, mock_page):
    page_params_cache = {}
    
    temp_locator = AsyncMock()
    temp_locator.input_value.return_value = "invalid"
    mock_page.locator.return_value = temp_locator
    
    await controller._adjust_temperature(
        0.5, page_params_cache, mock_lock, mock_check_disconnect
    )
    
    assert "temperature" not in page_params_cache

@pytest.mark.asyncio
async def test_adjust_max_tokens_from_model_config(controller, mock_lock, mock_check_disconnect, mock_page):
    page_params_cache = {}
    parsed_model_list = [{"id": "model-a", "supported_max_output_tokens": 1024}]
    
    tokens_locator = AsyncMock()
    tokens_locator.input_value.side_effect = ["512", "1024"]
    mock_page.locator.return_value = tokens_locator
    
    await controller._adjust_max_tokens(
        2048, # Requesting more than supported
        page_params_cache,
        mock_lock,
        "model-a",
        parsed_model_list,
        mock_check_disconnect
    )
    
    # Should be clamped to 1024
    tokens_locator.fill.assert_called_with("1024", timeout=5000)
    assert page_params_cache["max_output_tokens"] == 1024

@pytest.mark.asyncio
async def test_adjust_max_tokens_verify_fail(controller, mock_lock, mock_check_disconnect, mock_page, mock_save_snapshot):
    page_params_cache = {}
    
    tokens_locator = AsyncMock()
    tokens_locator.input_value.side_effect = ["100", "100"]
    mock_page.locator.return_value = tokens_locator
    
    await controller._adjust_max_tokens(
        200,
        page_params_cache,
        mock_lock,
        None,
        [],
        mock_check_disconnect
    )
    
    assert "max_output_tokens" not in page_params_cache
    mock_save_snapshot.assert_called()

@pytest.mark.asyncio
async def test_adjust_stop_sequences(controller, mock_lock, mock_check_disconnect, mock_page):
    page_params_cache = {}
    stop_sequences = ["stop1", "stop2"]
    
    input_locator = AsyncMock()
    remove_btn_locator = AsyncMock()
    
    # Simulate 2 existing chips then 0
    # Sequence:
    # 1. initial_chip_count = await count() -> 2
    # 2. while await count() > 0 -> 2 (True, enter loop)
    # 3. click()
    # 4. while await count() > 0 -> 1 (True, continue loop)
    # 5. click()
    # 6. while await count() > 0 -> 0 (False, exit loop)
    remove_btn_locator.count.side_effect = [2, 2, 1, 0]
    
    def get_locator(selector):
        if selector == STOP_SEQUENCE_INPUT_SELECTOR:
            return input_locator
        elif selector == MAT_CHIP_REMOVE_BUTTON_SELECTOR:
            return remove_btn_locator
        return AsyncMock()
    
    mock_page.locator.side_effect = get_locator
    
    await controller._adjust_stop_sequences(
        stop_sequences, page_params_cache, mock_lock, mock_check_disconnect
    )
    
    # Should remove existing chips
    assert remove_btn_locator.first.click.call_count == 2
    
    # Should add new sequences
    assert input_locator.fill.call_count == 2
    input_locator.fill.assert_has_calls([call("stop1", timeout=3000), call("stop2", timeout=3000)], any_order=True)
    assert input_locator.press.call_count == 2
    
    assert page_params_cache["stop_sequences"] == {"stop1", "stop2"}

@pytest.mark.asyncio
async def test_adjust_top_p_update(controller, mock_check_disconnect, mock_page):
    target_top_p = 0.9
    
    locator = AsyncMock()
    locator.input_value.side_effect = ["0.5", "0.9"]
    mock_page.locator.return_value = locator
    
    await controller._adjust_top_p(target_top_p, mock_check_disconnect)
    
    mock_page.locator.assert_called_with(TOP_P_INPUT_SELECTOR)
    locator.fill.assert_called_with(str(target_top_p), timeout=5000)

@pytest.mark.asyncio
async def test_ensure_tools_panel_expanded(controller, mock_check_disconnect, mock_page):
    # Setup: panel is collapsed
    collapse_btn = AsyncMock()
    # locator() is sync, so we need to mock it as MagicMock on the AsyncMock
    collapse_btn.locator = MagicMock()
    
    grandparent = AsyncMock()
    grandparent.get_attribute.return_value = "some-class" # not expanded
    
    collapse_btn.locator.return_value = grandparent
    mock_page.locator.return_value = collapse_btn
    
    await controller._ensure_tools_panel_expanded(mock_check_disconnect)
    
    collapse_btn.click.assert_called_once()

@pytest.mark.asyncio
async def test_ensure_tools_panel_already_expanded(controller, mock_check_disconnect, mock_page):
    # Setup: panel is expanded
    collapse_btn = AsyncMock()
    # locator() is sync
    collapse_btn.locator = MagicMock()
    
    grandparent = AsyncMock()
    grandparent.get_attribute.return_value = "some-class expanded"
    
    collapse_btn.locator.return_value = grandparent
    mock_page.locator.return_value = collapse_btn
    
    await controller._ensure_tools_panel_expanded(mock_check_disconnect)
    
    collapse_btn.click.assert_not_called()

@pytest.mark.asyncio
async def test_open_url_content(controller, mock_check_disconnect, mock_page):
    # Setup: switch is off
    switch = AsyncMock()
    switch.get_attribute.return_value = "false"
    mock_page.locator.return_value = switch
    
    await controller._open_url_content(mock_check_disconnect)
    
    switch.click.assert_called_once()

@pytest.mark.asyncio
async def test_should_enable_google_search(controller):
    # Case 1: No tools -> Default (True/False based on config, assuming True for test if config not mocked, but config is imported)
    # We need to check what ENABLE_GOOGLE_SEARCH is in config. 
    # In parameters.py it imports ENABLE_GOOGLE_SEARCH.
    # Let's assume we want to test the logic based on tools param.
    
    # Case 2: Tools with googleSearch
    params_with_search = {
        "tools": [{"function": {"name": "googleSearch"}}]
    }
    assert controller._should_enable_google_search(params_with_search) is True
    
    # Case 3: Tools with google_search_retrieval
    params_with_retrieval = {
        "tools": [{"google_search_retrieval": {}}]
    }
    assert controller._should_enable_google_search(params_with_retrieval) is True
    
    # Case 4: Tools without search
    params_no_search = {
        "tools": [{"function": {"name": "otherTool"}}]
    }
    assert controller._should_enable_google_search(params_no_search) is False

@pytest.mark.asyncio
async def test_adjust_google_search(controller, mock_check_disconnect, mock_page):
    # Setup: Request wants search enabled, currently disabled
    request_params = {"tools": [{"function": {"name": "googleSearch"}}]}
    
    toggle = AsyncMock()
    toggle.get_attribute.side_effect = ["false", "true"] # Initial check, then check after click
    mock_page.locator.return_value = toggle
    
    await controller._adjust_google_search(request_params, mock_check_disconnect)
    
    toggle.click.assert_called_once()

@pytest.mark.asyncio
async def test_adjust_parameters_full_flow(controller, mock_lock, mock_check_disconnect, mock_page):
    # Mock all internal adjust methods to verify orchestration
    with patch.object(controller, '_adjust_temperature', new_callable=AsyncMock) as mock_temp, \
         patch.object(controller, '_adjust_max_tokens', new_callable=AsyncMock) as mock_tokens, \
         patch.object(controller, '_adjust_stop_sequences', new_callable=AsyncMock) as mock_stop, \
         patch.object(controller, '_adjust_top_p', new_callable=AsyncMock) as mock_top_p, \
         patch.object(controller, '_ensure_tools_panel_expanded', new_callable=AsyncMock) as mock_panel, \
         patch.object(controller, '_open_url_content', new_callable=AsyncMock) as mock_url, \
         patch.object(controller, '_adjust_google_search', new_callable=AsyncMock) as mock_search:
        
        # Mock _handle_thinking_budget if it were to exist (dynamically added in real usage)
        controller._handle_thinking_budget = AsyncMock()
        
        request_params = {
            "temperature": 0.9,
            "max_output_tokens": 100,
            "stop": ["stop"],
            "top_p": 0.95
        }
        page_params_cache = {}
        
        await controller.adjust_parameters(
            request_params,
            page_params_cache,
            mock_lock,
            "model-id",
            [],
            mock_check_disconnect
        )
        
        mock_temp.assert_called_once()
        mock_tokens.assert_called_once()
        mock_stop.assert_called_once()
        mock_top_p.assert_called_once()
        mock_panel.assert_called_once()
        # mock_url called if ENABLE_URL_CONTEXT is True. 
        # We can't easily control ENABLE_URL_CONTEXT here without patching config before import or reloading module.
        # But we can check if it was called or not based on default.
        
        controller._handle_thinking_budget.assert_called_once()
        mock_search.assert_called_once()

@pytest.mark.asyncio
async def test_client_disconnected_error(controller, mock_lock, mock_check_disconnect):
    mock_check_disconnect.side_effect = lambda stage: True
    
    with pytest.raises(ClientDisconnectedError):
        await controller.adjust_parameters({}, {}, mock_lock, None, [], mock_check_disconnect)
