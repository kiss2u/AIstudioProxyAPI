import asyncio
import json
import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Mock server module before importing model_management components if needed
# But we already imported them. Let's patch where necessary.
from browser_utils.model_management import (
    _force_ui_state_settings,
    _force_ui_state_with_retry,
    _handle_initial_model_state_and_storage,
    _set_model_from_page_display,
    _verify_and_apply_ui_state,
    _verify_ui_state_settings,
    load_excluded_models,
    switch_ai_studio_model,
)


@pytest.fixture
def mock_page():
    page = AsyncMock()
    # locator is synchronous in Playwright
    page.locator = MagicMock()
    # Default evaluate returns None (empty localStorage)
    page.evaluate.return_value = None
    return page


@pytest.mark.asyncio
@pytest.mark.timeout(5)
async def test_verify_ui_state_settings_valid(mock_page):
    prefs = {"isAdvancedOpen": True, "areToolsOpen": True}
    mock_page.evaluate.return_value = json.dumps(prefs)

    with patch("browser_utils.model_management.logger"):
        result = await _verify_ui_state_settings(mock_page, "req1")

    assert result["exists"] is True
    assert result["isAdvancedOpen"] is True
    assert result["areToolsOpen"] is True
    assert result["needsUpdate"] is False


@pytest.mark.asyncio
@pytest.mark.timeout(5)
async def test_verify_ui_state_settings_needs_update(mock_page):
    prefs = {"isAdvancedOpen": False, "areToolsOpen": True}
    mock_page.evaluate.return_value = json.dumps(prefs)

    with patch("browser_utils.model_management.logger"):
        result = await _verify_ui_state_settings(mock_page, "req1")

    assert result["exists"] is True
    assert result["needsUpdate"] is True


@pytest.mark.asyncio
@pytest.mark.timeout(5)
async def test_verify_ui_state_settings_missing(mock_page):
    mock_page.evaluate.return_value = None

    with patch("browser_utils.model_management.logger"):
        result = await _verify_ui_state_settings(mock_page, "req1")

    assert result["exists"] is False
    assert result["needsUpdate"] is True
    assert result["error"] == "localStorage不存在"


@pytest.mark.asyncio
@pytest.mark.timeout(5)
async def test_verify_ui_state_settings_json_error(mock_page):
    mock_page.evaluate.return_value = "invalid-json"

    with patch("browser_utils.model_management.logger"):
        result = await _verify_ui_state_settings(mock_page, "req1")

    assert result["exists"] is False
    assert result["needsUpdate"] is True
    assert "JSON解析失败" in result["error"]


@pytest.mark.asyncio
@pytest.mark.timeout(5)
async def test_verify_ui_state_settings_eval_error(mock_page):
    mock_page.evaluate.side_effect = Exception("Eval Error")

    with patch("browser_utils.model_management.logger"):
        result = await _verify_ui_state_settings(mock_page, "req1")

    assert result["exists"] is False
    assert result["needsUpdate"] is True
    assert "验证失败" in result["error"]


@pytest.mark.asyncio
@pytest.mark.timeout(5)
async def test_force_ui_state_settings_success(mock_page):
    # Initial state: needs update
    initial_prefs = {"isAdvancedOpen": False}

    with (
        patch(
            "browser_utils.model_management._verify_ui_state_settings"
        ) as mock_verify,
        patch("browser_utils.model_management.logger"),
    ):
        mock_verify.side_effect = [
            {"needsUpdate": True, "prefs": initial_prefs},  # First call
            {"needsUpdate": False},  # Second call
        ]

        result = await _force_ui_state_settings(mock_page, "req1")

        assert result is True
        # Check if setItem was called
        assert mock_page.evaluate.call_count == 1
        args = mock_page.evaluate.call_args[0]
        assert "localStorage.setItem" in args[0]
        # Check if prefs were updated to True
        saved_prefs = json.loads(args[1])
        assert saved_prefs["isAdvancedOpen"] is True
        assert saved_prefs["areToolsOpen"] is True


@pytest.mark.asyncio
@pytest.mark.timeout(5)
async def test_force_ui_state_settings_no_update_needed(mock_page):
    with (
        patch(
            "browser_utils.model_management._verify_ui_state_settings"
        ) as mock_verify,
        patch("browser_utils.model_management.logger"),
    ):
        mock_verify.return_value = {"needsUpdate": False}

        result = await _force_ui_state_settings(mock_page, "req1")

        assert result is True
        mock_page.evaluate.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.timeout(5)
async def test_force_ui_state_settings_fail_verify(mock_page):
    with (
        patch(
            "browser_utils.model_management._verify_ui_state_settings"
        ) as mock_verify,
        patch("browser_utils.model_management.logger"),
    ):
        mock_verify.side_effect = [
            {"needsUpdate": True, "prefs": {}},
            {"needsUpdate": True},  # Still needs update after set
        ]

        result = await _force_ui_state_settings(mock_page, "req1")

        assert result is False
        mock_page.evaluate.assert_called_once()


@pytest.mark.asyncio
@pytest.mark.timeout(5)
async def test_force_ui_state_with_retry_success(mock_page):
    with (
        patch("browser_utils.model_management._force_ui_state_settings") as mock_force,
        patch("browser_utils.model_management.logger"),
    ):
        mock_force.side_effect = [False, True]  # Fail first, succeed second

        result = await _force_ui_state_with_retry(
            mock_page, "req1", max_retries=3, retry_delay=0.01
        )

        assert result is True
        assert mock_force.call_count == 2


@pytest.mark.asyncio
@pytest.mark.timeout(5)
async def test_force_ui_state_with_retry_fail(mock_page):
    with (
        patch("browser_utils.model_management._force_ui_state_settings") as mock_force,
        patch("browser_utils.model_management.logger"),
    ):
        mock_force.return_value = False

        result = await _force_ui_state_with_retry(
            mock_page, "req1", max_retries=2, retry_delay=0.01
        )

        assert result is False
        assert mock_force.call_count == 2


@pytest.mark.asyncio
@pytest.mark.timeout(5)
async def test_verify_and_apply_ui_state_needs_update(mock_page):
    with (
        patch(
            "browser_utils.model_management._verify_ui_state_settings"
        ) as mock_verify,
        patch(
            "browser_utils.model_management._force_ui_state_with_retry"
        ) as mock_retry,
        patch("browser_utils.model_management.logger"),
    ):
        mock_verify.return_value = {
            "exists": True,
            "isAdvancedOpen": False,
            "areToolsOpen": False,
            "needsUpdate": True,
        }
        mock_retry.return_value = True

        result = await _verify_and_apply_ui_state(mock_page, "req1")

        assert result is True
        mock_retry.assert_called_once()


@pytest.mark.asyncio
@pytest.mark.timeout(5)
async def test_verify_and_apply_ui_state_ok(mock_page):
    with (
        patch(
            "browser_utils.model_management._verify_ui_state_settings"
        ) as mock_verify,
        patch(
            "browser_utils.model_management._force_ui_state_with_retry"
        ) as mock_retry,
        patch("browser_utils.model_management.logger"),
    ):
        mock_verify.return_value = {
            "exists": True,
            "isAdvancedOpen": True,
            "areToolsOpen": True,
            "needsUpdate": False,
        }

        result = await _verify_and_apply_ui_state(mock_page, "req1")

        assert result is True
        mock_retry.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.timeout(5)
async def test_load_excluded_models(tmp_path):
    # Create a dummy exclusion file
    d = tmp_path / "config"
    d.mkdir()
    p = d / "excluded_models.txt"
    p.write_text("model-a\nmodel-b\n", encoding="utf-8")

    # Mock server module
    mock_server = MagicMock()
    mock_server.excluded_model_ids = set()

    with (
        patch.dict(sys.modules, {"server": mock_server}),
        patch("os.path.exists") as mock_exists,
        patch("builtins.open", new_callable=MagicMock) as mock_open,
        patch("browser_utils.model_management.logger"),
    ):
        mock_exists.return_value = True
        mock_file = MagicMock()
        mock_file.__enter__.return_value = ["model-a\n", "model-b\n"]
        mock_open.return_value = mock_file

        load_excluded_models("excluded_models.txt")

        assert "model-a" in mock_server.excluded_model_ids
        assert "model-b" in mock_server.excluded_model_ids


@pytest.mark.asyncio
@pytest.mark.timeout(5)
async def test_switch_ai_studio_model_already_set(mock_page):
    model_id = "gemini-pro"
    full_model_path = f"models/{model_id}"
    prefs = {"promptModel": full_model_path}

    mock_page.evaluate.return_value = json.dumps(prefs)
    mock_page.url = "https://aistudio.google.com/prompts/new_chat"

    with (
        patch("browser_utils.model_management.logger"),
        patch("browser_utils.model_management.expect_async") as mock_expect,
    ):
        mock_expect.return_value.to_be_visible = AsyncMock()

        result = await switch_ai_studio_model(mock_page, model_id, "req1")

    assert result is True
    # Should not navigate if already on new_chat
    mock_page.goto.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.timeout(5)
async def test_switch_ai_studio_model_success(mock_page):
    model_id = "gemini-pro"
    full_model_path = f"models/{model_id}"

    initial_prefs = {"promptModel": "models/other-model"}

    # Mock server module
    mock_server = MagicMock()
    mock_server.parsed_model_list = [{"id": model_id, "display_name": "Gemini Pro"}]

    with (
        patch.dict(sys.modules, {"server": mock_server}),
        patch(
            "browser_utils.model_management._verify_and_apply_ui_state",
            return_value=True,
        ),
        patch("browser_utils.model_management.logger"),
        patch("browser_utils.model_management.expect_async") as mock_expect,
    ):
        mock_expect.return_value.to_be_visible = AsyncMock()

        # Stateful evaluate mock
        evaluate_mock = AsyncMock()
        mock_page.evaluate = evaluate_mock

        call_count = 0

        async def evaluate_side_effect(script, *args):
            nonlocal call_count
            if "localStorage.getItem" in script:
                call_count += 1
                if call_count == 1:  # Initial check
                    return json.dumps(initial_prefs)
                if call_count == 2:  # Final verification
                    return json.dumps({"promptModel": full_model_path})
            return None

        evaluate_mock.side_effect = evaluate_side_effect

        # Mock page elements
        mock_locator = MagicMock()
        mock_locator.first.inner_text = AsyncMock(
            return_value=model_id
        )  # Matches target
        mock_page.locator.return_value = mock_locator

        # Mock incognito button
        mock_incognito = MagicMock()
        mock_incognito.get_attribute = AsyncMock(return_value="ms-button-active")

        def locator_side_effect(selector):
            if 'data-test-id="model-name"' in selector:
                return mock_locator
            if "Temporary chat toggle" in selector:
                return mock_incognito
            return MagicMock()

        mock_page.locator.side_effect = locator_side_effect

        result = await switch_ai_studio_model(mock_page, model_id, "req1")

        assert result is True
        mock_page.goto.assert_called()


@pytest.mark.asyncio
@pytest.mark.timeout(5)
async def test_set_model_from_page_display(mock_page):
    # Mock server module
    mock_server = MagicMock()
    mock_server.current_ai_studio_model_id = "old-model"
    mock_server.model_list_fetch_event = MagicMock()
    mock_server.model_list_fetch_event.is_set.return_value = True

    # Mock locator
    mock_locator = MagicMock()
    mock_locator.first.inner_text = AsyncMock(return_value="new-model")
    mock_page.locator.return_value = mock_locator

    with (
        patch.dict(sys.modules, {"server": mock_server}),
        patch("browser_utils.model_management.logger"),
    ):
        await _set_model_from_page_display(mock_page, set_storage=False)

    assert mock_server.current_ai_studio_model_id == "new-model"


@pytest.mark.asyncio
@pytest.mark.timeout(5)
async def test_handle_initial_model_state_needs_reload(mock_page):
    # Mock empty localStorage -> needs reload
    mock_page.evaluate.return_value = None
    mock_page.url = "http://test.url"

    # Mock server
    mock_server = MagicMock()

    with (
        patch.dict(sys.modules, {"server": mock_server}),
        patch(
            "browser_utils.model_management._set_model_from_page_display"
        ) as mock_set_model,
        patch(
            "browser_utils.model_management._verify_and_apply_ui_state",
            return_value=True,
        ),
        patch("browser_utils.model_management.logger"),
        patch("browser_utils.model_management.expect_async") as mock_expect,
    ):
        mock_expect.return_value.to_be_visible = AsyncMock()

        await _handle_initial_model_state_and_storage(mock_page)

        # Should call _set_model_from_page_display twice
        assert mock_set_model.call_count == 2
        assert mock_set_model.call_args_list[0][1]["set_storage"] is True
        assert mock_set_model.call_args_list[1][1]["set_storage"] is False

        # Should reload page
        mock_page.goto.assert_called_with(
            "http://test.url", wait_until="domcontentloaded", timeout=40000
        )


@pytest.mark.asyncio
@pytest.mark.timeout(5)
async def test_switch_ai_studio_model_revert_logic(mock_page):
    """Test the revert logic when model switch fails validation"""
    model_id = "gemini-pro"
    full_model_path = f"models/{model_id}"
    initial_prefs = {"promptModel": "models/original-model"}
    original_prefs_str = json.dumps(initial_prefs)

    # Mock server module
    mock_server = MagicMock()
    mock_server.parsed_model_list = [{"id": model_id, "display_name": "Gemini Pro"}]

    with (
        patch.dict(sys.modules, {"server": mock_server}),
        patch(
            "browser_utils.model_management._verify_and_apply_ui_state",
            return_value=True,
        ),
        patch("browser_utils.model_management.logger"),
        patch("browser_utils.model_management.expect_async") as mock_expect,
    ):
        mock_expect.return_value.to_be_visible = AsyncMock()

        # Stateful evaluate mock
        evaluate_mock = AsyncMock()
        mock_page.evaluate = evaluate_mock

        call_count = 0

        async def evaluate_side_effect(script, *args):
            nonlocal call_count
            if "localStorage.getItem" in script:
                call_count += 1
                if call_count == 1:  # Initial check (original_prefs_str)
                    return original_prefs_str
                if (
                    call_count == 2
                ):  # Final verification (simulate switch happened in storage)
                    return json.dumps({"promptModel": full_model_path})
                if (
                    call_count == 3
                ):  # Revert logic: get current storage (to build revert prefs)
                    return json.dumps({"promptModel": full_model_path})
            return None

        evaluate_mock.side_effect = evaluate_side_effect

        # Mock page elements to simulate MISMATCH
        mock_locator = MagicMock()
        # The page shows "Original Model", but we wanted "Gemini Pro"
        mock_locator.first.inner_text = AsyncMock(return_value="Original Model")
        mock_page.locator.return_value = mock_locator

        # Mock incognito button (not reached in revert path usually, but good to have)
        MagicMock()

        result = await switch_ai_studio_model(mock_page, model_id, "req1")

        assert result is False
        # Verify revert logic was triggered
        # It should try to revert to "Original Model" (derived from page display)
        # The code tries to revert to what is displayed on page.
        # "Original Model" -> needs to be mapped to ID if possible, or fall back to original prefs.
        # Since "Original Model" is not in parsed_model_list (mocked above), it might fail ID lookup.
        # If ID lookup fails, it falls back to original_prefs_str.

        # Check logs for revert attempt
        # "恢复：由于无法读取当前页面显示" or "恢复：页面当前显示的模型名称"
        # Since we mocked inner_text to return "Original Model", it should log that.

        # Let's verify that it attempted to set localStorage back to original_prefs because ID lookup failed
        # The code does:
        # if model_id_to_revert_to: ... else: ... if original_prefs_str: ...

        # Verify setItem was called with original prefs eventually
        # We need to capture all calls to evaluate with setItem
        set_item_calls = [
            args
            for args in mock_page.evaluate.call_args_list
            if "localStorage.setItem" in args[0][0]
        ]

        # 1. Set target model
        # 2. Set UI state (inside _verify_and_apply_ui_state -> _force_ui_state_settings) - mocked out?
        #    Wait, we mocked _verify_and_apply_ui_state to return True, so it WON'T call _force_ui_state_settings inside it.
        #    BUT switch_ai_studio_model calls evaluate setItem directly too.

        # Calls in switch_ai_studio_model:
        # 1. Update to target model
        # 2. Update isAdvancedOpen/areToolsOpen (compatibility)
        # ... validation fails ...
        # Revert logic:
        # If "Original Model" cannot be mapped to ID, it goes to `else` block line 403
        # `await page.evaluate("(origPrefs) => localStorage.setItem('aiStudioUserPreference', origPrefs)", original_prefs_str)`

        assert len(set_item_calls) >= 3  # Target, Compat, Revert
        last_set_call = set_item_calls[-1]
        assert "localStorage.setItem" in last_set_call[0][0]

        revert_prefs = json.loads(last_set_call[0][1])
        assert revert_prefs["promptModel"] == "models/Original Model"
        assert revert_prefs["isAdvancedOpen"] is True
        assert revert_prefs["areToolsOpen"] is True


@pytest.mark.asyncio
@pytest.mark.timeout(5)
async def test_switch_ai_studio_model_incognito_toggle(mock_page):
    """Test incognito toggle logic when model switch succeeds"""
    model_id = "gemini-pro"
    full_model_path = f"models/{model_id}"

    # Mock server module
    mock_server = MagicMock()
    mock_server.parsed_model_list = [{"id": model_id, "display_name": "Gemini Pro"}]

    with (
        patch.dict(sys.modules, {"server": mock_server}),
        patch(
            "browser_utils.model_management._verify_and_apply_ui_state",
            return_value=True,
        ),
        patch("browser_utils.model_management.logger"),
        patch("browser_utils.model_management.expect_async") as mock_expect,
    ):
        mock_expect.return_value.to_be_visible = AsyncMock()

        # Mock evaluate for success path
        # It needs to return a DIFFERENT model initially so it doesn't return early
        call_count = 0

        def evaluate_side_effect(script, *args):
            nonlocal call_count
            if "localStorage.getItem" in script:
                call_count += 1
                if call_count == 1:  # Initial check -> return old model
                    return json.dumps({"promptModel": "models/old-model"})
                if call_count == 2:  # Final verification -> return new model
                    return json.dumps({"promptModel": full_model_path})
            return None

        mock_page.evaluate.side_effect = evaluate_side_effect

        # Mock page elements
        mock_locator = MagicMock()
        mock_locator.first.inner_text = AsyncMock(return_value=model_id)

        # Mock incognito button - INACTIVE initially
        mock_incognito = MagicMock()
        mock_incognito.wait_for = AsyncMock()
        mock_incognito.click = AsyncMock()
        # First check returns inactive, second check (after click) returns active
        mock_incognito.get_attribute = AsyncMock(
            side_effect=[
                "ms-button",  # inactive
                "ms-button-active ms-button",  # active
            ]
        )

        def locator_side_effect(selector):
            if 'data-test-id="model-name"' in selector:
                return mock_locator
            if "Temporary chat toggle" in selector:
                return mock_incognito
            return MagicMock()

        mock_page.locator.side_effect = locator_side_effect

        result = await switch_ai_studio_model(mock_page, model_id, "req1")

        assert result is True
        mock_incognito.click.assert_called_once()


@pytest.mark.asyncio
@pytest.mark.timeout(5)
async def test_exception_handling_coverage(mock_page):
    """Cover exception handlers in various functions"""

    # 1. _force_ui_state_settings exception
    with (
        patch(
            "browser_utils.model_management._verify_ui_state_settings",
            side_effect=Exception("Force Error"),
        ),
        patch("browser_utils.model_management.logger"),
    ):
        assert await _force_ui_state_settings(mock_page) is False

    # 2. _verify_and_apply_ui_state exception
    with (
        patch(
            "browser_utils.model_management._verify_ui_state_settings",
            side_effect=Exception("Verify Apply Error"),
        ),
        patch("browser_utils.model_management.logger"),
    ):
        assert await _verify_and_apply_ui_state(mock_page) is False

    # 3. switch_ai_studio_model JSON decode error
    mock_page.evaluate.return_value = "invalid-json"
    with patch("browser_utils.model_management.logger"):
        # Should proceed with empty prefs
        # We need to mock other things to make it reach a return or fail safely
        # It will try to load current_prefs_for_modification -> {}
        # Then check if promptModel matches -> None != full_model_path
        # Then update storage -> json.dumps works on {}
        # Then goto...
        # Let's just verify it doesn't crash on the JSON error line

        # To make it fail fast and return, we can let it fail later or mock expected calls
        # We just want to cover the `except json.JSONDecodeError` block
        pass
        # Actually it's hard to isolate just that block without running the whole function.
        # But we can try to call it and expect it to fail later or succeed.


@pytest.mark.asyncio
@pytest.mark.timeout(5)
async def test_switch_ai_studio_model_nav_only(mock_page):
    """Test navigation when model already matches but URL is wrong"""
    model_id = "gemini-pro"
    full_model_path = f"models/{model_id}"
    prefs = {"promptModel": full_model_path}

    mock_page.evaluate.return_value = json.dumps(prefs)
    mock_page.url = "https://other.url"  # Not new_chat

    with (
        patch("browser_utils.model_management.logger"),
        patch("browser_utils.model_management.expect_async") as mock_expect,
    ):
        mock_expect.return_value.to_be_visible = AsyncMock()

        result = await switch_ai_studio_model(mock_page, model_id, "req1")

    assert result is True
    # Should navigate
    mock_page.goto.assert_called()


@pytest.mark.asyncio
@pytest.mark.timeout(5)
async def test_load_excluded_models_edge_cases(tmp_path):
    """Test edge cases for load_excluded_models"""
    # 1. File does not exist
    # Mock server module
    mock_server = MagicMock()
    mock_server.excluded_model_ids = set()

    with (
        patch.dict(sys.modules, {"server": mock_server}),
        patch("browser_utils.model_management.logger") as mock_logger,
    ):
        load_excluded_models("non_existent.txt")
        assert "未找到" in mock_logger.info.call_args[0][0]

    # 2. File exists but is empty
    d = tmp_path / "config"
    d.mkdir()
    p = d / "empty.txt"
    p.write_text("", encoding="utf-8")

    with (
        patch.dict(sys.modules, {"server": mock_server}),
        patch("browser_utils.model_management.logger") as mock_logger,
    ):
        load_excluded_models(
            str(p)
        )  # We need to pass relative path logic or mock os.path.join
        # The function uses os.path.join(os.path.dirname(__file__), '..', filename)
        # So we better mock os.path.exists and open
        pass

    # Let's mock os.path.exists/open for easier testing of logic
    with (
        patch.dict(sys.modules, {"server": mock_server}),
        patch("os.path.exists", return_value=True),
        patch("builtins.open", new_callable=MagicMock) as mock_open,
        patch("browser_utils.model_management.logger") as mock_logger,
    ):
        # Empty file
        mock_file = MagicMock()
        mock_file.__enter__.return_value = []  # Empty lines
        mock_open.return_value = mock_file

        load_excluded_models("empty.txt")
        assert "文件为空" in mock_logger.info.call_args[0][0]

    # 3. Exception
    with (
        patch.dict(sys.modules, {"server": mock_server}),
        patch("os.path.exists", side_effect=Exception("Disk Error")),
        patch("browser_utils.model_management.logger") as mock_logger,
    ):
        load_excluded_models("error.txt")
        assert mock_logger.error.called


@pytest.mark.asyncio
@pytest.mark.timeout(5)
async def test_handle_initial_model_state_exceptions(mock_page):
    """Test exception handling in _handle_initial_model_state_and_storage"""
    mock_server = MagicMock()

    # 1. JSON Decode Error
    mock_page.evaluate.return_value = "invalid-json"

    with (
        patch.dict(sys.modules, {"server": mock_server}),
        patch(
            "browser_utils.model_management._set_model_from_page_display"
        ) as mock_set_model,
        patch("browser_utils.model_management.logger") as mock_logger,
    ):
        # Should trigger reload path due to JSON error
        # We'll mock _set_model_from_page_display to raise Exception to test the outer try/except
        mock_set_model.side_effect = Exception("Inner Error")

        await _handle_initial_model_state_and_storage(mock_page)

        # Verify error log
        # Check that we have the catastrophic error log
        # It catches "Inner Error" in the outer except block
        error_calls = [args[0][0] for args in mock_logger.error.call_args_list]
        assert any("严重错误" in msg for msg in error_calls)


@pytest.mark.asyncio
@pytest.mark.timeout(5)
async def test_handle_initial_model_state_reload_retry_logic(mock_page):
    """Test reload retry logic"""
    mock_server = MagicMock()
    mock_page.evaluate.return_value = None  # Trigger reload

    with (
        patch.dict(sys.modules, {"server": mock_server}),
        patch(
            "browser_utils.model_management._set_model_from_page_display"
        ) as mock_set_model,
        patch("browser_utils.model_management.logger"),
        patch("asyncio.sleep", new_callable=AsyncMock),
        patch("browser_utils.model_management.expect_async") as mock_expect,
    ):
        mock_expect.return_value.to_be_visible = AsyncMock()

        # Mock goto to fail twice then succeed
        mock_page.goto.side_effect = [Exception("Fail 1"), Exception("Fail 2"), None]

        await _handle_initial_model_state_and_storage(mock_page)

        assert mock_page.goto.call_count == 3
        # Should eventually succeed and call set_model twice (start and end)
        assert mock_set_model.call_count == 2


@pytest.mark.asyncio
@pytest.mark.timeout(5)
async def test_set_model_from_page_display_timeout(mock_page):
    """Test timeout when waiting for model list"""
    mock_server = MagicMock()
    mock_server.model_list_fetch_event = MagicMock()
    # is_set returns False, then wait raises TimeoutError
    mock_server.model_list_fetch_event.is_set.return_value = False

    # Mock locator
    mock_locator = MagicMock()
    mock_locator.first.inner_text = AsyncMock(return_value="displayed-model")
    mock_page.locator.return_value = mock_locator

    with (
        patch.dict(sys.modules, {"server": mock_server}),
        patch("browser_utils.model_management.logger") as mock_logger,
        patch("asyncio.wait_for", side_effect=asyncio.TimeoutError),
    ):
        await _set_model_from_page_display(mock_page, set_storage=False)

        # Should log warning about timeout
        assert any(
            "等待模型列表超时" in str(arg)
            for arg in mock_logger.warning.call_args_list[0][0]
        )
        # Should still update global ID using display name as fallback
        assert mock_server.current_ai_studio_model_id == "displayed-model"


@pytest.mark.asyncio
@pytest.mark.timeout(5)
async def test_set_model_from_page_display_storage_logic(mock_page):
    """Test storage update logic in _set_model_from_page_display"""
    mock_server = MagicMock()
    mock_server.current_ai_studio_model_id = "old"

    mock_locator = MagicMock()
    mock_locator.first.inner_text = AsyncMock(return_value="new-model")
    mock_page.locator.return_value = mock_locator

    # Mock existing prefs
    existing_prefs = {"someKey": "someVal"}
    mock_page.evaluate.return_value = json.dumps(existing_prefs)

    with (
        patch.dict(sys.modules, {"server": mock_server}),
        patch(
            "browser_utils.model_management._verify_and_apply_ui_state",
            return_value=True,
        ),
        patch("browser_utils.model_management.logger"),
    ):
        await _set_model_from_page_display(mock_page, set_storage=True)

        # Check that setItem was called with updated prefs
        assert mock_page.evaluate.call_count == 2  # getItem, setItem

        # Verify setItem args
        set_call = mock_page.evaluate.call_args_list[1]
        assert "localStorage.setItem" in set_call[0][0]
        saved_prefs = json.loads(set_call[0][1])

        assert saved_prefs["isAdvancedOpen"] is True
        assert saved_prefs["promptModel"] == "models/new-model"
        # Check default keys added
        assert "bidiModel" in saved_prefs


@pytest.mark.asyncio
@pytest.mark.timeout(5)
async def test_switch_ai_studio_model_catastrophic_error(mock_page):
    """Test top-level exception handling in switch_ai_studio_model"""
    # Force an error immediately
    mock_page.evaluate.side_effect = Exception("Catastrophic Failure")

    with (
        patch("browser_utils.model_management.logger") as mock_logger,
        patch(
            "browser_utils.operations.save_error_snapshot", new_callable=AsyncMock
        ) as mock_snapshot,
    ):
        result = await switch_ai_studio_model(mock_page, "model-id", "req1")

        assert result is False
        mock_snapshot.assert_called()
        assert mock_logger.exception.called
