from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from playwright.async_api import Error as PlaywrightAsyncError

from browser_utils.operations import (
    _get_final_response_content,
    _get_injected_models,
    _handle_model_list_response,
    _parse_userscript_models,
    _wait_for_response_completion,
    detect_and_extract_page_error,
    get_raw_text_content,
    get_response_via_copy_button,
    get_response_via_edit_button,
)


@pytest.mark.asyncio
async def test_get_raw_text_content_pre_element():
    """Test getting text from pre element."""
    element = MagicMock()
    pre_element = MagicMock()

    element.locator.return_value.last = pre_element
    element.wait_for = AsyncMock()
    pre_element.wait_for = AsyncMock()
    pre_element.inner_text = AsyncMock(return_value="pre content")

    result = await get_raw_text_content(element, "old", "req_id")
    assert result == "pre content"


@pytest.mark.asyncio
async def test_get_raw_text_content_fallback():
    """Test fallback to element text when pre not found."""
    element = MagicMock()
    pre_element = MagicMock()

    element.locator.return_value.last = pre_element
    element.wait_for = AsyncMock()
    pre_element.wait_for = AsyncMock(side_effect=PlaywrightAsyncError("Not found"))
    element.inner_text = AsyncMock(return_value="element content")

    result = await get_raw_text_content(element, "old", "req_id")
    assert result == "element content"


def test_parse_userscript_models():
    """Test parsing models from userscript."""
    script = """
    const SCRIPT_VERSION = 'v1.0';
    const MODELS_TO_INJECT = [
        {
            name: 'models/test-model',
            displayName: 'Test Model',
            description: 'A test model'
        }
    ];
    """
    models = _parse_userscript_models(script)
    assert len(models) == 1
    assert models[0]["name"] == "models/test-model"


def test_parse_userscript_models_empty():
    """Test parsing empty or invalid userscript."""
    script = "const SCRIPT_VERSION = 'v1.0';"
    models = _parse_userscript_models(script)
    assert models == []


@patch("os.environ.get")
@patch("os.path.exists")
@patch("builtins.open")
def test_get_injected_models(
    mock_open: MagicMock, mock_exists: MagicMock, mock_env: MagicMock
):
    """Test getting injected models."""
    mock_env.return_value = "true"
    mock_exists.return_value = True

    script_content = """
    const SCRIPT_VERSION = 'v1.0';
    const MODELS_TO_INJECT = [
        {
            name: 'models/test-model',
            displayName: 'Test Model',
            description: 'A test model'
        }
    ];
    """
    mock_open.return_value.__enter__.return_value.read.return_value = script_content

    models = _get_injected_models()
    assert len(models) == 1
    assert models[0]["id"] == "test-model"
    assert models[0]["injected"] is True


@pytest.mark.asyncio
async def test_handle_model_list_response_success():
    """Test handling successful model list response.

    Note: This is a minimal test that verifies the function can be called without crashing.
    Full integration testing of model list parsing requires complex server state mocking.
    """
    response = MagicMock()
    response.url = "https://ai.google.dev/api/models"
    response.ok = True
    response.json = AsyncMock(
        return_value={
            "models": [
                {
                    "name": "models/gemini-pro",
                    "displayName": "Gemini Pro",
                    "description": "Best model",
                }
            ]
        }
    )

    mock_server = MagicMock()
    mock_server.parsed_model_list = []
    mock_server.global_model_list_raw_json = None
    mock_server.model_list_fetch_event = None

    with patch.dict("sys.modules", {"server": mock_server}):
        await _handle_model_list_response(response)


@pytest.mark.asyncio
async def test_detect_and_extract_page_error_found(mock_page: MagicMock):
    """Test detecting page error."""
    error_locator = MagicMock()
    message_locator = MagicMock()

    mock_page.locator.return_value.last = error_locator
    error_locator.locator.return_value = message_locator

    error_locator.wait_for = AsyncMock()
    message_locator.text_content = AsyncMock(return_value="Error message")

    result = await detect_and_extract_page_error(mock_page, "req_id")
    assert result == "Error message"


@pytest.mark.asyncio
async def test_detect_and_extract_page_error_not_found(mock_page: MagicMock):
    """Test detecting page error when none exists."""
    error_locator = MagicMock()
    mock_page.locator.return_value.last = error_locator
    error_locator.wait_for = AsyncMock(side_effect=PlaywrightAsyncError("Timeout"))

    result = await detect_and_extract_page_error(mock_page, "req_id")
    assert result is None


@pytest.mark.asyncio
async def test_get_response_via_edit_button_success(mock_page: MagicMock):
    """Test getting response via edit button."""
    check_disconnect = MagicMock()

    # Setup locator chain: page -> last message -> edit button & textarea
    last_msg = MagicMock()
    edit_btn = MagicMock()
    textarea = MagicMock()

    mock_page.locator.return_value.last = last_msg
    last_msg.get_by_label = MagicMock(return_value=edit_btn)
    last_msg.locator.return_value = textarea
    textarea.locator.return_value = textarea  # Nested locator

    # Setup async actions
    last_msg.hover = AsyncMock()
    edit_btn.click = AsyncMock()
    textarea.get_attribute = AsyncMock(return_value="Response content")

    # Mock playwright expect
    with patch("playwright.async_api.expect", new_callable=MagicMock) as mock_expect:
        mock_expect_obj = MagicMock()
        mock_expect_obj.to_be_visible = AsyncMock()
        mock_expect.return_value = mock_expect_obj

        # Execute
        result = await get_response_via_edit_button(
            mock_page, "req_id", check_disconnect
        )

        # Verify
        assert result == "Response content"


@pytest.mark.asyncio
async def test_get_response_via_copy_button_success(mock_page: MagicMock):
    """Test getting response via copy button."""
    check_disconnect = MagicMock()

    # Setup locators
    last_msg = MagicMock()
    mock_page.locator.return_value.last = last_msg

    more_opts = MagicMock()
    last_msg.get_by_label.return_value = more_opts

    copy_btn = MagicMock()
    mock_page.get_by_role.return_value = copy_btn

    # Setup actions
    last_msg.hover = AsyncMock()
    more_opts.click = AsyncMock()
    copy_btn.click = AsyncMock()
    mock_page.evaluate = AsyncMock(return_value="Copied content")

    with patch("playwright.async_api.expect", new_callable=MagicMock) as mock_expect:
        mock_expect_obj = MagicMock()
        mock_expect_obj.to_be_visible = AsyncMock()
        mock_expect.return_value = mock_expect_obj

        # The function calls copy_markdown_button.click()
        # The error log says: '复制 Markdown' 按钮 (通过 get_by_role) 点击失败: 'coroutine' object has no attribute 'click'

        # This means copy_markdown_button is a coroutine?
        # copy_markdown_button = page.get_by_role("menuitem", name="Copy markdown")
        # page.get_by_role returns a Locator (synchronous object).

        # But we mocked mock_page.get_by_role.return_value = copy_btn
        # copy_btn = MagicMock()
        # copy_btn.click = AsyncMock()

        # If mock_page.get_by_role is an AsyncMock (default for methods on AsyncMock), calling it returns a coroutine.
        # But get_by_role is synchronous in Playwright (returns Locator).
        # So we need to make sure mock_page.get_by_role returns the locator immediately, not a coroutine.

        # mock_page is created as AsyncMock in conftest.py.
        # Methods on AsyncMock are AsyncMocks by default.
        # We need to set get_by_role to be a MagicMock (synchronous).

        mock_page.get_by_role = MagicMock(return_value=copy_btn)

        result = await get_response_via_copy_button(
            mock_page, "req_id", check_disconnect
        )
        assert result == "Copied content"


@pytest.mark.asyncio
async def test_wait_for_response_completion_success(mock_page: MagicMock):
    """Test waiting for response completion."""
    prompt_area = MagicMock()
    submit_btn = MagicMock()
    edit_btn = MagicMock()
    check_disconnect = MagicMock()

    # Setup states
    prompt_area.input_value = AsyncMock(return_value="")
    submit_btn.is_disabled = AsyncMock(return_value=True)
    edit_btn.is_visible = AsyncMock(return_value=True)

    result = await _wait_for_response_completion(
        mock_page,
        prompt_area,
        submit_btn,
        edit_btn,
        "req_id",
        check_disconnect,
        "chat_id",
        timeout_ms=1000,
        initial_wait_ms=0,
    )
    assert result is True


@pytest.mark.asyncio
async def test_get_final_response_content_edit_success(mock_page: MagicMock):
    """Test getting final content via edit button."""
    check_disconnect = MagicMock()

    with patch(
        "browser_utils.operations_modules.interactions.get_response_via_edit_button",
        new_callable=AsyncMock,
    ) as mock_edit:
        mock_edit.return_value = "Content"

        result = await _get_final_response_content(
            mock_page, "req_id", check_disconnect
        )
        assert result == "Content"


@pytest.mark.asyncio
async def test_get_final_response_content_fallback_copy(mock_page: MagicMock):
    """Test fallback to copy button when edit fails."""
    check_disconnect = MagicMock()

    with (
        patch(
            "browser_utils.operations_modules.interactions.get_response_via_edit_button",
            new_callable=AsyncMock,
        ) as mock_edit,
        patch(
            "browser_utils.operations_modules.interactions.get_response_via_copy_button",
            new_callable=AsyncMock,
        ) as mock_copy,
    ):
        mock_edit.return_value = None
        mock_copy.return_value = "Content"

        result = await _get_final_response_content(
            mock_page, "req_id", check_disconnect
        )
        assert result == "Content"
