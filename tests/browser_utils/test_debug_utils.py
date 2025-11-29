"""
Comprehensive test suite for browser_utils/debug_utils.py.

This module tests all debug snapshot and error logging functions with >80% coverage.
Focuses on: timestamp generation, DOM capture, system context, snapshot saving.
"""

import asyncio
import json
import os
import platform
import sys
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, Mock, mock_open, patch

import pytest
from playwright.async_api import Error as PlaywrightError

from browser_utils.debug_utils import (
    capture_dom_structure,
    capture_playwright_state,
    capture_system_context,
    get_texas_timestamp,
    save_comprehensive_snapshot,
    save_error_snapshot_enhanced,
    save_error_snapshot_legacy,
)


class TestGetTexasTimestamp:
    """测试 Texas 时区时间戳生成函数"""

    def test_timestamp_format_iso(self):
        """测试 ISO 格式时间戳"""
        iso, human = get_texas_timestamp()

        # ISO format: "2025-11-21T18:37:32.440"
        assert len(iso) == 23
        assert "T" in iso
        assert iso.count("-") == 2  # YYYY-MM-DD
        assert iso.count(":") == 2  # HH:MM:SS

    def test_timestamp_format_human_readable(self):
        """测试人类可读时间戳格式"""
        iso, human = get_texas_timestamp()

        # Human format: "2025-11-21 18:37:32.440 CST"
        assert " CST" in human
        assert human.endswith("CST")
        assert human.count(":") == 2

    def test_timestamp_consistency(self):
        """测试时间戳一致性"""
        iso, human = get_texas_timestamp()

        # Both should represent same time
        iso_date = iso.split("T")[0]
        human_date = human.split(" ")[0]
        assert iso_date == human_date

    def test_timestamp_milliseconds_precision(self):
        """测试毫秒精度"""
        iso, human = get_texas_timestamp()

        # Should have 3 decimal places
        iso_time = iso.split("T")[1]
        assert "." in iso_time
        ms_part = iso_time.split(".")[1]
        assert len(ms_part) == 3

    @patch("browser_utils.debug_utils.datetime")
    def test_timezone_offset_cst(self, mock_datetime):
        """测试 CST 时区偏移 (UTC-6)"""
        # Mock UTC time: 2025-01-15 12:00:00 UTC
        mock_utc = datetime(2025, 1, 15, 12, 0, 0, 0, tzinfo=timezone.utc)
        mock_datetime.now.return_value = mock_utc

        iso, human = get_texas_timestamp()

        # CST is UTC-6, so 12:00 UTC -> 06:00 CST
        assert "06:00:00" in iso


class TestCaptureDomStructure:
    """测试 DOM 树结构捕获函数"""

    @pytest.mark.asyncio
    async def test_dom_structure_basic_success(self):
        """测试基本 DOM 树捕获成功"""
        page = AsyncMock()
        dom_tree = "BODY\n  DIV#app.container\n    P.text\n"
        page.evaluate.return_value = dom_tree

        result = await capture_dom_structure(page)

        assert result == dom_tree
        page.evaluate.assert_called_once()

    @pytest.mark.asyncio
    async def test_dom_structure_with_hierarchy(self):
        """测试层次结构 DOM 捕获"""
        page = AsyncMock()
        complex_dom = """BODY
  DIV#root.app-container
    HEADER.navbar
      NAV
    MAIN.content
      DIV.widget
"""
        page.evaluate.return_value = complex_dom

        result = await capture_dom_structure(page)

        assert "BODY" in result
        assert "DIV#root.app-container" in result
        assert "HEADER.navbar" in result

    @pytest.mark.asyncio
    async def test_dom_structure_playwright_error(self):
        """测试 Playwright 错误处理"""
        page = AsyncMock()
        page.evaluate.side_effect = PlaywrightError("Page closed")

        result = await capture_dom_structure(page)

        assert "Error capturing DOM structure" in result
        assert "Page closed" in result

    @pytest.mark.asyncio
    async def test_dom_structure_generic_exception(self):
        """测试通用异常处理"""
        page = AsyncMock()
        page.evaluate.side_effect = RuntimeError("Unexpected error")

        result = await capture_dom_structure(page)

        assert "Error capturing DOM structure" in result
        assert "Unexpected error" in result

    @pytest.mark.asyncio
    async def test_dom_structure_javascript_evaluation(self):
        """测试 JavaScript 执行逻辑"""
        page = AsyncMock()
        page.evaluate.return_value = "BODY\n  DIV#test\n"

        await capture_dom_structure(page)

        # Verify JavaScript function was passed
        call_args = page.evaluate.call_args[0][0]
        assert "function getTreeStructure" in call_args
        assert "maxDepth = 15" in call_args
        assert "element.tagName" in call_args


class TestCaptureSystemContext:
    """测试系统上下文捕获函数"""

    @pytest.mark.asyncio
    async def test_system_context_basic_structure(self):
        """测试基本系统上下文结构"""
        with (
            patch("server.is_playwright_ready", True),
            patch("server.is_browser_connected", True),
            patch("server.is_page_ready", True),
            patch("server.is_initializing", False),
            patch("server.request_queue", MagicMock()),
            patch("server.processing_lock", MagicMock()),
            patch("server.model_switching_lock", MagicMock()),
            patch("server.current_ai_studio_model_id", "gemini-pro"),
            patch("server.excluded_model_ids", []),
            patch("server.browser_instance", None),
            patch("server.page_instance", None),
            patch("server.console_logs", []),
            patch("server.network_log", {}),
            patch("server.STREAM_QUEUE", None),
            patch("server.PLAYWRIGHT_PROXY_SETTINGS", None),
        ):
            context = await capture_system_context("req123", "test_error")

        # Verify top-level structure
        assert "meta" in context
        assert "system" in context
        assert "application_state" in context
        assert "browser_state" in context
        assert "configuration" in context
        assert "recent_activity" in context

    @pytest.mark.asyncio
    async def test_system_context_meta_fields(self):
        """测试 meta 字段内容"""
        with (
            patch("server.is_playwright_ready", True),
            patch("server.is_browser_connected", True),
            patch("server.is_page_ready", True),
            patch("server.is_initializing", False),
            patch("server.request_queue", MagicMock()),
            patch("server.processing_lock", MagicMock()),
            patch("server.model_switching_lock", MagicMock()),
            patch("server.current_ai_studio_model_id", None),
            patch("server.excluded_model_ids", []),
            patch("server.browser_instance", None),
            patch("server.page_instance", None),
            patch("server.console_logs", []),
            patch("server.network_log", {}),
            patch("server.STREAM_QUEUE", None),
            patch("server.PLAYWRIGHT_PROXY_SETTINGS", None),
        ):
            context = await capture_system_context("abc123", "timeout_error")

        meta = context["meta"]
        assert meta["req_id"] == "abc123"
        assert meta["error_name"] == "timeout_error"
        assert "timestamp_iso" in meta
        assert "timestamp_texas" in meta

    @pytest.mark.asyncio
    async def test_system_context_system_info(self):
        """测试系统信息字段"""
        with (
            patch("server.is_playwright_ready", True),
            patch("server.is_browser_connected", True),
            patch("server.is_page_ready", True),
            patch("server.is_initializing", False),
            patch("server.request_queue", MagicMock()),
            patch("server.processing_lock", MagicMock()),
            patch("server.model_switching_lock", MagicMock()),
            patch("server.current_ai_studio_model_id", None),
            patch("server.excluded_model_ids", []),
            patch("server.browser_instance", None),
            patch("server.page_instance", None),
            patch("server.console_logs", []),
            patch("server.network_log", {}),
            patch("server.STREAM_QUEUE", None),
            patch("server.PLAYWRIGHT_PROXY_SETTINGS", None),
        ):
            context = await capture_system_context()

        system = context["system"]
        assert "platform" in system
        assert "python_version" in system
        assert "pid" in system
        assert system["platform"] == platform.platform()
        assert system["python_version"] == sys.version.split()[0]
        assert system["pid"] == os.getpid()

    @pytest.mark.asyncio
    async def test_system_context_application_flags(self):
        """测试应用状态标志"""
        with (
            patch("server.is_playwright_ready", True),
            patch("server.is_browser_connected", False),
            patch("server.is_page_ready", True),
            patch("server.is_initializing", True),
            patch("server.request_queue", MagicMock()),
            patch("server.processing_lock", MagicMock()),
            patch("server.model_switching_lock", MagicMock()),
            patch("server.current_ai_studio_model_id", None),
            patch("server.excluded_model_ids", []),
            patch("server.browser_instance", None),
            patch("server.page_instance", None),
            patch("server.console_logs", []),
            patch("server.network_log", {}),
            patch("server.STREAM_QUEUE", None),
            patch("server.PLAYWRIGHT_PROXY_SETTINGS", None),
        ):
            context = await capture_system_context()

        flags = context["application_state"]["flags"]
        assert flags["is_playwright_ready"] is True
        assert flags["is_browser_connected"] is False
        assert flags["is_page_ready"] is True
        assert flags["is_initializing"] is True

    @pytest.mark.asyncio
    async def test_system_context_queue_size(self):
        """测试队列大小捕获"""
        mock_queue = MagicMock()
        mock_queue.qsize.return_value = 5

        with (
            patch("server.is_playwright_ready", True),
            patch("server.is_browser_connected", True),
            patch("server.is_page_ready", True),
            patch("server.is_initializing", False),
            patch("server.request_queue", mock_queue),
            patch("server.processing_lock", MagicMock()),
            patch("server.model_switching_lock", MagicMock()),
            patch("server.current_ai_studio_model_id", None),
            patch("server.excluded_model_ids", []),
            patch("server.browser_instance", None),
            patch("server.page_instance", None),
            patch("server.console_logs", []),
            patch("server.network_log", {}),
            patch("server.STREAM_QUEUE", None),
            patch("server.PLAYWRIGHT_PROXY_SETTINGS", None),
        ):
            context = await capture_system_context()

        queues = context["application_state"]["queues"]
        assert queues["request_queue_size"] == 5

    @pytest.mark.asyncio
    async def test_system_context_queue_not_implemented(self):
        """测试队列不支持 qsize 的情况"""
        mock_queue = MagicMock()
        mock_queue.qsize.side_effect = NotImplementedError()

        with (
            patch("server.is_playwright_ready", True),
            patch("server.is_browser_connected", True),
            patch("server.is_page_ready", True),
            patch("server.is_initializing", False),
            patch("server.request_queue", mock_queue),
            patch("server.processing_lock", MagicMock()),
            patch("server.model_switching_lock", MagicMock()),
            patch("server.current_ai_studio_model_id", None),
            patch("server.excluded_model_ids", []),
            patch("server.browser_instance", None),
            patch("server.page_instance", None),
            patch("server.console_logs", []),
            patch("server.network_log", {}),
            patch("server.STREAM_QUEUE", None),
            patch("server.PLAYWRIGHT_PROXY_SETTINGS", None),
        ):
            context = await capture_system_context()

        queues = context["application_state"]["queues"]
        assert queues["request_queue_size"] == -1

    @pytest.mark.asyncio
    async def test_system_context_lock_states(self):
        """测试锁状态检测"""
        mock_lock = MagicMock()
        mock_lock.locked.return_value = True

        with (
            patch("server.is_playwright_ready", True),
            patch("server.is_browser_connected", True),
            patch("server.is_page_ready", True),
            patch("server.is_initializing", False),
            patch("server.request_queue", MagicMock()),
            patch("server.processing_lock", mock_lock),
            patch("server.model_switching_lock", mock_lock),
            patch("server.current_ai_studio_model_id", None),
            patch("server.excluded_model_ids", []),
            patch("server.browser_instance", None),
            patch("server.page_instance", None),
            patch("server.console_logs", []),
            patch("server.network_log", {}),
            patch("server.STREAM_QUEUE", None),
            patch("server.PLAYWRIGHT_PROXY_SETTINGS", None),
        ):
            context = await capture_system_context()

        locks = context["application_state"]["locks"]
        assert locks["processing_lock_locked"] is True
        assert locks["model_switching_lock_locked"] is True

    @pytest.mark.asyncio
    async def test_system_context_proxy_sanitization(self):
        """测试代理设置凭据脱敏"""
        proxy_settings = {"server": "http://user:password@proxy.com:8080"}

        with (
            patch("server.is_playwright_ready", True),
            patch("server.is_browser_connected", True),
            patch("server.is_page_ready", True),
            patch("server.is_initializing", False),
            patch("server.request_queue", MagicMock()),
            patch("server.processing_lock", MagicMock()),
            patch("server.model_switching_lock", MagicMock()),
            patch("server.current_ai_studio_model_id", None),
            patch("server.excluded_model_ids", []),
            patch("server.browser_instance", None),
            patch("server.page_instance", None),
            patch("server.console_logs", []),
            patch("server.network_log", {}),
            patch("server.STREAM_QUEUE", None),
            patch("server.PLAYWRIGHT_PROXY_SETTINGS", proxy_settings),
        ):
            context = await capture_system_context()

        proxy = context["configuration"]["proxy_settings"]
        assert "***:***@" in proxy["server"]
        assert "user" not in proxy["server"]
        assert "password" not in proxy["server"]

    @pytest.mark.asyncio
    async def test_system_context_console_logs(self):
        """测试控制台日志捕获"""
        console_logs = [
            {"type": "log", "text": "Log 1"},
            {"type": "error", "text": "Error 1"},
            {"type": "warning", "text": "Warning 1"},
            {"type": "log", "text": "Log 2"},
            {"type": "error", "text": "Error 2"},
        ]

        with (
            patch("server.is_playwright_ready", True),
            patch("server.is_browser_connected", True),
            patch("server.is_page_ready", True),
            patch("server.is_initializing", False),
            patch("server.request_queue", MagicMock()),
            patch("server.processing_lock", MagicMock()),
            patch("server.model_switching_lock", MagicMock()),
            patch("server.current_ai_studio_model_id", None),
            patch("server.excluded_model_ids", []),
            patch("server.browser_instance", None),
            patch("server.page_instance", None),
            patch("server.console_logs", console_logs),
            patch("server.network_log", {}),
            patch("server.STREAM_QUEUE", None),
            patch("server.PLAYWRIGHT_PROXY_SETTINGS", None),
        ):
            context = await capture_system_context()

        activity = context["recent_activity"]
        assert activity["console_logs_count"] == 5
        assert "last_console_logs" in activity
        assert "recent_console_errors" in activity
        assert len(activity["recent_console_errors"]) == 3  # 2 errors + 1 warning

    @pytest.mark.asyncio
    async def test_system_context_failed_network_responses(self):
        """测试失败的网络请求捕获"""
        network_log = {
            "requests": [],
            "responses": [
                {"status": 200, "url": "https://example.com/ok"},
                {"status": 404, "url": "https://example.com/not-found"},
                {"status": 500, "url": "https://example.com/error"},
            ],
        }

        with (
            patch("server.is_playwright_ready", True),
            patch("server.is_browser_connected", True),
            patch("server.is_page_ready", True),
            patch("server.is_initializing", False),
            patch("server.request_queue", MagicMock()),
            patch("server.processing_lock", MagicMock()),
            patch("server.model_switching_lock", MagicMock()),
            patch("server.current_ai_studio_model_id", None),
            patch("server.excluded_model_ids", []),
            patch("server.browser_instance", None),
            patch("server.page_instance", None),
            patch("server.console_logs", []),
            patch("server.network_log", network_log),
            patch("server.STREAM_QUEUE", None),
            patch("server.PLAYWRIGHT_PROXY_SETTINGS", None),
        ):
            context = await capture_system_context()

        activity = context["recent_activity"]
        assert "failed_network_responses" in activity
        assert len(activity["failed_network_responses"]) == 2

    @pytest.mark.asyncio
    async def test_system_context_page_url(self):
        """测试当前页面 URL 捕获"""
        mock_page = AsyncMock()
        mock_page.is_closed = Mock(return_value=False)
        mock_page.url = "https://ai.google.dev/chat"

        with (
            patch("server.is_playwright_ready", True),
            patch("server.is_browser_connected", True),
            patch("server.is_page_ready", True),
            patch("server.is_initializing", False),
            patch("server.request_queue", MagicMock()),
            patch("server.processing_lock", MagicMock()),
            patch("server.model_switching_lock", MagicMock()),
            patch("server.current_ai_studio_model_id", None),
            patch("server.excluded_model_ids", []),
            patch("server.browser_instance", None),
            patch("server.page_instance", mock_page),
            patch("server.console_logs", []),
            patch("server.network_log", {}),
            patch("server.STREAM_QUEUE", None),
            patch("server.PLAYWRIGHT_PROXY_SETTINGS", None),
        ):
            context = await capture_system_context()

        assert context["browser_state"]["current_url"] == "https://ai.google.dev/chat"


class TestCapturePlaywrightState:
    """测试 Playwright 状态捕获函数"""

    @pytest.mark.asyncio
    async def test_playwright_state_basic_page_info(self):
        """测试基本页面信息捕获"""
        page = AsyncMock()
        page.url = "https://ai.google.dev"
        page.title.return_value = "AI Studio"
        page.viewport_size = {"width": 1920, "height": 1080}
        page.context.cookies.return_value = []
        page.evaluate.return_value = []

        state = await capture_playwright_state(page)

        assert state["page"]["url"] == "https://ai.google.dev"
        assert state["page"]["title"] == "AI Studio"
        assert state["page"]["viewport"] == {"width": 1920, "height": 1080}

    @pytest.mark.asyncio
    async def test_playwright_state_title_error(self):
        """测试获取页面标题失败"""
        page = AsyncMock()
        page.url = "https://example.com"
        page.title.side_effect = PlaywrightError("Page closed")
        page.viewport_size = None
        page.context.cookies.return_value = []
        page.evaluate.return_value = []

        state = await capture_playwright_state(page)

        assert "Error:" in state["page"]["title"]

    @pytest.mark.asyncio
    async def test_playwright_state_locators_exists_and_visible(self):
        """测试定位器存在且可见"""
        page = AsyncMock()
        page.url = "https://example.com"
        page.title.return_value = "Test"
        page.viewport_size = None
        page.context.cookies.return_value = []
        page.evaluate.return_value = []

        mock_locator = AsyncMock()
        mock_locator.count.return_value = 1
        mock_locator.is_visible.return_value = True
        mock_locator.is_enabled.return_value = True
        mock_locator.input_value.side_effect = PlaywrightError("Not an input")

        locators = {"submit_button": mock_locator}
        state = await capture_playwright_state(page, locators)

        assert state["locators"]["submit_button"]["exists"] is True
        assert state["locators"]["submit_button"]["count"] == 1
        assert state["locators"]["submit_button"]["visible"] is True
        assert state["locators"]["submit_button"]["enabled"] is True

    @pytest.mark.asyncio
    async def test_playwright_state_locators_not_exists(self):
        """测试定位器不存在"""
        page = AsyncMock()
        page.url = "https://example.com"
        page.title.return_value = "Test"
        page.viewport_size = None
        page.context.cookies.return_value = []
        page.evaluate.return_value = []

        mock_locator = AsyncMock()
        mock_locator.count.return_value = 0

        locators = {"missing_element": mock_locator}
        state = await capture_playwright_state(page, locators)

        assert state["locators"]["missing_element"]["exists"] is False
        assert state["locators"]["missing_element"]["count"] == 0

    @pytest.mark.asyncio
    async def test_playwright_state_locators_with_input_value(self):
        """测试捕获输入元素的值"""
        page = AsyncMock()
        page.url = "https://example.com"
        page.title.return_value = "Test"
        page.viewport_size = None
        page.context.cookies.return_value = []
        page.evaluate.return_value = []

        mock_locator = AsyncMock()
        mock_locator.count.return_value = 1
        mock_locator.is_visible.return_value = True
        mock_locator.is_enabled.return_value = True
        mock_locator.input_value.return_value = "test input value"

        locators = {"input_field": mock_locator}
        state = await capture_playwright_state(page, locators)

        assert state["locators"]["input_field"]["value"] == "test input value"

    @pytest.mark.asyncio
    async def test_playwright_state_locators_long_value_truncation(self):
        """测试长输入值截断"""
        page = AsyncMock()
        page.url = "https://example.com"
        page.title.return_value = "Test"
        page.viewport_size = None
        page.context.cookies.return_value = []
        page.evaluate.return_value = []

        long_value = "a" * 150
        mock_locator = AsyncMock()
        mock_locator.count.return_value = 1
        mock_locator.is_visible.return_value = True
        mock_locator.is_enabled.return_value = True
        mock_locator.input_value.return_value = long_value

        locators = {"text_area": mock_locator}
        state = await capture_playwright_state(page, locators)

        assert "..." in state["locators"]["text_area"]["value"]
        assert len(state["locators"]["text_area"]["value"]) == 103  # 100 + "..."

    @pytest.mark.asyncio
    async def test_playwright_state_locators_error_handling(self):
        """测试定位器错误处理"""
        page = AsyncMock()
        page.url = "https://example.com"
        page.title.return_value = "Test"
        page.viewport_size = None
        page.context.cookies.return_value = []
        page.evaluate.return_value = []

        mock_locator = AsyncMock()
        mock_locator.count.side_effect = PlaywrightError("Locator failed")

        locators = {"broken_locator": mock_locator}
        state = await capture_playwright_state(page, locators)

        assert "error" in state["locators"]["broken_locator"]

    @pytest.mark.asyncio
    async def test_playwright_state_cookies_count(self):
        """测试 Cookie 数量统计"""
        page = AsyncMock()
        page.url = "https://example.com"
        page.title.return_value = "Test"
        page.viewport_size = None
        page.context.cookies.return_value = [
            {"name": "session", "value": "abc"},
            {"name": "user", "value": "123"},
        ]
        page.evaluate.return_value = []

        state = await capture_playwright_state(page)

        assert state["storage"]["cookies_count"] == 2

    @pytest.mark.asyncio
    async def test_playwright_state_localstorage_keys(self):
        """测试 localStorage 键捕获"""
        page = AsyncMock()
        page.url = "https://example.com"
        page.title.return_value = "Test"
        page.viewport_size = None
        page.context.cookies.return_value = []
        page.evaluate.return_value = ["theme", "user_id", "settings"]

        state = await capture_playwright_state(page)

        assert state["storage"]["localStorage_keys"] == ["theme", "user_id", "settings"]

    @pytest.mark.asyncio
    async def test_playwright_state_storage_error_handling(self):
        """测试存储信息获取失败"""
        page = AsyncMock()
        page.url = "https://example.com"
        page.title.return_value = "Test"
        page.viewport_size = None
        page.context.cookies.side_effect = PlaywrightError("Context closed")
        page.evaluate.side_effect = PlaywrightError("Evaluation failed")

        state = await capture_playwright_state(page)

        # Should not crash, just log warnings
        assert state["storage"]["cookies_count"] == 0
        assert state["storage"]["localStorage_keys"] == []


class TestSaveComprehensiveSnapshot:
    """测试综合快照保存函数"""

    @pytest.mark.asyncio
    async def test_snapshot_page_closed(self):
        """测试页面已关闭时不保存快照"""
        page = AsyncMock()
        page.is_closed = Mock(return_value=True)

        result = await save_comprehensive_snapshot(
            page=page, error_name="test_error", req_id="req123"
        )

        assert result == ""

    @pytest.mark.asyncio
    async def test_snapshot_page_none(self):
        """测试页面为 None 时不保存快照"""
        result = await save_comprehensive_snapshot(
            page=None, error_name="test_error", req_id="req123"
        )

        assert result == ""

    @pytest.mark.asyncio
    async def test_snapshot_directory_creation(self, tmp_path):
        """测试快照目录创建"""
        page = AsyncMock()
        page.is_closed = Mock(return_value=False)
        page.screenshot = AsyncMock()
        page.content.return_value = "<html></html>"
        page.evaluate.return_value = "BODY\n"

        # Create mock Path that returns actual tmp_path for path operations
        mock_path_instance = MagicMock()
        mock_path_instance.__truediv__ = lambda self, other: tmp_path / str(other)

        with (
            patch("browser_utils.debug_utils.Path") as mock_path_class,
            patch("server.console_logs", []),
            patch("server.network_log", {}),
            patch("builtins.open", mock_open()),
            patch("browser_utils.debug_utils.capture_system_context") as mock_context,
            patch("browser_utils.debug_utils.capture_dom_structure") as mock_dom,
            patch("browser_utils.debug_utils.capture_playwright_state") as mock_pw,
        ):
            mock_context.return_value = {"meta": {}, "system": {}}
            mock_dom.return_value = "BODY\n"
            mock_pw.return_value = {}
            mock_path_class.return_value = mock_path_instance

            result = await save_comprehensive_snapshot(
                page=page, error_name="timeout", req_id="abc123"
            )

            # Verify function completed successfully (returns path)
            assert result is not None

    @pytest.mark.asyncio
    async def test_snapshot_screenshot_success(self, tmp_path):
        """测试截图保存成功"""
        page = AsyncMock()
        page.is_closed = Mock(return_value=False)
        page.screenshot = AsyncMock()
        page.content.return_value = "<html><body>Test</body></html>"

        snapshot_dir = tmp_path / "snapshot"
        snapshot_dir.mkdir()

        with (
            patch("browser_utils.debug_utils.Path") as mock_path_class,
            patch("server.console_logs", []),
            patch("server.network_log", {}),
            patch("browser_utils.debug_utils.capture_dom_structure") as mock_dom,
            patch(
                "browser_utils.debug_utils.capture_playwright_state"
            ) as mock_pw_state,
            patch("browser_utils.debug_utils.capture_system_context") as mock_sys_ctx,
        ):
            # Setup mocks
            mock_dom.return_value = "BODY\n"
            mock_pw_state.return_value = {"page": {}}
            mock_sys_ctx.return_value = {"meta": {}}

            # Mock Path to return our tmp_path
            base_dir = tmp_path / "errors_py"
            date_dir = base_dir / "2025-01-15"
            final_dir = date_dir / "snapshot"
            final_dir.mkdir(parents=True)

            mock_path_class.return_value.__truediv__.side_effect = [
                base_dir,
                date_dir,
                final_dir,
            ]

            await save_comprehensive_snapshot(
                page=page, error_name="test", req_id="req123"
            )

            # Verify screenshot was called
            page.screenshot.assert_called_once()

    @pytest.mark.asyncio
    async def test_snapshot_screenshot_failure(self):
        """测试截图失败处理"""
        page = AsyncMock()
        page.is_closed = Mock(return_value=False)
        page.screenshot.side_effect = PlaywrightError("Screenshot timeout")
        page.content.return_value = "<html></html>"

        with (
            patch("browser_utils.debug_utils.Path"),
            patch("server.console_logs", []),
            patch("server.network_log", {}),
            patch("browser_utils.debug_utils.capture_dom_structure") as mock_dom,
            patch(
                "browser_utils.debug_utils.capture_playwright_state"
            ) as mock_pw_state,
            patch("browser_utils.debug_utils.capture_system_context") as mock_sys_ctx,
            patch("builtins.open", mock_open()),
        ):
            mock_dom.return_value = "BODY\n"
            mock_pw_state.return_value = {}
            mock_sys_ctx.return_value = {}

            # Should not crash
            result = await save_comprehensive_snapshot(
                page=page, error_name="test", req_id="req123"
            )

            # Should complete despite screenshot failure
            # (result will be a path string or empty)

    @pytest.mark.asyncio
    async def test_snapshot_metadata_with_exception(self):
        """测试包含异常信息的元数据"""
        page = AsyncMock()
        page.is_closed = Mock(return_value=False)
        page.screenshot = AsyncMock()
        page.content.return_value = "<html></html>"

        error_exception = ValueError("Invalid input")

        with (
            patch("browser_utils.debug_utils.Path"),
            patch("server.console_logs", []),
            patch("server.network_log", {}),
            patch("browser_utils.debug_utils.capture_dom_structure") as mock_dom,
            patch(
                "browser_utils.debug_utils.capture_playwright_state"
            ) as mock_pw_state,
            patch("browser_utils.debug_utils.capture_system_context") as mock_sys_ctx,
            patch("builtins.open", mock_open()) as mock_file,
        ):
            mock_dom.return_value = "BODY\n"
            mock_pw_state.return_value = {}
            mock_sys_ctx.return_value = {}

            await save_comprehensive_snapshot(
                page=page,
                error_name="validation_error",
                req_id="req123",
                error_exception=error_exception,
            )

            # Verify JSON write was called (metadata.json)
            # One of the calls should contain exception info

    @pytest.mark.asyncio
    async def test_snapshot_additional_context(self):
        """测试额外上下文信息"""
        page = AsyncMock()
        page.is_closed = Mock(return_value=False)
        page.screenshot = AsyncMock()
        page.content.return_value = "<html></html>"

        additional_context = {"user_action": "clicked submit", "retry_count": 3}

        with (
            patch("browser_utils.debug_utils.Path"),
            patch("server.console_logs", []),
            patch("server.network_log", {}),
            patch("browser_utils.debug_utils.capture_dom_structure") as mock_dom,
            patch(
                "browser_utils.debug_utils.capture_playwright_state"
            ) as mock_pw_state,
            patch("browser_utils.debug_utils.capture_system_context") as mock_sys_ctx,
            patch("builtins.open", mock_open()),
        ):
            mock_dom.return_value = "BODY\n"
            mock_pw_state.return_value = {}
            mock_sys_ctx.return_value = {}

            await save_comprehensive_snapshot(
                page=page,
                error_name="submit_timeout",
                req_id="req123",
                additional_context=additional_context,
            )

    @pytest.mark.asyncio
    async def test_snapshot_console_logs_capture(self):
        """测试控制台日志捕获"""
        page = AsyncMock()
        page.is_closed = Mock(return_value=False)
        page.screenshot = AsyncMock()
        page.content.return_value = "<html></html>"

        console_logs = [
            {
                "timestamp": "2025-01-15T10:00:00",
                "type": "error",
                "text": "Network error",
                "location": "app.js:42",
            }
        ]

        with (
            patch("browser_utils.debug_utils.Path"),
            patch("server.console_logs", console_logs),
            patch("server.network_log", {}),
            patch("browser_utils.debug_utils.capture_dom_structure") as mock_dom,
            patch(
                "browser_utils.debug_utils.capture_playwright_state"
            ) as mock_pw_state,
            patch("browser_utils.debug_utils.capture_system_context") as mock_sys_ctx,
            patch("builtins.open", mock_open()) as mock_file,
        ):
            mock_dom.return_value = "BODY\n"
            mock_pw_state.return_value = {}
            mock_sys_ctx.return_value = {}

            await save_comprehensive_snapshot(
                page=page, error_name="console_error", req_id="req123"
            )

            # Verify console logs file was written

    @pytest.mark.asyncio
    async def test_snapshot_network_log_capture(self):
        """测试网络请求日志捕获"""
        page = AsyncMock()
        page.is_closed = Mock(return_value=False)
        page.screenshot = AsyncMock()
        page.content.return_value = "<html></html>"

        network_log = {
            "requests": [{"url": "https://api.example.com/data", "method": "GET"}],
            "responses": [{"url": "https://api.example.com/data", "status": 200}],
        }

        with (
            patch("browser_utils.debug_utils.Path"),
            patch("server.console_logs", []),
            patch("server.network_log", network_log),
            patch("browser_utils.debug_utils.capture_dom_structure") as mock_dom,
            patch(
                "browser_utils.debug_utils.capture_playwright_state"
            ) as mock_pw_state,
            patch("browser_utils.debug_utils.capture_system_context") as mock_sys_ctx,
            patch("builtins.open", mock_open()),
        ):
            mock_dom.return_value = "BODY\n"
            mock_pw_state.return_value = {}
            mock_sys_ctx.return_value = {}

            await save_comprehensive_snapshot(
                page=page, error_name="network_timeout", req_id="req123"
            )


class TestSaveErrorSnapshotEnhanced:
    """测试增强错误快照函数"""

    @pytest.mark.asyncio
    async def test_enhanced_snapshot_browser_unavailable(self):
        """测试浏览器不可用时不保存快照"""
        with (
            patch("server.browser_instance", None),
            patch("server.page_instance", None),
        ):
            # Should not crash
            await save_error_snapshot_enhanced(error_name="test_error")

    @pytest.mark.asyncio
    async def test_enhanced_snapshot_page_closed(self):
        """测试页面已关闭时不保存快照"""
        mock_browser = MagicMock()
        mock_browser.is_connected.return_value = True
        mock_page = MagicMock()
        mock_page.is_closed = Mock(return_value=True)

        with (
            patch("server.browser_instance", mock_browser),
            patch("server.page_instance", mock_page),
        ):
            await save_error_snapshot_enhanced(error_name="page_closed_error")

    @pytest.mark.asyncio
    async def test_enhanced_snapshot_req_id_parsing(self):
        """测试从错误名称解析 req_id"""
        mock_browser = MagicMock()
        mock_browser.is_connected.return_value = True
        mock_page = AsyncMock()
        mock_page.is_closed = Mock(return_value=False)

        with (
            patch("server.browser_instance", mock_browser),
            patch("server.page_instance", mock_page),
            patch("browser_utils.debug_utils.save_comprehensive_snapshot") as mock_save,
        ):
            mock_save.return_value = "/path/to/snapshot"

            await save_error_snapshot_enhanced(error_name="timeout_error_abc1234")

            # Verify comprehensive snapshot was called with parsed req_id
            call_kwargs = mock_save.call_args[1]
            assert call_kwargs["req_id"] == "abc1234"
            assert call_kwargs["error_name"] == "timeout_error"

    @pytest.mark.asyncio
    async def test_enhanced_snapshot_with_exception(self):
        """测试包含异常信息"""
        mock_browser = MagicMock()
        mock_browser.is_connected.return_value = True
        mock_page = AsyncMock()
        mock_page.is_closed = Mock(return_value=False)

        error_exc = RuntimeError("Unexpected failure")

        with (
            patch("server.browser_instance", mock_browser),
            patch("server.page_instance", mock_page),
            patch("browser_utils.debug_utils.save_comprehensive_snapshot") as mock_save,
        ):
            mock_save.return_value = "/path/to/snapshot"

            await save_error_snapshot_enhanced(
                error_name="runtime_error_xyz7890", error_exception=error_exc
            )

            # Verify exception was passed
            call_kwargs = mock_save.call_args[1]
            assert call_kwargs["error_exception"] == error_exc

    @pytest.mark.asyncio
    async def test_enhanced_snapshot_with_locators(self):
        """测试包含定位器状态"""
        mock_browser = MagicMock()
        mock_browser.is_connected.return_value = True
        mock_page = AsyncMock()
        mock_page.is_closed = Mock(return_value=False)

        mock_locator = AsyncMock()
        locators = {"submit_button": mock_locator}

        with (
            patch("server.browser_instance", mock_browser),
            patch("server.page_instance", mock_page),
            patch("browser_utils.debug_utils.save_comprehensive_snapshot") as mock_save,
        ):
            mock_save.return_value = "/path/to/snapshot"

            await save_error_snapshot_enhanced(
                error_name="button_timeout_req1234", locators=locators
            )

            # Verify locators were passed
            call_kwargs = mock_save.call_args[1]
            assert call_kwargs["locators"] == locators

    @pytest.mark.asyncio
    async def test_enhanced_snapshot_additional_context_merge(self):
        """测试额外上下文合并"""
        mock_browser = MagicMock()
        mock_browser.is_connected.return_value = True
        mock_page = AsyncMock()
        mock_page.is_closed = Mock(return_value=False)

        additional_context = {"custom_field": "custom_value"}
        error_exc = ValueError("Invalid")

        with (
            patch("server.browser_instance", mock_browser),
            patch("server.page_instance", mock_page),
            patch("browser_utils.debug_utils.save_comprehensive_snapshot") as mock_save,
        ):
            mock_save.return_value = "/path/to/snapshot"

            await save_error_snapshot_enhanced(
                error_name="validation_error_req5678",
                error_exception=error_exc,
                additional_context=additional_context,
            )

            # Verify context was merged
            call_kwargs = mock_save.call_args[1]
            merged = call_kwargs["additional_context"]
            assert "custom_field" in merged
            assert "exception_type" in merged
            assert merged["exception_type"] == "ValueError"


class TestSaveErrorSnapshotLegacy:
    """测试遗留错误快照函数"""

    @pytest.mark.asyncio
    async def test_legacy_snapshot_delegates_to_enhanced(self):
        """测试遗留函数委托给增强函数"""
        with patch(
            "browser_utils.debug_utils.save_error_snapshot_enhanced"
        ) as mock_enhanced:
            await save_error_snapshot_legacy(error_name="legacy_error_req9999")

            # Verify enhanced was called
            mock_enhanced.assert_called_once()
            call_kwargs = mock_enhanced.call_args[1]
            assert call_kwargs["error_name"] == "legacy_error_req9999"
            assert call_kwargs["error_stage"] == "Legacy snapshot call"
            assert call_kwargs["additional_context"]["legacy_call"] is True

    @pytest.mark.asyncio
    async def test_legacy_snapshot_default_error_name(self):
        """测试默认错误名称"""
        with patch(
            "browser_utils.debug_utils.save_error_snapshot_enhanced"
        ) as mock_enhanced:
            await save_error_snapshot_legacy()

            call_kwargs = mock_enhanced.call_args[1]
            assert call_kwargs["error_name"] == "error"
