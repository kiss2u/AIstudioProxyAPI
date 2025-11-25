import pytest
from unittest.mock import MagicMock, AsyncMock, patch
from browser_utils.initialization import _initialize_page_logic, _close_page_logic

@pytest.mark.asyncio
async def test_initialize_page_logic_success(mock_browser, mock_browser_context, mock_page, mock_env):
    # Mock server module
    with patch.dict("sys.modules", {"server": MagicMock()}):
        import server
        server.PLAYWRIGHT_PROXY_SETTINGS = None
        
        # Mock page finding logic
        mock_page.url = "https://aistudio.google.com/prompts/new_chat"
        mock_page.is_closed.return_value = False
        mock_browser_context.pages = [mock_page]
        
        # Mock locators for verification
        # inner_text needs to be awaitable
        mock_page.locator.return_value.first.inner_text = AsyncMock(return_value="Gemini 1.5 Pro")
        
        mock_expect = MagicMock()
        # expect_async(locator) returns an object (assertion wrapper)
        # that object has async methods like to_be_visible()
        assertion_wrapper = MagicMock()
        assertion_wrapper.to_be_visible = AsyncMock()
        mock_expect.return_value = assertion_wrapper
        
        with patch("browser_utils.initialization.core.expect_async", mock_expect):
            page, ready = await _initialize_page_logic(mock_browser)
            
            assert page == mock_page
            assert ready is True
            mock_browser.new_context.assert_called()

@pytest.mark.asyncio
async def test_initialize_page_logic_new_page(mock_browser, mock_browser_context, mock_page, mock_env):
    # Mock server module
    with patch.dict("sys.modules", {"server": MagicMock()}):
        import server
        server.PLAYWRIGHT_PROXY_SETTINGS = None
        
        # No existing pages
        mock_browser_context.pages = []
        mock_browser_context.new_page.return_value = mock_page
        mock_page.url = "https://aistudio.google.com/prompts/new_chat"
        
        # Mock locators for verification
        # inner_text needs to be awaitable
        mock_page.locator.return_value.first.inner_text = AsyncMock(return_value="Gemini 1.5 Pro")
        
        mock_expect = MagicMock()
        assertion_wrapper = MagicMock()
        assertion_wrapper.to_be_visible = AsyncMock()
        mock_expect.return_value = assertion_wrapper
        
        with patch("browser_utils.initialization.core.expect_async", mock_expect):
            page, ready = await _initialize_page_logic(mock_browser)
            
            assert page == mock_page
            assert ready is True
            mock_page.goto.assert_called()

@pytest.mark.asyncio
async def test_close_page_logic_success():
    # Mock page
    mock_page = AsyncMock()
    # is_closed must be synchronous and return False
    mock_page.is_closed = MagicMock(return_value=False)
    
    # Import server directly to modify it
    import server
    
    # Backup
    original_page = getattr(server, 'page_instance', None)
    original_ready = getattr(server, 'is_page_ready', False)
    
    try:
        server.page_instance = mock_page
        server.is_page_ready = True
        
        await _close_page_logic()
        
        mock_page.close.assert_called()
        assert server.page_instance is None
        assert server.is_page_ready is False
    finally:
        # Restore
        server.page_instance = original_page
        server.is_page_ready = original_ready

@pytest.mark.asyncio
async def test_close_page_logic_already_closed():
    # Mock server module
    with patch.dict("sys.modules", {"server": MagicMock()}):
        import server
        mock_page = AsyncMock()
        mock_page.is_closed.return_value = True
        server.page_instance = mock_page
        
        await _close_page_logic()
        
        mock_page.close.assert_not_called()
        assert server.page_instance is None

@pytest.mark.asyncio
async def test_initialize_page_logic_headless_auth_missing(mock_browser, mock_env):
    with patch.dict("os.environ", {"LAUNCH_MODE": "headless", "ACTIVE_AUTH_JSON_PATH": ""}), \
         patch.dict("sys.modules", {"server": MagicMock()}):
        
        with pytest.raises(RuntimeError) as exc:
            await _initialize_page_logic(mock_browser)
        assert "ACTIVE_AUTH_JSON_PATH" in str(exc.value)

@pytest.mark.asyncio
async def test_initialize_page_logic_proxy_settings(mock_browser, mock_browser_context, mock_page, mock_env):
    with patch.dict("sys.modules", {"server": MagicMock()}) as mock_server_module:
        import server
        server.PLAYWRIGHT_PROXY_SETTINGS = {"server": "http://proxy:8080"}
        
        mock_browser_context.pages = [mock_page]
        mock_page.url = "https://aistudio.google.com/prompts/new_chat"
        mock_page.is_closed.return_value = False
        
        mock_page.locator.return_value.first.inner_text = AsyncMock(return_value="Gemini 1.5 Pro")
        
        mock_expect = MagicMock()
        assertion_wrapper = MagicMock()
        assertion_wrapper.to_be_visible = AsyncMock()
        mock_expect.return_value = assertion_wrapper
        
        with patch("browser_utils.initialization.core.expect_async", mock_expect):
            await _initialize_page_logic(mock_browser)
            
            # Verify proxy was passed to new_context
            call_args = mock_browser.new_context.call_args
            assert call_args is not None
            assert call_args[1]['proxy'] == {"server": "http://proxy:8080"}