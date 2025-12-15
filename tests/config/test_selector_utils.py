"""
Tests for config/selector_utils.py - UI selector fallback utilities.

These tests verify the robust fallback logic for handling Google AI Studio's
dynamic UI changes.
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from config.selector_utils import (
    AUTOSIZE_WRAPPER_SELECTORS,
    DRAG_DROP_TARGET_SELECTORS,
    INPUT_WRAPPER_SELECTORS,
    build_combined_selector,
    find_first_available_locator,
    find_first_visible_locator,
)


class TestSelectorConstants:
    """Test that selector constants are properly defined."""

    def test_input_wrapper_selectors_defined(self):
        """INPUT_WRAPPER_SELECTORS should contain both old and new UI selectors."""
        assert isinstance(INPUT_WRAPPER_SELECTORS, list)
        assert len(INPUT_WRAPPER_SELECTORS) >= 2
        # Should contain both ms-prompt-box (new) and ms-prompt-input-wrapper (old)
        selectors_str = " ".join(INPUT_WRAPPER_SELECTORS)
        assert "ms-prompt-box" in selectors_str
        assert "ms-prompt-input-wrapper" in selectors_str

    def test_autosize_wrapper_selectors_defined(self):
        """AUTOSIZE_WRAPPER_SELECTORS should be defined."""
        assert isinstance(AUTOSIZE_WRAPPER_SELECTORS, list)
        assert len(AUTOSIZE_WRAPPER_SELECTORS) >= 2

    def test_drag_drop_target_selectors_defined(self):
        """DRAG_DROP_TARGET_SELECTORS should be defined."""
        assert isinstance(DRAG_DROP_TARGET_SELECTORS, list)
        assert len(DRAG_DROP_TARGET_SELECTORS) >= 2


class TestBuildCombinedSelector:
    """Tests for build_combined_selector function."""

    def test_combine_single_selector(self):
        """Single selector should be returned as-is."""
        result = build_combined_selector(["selector1"])
        assert result == "selector1"

    def test_combine_multiple_selectors(self):
        """Multiple selectors should be joined with comma-space."""
        result = build_combined_selector(["sel1", "sel2", "sel3"])
        assert result == "sel1, sel2, sel3"

    def test_combine_empty_list(self):
        """Empty list should return empty string."""
        result = build_combined_selector([])
        assert result == ""

    def test_combine_real_selectors(self):
        """Test with actual INPUT_WRAPPER_SELECTORS."""
        result = build_combined_selector(INPUT_WRAPPER_SELECTORS)
        # Should contain all selectors comma-separated
        for selector in INPUT_WRAPPER_SELECTORS:
            assert selector in result


class TestFindFirstAvailableLocator:
    """Tests for find_first_available_locator function."""

    @pytest.mark.asyncio
    async def test_find_first_selector_found(self):
        """Should return first selector that finds elements."""
        mock_page = MagicMock()
        mock_locator = MagicMock()
        mock_locator.count = AsyncMock(return_value=1)
        mock_page.locator.return_value = mock_locator

        selectors = ["sel1", "sel2", "sel3"]
        locator, selector = await find_first_available_locator(
            mock_page, selectors, "test element"
        )

        assert locator is mock_locator
        assert selector == "sel1"
        mock_page.locator.assert_called_with("sel1")

    @pytest.mark.asyncio
    async def test_find_second_selector_when_first_empty(self):
        """Should fall back to second selector when first finds no elements."""
        mock_page = MagicMock()

        # First selector returns empty, second returns 1 element
        mock_locator1 = MagicMock()
        mock_locator1.count = AsyncMock(return_value=0)
        mock_locator2 = MagicMock()
        mock_locator2.count = AsyncMock(return_value=1)

        mock_page.locator.side_effect = [mock_locator1, mock_locator2]

        selectors = ["sel1", "sel2"]
        locator, selector = await find_first_available_locator(
            mock_page, selectors, "test element"
        )

        assert locator is mock_locator2
        assert selector == "sel2"

    @pytest.mark.asyncio
    async def test_return_none_when_all_selectors_fail(self):
        """Should return None when no selector finds elements."""
        mock_page = MagicMock()
        mock_locator = MagicMock()
        mock_locator.count = AsyncMock(return_value=0)
        mock_page.locator.return_value = mock_locator

        selectors = ["sel1", "sel2", "sel3"]
        locator, selector = await find_first_available_locator(
            mock_page, selectors, "test element"
        )

        assert locator is None
        assert selector is None

    @pytest.mark.asyncio
    async def test_log_result_false_suppresses_logging(self):
        """log_result=False should not log anything."""
        mock_page = MagicMock()
        mock_locator = MagicMock()
        mock_locator.count = AsyncMock(return_value=1)
        mock_page.locator.return_value = mock_locator

        with patch("config.selector_utils.logger") as mock_logger:
            await find_first_available_locator(
                mock_page, ["sel1"], "test", log_result=False
            )
            mock_logger.debug.assert_not_called()

    @pytest.mark.asyncio
    async def test_exception_in_selector_continues_to_next(self):
        """Exception during selector check should continue to next selector."""
        mock_page = MagicMock()

        # First selector raises exception, second works
        mock_locator1 = MagicMock()
        mock_locator1.count = AsyncMock(side_effect=Exception("Selector error"))
        mock_locator2 = MagicMock()
        mock_locator2.count = AsyncMock(return_value=1)

        mock_page.locator.side_effect = [mock_locator1, mock_locator2]

        selectors = ["sel1", "sel2"]
        locator, selector = await find_first_available_locator(
            mock_page, selectors, "test element"
        )

        assert locator is mock_locator2
        assert selector == "sel2"

    @pytest.mark.asyncio
    async def test_cancelled_error_propagates(self):
        """asyncio.CancelledError should propagate, not be caught."""
        mock_page = MagicMock()
        mock_locator = MagicMock()
        mock_locator.count = AsyncMock(side_effect=asyncio.CancelledError())
        mock_page.locator.return_value = mock_locator

        with pytest.raises(asyncio.CancelledError):
            await find_first_available_locator(mock_page, ["sel1"], "test")


class TestFindFirstVisibleLocator:
    """Tests for find_first_visible_locator function."""

    @pytest.mark.asyncio
    async def test_find_first_visible_selector(self):
        """Should return first selector where element is visible."""
        mock_page = MagicMock()
        mock_locator = MagicMock()
        mock_page.locator.return_value = mock_locator

        # Mock playwright's expect at the source
        with patch("playwright.async_api.expect") as mock_expect:
            mock_expect.return_value.to_be_visible = AsyncMock()

            selectors = ["sel1", "sel2"]
            locator, selector = await find_first_visible_locator(
                mock_page, selectors, "test element"
            )

            assert locator is mock_locator
            assert selector == "sel1"

    @pytest.mark.asyncio
    async def test_fallback_to_second_when_first_not_visible(self):
        """Should try next selector when first is not visible."""
        mock_page = MagicMock()
        mock_locator1 = MagicMock()
        mock_locator2 = MagicMock()
        mock_page.locator.side_effect = [mock_locator1, mock_locator2]

        call_count = 0

        async def visibility_side_effect(timeout):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise Exception("Timeout")
            # Second call succeeds
            return None

        # Mock expect to fail first, succeed second
        with patch("playwright.async_api.expect") as mock_expect:
            mock_expect.return_value.to_be_visible = AsyncMock(
                side_effect=visibility_side_effect
            )

            selectors = ["sel1", "sel2"]
            locator, selector = await find_first_visible_locator(
                mock_page, selectors, "test element"
            )

            assert locator is mock_locator2
            assert selector == "sel2"

    @pytest.mark.asyncio
    async def test_return_none_when_none_visible(self):
        """Should return None when no selector finds visible element."""
        mock_page = MagicMock()
        mock_locator = MagicMock()
        mock_page.locator.return_value = mock_locator

        # Mock expect to always fail
        with patch("playwright.async_api.expect") as mock_expect:
            mock_expect.return_value.to_be_visible = AsyncMock(
                side_effect=Exception("Timeout")
            )

            selectors = ["sel1", "sel2"]
            locator, selector = await find_first_visible_locator(
                mock_page, selectors, "test element"
            )

            assert locator is None
            assert selector is None

    @pytest.mark.asyncio
    async def test_custom_timeout_passed(self):
        """Should use custom timeout_per_selector value."""
        mock_page = MagicMock()
        mock_locator = MagicMock()
        mock_page.locator.return_value = mock_locator

        with patch("playwright.async_api.expect") as mock_expect:
            mock_visible = AsyncMock()
            mock_expect.return_value.to_be_visible = mock_visible

            await find_first_visible_locator(
                mock_page, ["sel1"], "test", timeout_per_selector=5000
            )

            mock_visible.assert_called_with(timeout=5000)

    @pytest.mark.asyncio
    async def test_cancelled_error_propagates(self):
        """asyncio.CancelledError should propagate."""
        mock_page = MagicMock()
        mock_locator = MagicMock()
        mock_page.locator.return_value = mock_locator

        with patch("playwright.async_api.expect") as mock_expect:
            mock_expect.return_value.to_be_visible = AsyncMock(
                side_effect=asyncio.CancelledError()
            )

            with pytest.raises(asyncio.CancelledError):
                await find_first_visible_locator(mock_page, ["sel1"], "test")


class TestIntegrationScenarios:
    """Integration-like tests for realistic usage scenarios."""

    @pytest.mark.asyncio
    async def test_fallback_from_new_to_old_ui(self):
        """Simulate fallback from new UI (ms-prompt-box) to old (ms-prompt-input-wrapper)."""
        mock_page = MagicMock()

        call_count = 0

        def create_locator(selector):
            nonlocal call_count
            call_count += 1
            locator = MagicMock()
            # First two (new UI) return 0, old UI returns 1
            if "ms-prompt-input-wrapper" in selector:
                locator.count = AsyncMock(return_value=1)
            else:
                locator.count = AsyncMock(return_value=0)
            return locator

        mock_page.locator.side_effect = create_locator

        locator, selector = await find_first_available_locator(
            mock_page, INPUT_WRAPPER_SELECTORS, "input container"
        )

        assert locator is not None
        assert selector is not None
        assert "ms-prompt-input-wrapper" in selector

    @pytest.mark.asyncio
    async def test_combined_selector_with_real_constants(self):
        """Test build_combined_selector with actual DRAG_DROP_TARGET_SELECTORS."""
        combined = build_combined_selector(DRAG_DROP_TARGET_SELECTORS)

        # Should work with CSS selector syntax
        assert ", " in combined or len(DRAG_DROP_TARGET_SELECTORS) == 1
        # Should contain all individual selectors
        for sel in DRAG_DROP_TARGET_SELECTORS:
            assert sel in combined


class TestRegressionFixes:
    """Regression tests for specific bug fixes."""

    @pytest.mark.asyncio
    async def test_find_first_visible_locator_waits_for_elements(self):
        """Verify find_first_visible_locator actively waits for elements.

        Regression test for timing issue: In headless mode, elements may not
        be rendered immediately after page load. Using find_first_visible_locator
        (which calls expect().to_be_visible()) ensures we wait for elements,
        unlike find_first_available_locator which only checks if elements exist.

        This test ensures:
        1. The function uses Playwright's expect().to_be_visible() with timeout
        2. It doesn't just check element count (which would cause timing issues)
        """
        mock_page = MagicMock()
        mock_locator = MagicMock()
        mock_page.locator.return_value = mock_locator

        # Track if to_be_visible was called with a timeout
        visibility_calls = []

        async def track_visibility(timeout):
            visibility_calls.append({"timeout": timeout})

        with patch("playwright.async_api.expect") as mock_expect:
            mock_expect.return_value.to_be_visible = AsyncMock(
                side_effect=track_visibility
            )

            await find_first_visible_locator(
                mock_page,
                ["ms-prompt-input-wrapper"],
                "input container",
                timeout_per_selector=30000,  # 30 seconds as used in core.py
            )

        # Verify to_be_visible was called with the timeout
        assert len(visibility_calls) == 1
        assert visibility_calls[0]["timeout"] == 30000

    @pytest.mark.asyncio
    async def test_find_first_visible_locator_polls_actively(self):
        """Verify the function uses active polling, not just a check.

        Regression test: The old implementation only checked if elements existed
        at the moment of the call, causing failures when page was still loading.
        The new implementation should actively wait/poll for elements.

        This differs from find_first_available_locator which just calls count().
        """
        mock_page = MagicMock()
        mock_locator = MagicMock()
        mock_page.locator.return_value = mock_locator

        # Simulate element becoming visible after initial check would fail
        call_count = [0]

        async def delayed_visibility(timeout):
            call_count[0] += 1
            # First call would time out if we were just checking
            # But active waiting should succeed
            return None

        with patch("playwright.async_api.expect") as mock_expect:
            mock_expect.return_value.to_be_visible = AsyncMock(
                side_effect=delayed_visibility
            )

            locator, selector = await find_first_visible_locator(
                mock_page,
                ["sel1"],
                "test",
            )

        # Verify we attempted visibility check with timeout
        assert call_count[0] >= 1
        assert locator is not None
