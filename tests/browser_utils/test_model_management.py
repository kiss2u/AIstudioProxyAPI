import pytest
import asyncio
import json
from unittest.mock import MagicMock, AsyncMock, patch
from browser_utils.model_management import (
    _verify_ui_state_settings,
    _force_ui_state_settings,
    switch_ai_studio_model,
    _handle_initial_model_state_and_storage
)

@pytest.mark.asyncio
async def test_verify_ui_state_settings_success(mock_page):
    # Mock localStorage
    prefs = {
        "isAdvancedOpen": True,
        "areToolsOpen": True
    }
    mock_page.evaluate.return_value = json.dumps(prefs)
    
    result = await _verify_ui_state_settings(mock_page)
    
    assert result['exists'] is True
    assert result['isAdvancedOpen'] is True
    assert result['areToolsOpen'] is True
    assert result['needsUpdate'] is False

@pytest.mark.asyncio
async def test_verify_ui_state_settings_needs_update(mock_page):
    # Mock localStorage with incorrect settings
    prefs = {
        "isAdvancedOpen": False,
        "areToolsOpen": True
    }
    mock_page.evaluate.return_value = json.dumps(prefs)
    
    result = await _verify_ui_state_settings(mock_page)
    
    assert result['exists'] is True
    assert result['isAdvancedOpen'] is False
    assert result['needsUpdate'] is True

@pytest.mark.asyncio
async def test_force_ui_state_settings_success(mock_page):
    # First verify returns needs update
    # Second verify returns success
    
    # We need to mock _verify_ui_state_settings behavior
    # Since it's imported in the module, we should patch it there
    
    with patch('browser_utils.model_management._verify_ui_state_settings') as mock_verify:
        mock_verify.side_effect = [
            # First call: needs update
            {
                'exists': True,
                'needsUpdate': True,
                'prefs': {}
            },
            # Second call: success
            {
                'exists': True,
                'needsUpdate': False,
                'prefs': {'isAdvancedOpen': True, 'areToolsOpen': True}
            }
        ]
        
        result = await _force_ui_state_settings(mock_page)
        
        assert result is True
        mock_page.evaluate.assert_called() # Should call setItem

@pytest.mark.asyncio
async def test_switch_ai_studio_model_success(mock_page):
    model_id = "gemini-1.5-pro"
    req_id = "test-req"
    
    # Mock localStorage behavior
    storage = {"promptModel": "models/old-model"}
    
    async def evaluate_side_effect(script, *args):
        if "getItem" in script:
            return json.dumps(storage)
        elif "setItem" in script:
            if args:
                new_prefs = json.loads(args[0])
                storage.update(new_prefs)
            return None
        return None
    
    mock_page.evaluate.side_effect = evaluate_side_effect
    
    # Mock expect_async
    mock_expect = MagicMock()
    assertion_wrapper = MagicMock()
    assertion_wrapper.to_be_visible = AsyncMock()
    mock_expect.return_value = assertion_wrapper
    
    # Mock UI state verification
    with patch('browser_utils.model_management._verify_and_apply_ui_state', return_value=True), \
         patch('browser_utils.model_management.expect_async', mock_expect):
        # Mock page navigation and visibility checks
        mock_page.goto = AsyncMock()
        
        # Mock locators
        input_locator = MagicMock()
        model_name_locator = MagicMock()
        model_name_locator.first.inner_text = AsyncMock(return_value=model_id)
        incognito_locator = MagicMock()
        incognito_locator.get_attribute = AsyncMock(return_value="ms-button-active")
        incognito_locator.click = AsyncMock()
        incognito_locator.wait_for = AsyncMock()
        
        def locator_side_effect(selector):
            if 'model-name' in selector:
                return model_name_locator
            elif 'Temporary chat toggle' in selector:
                return incognito_locator
            else:
                return input_locator
                
        mock_page.locator.side_effect = locator_side_effect
        
        result = await switch_ai_studio_model(mock_page, model_id, req_id)
        
        assert result is True
        mock_page.goto.assert_called()

@pytest.mark.asyncio
async def test_handle_initial_model_state_success(mock_page):
    # Mock server module
    with patch.dict("sys.modules", {"server": MagicMock()}):
        import server
        server.current_ai_studio_model_id = None
        
        # Mock localStorage with valid model
        prefs = {
            "promptModel": "models/gemini-1.5-pro",
            "isAdvancedOpen": True,
            "areToolsOpen": True
        }
        mock_page.evaluate.return_value = json.dumps(prefs)
        
        with patch('browser_utils.model_management._verify_ui_state_settings') as mock_verify:
            mock_verify.return_value = {
                'exists': True,
                'needsUpdate': False,
                'isAdvancedOpen': True,
                'areToolsOpen': True
            }
            
            await _handle_initial_model_state_and_storage(mock_page)
            
            assert server.current_ai_studio_model_id == "gemini-1.5-pro"

@pytest.mark.asyncio
async def test_handle_initial_model_state_needs_reload(mock_page):
    # Mock server module
    with patch.dict("sys.modules", {"server": MagicMock()}):
        import server
        
        # Mock localStorage missing
        mock_page.evaluate.return_value = None
        
        # Mock expect_async
        mock_expect = MagicMock()
        assertion_wrapper = MagicMock()
        assertion_wrapper.to_be_visible = AsyncMock()
        mock_expect.return_value = assertion_wrapper

        with patch('browser_utils.model_management._set_model_from_page_display', new_callable=AsyncMock) as mock_set_model, \
             patch('browser_utils.model_management._verify_and_apply_ui_state', new_callable=AsyncMock) as mock_verify_apply, \
             patch('browser_utils.model_management.expect_async', mock_expect):
            
            mock_verify_apply.return_value = True
            
            await _handle_initial_model_state_and_storage(mock_page)
            
            # Should trigger reload flow
            mock_set_model.assert_called()
            mock_page.goto.assert_called()

@pytest.mark.asyncio
async def test_ensure_model_selected_already_selected(mock_page):
    # Test case where the model is already selected in localStorage
    model_id = "gemini-1.5-pro"
    req_id = "test-req"
    
    # Mock localStorage to return the target model
    mock_page.evaluate.return_value = json.dumps({"promptModel": f"models/{model_id}"})
    
    # Mock page URL to be new_chat
    mock_page.url = "https://aistudio.google.com/prompts/new_chat"
    
    result = await switch_ai_studio_model(mock_page, model_id, req_id)
    
    assert result is True
    # Should NOT navigate if already on new_chat and model matches
    mock_page.goto.assert_not_called()

@pytest.mark.asyncio
async def test_ensure_model_selected_needs_switch(mock_page):
    # Test case where model needs to be switched
    model_id = "gemini-1.5-pro"
    req_id = "test-req"
    
    # Mock localStorage to return DIFFERENT model
    mock_page.evaluate.side_effect = [
        json.dumps({"promptModel": "models/gemini-1.0-pro"}), # Initial check
        None, # setItem
        None, # setItem (advanced)
        json.dumps({"promptModel": f"models/{model_id}"}), # Final check
        json.dumps({"promptModel": f"models/{model_id}"})  # Revert check (not needed if success)
    ]
    
    # Mock UI state verification
    with patch('browser_utils.model_management._verify_and_apply_ui_state', return_value=True):
        # Mock page navigation
        mock_page.goto = AsyncMock()
        
        # Mock visibility checks
        mock_expect = MagicMock()
        assertion_wrapper = MagicMock()
        assertion_wrapper.to_be_visible = AsyncMock()
        mock_expect.return_value = assertion_wrapper
        
        # Mock locators
        model_name_locator = MagicMock()
        model_name_locator.first.inner_text = AsyncMock(return_value=model_id)
        
        incognito_locator = MagicMock()
        incognito_locator.get_attribute = AsyncMock(return_value="ms-button-active")
        
        def locator_side_effect(selector):
            if 'model-name' in selector:
                return model_name_locator
            elif 'Temporary chat toggle' in selector:
                return incognito_locator
            return MagicMock()
            
        mock_page.locator.side_effect = locator_side_effect
        
        with patch('browser_utils.model_management.expect_async', mock_expect):
            result = await switch_ai_studio_model(mock_page, model_id, req_id)
            
            assert result is True
            mock_page.goto.assert_called() # Should navigate to apply changes

@pytest.mark.asyncio
async def test_verify_ui_state_settings_json_error(mock_page):
    # Test JSON decode error handling
    mock_page.evaluate.return_value = "invalid-json"
    
    result = await _verify_ui_state_settings(mock_page)
    
    assert result['exists'] is False
    assert result['needsUpdate'] is True
    assert 'JSON解析失败' in result['error']

@pytest.mark.asyncio
async def test_verify_ui_state_settings_exception(mock_page):
    # Test general exception handling
    mock_page.evaluate.side_effect = Exception("Storage access failed")
    
    result = await _verify_ui_state_settings(mock_page)
    
    assert result['exists'] is False
    assert result['needsUpdate'] is True
    assert '验证失败' in result['error']
@pytest.mark.asyncio
async def test_force_ui_state_with_retry_success(mock_page):
    from browser_utils.model_management import _force_ui_state_with_retry
    
    with patch('browser_utils.model_management._force_ui_state_settings', new_callable=AsyncMock) as mock_force:
        mock_force.side_effect = [False, True] # Fail once, then succeed
        
        result = await _force_ui_state_with_retry(mock_page, max_retries=3, retry_delay=0.01)
        
        assert result is True
        assert mock_force.call_count == 2

@pytest.mark.asyncio
async def test_force_ui_state_with_retry_failure(mock_page):
    from browser_utils.model_management import _force_ui_state_with_retry
    
    with patch('browser_utils.model_management._force_ui_state_settings', new_callable=AsyncMock) as mock_force:
        mock_force.return_value = False
        
        result = await _force_ui_state_with_retry(mock_page, max_retries=2, retry_delay=0.01)
        
        assert result is False
        assert mock_force.call_count == 2

@pytest.mark.asyncio
async def test_verify_and_apply_ui_state_needs_update(mock_page):
    from browser_utils.model_management import _verify_and_apply_ui_state
    
    with patch('browser_utils.model_management._verify_ui_state_settings') as mock_verify, \
         patch('browser_utils.model_management._force_ui_state_with_retry', new_callable=AsyncMock) as mock_force_retry:
        
        mock_verify.return_value = {
            'exists': True,
            'needsUpdate': True,
            'isAdvancedOpen': False,
            'areToolsOpen': False
        }
        mock_force_retry.return_value = True
        
        result = await _verify_and_apply_ui_state(mock_page)
        
        assert result is True
        mock_force_retry.assert_called_once()

@pytest.mark.asyncio
async def test_load_excluded_models():
    from browser_utils.model_management import load_excluded_models
    
    with patch.dict("sys.modules", {"server": MagicMock()}):
        import server
        server.excluded_model_ids = set()
        
        # Create a temporary file
        import tempfile
        import os
        
        with tempfile.NamedTemporaryFile(mode='w', delete=False, encoding='utf-8') as tmp:
            tmp.write("model-a\nmodel-b\n")
            tmp_path = tmp.name
            
        try:
            # We need to patch os.path.join to point to our temp file or just pass absolute path if the function supports it.
            # The function does: os.path.join(os.path.dirname(__file__), '..', filename)
            # So we can pass an absolute path if we mock os.path.join to return the second arg if it's absolute?
            # Or just mock open.
            
            with patch('builtins.open', create=True) as mock_open:
                mock_open.return_value.__enter__.return_value = ["model-a\n", "model-b\n"]
                with patch('os.path.exists', return_value=True):
                    load_excluded_models("dummy_path")
                    
            assert "model-a" in server.excluded_model_ids
            assert "model-b" in server.excluded_model_ids
            
        finally:
            os.unlink(tmp_path)

@pytest.mark.asyncio
async def test_set_model_from_page_display(mock_page):
    from browser_utils.model_management import _set_model_from_page_display
    
    with patch.dict("sys.modules", {"server": MagicMock()}):
        import server
        server.current_ai_studio_model_id = "old-model"
        server.model_list_fetch_event = None
        
        # Mock page display
        model_name_locator = MagicMock()
        model_name_locator.first.inner_text = AsyncMock(return_value="new-model")
        mock_page.locator.return_value = model_name_locator
        
        # Mock localStorage
        mock_page.evaluate.return_value = json.dumps({})
        
        with patch('browser_utils.model_management._verify_and_apply_ui_state', new_callable=AsyncMock) as mock_verify_apply:
            mock_verify_apply.return_value = True
            
            await _set_model_from_page_display(mock_page, set_storage=True)
            
            assert server.current_ai_studio_model_id == "new-model"
            mock_page.evaluate.assert_called() # Should update storage
@pytest.mark.asyncio
async def test_switch_ai_studio_model_display_mismatch_revert_success(mock_page):
    from browser_utils.model_management import switch_ai_studio_model
    
    model_id = "gemini-1.5-pro"
    req_id = "test-req"
    
    # Mock localStorage
    storage = {"promptModel": "models/old-model"}
    
    async def evaluate_side_effect(script, *args):
        if "getItem" in script:
            return json.dumps(storage)
        elif "setItem" in script:
            if args:
                new_prefs = json.loads(args[0])
                storage.update(new_prefs)
            return None
        return None
    
    mock_page.evaluate.side_effect = evaluate_side_effect
    
    # Mock expect_async
    mock_expect = MagicMock()
    assertion_wrapper = MagicMock()
    assertion_wrapper.to_be_visible = AsyncMock()
    mock_expect.return_value = assertion_wrapper
    
    # Mock UI state verification
    with patch('browser_utils.model_management._verify_and_apply_ui_state', return_value=True), \
         patch('browser_utils.model_management.expect_async', mock_expect), \
         patch.dict("sys.modules", {"server": MagicMock()}):
        
        import server
        server.parsed_model_list = [{"id": model_id, "display_name": "Gemini 1.5 Pro"}]
        
        # Mock page navigation
        mock_page.goto = AsyncMock()
        
        # Mock locators
        model_name_locator = MagicMock()
        # First call returns mismatch, second call (during revert) returns original model name
        model_name_locator.first.inner_text = AsyncMock(side_effect=["Wrong Model", "Old Model"])
        
        incognito_locator = MagicMock()
        incognito_locator.get_attribute = AsyncMock(return_value="ms-button-active")
        
        def locator_side_effect(selector):
            if 'model-name' in selector:
                return model_name_locator
            elif 'Temporary chat toggle' in selector:
                return incognito_locator
            return MagicMock()
            
        mock_page.locator.side_effect = locator_side_effect
        
        result = await switch_ai_studio_model(mock_page, model_id, req_id)
        
        # It should return False because it failed to switch and reverted
        assert result is False
        # Should have navigated at least twice (once to switch, once to revert)
        assert mock_page.goto.call_count >= 2
@pytest.mark.asyncio
async def test_set_model_from_page_display_wait_for_event(mock_page):
    from browser_utils.model_management import _set_model_from_page_display
    
    with patch.dict("sys.modules", {"server": MagicMock()}):
        import server
        server.current_ai_studio_model_id = "old-model"
        
        # Mock event
        event = asyncio.Event()
        server.model_list_fetch_event = event
        
        # Mock page display
        model_name_locator = MagicMock()
        model_name_locator.first.inner_text = AsyncMock(return_value="new-model")
        mock_page.locator.return_value = model_name_locator
        
        # Mock localStorage
        mock_page.evaluate.return_value = json.dumps({})
        
        # Start a task to set the event after a short delay
        async def set_event():
            await asyncio.sleep(0.1)
            event.set()
            
        asyncio.create_task(set_event())
        
        with patch('browser_utils.model_management._verify_and_apply_ui_state', new_callable=AsyncMock) as mock_verify_apply:
            mock_verify_apply.return_value = True
            
            await _set_model_from_page_display(mock_page, set_storage=False)
            
            assert server.current_ai_studio_model_id == "new-model"
            assert event.is_set()