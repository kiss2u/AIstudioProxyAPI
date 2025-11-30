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


# ==================== New Fixtures for Improved Testing ====================


@pytest.fixture
def mock_playwright_stack():
    """
    Factory fixture providing consistent Playwright mock stack.

    Returns a tuple of (playwright, browser, context, page) with all common
    methods pre-configured. This replaces the need to use multiple separate
    fixtures (mock_playwright, mock_browser, mock_browser_context, mock_page).

    Example:
        def test_something(mock_playwright_stack):
            playwright, browser, context, page = mock_playwright_stack
            # Use page.goto, page.click, etc. - all pre-configured
    """
    from playwright.async_api import Page as AsyncPage

    # Create mock page with all common methods
    page = AsyncMock(spec=AsyncPage)
    page.goto = AsyncMock()
    page.wait_for_selector = AsyncMock()
    page.wait_for_load_state = AsyncMock()
    page.click = AsyncMock()
    page.fill = AsyncMock()
    page.evaluate = AsyncMock(return_value="[]")
    page.locator = MagicMock(return_value=MagicMock())
    page.query_selector = AsyncMock(return_value=MagicMock())
    page.query_selector_all = AsyncMock(return_value=[])
    page.content = AsyncMock(return_value="<html></html>")
    page.url = "https://aistudio.google.com/app/prompts/new_chat"

    # Create mock context
    context = AsyncMock()
    context.new_page = AsyncMock(return_value=page)
    context.close = AsyncMock()

    # Create mock browser
    browser = AsyncMock()
    browser.new_context = AsyncMock(return_value=context)
    browser.close = AsyncMock()

    # Create mock playwright
    playwright = AsyncMock()
    playwright.firefox.launch = AsyncMock(return_value=browser)
    playwright.chromium.launch = AsyncMock(return_value=browser)

    return playwright, browser, context, page


@pytest.fixture
def make_chat_request():
    """
    Factory fixture for creating ChatCompletionRequest instances with custom parameters.

    This allows tests to create multiple request objects with different configurations
    without repeating boilerplate code.

    Args:
        model: Model ID (default: "gemini-1.5-pro")
        stream: Whether to stream response (default: False)
        **kwargs: Additional fields to override (temperature, max_tokens, etc.)

    Returns:
        Function that creates ChatCompletionRequest instances

    Example:
        def test_streaming(make_chat_request):
            request1 = make_chat_request(stream=True)
            request2 = make_chat_request(model="gemini-1.5-flash", temperature=0.5)
    """
    from models import ChatCompletionRequest, Message

    def _make(model: str = "gemini-1.5-pro", stream: bool = False, **kwargs):
        default_request = {
            "model": model,
            "messages": [Message(role="user", content="Test message")],
            "stream": stream,
            "temperature": 1.0,
            "max_tokens": 8192,
        }
        return ChatCompletionRequest(**{**default_request, **kwargs})

    return _make


@pytest.fixture
def make_request_context(mock_playwright_stack):
    """
    Factory fixture for creating request context dictionaries with customizable fields.

    This provides a realistic RequestContext with sane defaults that can be overridden
    for specific test scenarios. Uses mock browser from mock_playwright_stack.

    Args:
        **overrides: Fields to override in the context

    Returns:
        Function that creates RequestContext dicts

    Example:
        def test_context(make_request_context):
            ctx = make_request_context(req_id="custom-id", is_page_ready=False)
            assert ctx["req_id"] == "custom-id"
    """
    import logging

    _, _, _, page = mock_playwright_stack

    def _make(**overrides):
        # Import here to avoid circular imports
        from api_utils.server_state import state

        default_context = {
            "req_id": "test-req",
            "page": page,
            "logger": logging.getLogger("test"),
            "is_page_ready": True,
            "parsed_model_list": [],
            "current_ai_studio_model_id": "gemini-1.5-pro",
            "model_switching_lock": state.model_switching_lock,
            "params_cache_lock": state.params_cache_lock,
            "page_params_cache": {},
            # Additional RequestContext fields (from context_types.py)
            "is_streaming": False,
            "model_actually_switched": False,
            "requested_model": "gemini-1.5-pro",
            "model_id_to_use": None,
            "needs_model_switching": False,
        }
        return {**default_context, **overrides}

    return _make


@pytest.fixture
def real_locks_mock_browser():
    """
    Hybrid fixture providing real asyncio primitives + mock browser boundaries.

    Use this for tests that need real lock/queue behavior but don't need a real browser.
    This is useful for testing concurrency without the overhead of integration tests.

    Provides:
    - REAL asyncio.Lock instances (processing_lock, model_switching_lock, params_cache_lock)
    - REAL asyncio.Queue (request_queue)
    - MOCK browser/page (external I/O boundaries)

    Use when:
    - Testing lock contention and mutual exclusion
    - Testing queue processing without full integration
    - Need real async behavior but not real browser

    Don't use when:
    - Testing pure logic (use regular fixtures)
    - Testing full request flow (use real_server_state from integration conftest)

    Example:
        async def test_lock_behavior(real_locks_mock_browser):
            async with real_locks_mock_browser.processing_lock:
                # This actually blocks other tasks
                await some_operation()
    """
    from api_utils.server_state import state

    # Reset state to clean slate
    state.reset()

    # Create REAL asyncio primitives
    state.processing_lock = asyncio.Lock()
    state.model_switching_lock = asyncio.Lock()
    state.params_cache_lock = asyncio.Lock()
    state.request_queue = asyncio.Queue()

    # Mock only external boundaries (browser/page - these are I/O)
    mock_page = AsyncMock()
    mock_page.goto = AsyncMock()
    mock_page.wait_for_selector = AsyncMock()
    mock_page.click = AsyncMock()
    mock_page.fill = AsyncMock()
    mock_page.evaluate = AsyncMock()
    mock_page.locator = MagicMock(return_value=MagicMock())
    mock_page.is_closed = MagicMock(return_value=False)  # Page is open

    mock_browser = AsyncMock()
    mock_browser.close = AsyncMock()

    state.page_instance = mock_page
    state.browser_instance = mock_browser
    state.is_page_ready = True
    state.is_browser_connected = True

    yield state

    # Cleanup: Clear queue and reset state
    while not state.request_queue.empty():
        try:
            state.request_queue.get_nowait()
            state.request_queue.task_done()
        except asyncio.QueueEmpty:
            break

    state.reset()
