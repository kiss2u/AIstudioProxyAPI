import asyncio
import sys
import types
from unittest.mock import AsyncMock, MagicMock

import pytest

# @pytest.fixture(scope="session")
# def event_loop():
#     """Create an instance of the default event loop for each test case."""
#     loop = asyncio.get_event_loop_policy().new_event_loop()
#     yield loop
#     loop.close()


@pytest.fixture(autouse=True)
def mock_server_module():
    """Mock the server module to prevent import errors and provide global state."""
    module_name = "server"

    # Create a mock module
    mock_module = types.ModuleType(module_name)

    # Set up required attributes
    mock_module.logger = MagicMock()
    mock_module.request_queue = asyncio.Queue()
    mock_module.processing_lock = asyncio.Lock()
    mock_module.model_switching_lock = asyncio.Lock()
    mock_module.params_cache_lock = asyncio.Lock()
    mock_module.page_instance = AsyncMock()
    mock_module.browser_instance = AsyncMock()
    mock_module.parsed_model_list = []
    mock_module.log_ws_manager = MagicMock()
    mock_module.STREAM_QUEUE = MagicMock()
    mock_module.STREAM_PROCESS = AsyncMock()
    mock_module.PLAYWRIGHT_PROXY_SETTINGS = {}
    mock_module.is_initializing = False
    mock_module.is_page_ready = True
    mock_module.is_browser_connected = True
    mock_module.model_list_fetch_event = asyncio.Event()
    mock_module.worker_task = MagicMock()
    mock_module.queue_worker = AsyncMock()
    mock_module.playwright_manager = AsyncMock()
    mock_module.global_model_list_raw_json = None
    mock_module.current_ai_studio_model_id = None
    mock_module.is_playwright_ready = True
    mock_module.excluded_model_ids = []
    mock_module.console_logs = []
    mock_module.network_log = {"requests": [], "responses": []}

    # Save original if it exists
    original_module = sys.modules.get(module_name)

    # Inject mock
    sys.modules[module_name] = mock_module

    yield mock_module

    # Restore original or clean up
    if original_module:
        sys.modules[module_name] = original_module
    else:
        sys.modules.pop(module_name, None)


@pytest.fixture
def mock_env(monkeypatch):
    """Mock environment variables."""
    monkeypatch.setenv("LAUNCH_MODE", "test")
    monkeypatch.setenv("STREAM_PORT", "0")
    monkeypatch.setenv("PORT", "2048")


@pytest.fixture
def mock_page():
    """Mock Playwright Page object."""
    page = AsyncMock()
    page.goto = AsyncMock()
    page.wait_for_selector = AsyncMock()
    page.click = AsyncMock()
    page.fill = AsyncMock()
    page.evaluate = AsyncMock()
    page.locator = MagicMock()
    return page


@pytest.fixture
def mock_browser_context(mock_page):
    """Mock Playwright BrowserContext."""
    context = AsyncMock()
    context.new_page.return_value = mock_page
    return context


@pytest.fixture
def mock_browser(mock_browser_context):
    """Mock Playwright Browser."""
    browser = AsyncMock()
    browser.new_context.return_value = mock_browser_context
    return browser


@pytest.fixture
def mock_playwright(mock_browser):
    """Mock Playwright object."""
    playwright = AsyncMock()
    playwright.chromium.launch.return_value = mock_browser
    playwright.firefox.launch.return_value = mock_browser
    return playwright
