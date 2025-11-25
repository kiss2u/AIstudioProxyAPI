import pytest
import asyncio
from unittest.mock import MagicMock, AsyncMock
import os

@pytest.fixture(scope="session")
def event_loop():
    """Create an instance of the default event loop for each test case."""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()

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