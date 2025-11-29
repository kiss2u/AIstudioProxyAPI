import asyncio
import time
from unittest.mock import AsyncMock, MagicMock, call, patch

import pytest
from fastapi import HTTPException

from api_utils.queue_worker import QueueManager, queue_worker

# --- Fixtures ---


@pytest.fixture
def queue_manager():
    return QueueManager()


@pytest.fixture
def mock_req_item():
    req_id = "test-req-id"
    request_data = MagicMock()
    request_data.stream = False
    http_request = MagicMock()
    result_future = asyncio.Future()
    return {
        "req_id": req_id,
        "request_data": request_data,
        "http_request": http_request,
        "result_future": result_future,
        "cancelled": False,
    }


# --- Tests for QueueManager.initialize_globals ---


@pytest.mark.asyncio
async def test_handle_streaming_delay(queue_manager):
    queue_manager.logger = MagicMock()

    # Case 1: Not streaming request -> No delay
    start_time = time.time()
    await queue_manager.handle_streaming_delay("req1", False)
    assert time.time() - start_time < 0.1

    # Case 2: Streaming request but last was not streaming -> No delay
    queue_manager.was_last_request_streaming = False
    start_time = time.time()
    await queue_manager.handle_streaming_delay("req2", True)
    assert time.time() - start_time < 0.1

    # Case 3: Sequential streaming requests within 1s -> Delay
    queue_manager.was_last_request_streaming = True
    queue_manager.last_request_completion_time = time.time()

    # Mock sleep to avoid actual waiting but verify call
    with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
        await queue_manager.handle_streaming_delay("req3", True)
        mock_sleep.assert_called_once()
        # Verify delay calculation (should be around 0.5 - 1.0)
        args, _ = mock_sleep.call_args
        assert 0.5 <= args[0] <= 1.0


@pytest.mark.asyncio
async def test_process_request_client_disconnected_early(queue_manager, mock_req_item):
    queue_manager.logger = MagicMock()
    queue_manager.request_queue = MagicMock()

    # Mock connection check returning False
    with patch(
        "api_utils.request_processor._check_client_connection", new_callable=AsyncMock
    ) as mock_check:
        mock_check.return_value = False

        await queue_manager.process_request(mock_req_item)

        # Verify future exception set (499)
        assert mock_req_item["result_future"].done()
        with pytest.raises(HTTPException) as exc:
            mock_req_item["result_future"].result()
        assert exc.value.status_code == 499


@pytest.mark.asyncio
async def test_process_request_success_flow(queue_manager, mock_req_item):
    queue_manager.logger = MagicMock()
    queue_manager.request_queue = MagicMock()
    queue_manager.processing_lock = asyncio.Lock()

    # Mock dependencies
    with (
        patch(
            "api_utils.request_processor._check_client_connection",
            new_callable=AsyncMock,
        ) as mock_check,
        patch.object(
            queue_manager, "_execute_request_logic", new_callable=AsyncMock
        ) as mock_exec,
        patch.object(
            queue_manager, "_cleanup_after_processing", new_callable=AsyncMock
        ) as mock_cleanup,
    ):
        mock_check.return_value = True

        await queue_manager.process_request(mock_req_item)

        mock_exec.assert_called_once()
        mock_cleanup.assert_called_once()
        queue_manager.request_queue.task_done.assert_called_once()
        assert (
            queue_manager.was_last_request_streaming is False
        )  # Request default is False


@pytest.mark.asyncio
async def test_process_request_retry_logic_refresh(queue_manager, mock_req_item):
    """Test Tier 1 recovery (Page Refresh)"""
    queue_manager.logger = MagicMock()
    queue_manager.request_queue = MagicMock()
    queue_manager.processing_lock = asyncio.Lock()

    # Fail first time, succeed second time
    mock_exec = AsyncMock(side_effect=[Exception("Some error"), None])

    with (
        patch(
            "api_utils.request_processor._check_client_connection",
            new_callable=AsyncMock,
        ) as mock_check,
        patch.object(queue_manager, "_execute_request_logic", mock_exec),
        patch.object(
            queue_manager, "_refresh_page", new_callable=AsyncMock
        ) as mock_refresh,
        patch.object(
            queue_manager, "_cleanup_after_processing", new_callable=AsyncMock
        ),
    ):
        mock_check.return_value = True

        await queue_manager.process_request(mock_req_item)

        # Should have called execute twice
        assert mock_exec.call_count == 2
        # Should have called refresh once
        mock_refresh.assert_called_once()


@pytest.mark.asyncio
async def test_process_request_retry_logic_switch_profile(queue_manager, mock_req_item):
    """Test Tier 2 recovery (Switch Profile)"""
    queue_manager.logger = MagicMock()
    queue_manager.request_queue = MagicMock()
    queue_manager.processing_lock = asyncio.Lock()

    # Fail first time (refresh), fail second time (switch), succeed third time
    mock_exec = AsyncMock(side_effect=[Exception("Err1"), Exception("Err2"), None])

    with (
        patch(
            "api_utils.request_processor._check_client_connection",
            new_callable=AsyncMock,
        ) as mock_check,
        patch.object(queue_manager, "_execute_request_logic", mock_exec),
        patch.object(
            queue_manager, "_refresh_page", new_callable=AsyncMock
        ) as mock_refresh,
        patch.object(
            queue_manager, "_switch_auth_profile", new_callable=AsyncMock
        ) as mock_switch,
        patch.object(
            queue_manager, "_cleanup_after_processing", new_callable=AsyncMock
        ),
    ):
        mock_check.return_value = True

        await queue_manager.process_request(mock_req_item)

        assert mock_exec.call_count == 3
        mock_refresh.assert_called_once()
        mock_switch.assert_called_once()


@pytest.mark.asyncio
async def test_process_request_quota_error_immediate_switch(
    queue_manager, mock_req_item
):
    """Test Immediate Profile Switch on Quota Error"""
    queue_manager.logger = MagicMock()
    queue_manager.request_queue = MagicMock()
    queue_manager.processing_lock = asyncio.Lock()

    # Fail with quota error first, then succeed
    mock_exec = AsyncMock(side_effect=[Exception("429 Too Many Requests"), None])

    with (
        patch(
            "api_utils.request_processor._check_client_connection",
            new_callable=AsyncMock,
        ) as mock_check,
        patch.object(queue_manager, "_execute_request_logic", mock_exec),
        patch.object(
            queue_manager, "_switch_auth_profile", new_callable=AsyncMock
        ) as mock_switch,
        patch.object(
            queue_manager, "_cleanup_after_processing", new_callable=AsyncMock
        ),
    ):
        mock_check.return_value = True

        await queue_manager.process_request(mock_req_item)

        # Should call switch immediately, skipping refresh
        mock_switch.assert_called_once()
        assert mock_exec.call_count == 2


@pytest.mark.asyncio
async def test_execute_request_logic_calls_processor(queue_manager, mock_req_item):
    queue_manager.logger = MagicMock()

    with (
        patch(
            "api_utils._process_request_refactored", new_callable=AsyncMock
        ) as mock_process,
        patch.object(
            queue_manager, "_monitor_completion", new_callable=AsyncMock
        ) as mock_monitor,
    ):
        # Return tuple (event, btn, checker, state)
        mock_event = asyncio.Event()
        mock_btn = MagicMock()
        mock_checker = MagicMock()
        mock_state = {"has_content": True}
        mock_process.return_value = (mock_event, mock_btn, mock_checker, mock_state)

        await queue_manager._execute_request_logic(
            mock_req_item["req_id"],
            mock_req_item["request_data"],
            mock_req_item["http_request"],
            mock_req_item["result_future"],
        )

        mock_process.assert_called_once()
        mock_monitor.assert_called_once()

        # Verify stored context
        assert queue_manager.current_completion_event == mock_event
        assert queue_manager.current_submit_btn_loc == mock_btn


@pytest.mark.asyncio
async def test_refresh_page(queue_manager):
    queue_manager.logger = MagicMock()
    mock_page = AsyncMock()

    with patch("server.page_instance", mock_page):
        await queue_manager._refresh_page("req1")

        mock_page.reload.assert_called_once()
        mock_page.wait_for_selector.assert_called_once()


@pytest.mark.asyncio
async def test_refresh_page_no_instance(queue_manager):
    queue_manager.logger = MagicMock()

    with patch("server.page_instance", None):
        with pytest.raises(RuntimeError):
            await queue_manager._refresh_page("req1")


@pytest.mark.asyncio
async def test_switch_auth_profile(queue_manager):
    queue_manager.logger = MagicMock()
    mock_browser = AsyncMock()
    mock_browser.is_connected.return_value = True
    mock_browser.version = "Mozilla Firefox 115.0"
    mock_page = AsyncMock()
    mock_playwright_mgr = MagicMock()
    mock_playwright_mgr.firefox.connect = AsyncMock(return_value=mock_browser)

    with (
        patch("server.browser_instance", mock_browser),
        patch("server.playwright_manager", mock_playwright_mgr),
        patch("server.is_browser_connected", True),
        patch("server.page_instance", None),
        patch("server.is_page_ready", False),
        patch("api_utils.auth_manager.auth_manager") as mock_auth_mgr,
        patch(
            "browser_utils.initialization.core.close_page_logic", new_callable=AsyncMock
        ) as mock_close,
        patch(
            "browser_utils.initialization.core.initialize_page_logic",
            new_callable=AsyncMock,
        ) as mock_init,
        patch(
            "browser_utils.initialization.core.enable_temporary_chat_mode",
            new_callable=AsyncMock,
        ) as mock_temp_chat,
        patch(
            "browser_utils.model_management._handle_initial_model_state_and_storage",
            new_callable=AsyncMock,
        ) as mock_handle_model,
        patch(
            "config.get_environment_variable",
            return_value="ws://127.0.0.1:9222/devtools/browser/test",
        ),
    ):
        mock_auth_mgr.get_next_profile = AsyncMock(return_value="profile2.json")
        mock_init.return_value = (mock_page, True)

        await queue_manager._switch_auth_profile("req1")

        mock_auth_mgr.mark_profile_failed.assert_called_once()
        mock_auth_mgr.get_next_profile.assert_called_once()
        mock_close.assert_called_once()
        mock_browser.close.assert_called_once()
        mock_playwright_mgr.firefox.connect.assert_called_once()
        mock_init.assert_called_once()
        mock_handle_model.assert_called_once_with(mock_page)
        mock_temp_chat.assert_called_once_with(mock_page)


@pytest.mark.asyncio
async def test_initialize_globals(queue_manager):
    with (
        patch("server.request_queue", None),
        patch("server.processing_lock", None),
        patch("server.model_switching_lock", None),
        patch("server.params_cache_lock", None),
        patch("server.logger", MagicMock()) as mock_logger,
    ):
        queue_manager.initialize_globals()

        assert queue_manager.request_queue is not None
        assert queue_manager.processing_lock is not None
        assert queue_manager.model_switching_lock is not None
        assert queue_manager.params_cache_lock is not None
        assert queue_manager.logger == mock_logger


@pytest.mark.asyncio
async def test_initialize_globals_existing(queue_manager):
    mock_q = MagicMock()
    mock_l1 = MagicMock()
    mock_l2 = MagicMock()
    mock_l3 = MagicMock()

    with (
        patch("server.request_queue", mock_q),
        patch("server.processing_lock", mock_l1),
        patch("server.model_switching_lock", mock_l2),
        patch("server.params_cache_lock", mock_l3),
    ):
        queue_manager.initialize_globals()

        assert queue_manager.request_queue == mock_q
        assert queue_manager.processing_lock == mock_l1
        assert queue_manager.model_switching_lock == mock_l2
        assert queue_manager.params_cache_lock == mock_l3


# --- Tests for QueueManager.check_queue_disconnects ---


@pytest.mark.asyncio
async def test_check_queue_disconnects(queue_manager):
    mock_queue = MagicMock()
    mock_queue.put = AsyncMock()
    queue_manager.request_queue = mock_queue

    # Item 1: Disconnected
    item1 = {
        "req_id": "1",
        "http_request": MagicMock(),
        "cancelled": False,
        "result_future": asyncio.Future(),
    }
    item1["http_request"].is_disconnected = AsyncMock(return_value=True)

    # Item 2: Connected
    item2 = {
        "req_id": "2",
        "http_request": MagicMock(),
        "cancelled": False,
        "result_future": asyncio.Future(),
    }
    item2["http_request"].is_disconnected = AsyncMock(return_value=False)

    mock_queue.qsize.return_value = 2
    mock_queue.get_nowait.side_effect = [item1, item2, asyncio.QueueEmpty()]

    await queue_manager.check_queue_disconnects()

    assert item1["cancelled"] is True
    assert item1["result_future"].done()

    assert item2["cancelled"] is False
    assert not item2["result_future"].done()

    # Verify items are put back
    assert mock_queue.put.call_count == 2
    mock_queue.put.assert_has_calls([call(item1), call(item2)])


# --- Tests for QueueManager.get_next_request ---


@pytest.mark.asyncio
async def test_get_next_request_timeout(queue_manager):
    mock_queue = MagicMock()
    mock_queue.get = AsyncMock(side_effect=asyncio.TimeoutError)
    queue_manager.request_queue = mock_queue

    with patch("asyncio.wait_for", AsyncMock(side_effect=asyncio.TimeoutError)):
        result = await queue_manager.get_next_request()
        assert result is None


@pytest.mark.asyncio
async def test_get_next_request_success(queue_manager):
    mock_queue = MagicMock()
    item = {"req_id": "test"}
    mock_queue.get = AsyncMock(return_value=item)
    queue_manager.request_queue = mock_queue

    with patch("asyncio.wait_for", AsyncMock(return_value=item)):
        result = await queue_manager.get_next_request()
        assert result == item


# --- Tests for QueueManager.process_request ---


@pytest.mark.asyncio
async def test_process_request_cancelled(queue_manager, mock_req_item):
    mock_req_item["cancelled"] = True
    queue_manager.request_queue = MagicMock()

    await queue_manager.process_request(mock_req_item)

    assert mock_req_item["result_future"].done()
    with pytest.raises(HTTPException) as exc:
        mock_req_item["result_future"].result()
    assert exc.value.status_code == 499


@pytest.mark.asyncio
async def test_process_request_lock_none(queue_manager, mock_req_item):
    queue_manager.processing_lock = None
    queue_manager.request_queue = MagicMock()

    with patch(
        "api_utils.request_processor._check_client_connection",
        AsyncMock(return_value=True),
    ):
        await queue_manager.process_request(mock_req_item)

    assert mock_req_item["result_future"].done()
    with pytest.raises(HTTPException) as exc:
        mock_req_item["result_future"].result()
    assert exc.value.status_code == 500
    assert "Processing lock missing" in exc.value.detail


@pytest.mark.asyncio
async def test_process_request_disconnect_before_lock(queue_manager, mock_req_item):
    queue_manager.processing_lock = AsyncMock()
    queue_manager.request_queue = MagicMock()

    # First check returns False (disconnected)
    with patch(
        "api_utils.request_processor._check_client_connection",
        AsyncMock(return_value=False),
    ):
        await queue_manager.process_request(mock_req_item)

    assert mock_req_item["result_future"].done()
    with pytest.raises(HTTPException) as exc:
        mock_req_item["result_future"].result()
    assert exc.value.status_code == 499


@pytest.mark.asyncio
async def test_process_request_disconnect_waiting_lock(queue_manager, mock_req_item):
    queue_manager.processing_lock = AsyncMock()
    queue_manager.request_queue = MagicMock()

    # First check True, Second check (before lock) False
    # Note: process_request checks once outside lock, then acquires lock, then checks inside.
    # If we want to simulate disconnect "waiting for lock", we might need to simulate lock delay.
    # But here we just test that if the second check (inside lock) fails, it aborts.

    with (
        patch(
            "api_utils.request_processor._check_client_connection",
            AsyncMock(side_effect=[True, False]),
        ),
        patch.object(queue_manager, "_execute_request_logic", AsyncMock()) as mock_exec,
    ):
        await queue_manager.process_request(mock_req_item)
        mock_exec.assert_not_called()

    assert mock_req_item["result_future"].done()
    with pytest.raises(HTTPException) as exc:
        mock_req_item["result_future"].result()
    assert exc.value.status_code == 499


@pytest.mark.asyncio
async def test_process_request_disconnect_inside_lock(queue_manager, mock_req_item):
    queue_manager.processing_lock = MagicMock()
    queue_manager.processing_lock.__aenter__ = AsyncMock()
    queue_manager.processing_lock.__aexit__ = AsyncMock()
    queue_manager.request_queue = MagicMock()

    # First True (outside), Second False (inside)
    with (
        patch(
            "api_utils.request_processor._check_client_connection",
            AsyncMock(side_effect=[True, False]),
        ),
        patch.object(queue_manager, "_execute_request_logic", AsyncMock()) as mock_exec,
    ):
        await queue_manager.process_request(mock_req_item)
        mock_exec.assert_not_called()

    assert mock_req_item["result_future"].done()
    with pytest.raises(HTTPException) as exc:
        mock_req_item["result_future"].result()
    assert exc.value.status_code == 499


@pytest.mark.asyncio
async def test_process_request_future_done(queue_manager, mock_req_item):
    queue_manager.processing_lock = MagicMock()
    queue_manager.processing_lock.__aenter__ = AsyncMock()
    queue_manager.processing_lock.__aexit__ = AsyncMock()
    queue_manager.request_queue = MagicMock()

    mock_req_item["result_future"].set_result("Already done")

    # Part 1: Verify cleanup is called even if future is done
    with (
        patch(
            "api_utils.request_processor._check_client_connection",
            AsyncMock(return_value=True),
        ),
        patch.object(
            queue_manager, "_cleanup_after_processing", AsyncMock()
        ) as mock_cleanup,
    ):
        await queue_manager.process_request(mock_req_item)
        mock_cleanup.assert_called_once()

    # Part 2: Verify execute logic is NOT called
    with (
        patch(
            "api_utils.request_processor._check_client_connection",
            AsyncMock(return_value=True),
        ),
        patch.object(queue_manager, "_execute_request_logic", AsyncMock()) as mock_exec,
        patch.object(
            queue_manager, "_cleanup_after_processing", AsyncMock()
        ) as mock_cleanup,
    ):
        await queue_manager.process_request(mock_req_item)
        mock_exec.assert_not_called()
        mock_cleanup.assert_called_once()


# --- Recovery Tests ---


@pytest.mark.asyncio
async def test_process_request_recovery_tier1(queue_manager, mock_req_item):
    # Tier 1: Page Refresh (新的快速恢复策略)
    queue_manager.processing_lock = MagicMock()
    queue_manager.processing_lock.__aenter__ = AsyncMock()
    queue_manager.processing_lock.__aexit__ = AsyncMock(return_value=None)
    queue_manager.request_queue = MagicMock()

    with (
        patch(
            "api_utils.request_processor._check_client_connection",
            AsyncMock(return_value=True),
        ),
        patch.object(queue_manager, "_execute_request_logic", AsyncMock()) as mock_exec,
        patch.object(queue_manager, "_refresh_page", AsyncMock()) as mock_refresh,
        patch.object(queue_manager, "_cleanup_after_processing", AsyncMock()),
    ):
        # Fail once, then succeed
        mock_exec.side_effect = [Exception("Fail 1"), None]

        await queue_manager.process_request(mock_req_item)

        assert mock_exec.call_count == 2
        mock_refresh.assert_called_once()  # Tier 1 calls _refresh_page


@pytest.mark.asyncio
async def test_process_request_recovery_tier2(queue_manager, mock_req_item):
    # Tier 2: Auth Profile Switch (第二次失败后切换配置文件)
    queue_manager.processing_lock = MagicMock()
    queue_manager.processing_lock.__aenter__ = AsyncMock()
    queue_manager.processing_lock.__aexit__ = AsyncMock(return_value=None)
    queue_manager.request_queue = MagicMock()

    with (
        patch(
            "api_utils.request_processor._check_client_connection",
            AsyncMock(return_value=True),
        ),
        patch.object(queue_manager, "_execute_request_logic", AsyncMock()) as mock_exec,
        patch.object(queue_manager, "_refresh_page", AsyncMock()) as mock_refresh,
        patch.object(queue_manager, "_switch_auth_profile", AsyncMock()) as mock_switch,
        patch.object(queue_manager, "_cleanup_after_processing", AsyncMock()),
    ):
        # Fail twice, then succeed
        mock_exec.side_effect = [Exception("Fail 1"), Exception("Fail 2"), None]

        await queue_manager.process_request(mock_req_item)

        assert mock_exec.call_count == 3
        mock_refresh.assert_called_once()  # Tier 1 after first failure
        mock_switch.assert_called_once()  # Tier 2 after second failure


@pytest.mark.asyncio
async def test_process_request_recovery_quota_error(queue_manager, mock_req_item):
    # 配额错误检测 - 立即切换配置文件 (跳过所有重试层级)
    queue_manager.processing_lock = MagicMock()
    queue_manager.processing_lock.__aenter__ = AsyncMock()
    queue_manager.processing_lock.__aexit__ = AsyncMock(return_value=None)
    queue_manager.request_queue = MagicMock()

    with (
        patch(
            "api_utils.request_processor._check_client_connection",
            AsyncMock(return_value=True),
        ),
        patch.object(queue_manager, "_execute_request_logic", AsyncMock()) as mock_exec,
        patch.object(queue_manager, "_switch_auth_profile", AsyncMock()) as mock_switch,
        patch.object(queue_manager, "_refresh_page", AsyncMock()) as mock_refresh,
        patch.object(queue_manager, "_cleanup_after_processing", AsyncMock()),
    ):
        # 第一次失败返回配额错误，切换配置文件后成功
        mock_exec.side_effect = [Exception("Quota exceeded error 429"), None]

        await queue_manager.process_request(mock_req_item)

        assert mock_exec.call_count == 2
        # 配额错误应立即触发 profile switch，而不是 page refresh
        mock_switch.assert_called_once()
        mock_refresh.assert_not_called()  # 配额错误跳过刷新步骤


@pytest.mark.asyncio
async def test_process_request_recovery_exhausted(queue_manager, mock_req_item):
    # 所有尝试耗尽 - 现在是 3 次尝试 (1 初始 + 1 刷新 + 1 配置文件切换)
    queue_manager.processing_lock = MagicMock()
    queue_manager.processing_lock.__aenter__ = AsyncMock()
    queue_manager.processing_lock.__aexit__ = AsyncMock(return_value=None)
    queue_manager.request_queue = MagicMock()

    with (
        patch(
            "api_utils.request_processor._check_client_connection",
            AsyncMock(return_value=True),
        ),
        patch.object(queue_manager, "_execute_request_logic", AsyncMock()) as mock_exec,
        patch.object(queue_manager, "_refresh_page", AsyncMock()) as mock_refresh,
        patch.object(queue_manager, "_switch_auth_profile", AsyncMock()) as mock_switch,
        patch.object(queue_manager, "_cleanup_after_processing", AsyncMock()),
    ):
        # Fail 3 times (max_attempts = 3)
        mock_exec.side_effect = [
            Exception("Fail 1"),
            Exception("Fail 2"),
            Exception("Fail 3"),
        ]

        # Should raise exception eventually
        with pytest.raises(Exception) as exc:
            await queue_manager.process_request(mock_req_item)

        assert "Fail 3" in str(exc.value)
        assert mock_exec.call_count == 3
        mock_refresh.assert_called_once()  # Tier 1: Page refresh after first failure
        mock_switch.assert_called_once()  # Tier 2: Profile switch after second failure


# --- Tests for _execute_request_logic ---


@pytest.mark.asyncio
async def test_execute_request_logic_streaming(queue_manager, mock_req_item):
    mock_event = asyncio.Event()
    mock_loc = MagicMock()
    mock_checker = MagicMock()

    with (
        patch(
            "api_utils._process_request_refactored",
            AsyncMock(return_value=(mock_event, mock_loc, mock_checker)),
        ),
        patch.object(queue_manager, "_monitor_completion", AsyncMock()) as mock_mon,
    ):
        await queue_manager._execute_request_logic(
            mock_req_item["req_id"],
            mock_req_item["request_data"],
            mock_req_item["http_request"],
            mock_req_item["result_future"],
        )

        assert queue_manager.current_completion_event == mock_event
        mock_mon.assert_called_once()
        args = mock_mon.call_args[0]
        assert args[3] == mock_event  # completion_event
        assert args[6] is True  # current_request_was_streaming


@pytest.mark.asyncio
async def test_execute_request_logic_non_streaming(queue_manager, mock_req_item):
    with (
        patch("api_utils._process_request_refactored", AsyncMock(return_value=None)),
        patch.object(queue_manager, "_monitor_completion", AsyncMock()) as mock_mon,
    ):
        await queue_manager._execute_request_logic(
            mock_req_item["req_id"],
            mock_req_item["request_data"],
            mock_req_item["http_request"],
            mock_req_item["result_future"],
        )

        assert queue_manager.current_completion_event is None
        mock_mon.assert_called_once()
        args = mock_mon.call_args[0]
        assert args[3] is None  # completion_event
        assert args[6] is False  # current_request_was_streaming


@pytest.mark.asyncio
async def test_execute_request_logic_error(queue_manager, mock_req_item):
    with patch(
        "api_utils._process_request_refactored",
        AsyncMock(side_effect=Exception("Process Error")),
    ):
        # 异常应被重新抛出以触发重试机制
        with pytest.raises(Exception) as exc:
            await queue_manager._execute_request_logic(
                mock_req_item["req_id"],
                mock_req_item["request_data"],
                mock_req_item["http_request"],
                mock_req_item["result_future"],
            )
        assert "Process Error" in str(exc.value)

        # 同时也应设置 result_future 的异常
        assert mock_req_item["result_future"].done()
        with pytest.raises(HTTPException) as http_exc:
            mock_req_item["result_future"].result()
        assert http_exc.value.status_code == 500
        assert "Process Error" in http_exc.value.detail


# --- Tests for _monitor_completion ---


@pytest.mark.asyncio
async def test_monitor_completion_streaming(queue_manager):
    req_id = "test"
    http_req = MagicMock()
    future = asyncio.Future()
    event = asyncio.Event()

    # Set event immediately
    event.set()

    with patch(
        "api_utils.client_connection.enhanced_disconnect_monitor", AsyncMock()
    ) as mock_disco:
        await queue_manager._monitor_completion(
            req_id, http_req, future, event, None, None, True
        )
        mock_disco.assert_called_once()


@pytest.mark.asyncio
async def test_monitor_completion_timeout(queue_manager):
    req_id = "test"
    http_req = MagicMock()
    future = asyncio.Future()
    event = asyncio.Event()

    # Don't set event, mock wait_for to timeout
    with (
        patch("api_utils.client_connection.enhanced_disconnect_monitor", AsyncMock()),
        patch("asyncio.wait_for", AsyncMock(side_effect=asyncio.TimeoutError)),
    ):
        await queue_manager._monitor_completion(
            req_id, http_req, future, event, None, None, True
        )

        assert future.done()
        with pytest.raises(HTTPException) as exc:
            future.result()
        assert exc.value.status_code == 504


@pytest.mark.asyncio
async def test_monitor_completion_error(queue_manager):
    req_id = "test"
    http_req = MagicMock()
    future = asyncio.Future()
    event = asyncio.Event()

    with (
        patch("api_utils.client_connection.enhanced_disconnect_monitor", AsyncMock()),
        patch("asyncio.wait_for", AsyncMock(side_effect=Exception("Wait Error"))),
    ):
        # 异常应被重新抛出以触发重试机制
        with pytest.raises(Exception) as exc:
            await queue_manager._monitor_completion(
                req_id, http_req, future, event, None, None, True
            )
        assert "Wait Error" in str(exc.value)

        # 同时也应设置 future 的异常
        assert future.done()
        with pytest.raises(HTTPException) as http_exc:
            future.result()
        assert http_exc.value.status_code == 500
        assert "Wait Error" in http_exc.value.detail


@pytest.mark.asyncio
async def test_monitor_completion_empty_response(queue_manager):
    """测试空响应检测功能 - 当 stream_state.has_content=False 时应抛出异常"""
    req_id = "test"
    http_req = MagicMock()
    future = asyncio.Future()
    event = asyncio.Event()
    stream_state = {"has_content": False}  # 模拟空响应

    # Set event immediately to simulate completion
    event.set()

    with patch(
        "api_utils.client_connection.enhanced_disconnect_monitor", AsyncMock()
    ) as mock_disco:
        mock_disco.return_value = False  # 没有提前断开

        # 应该抛出 RuntimeError 因为 stream_state.has_content=False
        with pytest.raises(RuntimeError) as exc:
            await queue_manager._monitor_completion(
                req_id, http_req, future, event, None, None, True, stream_state
            )
        assert "Empty response" in str(exc.value) or "空响应" in str(exc.value)


@pytest.mark.asyncio
async def test_monitor_completion_with_content(queue_manager):
    """测试有内容时不应抛出异常"""
    req_id = "test"
    http_req = MagicMock()
    future = asyncio.Future()
    event = asyncio.Event()
    stream_state = {"has_content": True}  # 有内容

    # Set event immediately
    event.set()

    with patch(
        "api_utils.client_connection.enhanced_disconnect_monitor", AsyncMock()
    ) as mock_disco:
        mock_disco.return_value = False
        # 不应抛出异常
        await queue_manager._monitor_completion(
            req_id, http_req, future, event, None, None, True, stream_state
        )
        mock_disco.assert_called_once()


# --- Tests for _handle_post_stream_button ---


@pytest.mark.asyncio
async def test_handle_post_stream_button_success(queue_manager):
    req_id = "test"
    loc = MagicMock()
    checker = MagicMock()
    event = asyncio.Event()

    mock_page_instance = MagicMock()
    mock_controller = MagicMock()
    mock_controller.ensure_generation_stopped = AsyncMock()

    with (
        patch("server.page_instance", mock_page_instance),
        patch(
            "browser_utils.page_controller.PageController", return_value=mock_controller
        ),
    ):
        await queue_manager._handle_post_stream_button(req_id, loc, checker, event)

        mock_controller.ensure_generation_stopped.assert_called_once_with(checker)


@pytest.mark.asyncio
async def test_handle_post_stream_button_error(queue_manager):
    req_id = "test"
    loc = MagicMock()
    checker = MagicMock()
    event = asyncio.Event()

    mock_page_instance = MagicMock()

    with (
        patch("server.page_instance", mock_page_instance),
        patch(
            "browser_utils.page_controller.PageController",
            side_effect=Exception("Error"),
        ),
        patch(
            "browser_utils.debug_utils.save_comprehensive_snapshot", AsyncMock()
        ) as mock_snap,
    ):
        await queue_manager._handle_post_stream_button(req_id, loc, checker, event)

        mock_snap.assert_called_once()


# --- Tests for _cleanup_after_processing ---


@pytest.mark.asyncio
async def test_cleanup_after_processing(queue_manager):
    req_id = "test"
    queue_manager.current_submit_btn_loc = MagicMock()
    queue_manager.current_client_disco_checker = MagicMock()

    mock_page_instance = MagicMock()
    mock_controller = MagicMock()
    mock_controller.clear_chat_history = AsyncMock()

    with (
        patch("api_utils.clear_stream_queue", AsyncMock()) as mock_clear_q,
        patch("server.page_instance", mock_page_instance),
        patch("server.is_page_ready", True),
        patch(
            "browser_utils.page_controller.PageController", return_value=mock_controller
        ),
    ):
        await queue_manager._cleanup_after_processing(req_id)

        mock_clear_q.assert_called_once()
        mock_controller.clear_chat_history.assert_called_once()


# --- Tests for queue_worker (Main Loop) ---


@pytest.mark.asyncio
@pytest.mark.timeout(5)
async def test_queue_worker_main_loop():
    # Test the main loop startup and shutdown
    with patch("api_utils.queue_worker.QueueManager") as MockManager:
        mock_instance = MockManager.return_value
        mock_instance.logger = MagicMock()
        # 新的诊断日志需要 request_queue.qsize()
        mock_queue = MagicMock()
        mock_queue.qsize.return_value = 0
        mock_instance.request_queue = mock_queue

        # Run once then cancel
        mock_instance.check_queue_disconnects = AsyncMock()
        mock_instance.get_next_request = AsyncMock(side_effect=asyncio.CancelledError)

        try:
            await queue_worker()
        except asyncio.CancelledError:
            pass

        mock_instance.initialize_globals.assert_called_once()
        mock_instance.check_queue_disconnects.assert_called_once()


@pytest.mark.asyncio
@pytest.mark.timeout(5)
async def test_queue_worker_main_loop_exception():
    # Test exception handling in main loop
    with patch("api_utils.queue_worker.QueueManager") as MockManager:
        mock_instance = MockManager.return_value
        mock_instance.logger = MagicMock()
        # 新的诊断日志需要 request_queue.qsize()
        mock_queue = MagicMock()
        mock_queue.qsize.return_value = 0
        mock_instance.request_queue = mock_queue

        # Raise exception then cancel
        mock_instance.check_queue_disconnects = AsyncMock(
            side_effect=[Exception("Loop Error"), asyncio.CancelledError]
        )

        with patch("asyncio.sleep", AsyncMock()) as mock_sleep:
            try:
                await queue_worker()
            except asyncio.CancelledError:
                pass

            mock_instance.logger.error.assert_called()
            mock_sleep.assert_called()


@pytest.mark.asyncio
async def test_check_queue_disconnects_edge_cases(queue_manager):
    mock_queue = MagicMock()
    mock_queue.put = AsyncMock()
    queue_manager.request_queue = mock_queue

    # Duplicate IDs
    item1 = {"req_id": "1", "cancelled": False}
    item2 = {"req_id": "1", "cancelled": False}  # Duplicate

    mock_queue.qsize.return_value = 2
    mock_queue.get_nowait.side_effect = [item1, item2, asyncio.QueueEmpty()]

    await queue_manager.check_queue_disconnects()

    # Both should be requeued, but logic handles duplicates by skipping processing check for second one
    assert mock_queue.put.call_count == 2


@pytest.mark.asyncio
async def test_check_queue_disconnects_exception(queue_manager):
    mock_queue = MagicMock()
    mock_queue.put = AsyncMock()
    queue_manager.request_queue = mock_queue

    item = {"req_id": "1", "http_request": MagicMock(), "cancelled": False}
    item["http_request"].is_disconnected = AsyncMock(
        side_effect=Exception("Check Error")
    )

    mock_queue.qsize.return_value = 1
    mock_queue.get_nowait.side_effect = [item, asyncio.QueueEmpty()]

    # Should catch exception and log error, but still requeue
    await queue_manager.check_queue_disconnects()

    mock_queue.put.assert_called_once_with(item)


@pytest.mark.asyncio
async def test_handle_post_stream_button_no_page(queue_manager):
    req_id = "test"
    loc = MagicMock()
    checker = MagicMock()
    event = asyncio.Event()

    with patch("server.page_instance", None):
        await queue_manager._handle_post_stream_button(req_id, loc, checker, event)
        # Should log warning and return, no exception


@pytest.mark.asyncio
async def test_cleanup_after_processing_exception(queue_manager):
    req_id = "test"
    with patch("api_utils.clear_stream_queue", side_effect=Exception("Cleanup Error")):
        await queue_manager._cleanup_after_processing(req_id)
        # Should catch and log error
