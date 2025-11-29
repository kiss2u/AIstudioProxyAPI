import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException, Request

from api_utils.request_processor import (
    _analyze_model_requirements,
    _cleanup_request_resources,
    _handle_auxiliary_stream_response,
    _handle_model_switch_failure,
    _handle_model_switching,
    _handle_parameter_cache,
    _handle_playwright_response,
    _handle_response_processing,
    _prepare_and_validate_request,
    _process_request_refactored,
    _validate_page_status,
)
from models import ChatCompletionRequest

# --- Fixtures ---


@pytest.fixture
def mock_http_request():
    return MagicMock(spec=Request)


@pytest.fixture
def mock_context():
    page_mock = AsyncMock()
    # is_closed is synchronous in Playwright, so it shouldn't return a coroutine
    page_mock.is_closed = MagicMock(return_value=False)
    return {
        "page": page_mock,
        "is_page_ready": True,
        "current_ai_studio_model_id": "gemini-2.0-flash",
        "logger": MagicMock(),
        "page_params_cache": {},
        "params_cache_lock": AsyncMock(),
        "model_id_to_use": "gemini-2.0-flash",
        "parsed_model_list": [],
    }


@pytest.fixture
def mock_request():
    return ChatCompletionRequest(
        messages=[{"role": "user", "content": "Hello"}],
        model="gemini-2.0-flash",
        stream=False,
    )


@pytest.fixture
def mock_check_disconnected():
    return MagicMock()


# --- Tests ---


@pytest.mark.asyncio
async def test_analyze_model_requirements(mock_context, mock_request):
    with patch(
        "api_utils.request_processor.ms_analyze", new_callable=AsyncMock
    ) as mock_ms_analyze:
        await _analyze_model_requirements("req1", mock_context, mock_request)
        mock_ms_analyze.assert_called_once()


@pytest.mark.asyncio
async def test_validate_page_status_success(mock_context, mock_check_disconnected):
    # Ensure is_closed returns False
    mock_context["page"].is_closed.return_value = False
    print(f"DEBUG TEST: page={mock_context['page']}")
    print(f"DEBUG TEST: is_closed={mock_context['page'].is_closed()}")
    print(f"DEBUG TEST: is_page_ready={mock_context['is_page_ready']}")
    await _validate_page_status("req1", mock_context, mock_check_disconnected)
    mock_check_disconnected.assert_called_once()


@pytest.mark.asyncio
async def test_validate_page_status_failure(mock_context, mock_check_disconnected):
    mock_context["page"] = None
    with pytest.raises(HTTPException) as exc:
        await _validate_page_status("req1", mock_context, mock_check_disconnected)
    assert exc.value.status_code == 503

    mock_context["page"] = AsyncMock()
    mock_context["page"].is_closed.return_value = True
    with pytest.raises(HTTPException) as exc:
        await _validate_page_status("req1", mock_context, mock_check_disconnected)
    assert exc.value.status_code == 503

    mock_context["page"].is_closed.return_value = False
    mock_context["is_page_ready"] = False
    with pytest.raises(HTTPException) as exc:
        await _validate_page_status("req1", mock_context, mock_check_disconnected)
    assert exc.value.status_code == 503


@pytest.mark.asyncio
async def test_handle_model_switching(mock_context, mock_check_disconnected):
    with patch(
        "api_utils.request_processor.ms_switch", new_callable=AsyncMock
    ) as mock_ms_switch:
        await _handle_model_switching("req1", mock_context, mock_check_disconnected)
        mock_ms_switch.assert_called_once()


@pytest.mark.asyncio
async def test_handle_model_switch_failure():
    mock_page = AsyncMock()
    mock_logger = MagicMock()
    with patch("server.current_ai_studio_model_id", "old_model"):
        with pytest.raises(HTTPException) as exc:
            await _handle_model_switch_failure(
                "req1", mock_page, "new_model", "old_model", mock_logger
            )
        assert exc.value.status_code == 422
        # Check if logger warning was called
        mock_logger.warning.assert_called()


@pytest.mark.asyncio
async def test_handle_parameter_cache(mock_context):
    with patch(
        "api_utils.request_processor.ms_param_cache", new_callable=AsyncMock
    ) as mock_ms_cache:
        await _handle_parameter_cache("req1", mock_context)
        mock_ms_cache.assert_called_once()


@pytest.mark.asyncio
async def test_prepare_and_validate_request_basic(
    mock_request, mock_check_disconnected
):
    with (
        patch("api_utils.request_processor.validate_chat_request") as mock_validate,
        patch(
            "api_utils.request_processor.prepare_combined_prompt",
            return_value=("prompt", []),
        ) as mock_prep,
        patch(
            "api_utils.request_processor.maybe_execute_tools", new_callable=AsyncMock
        ) as mock_tools,
    ):
        mock_tools.return_value = None

        prompt, images = await _prepare_and_validate_request(
            "req1", mock_request, mock_check_disconnected
        )

        assert prompt == "prompt"
        assert images == []
        mock_validate.assert_called_once()
        mock_prep.assert_called_once()
        mock_tools.assert_called_once()
        mock_check_disconnected.assert_called_once()


@pytest.mark.asyncio
async def test_prepare_and_validate_request_with_tools(
    mock_request, mock_check_disconnected
):
    mock_request.tools = [{"type": "function", "function": {"name": "test"}}]
    mock_request.mcp_endpoint = "http://mcp"

    tool_results = [{"name": "test_tool", "arguments": "{}", "result": "success"}]

    with (
        patch("api_utils.request_processor.validate_chat_request"),
        patch(
            "api_utils.request_processor.prepare_combined_prompt",
            return_value=("prompt", []),
        ),
        patch(
            "api_utils.request_processor.maybe_execute_tools", new_callable=AsyncMock
        ) as mock_tools,
        patch("api_utils.tools_registry.register_runtime_tools") as mock_register,
    ):
        mock_tools.return_value = tool_results

        prompt, _ = await _prepare_and_validate_request(
            "req1", mock_request, mock_check_disconnected
        )

        assert "Tool Execution: test_tool" in prompt
        assert "Result:\nsuccess" in prompt
        mock_register.assert_called_once()


@pytest.mark.asyncio
async def test_prepare_and_validate_request_attachments(
    mock_request, mock_check_disconnected
):
    # Mock ONLY_COLLECT_CURRENT_USER_ATTACHMENTS to True
    with (
        patch(
            "api_utils.request_processor.ONLY_COLLECT_CURRENT_USER_ATTACHMENTS", True
        ),
        patch("api_utils.request_processor.validate_chat_request"),
        patch(
            "api_utils.request_processor.prepare_combined_prompt",
            return_value=("prompt", []),
        ),
        patch(
            "api_utils.request_processor.maybe_execute_tools", new_callable=AsyncMock
        ) as mock_tools,
        patch(
            "api_utils.utils.extract_data_url_to_local", return_value="/tmp/file.png"
        ) as mock_extract,
        patch("os.path.exists", return_value=True),
    ):
        mock_tools.return_value = None
        # Use a mock object that supports getattr for role and attachments
        msg_mock = MagicMock()
        msg_mock.role = "user"
        msg_mock.content = "hi"
        msg_mock.attachments = ["data:image/png;base64,123"]
        # Make sure model_dump works if called (though not called in this specific path, but good practice)
        msg_mock.model_dump.return_value = {"role": "user", "content": "hi"}

        mock_request.messages = [msg_mock]

        _, images = await _prepare_and_validate_request(
            "req1", mock_request, mock_check_disconnected
        )

        assert "/tmp/file.png" in images
        mock_extract.assert_called_once()


@pytest.mark.asyncio
async def test_handle_response_processing_aux_stream(
    mock_request, mock_context, mock_check_disconnected
):
    mock_future = asyncio.Future()
    mock_locator = MagicMock()

    with (
        patch("config.get_environment_variable", return_value="8000"),
        patch(
            "api_utils.request_processor._handle_auxiliary_stream_response",
            new_callable=AsyncMock,
        ) as mock_aux,
    ):
        await _handle_response_processing(
            "req1",
            mock_request,
            None,
            mock_context,
            mock_future,
            mock_locator,
            mock_check_disconnected,
        )
        mock_aux.assert_called_once()


@pytest.mark.asyncio
async def test_handle_response_processing_playwright(
    mock_request, mock_context, mock_check_disconnected
):
    mock_future = asyncio.Future()
    mock_locator = MagicMock()
    mock_page = AsyncMock()

    with (
        patch("config.get_environment_variable", return_value="0"),
        patch(
            "api_utils.request_processor._handle_playwright_response",
            new_callable=AsyncMock,
        ) as mock_pw,
    ):
        await _handle_response_processing(
            "req1",
            mock_request,
            mock_page,
            mock_context,
            mock_future,
            mock_locator,
            mock_check_disconnected,
        )
        mock_pw.assert_called_once()


@pytest.mark.asyncio
async def test_handle_auxiliary_stream_response_streaming(
    mock_request, mock_context, mock_check_disconnected
):
    mock_request.stream = True
    mock_future = asyncio.Future()
    mock_locator = MagicMock()

    with patch("api_utils.request_processor.gen_sse_from_aux_stream") as mock_gen:
        mock_gen.return_value = iter([])  # dummy iterator

        completion_event, _, _, stream_state = await _handle_auxiliary_stream_response(
            "req1",
            mock_request,
            mock_context,
            mock_future,
            mock_locator,
            mock_check_disconnected,
        )

        assert isinstance(completion_event, asyncio.Event)
        assert stream_state == {"has_content": False}
        assert mock_future.done()
        # Check if result is StreamingResponse
        # Note: In actual code it sets StreamingResponse, which might not be easily checkable for class type if not imported,
        # but we can check attributes
        assert hasattr(mock_future.result(), "body_iterator")


@pytest.mark.asyncio
async def test_handle_auxiliary_stream_response_non_streaming_success(
    mock_request, mock_context, mock_check_disconnected
):
    mock_request.stream = False
    mock_future = asyncio.Future()
    mock_locator = MagicMock()

    async def mock_use_stream_response(req_id):
        yield {"done": False, "body": "part1"}
        yield {"done": True, "body": "full_content", "reason": "stop"}

    with (
        patch(
            "api_utils.request_processor.use_stream_response",
            side_effect=mock_use_stream_response,
        ),
        patch("api_utils.request_processor.calculate_usage_stats", return_value={}),
        patch(
            "api_utils.request_processor.build_chat_completion_response_json",
            return_value={"id": "resp1"},
        ),
    ):
        result = await _handle_auxiliary_stream_response(
            "req1",
            mock_request,
            mock_context,
            mock_future,
            mock_locator,
            mock_check_disconnected,
        )

        assert result is None
        assert mock_future.done()
        # Verify result is JSONResponse
        assert hasattr(mock_future.result(), "body")


@pytest.mark.asyncio
async def test_handle_auxiliary_stream_response_non_streaming_internal_timeout(
    mock_request, mock_context, mock_check_disconnected
):
    mock_request.stream = False
    mock_future = asyncio.Future()
    mock_locator = MagicMock()

    async def mock_use_stream_response(req_id):
        yield {"done": True, "reason": "internal_timeout"}

    with patch(
        "api_utils.request_processor.use_stream_response",
        side_effect=mock_use_stream_response,
    ):
        with pytest.raises(HTTPException) as exc:
            await _handle_auxiliary_stream_response(
                "req1",
                mock_request,
                mock_context,
                mock_future,
                mock_locator,
                mock_check_disconnected,
            )
        assert exc.value.status_code == 502


@pytest.mark.asyncio
async def test_handle_playwright_response_streaming(
    mock_request, mock_context, mock_check_disconnected
):
    mock_request.stream = True
    mock_future = asyncio.Future()
    mock_locator = MagicMock()
    mock_page = AsyncMock()

    with (
        patch(
            "api_utils.request_processor.locate_response_elements",
            new_callable=AsyncMock,
        ),
        patch("api_utils.request_processor.gen_sse_from_playwright") as mock_gen,
    ):
        mock_gen.return_value = iter([])

        completion_event, _, _ = await _handle_playwright_response(
            "req1",
            mock_request,
            mock_page,
            mock_context,
            mock_future,
            mock_locator,
            mock_check_disconnected,
        )

        assert isinstance(completion_event, asyncio.Event)
        assert mock_future.done()


@pytest.mark.asyncio
async def test_handle_playwright_response_non_streaming(
    mock_request, mock_context, mock_check_disconnected
):
    mock_request.stream = False
    mock_future = asyncio.Future()
    mock_locator = MagicMock()
    mock_page = AsyncMock()

    with (
        patch(
            "api_utils.request_processor.locate_response_elements",
            new_callable=AsyncMock,
        ),
        patch(
            "browser_utils.page_controller.PageController.get_response",
            new_callable=AsyncMock,
        ) as mock_get_resp,
        patch("api_utils.request_processor.calculate_usage_stats", return_value={}),
        patch(
            "api_utils.request_processor.build_chat_completion_response_json",
            return_value={"id": "resp1"},
        ),
    ):
        mock_get_resp.return_value = "response content"

        result = await _handle_playwright_response(
            "req1",
            mock_request,
            mock_page,
            mock_context,
            mock_future,
            mock_locator,
            mock_check_disconnected,
        )

        assert result is None
        assert mock_future.done()


@pytest.mark.asyncio
async def test_cleanup_request_resources():
    mock_task = MagicMock()
    mock_task.done.return_value = False
    mock_task.cancel.return_value = None

    # Make task awaitable
    async def await_task():
        pass

    mock_task.__await__ = await_task().__await__

    mock_event = asyncio.Event()
    mock_future = asyncio.Future()
    mock_future.set_exception(Exception("error"))

    with (
        patch("shutil.rmtree") as mock_rmtree,
        patch("os.path.isdir", return_value=True),
    ):
        await _cleanup_request_resources(
            "req1", mock_task, mock_event, mock_future, True
        )

        mock_task.cancel.assert_called_once()
        mock_rmtree.assert_called_once()
        assert mock_event.is_set()


@pytest.mark.asyncio
async def test_process_request_refactored_client_disconnected_early(
    mock_request, mock_http_request
):
    mock_future = asyncio.Future()

    with patch(
        "api_utils.request_processor._check_client_connection", new_callable=AsyncMock
    ) as mock_check:
        mock_check.return_value = False

        result = await _process_request_refactored(
            "req1", mock_request, mock_http_request, mock_future
        )

        assert result is None
        assert mock_future.exception().status_code == 499


@pytest.mark.asyncio
async def test_process_request_refactored_success(
    mock_request, mock_http_request, mock_context
):
    mock_future = asyncio.Future()
    mock_check_disconnected = MagicMock(return_value=False)
    mock_disconnect_task = MagicMock()

    with (
        patch(
            "api_utils.request_processor._check_client_connection",
            new_callable=AsyncMock,
        ) as mock_check_conn,
        patch(
            "api_utils.request_processor._initialize_request_context",
            new_callable=AsyncMock,
        ) as mock_init_ctx,
        patch(
            "api_utils.request_processor._analyze_model_requirements",
            new_callable=AsyncMock,
        ) as mock_analyze,
        patch(
            "api_utils.request_processor._setup_disconnect_monitoring",
            new_callable=AsyncMock,
        ) as mock_setup_mon,
        patch(
            "api_utils.request_processor._validate_page_status", new_callable=AsyncMock
        ) as mock_validate_page,
        patch(
            "api_utils.request_processor.PageController", autospec=True
        ) as MockPageController,
        patch(
            "api_utils.request_processor._handle_model_switching",
            new_callable=AsyncMock,
        ) as mock_handle_switch,
        patch(
            "api_utils.request_processor._handle_parameter_cache",
            new_callable=AsyncMock,
        ),
        patch(
            "api_utils.request_processor._prepare_and_validate_request",
            new_callable=AsyncMock,
        ) as mock_prep_req,
        patch(
            "api_utils.request_processor._handle_response_processing",
            new_callable=AsyncMock,
        ) as mock_handle_resp,
        patch(
            "api_utils.request_processor._cleanup_request_resources",
            new_callable=AsyncMock,
        ) as mock_cleanup,
        patch(
            "api_utils.request_processor.save_error_snapshot", new_callable=AsyncMock
        ) as mock_snapshot,
        patch(
            "api_utils.utils.collect_and_validate_attachments", return_value=[]
        ) as mock_collect_attachments,
        patch("config.get_environment_variable", return_value="0"),
    ):
        mock_check_conn.return_value = True
        mock_init_ctx.return_value = mock_context
        mock_analyze.return_value = mock_context
        mock_setup_mon.return_value = (
            None,
            mock_disconnect_task,
            mock_check_disconnected,
        )

        mock_prep_req.return_value = ("prompt", [])

        # Mock PageController instance
        mock_pc_instance = MockPageController.return_value
        mock_pc_instance.adjust_parameters = AsyncMock()
        mock_pc_instance.submit_prompt = AsyncMock()

        # Mock response processing result
        mock_event = asyncio.Event()
        mock_locator = MagicMock()
        mock_handle_resp.return_value = (
            mock_event,
            mock_locator,
            mock_check_disconnected,
        )

        # Mock page locator for submit button
        mock_context["page"].locator.return_value = mock_locator

        result = await _process_request_refactored(
            "req1", mock_request, mock_http_request, mock_future
        )

        if result is None:
            # Extract exception information if available
            exception_calls = mock_context["logger"].exception.call_args_list
            error_calls = mock_context["logger"].error.call_args_list
            warning_calls = mock_context["logger"].warning.call_args_list
            info_calls = mock_context["logger"].info.call_args_list

            future_exc = mock_future.exception() if mock_future.done() else "Not Done"

            error_msg = (
                f"_process_request_refactored failed (result is None).\n"
                f"Future Exception: {future_exc}\n"
                f"Snapshot calls: {mock_snapshot.call_args_list}\n"
                f"Exception calls: {exception_calls}\n"
                f"Error calls: {error_calls}\n"
                f"Warning calls: {warning_calls}\n"
                f"Info calls: {info_calls}\n"
                f"Check Conn Called: {mock_check_conn.called}, Return: {mock_check_conn.return_value}\n"
                f"Page: {mock_context['page']}\n"
            )
            pytest.fail(error_msg)

        assert result == (mock_event, mock_locator, mock_check_disconnected)

        mock_validate_page.assert_called_once()
        mock_handle_switch.assert_called_once()
        mock_pc_instance.adjust_parameters.assert_called_once()
        mock_pc_instance.submit_prompt.assert_called_once()
        mock_handle_resp.assert_called_once()
        mock_cleanup.assert_called_once()
        mock_collect_attachments.assert_called_once()


@pytest.mark.asyncio
async def test_process_request_refactored_exception(
    mock_request, mock_http_request, mock_context
):
    mock_future = asyncio.Future()

    with (
        patch(
            "api_utils.request_processor._check_client_connection",
            new_callable=AsyncMock,
        ) as mock_check_conn,
        patch(
            "api_utils.request_processor._initialize_request_context",
            side_effect=Exception("Unexpected Error"),
        ),
        patch(
            "api_utils.request_processor.save_error_snapshot", new_callable=AsyncMock
        ) as mock_snapshot,
        patch(
            "api_utils.request_processor._cleanup_request_resources",
            new_callable=AsyncMock,
        ) as mock_cleanup,
    ):
        mock_check_conn.return_value = True

        with pytest.raises(Exception) as exc:
            await _process_request_refactored(
                "req1", mock_request, mock_http_request, mock_future
            )

        assert "Unexpected Error" in str(exc.value)
        # Initialization happens before try/finally, so cleanup/snapshot won't be called
        mock_snapshot.assert_not_called()
        mock_cleanup.assert_not_called()
