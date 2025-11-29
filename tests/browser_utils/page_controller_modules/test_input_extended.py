from unittest.mock import AsyncMock, MagicMock, mock_open, patch

import pytest
from playwright.async_api import TimeoutError

from browser_utils.page_controller_modules.input import InputController


@pytest.fixture
def mock_page_controller():
    controller = MagicMock()
    controller.page = MagicMock()
    controller.logger = MagicMock()
    controller.req_id = "test-req-id"
    # Setup page methods
    controller.page.locator = MagicMock()
    controller.page.evaluate = AsyncMock()
    controller.page.keyboard = MagicMock()
    controller.page.keyboard.press = AsyncMock()
    controller._check_disconnect = AsyncMock()
    return controller


@pytest.fixture
def input_controller(mock_page_controller):
    return InputController(
        mock_page_controller.page,
        mock_page_controller.logger,
        mock_page_controller.req_id,
    )


@pytest.fixture(autouse=True)
def mock_expect_async():
    """Mock playwright.async_api.expect globally for this module."""
    with patch("browser_utils.page_controller_modules.input.expect_async") as mock:
        # Configure the mock to return an object with async methods
        matcher_mock = MagicMock()
        matcher_mock.to_be_visible = AsyncMock()
        matcher_mock.to_be_hidden = AsyncMock()
        matcher_mock.to_have_count = AsyncMock()
        mock.return_value = matcher_mock
        yield mock


@pytest.fixture(autouse=True)
def mock_constants():
    CONSTANTS = {
        "PROMPT_TEXTAREA_SELECTOR": "textarea.prompt",
        "SUBMIT_BUTTON_SELECTOR": "button.submit",
        "RESPONSE_CONTAINER_SELECTOR": "div.response",
    }
    # Patch in the input module where they are used
    with patch.multiple("browser_utils.page_controller_modules.input", **CONSTANTS):
        yield


@pytest.fixture(autouse=True)
def mock_timeouts():
    """Patch timeouts to be short for testing."""
    with patch("config.timeouts.SUBMIT_BUTTON_ENABLE_TIMEOUT_MS", 100):
        yield


@pytest.mark.asyncio
@pytest.mark.timeout(5)
async def test_open_upload_menu_retry_logic(input_controller, mock_page_controller):
    """Test retry logic when menu fails to open first time."""
    # Setup
    trigger = MagicMock()
    trigger.click = AsyncMock()

    menu_container = MagicMock()
    menu_item = MagicMock()

    # First visibility check fails, second succeeds (menu), third succeeds (button)
    matcher = MagicMock()
    matcher.to_be_visible = AsyncMock(
        side_effect=[Exception("Not visible"), None, None]
    )

    with patch(
        "browser_utils.page_controller_modules.input.expect_async", return_value=matcher
    ):

        def locator_side_effect(selector):
            if 'aria-label="Insert assets' in selector:
                return trigger
            if "cdk-overlay-container" in selector:
                return menu_container
            if "div[role='menu']" in selector:
                return menu_item
            return MagicMock()

        mock_page_controller.page.locator.side_effect = locator_side_effect

        # We also need the upload button logic to pass to reach success
        upload_btn = MagicMock()
        upload_btn.count = AsyncMock(return_value=1)
        upload_btn.first = upload_btn
        upload_btn.locator.return_value.count = AsyncMock(
            return_value=1
        )  # Input exists
        upload_btn.locator.return_value.set_input_files = AsyncMock()

        menu_container.locator.side_effect = (
            lambda s: upload_btn if "Upload File" in s else menu_item
        )

        result = await input_controller._open_upload_menu_and_choose_file(["test.jpg"])

        assert result is True
        assert trigger.click.call_count == 2


@pytest.mark.asyncio
@pytest.mark.timeout(5)
async def test_open_upload_menu_fail_after_retry(
    input_controller, mock_page_controller
):
    """Test failure when menu fails to open after retry."""
    trigger = MagicMock()
    trigger.click = AsyncMock()

    matcher = MagicMock()
    matcher.to_be_visible = AsyncMock(side_effect=Exception("Not visible"))

    with patch(
        "browser_utils.page_controller_modules.input.expect_async", return_value=matcher
    ):
        mock_page_controller.page.locator.return_value = trigger

        result = await input_controller._open_upload_menu_and_choose_file(["test.jpg"])

        assert result is False
        assert trigger.click.call_count == 2


@pytest.mark.asyncio
@pytest.mark.timeout(5)
async def test_open_upload_menu_no_upload_button(
    input_controller, mock_page_controller
):
    """Test failure when 'Upload File' button is not found."""
    matcher = MagicMock()
    matcher.to_be_visible = AsyncMock()

    with patch(
        "browser_utils.page_controller_modules.input.expect_async", return_value=matcher
    ):
        upload_btn = MagicMock()
        upload_btn.count = AsyncMock(return_value=0)  # Not found

        menu_container = MagicMock()
        menu_container.locator.return_value = upload_btn

        mock_page_controller.page.locator.side_effect = (
            lambda s: menu_container if "cdk-overlay-container" in s else MagicMock()
        )

        result = await input_controller._open_upload_menu_and_choose_file(["test.jpg"])

        assert result is False


@pytest.mark.asyncio
@pytest.mark.timeout(5)
async def test_handle_post_upload_dialog_exceptions(
    input_controller, mock_page_controller
):
    """Test exception handling in _handle_post_upload_dialog."""
    # Setup overlay container
    overlay = MagicMock()
    overlay.count = AsyncMock(return_value=1)

    # Setup button loop that raises exception then finds nothing
    btn = MagicMock()
    btn.count = AsyncMock(side_effect=Exception("Locator error"))

    overlay.locator.return_value = btn
    mock_page_controller.page.locator.return_value = overlay

    # Should not raise exception
    await input_controller._handle_post_upload_dialog()


@pytest.mark.asyncio
@pytest.mark.timeout(5)
async def test_ensure_files_attached_timeout(input_controller):
    """Test _ensure_files_attached returns False on timeout."""
    wrapper = MagicMock()
    # Always return 0 files
    wrapper.evaluate = AsyncMock(return_value={"inputs": 0, "chips": 0, "blobs": 0})

    result = await input_controller._ensure_files_attached(wrapper, timeout_ms=100)
    assert result is False


@pytest.mark.asyncio
@pytest.mark.timeout(5)
async def test_simulate_drag_drop_file_read_error(input_controller):
    """Test _simulate_drag_drop_files handling file read error."""
    # If read fails, it logs warning and skips. If no files left, raises exception.
    with patch("builtins.open", side_effect=Exception("Read failed")):
        with pytest.raises(Exception, match="无可用文件用于拖放"):
            await input_controller._simulate_drag_drop_files(
                MagicMock(), ["bad_file.jpg"]
            )


@pytest.mark.asyncio
@pytest.mark.timeout(5)
async def test_simulate_drag_drop_fallback_to_body(
    input_controller, mock_page_controller
):
    """Test _simulate_drag_drop_files fallback to document.body."""
    target = MagicMock()

    # All candidates fail visibility check
    matcher = MagicMock()
    matcher.to_be_visible = AsyncMock(side_effect=Exception("Not visible"))

    with (
        patch("builtins.open", mock_open(read_data=b"data")),
        patch(
            "browser_utils.page_controller_modules.input.expect_async",
            return_value=matcher,
        ),
    ):
        # page.evaluate should be called for fallback
        mock_page_controller.page.evaluate = AsyncMock()

        await input_controller._simulate_drag_drop_files(target, ["test.jpg"])

        mock_page_controller.page.evaluate.assert_called_once()


@pytest.mark.asyncio
@pytest.mark.timeout(5)
async def test_submit_prompt_wait_button_enabled_timeout(
    input_controller, mock_page_controller
):
    """Test submit_prompt raising TimeoutError when button doesn't enable."""
    # Setup basics
    prompt_area = MagicMock()
    prompt_area.evaluate = AsyncMock()

    submit_btn = MagicMock()
    submit_btn.is_enabled = AsyncMock(return_value=False)  # Never enabled

    mock_page_controller.page.locator.side_effect = (
        lambda s: submit_btn if "submit" in s else prompt_area
    )

    # Mock timeout constant to be very short
    with patch("config.timeouts.SUBMIT_BUTTON_ENABLE_TIMEOUT_MS", 100):
        with pytest.raises(TimeoutError, match="Submit button not enabled"):
            await input_controller.submit_prompt("test", [], lambda x: None)


@pytest.mark.asyncio
@pytest.mark.timeout(5)
async def test_submit_prompt_all_methods_fail(input_controller, mock_page_controller):
    """Test submit_prompt raising exception when all submit methods fail."""
    # Setup
    prompt_area = MagicMock()
    prompt_area.evaluate = AsyncMock()

    submit_btn = MagicMock()
    submit_btn.is_enabled = AsyncMock(return_value=True)
    submit_btn.click = AsyncMock(side_effect=Exception("Click failed"))

    mock_page_controller.page.locator.side_effect = (
        lambda s: submit_btn if "submit" in s else prompt_area
    )

    # Mock internal submit methods to fail
    input_controller._try_enter_submit = AsyncMock(return_value=False)
    input_controller._try_combo_submit = AsyncMock(return_value=False)
    input_controller._handle_post_upload_dialog = AsyncMock()

    with pytest.raises(
        Exception, match="Submit failed: Button, Enter, and Combo key all failed"
    ):
        await input_controller.submit_prompt("test", [], lambda x: None)


@pytest.mark.asyncio
@pytest.mark.timeout(5)
async def test_open_upload_menu_outer_exception(input_controller):
    """Test _open_upload_menu_and_choose_file handles outer exception."""
    # Mock locator to raise generic exception immediately
    input_controller.page.locator.side_effect = Exception("Fatal error")

    result = await input_controller._open_upload_menu_and_choose_file(["test.jpg"])
    assert result is False
