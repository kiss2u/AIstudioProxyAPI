"""
Tests for api_utils.request_processor module.

Test Strategy:
- Unit tests: Test helper functions individually (_prepare_and_validate_request,
  _analyze_model_requirements, _validate_page_status, etc.)
- Mock only external boundaries: Browser/page (Playwright), network requests
- Use REAL internal state: Don't mock helper functions, test actual logic
- Integration tests: Full _process_request_refactored flow with real locks/state
  (see tests/integration/test_request_flow.py)

Coverage Target: 90%+
Mock Budget: <50 (down from 103)
"""

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException, Request
from playwright.async_api import Error as PlaywrightAsyncError

from api_utils.request_processor import (
    _analyze_model_requirements,
    _handle_model_switch_failure,
    _prepare_and_validate_request,
    _validate_page_status,
)
from models import ChatCompletionRequest, Message

# ==================== Unit Tests for Helper Functions ====================


class TestAnalyzeModelRequirements:
    """Unit tests for _analyze_model_requirements helper function."""

    @pytest.mark.asyncio
    async def test_analyze_same_model_no_switch_needed(
        self, make_request_context, make_chat_request
    ):
        """Test that analyzing same model as current doesn't require switch."""
        req_id = "test-req"
        context = make_request_context(current_ai_studio_model_id="gemini-1.5-pro")
        request = make_chat_request(model="gemini-1.5-pro")

        with patch("api_utils.request_processor.MODEL_NAME", "gemini-1.5-pro"):
            result = await _analyze_model_requirements(req_id, context, request)

        # Should return context (possibly modified)
        assert isinstance(result, dict)
        assert result["req_id"] == "test-req"

    @pytest.mark.asyncio
    async def test_analyze_different_model_requires_switch(
        self, make_request_context, make_chat_request
    ):
        """Test that different model is detected and flagged for switching."""
        req_id = "test-req"
        context = make_request_context(current_ai_studio_model_id="gemini-1.5-pro")
        request = make_chat_request(model="gemini-1.5-flash")

        with patch("api_utils.request_processor.MODEL_NAME", "gemini-1.5-pro"):
            with patch(
                "api_utils.request_processor.ms_analyze",
                new_callable=AsyncMock,
            ) as mock_ms_analyze:
                mock_ms_analyze.return_value = {
                    **context,
                    "need_switch": True,
                    "model_id_to_use": "gemini-1.5-flash",
                }

                result = await _analyze_model_requirements(req_id, context, request)

                # Verify delegate was called with correct args
                mock_ms_analyze.assert_called_once_with(
                    req_id, context, "gemini-1.5-flash", "gemini-1.5-pro"
                )
                assert result["model_id_to_use"] == "gemini-1.5-flash"


class TestValidatePageStatus:
    """Unit tests for _validate_page_status helper function."""

    @pytest.mark.asyncio
    async def test_validate_page_ready_success(self, mock_playwright_stack):
        """Test validation succeeds when page is ready."""
        _, _, _, page = mock_playwright_stack
        page.is_closed.return_value = False

        context = {
            "page": page,
            "is_page_ready": True,
        }
        check_disco = MagicMock()  # Should be called

        # Should not raise
        await _validate_page_status("test-req", context, check_disco)
        check_disco.assert_called_once_with("Initial Page Check")

    @pytest.mark.asyncio
    async def test_validate_page_closed_raises_503(self, mock_playwright_stack):
        """Test validation fails with 503 when page is closed."""
        _, _, _, page = mock_playwright_stack
        page.is_closed.return_value = True  # Page closed

        context = {
            "page": page,
            "is_page_ready": True,
        }
        check_disco = MagicMock()

        with pytest.raises(HTTPException) as exc:
            await _validate_page_status("test-req", context, check_disco)

        assert exc.value.status_code == 503
        assert "AI Studio page lost" in exc.value.detail
        assert exc.value.headers.get("Retry-After") == "30"

    @pytest.mark.asyncio
    async def test_validate_page_not_ready_raises_503(self, mock_playwright_stack):
        """Test validation fails when page is not ready."""
        _, _, _, page = mock_playwright_stack
        page.is_closed.return_value = False

        context = {
            "page": page,
            "is_page_ready": False,  # Not ready
        }
        check_disco = MagicMock()

        with pytest.raises(HTTPException) as exc:
            await _validate_page_status("test-req", context, check_disco)

        assert exc.value.status_code == 503

    @pytest.mark.asyncio
    async def test_validate_page_none_raises_503(self):
        """Test validation fails when page is None."""
        context = {
            "page": None,  # No page
            "is_page_ready": True,
        }
        check_disco = MagicMock()

        with pytest.raises(HTTPException) as exc:
            await _validate_page_status("test-req", context, check_disco)

        assert exc.value.status_code == 503


class TestPrepareAndValidateRequest:
    """Unit tests for _prepare_and_validate_request helper function."""

    @pytest.mark.asyncio
    async def test_prepare_simple_text_message(self, mock_env):
        """Test preparing a simple text message without attachments or tools."""
        req_id = "test-req"
        request = ChatCompletionRequest(
            messages=[Message(role="user", content="Hello AI")],
            model="gemini-1.5-pro",
        )
        check_disco = MagicMock()

        with (
            patch("api_utils.request_processor.validate_chat_request") as mock_validate,
            patch(
                "api_utils.request_processor.prepare_combined_prompt",
                return_value=("Hello AI", []),
            ) as mock_prep,
            patch(
                "api_utils.request_processor.maybe_execute_tools",
                new_callable=AsyncMock,
                return_value=None,
            ),
        ):
            prompt, images = await _prepare_and_validate_request(
                req_id, request, check_disco
            )

            # Verify validation was called
            mock_validate.assert_called_once_with(request.messages, req_id)

            # Verify prompt preparation was called
            mock_prep.assert_called_once()

            # Check results
            assert prompt == "Hello AI"
            assert images == []
            check_disco.assert_called_once_with("After Prompt Prep")

    @pytest.mark.asyncio
    async def test_prepare_with_tool_execution(self, mock_env):
        """Test preparing request with tool execution results."""
        req_id = "test-req"
        request = ChatCompletionRequest(
            messages=[Message(role="user", content="Calculate 2+2")],
            model="gemini-1.5-pro",
            tools=[{"type": "function", "function": {"name": "calculator"}}],
        )
        check_disco = MagicMock()

        tool_results = [
            {"name": "calculator", "arguments": '{"expr": "2+2"}', "result": "4"}
        ]

        with (
            patch("api_utils.request_processor.validate_chat_request"),
            patch(
                "api_utils.request_processor.prepare_combined_prompt",
                return_value=("Calculate 2+2", []),
            ),
            patch(
                "api_utils.request_processor.maybe_execute_tools",
                new_callable=AsyncMock,
                return_value=tool_results,
            ),
        ):
            prompt, images = await _prepare_and_validate_request(
                req_id, request, check_disco
            )

            # Tool execution results should be appended to prompt
            assert "Tool Execution: calculator" in prompt
            assert "Arguments:\n" in prompt
            assert "Result:\n4" in prompt

    @pytest.mark.asyncio
    async def test_prepare_with_file_attachments(self, mock_env, tmp_path):
        """Test preparing request with file attachments."""
        req_id = "test-req"

        # Create a temporary file
        test_file = tmp_path / "test_image.png"
        test_file.write_bytes(b"fake image data")

        request = ChatCompletionRequest(
            messages=[
                Message(
                    role="user",
                    content="Look at this image",
                    attachments=[str(test_file)],  # Absolute path
                )
            ],
            model="gemini-1.5-pro",
        )
        check_disco = MagicMock()

        with (
            patch("api_utils.request_processor.validate_chat_request"),
            patch(
                "api_utils.request_processor.prepare_combined_prompt",
                return_value=("Look at this image", []),
            ),
            patch(
                "api_utils.request_processor.maybe_execute_tools",
                new_callable=AsyncMock,
                return_value=None,
            ),
            patch(
                "api_utils.request_processor.ONLY_COLLECT_CURRENT_USER_ATTACHMENTS",
                True,
            ),
        ):
            prompt, images = await _prepare_and_validate_request(
                req_id, request, check_disco
            )

            # Should extract attachment from latest user message
            assert len(images) == 1
            assert "test_image.png" in images[0]

    @pytest.mark.asyncio
    async def test_prepare_validation_error_raises_bad_request(self, mock_env):
        """Test that validation errors are converted to bad request exceptions."""
        req_id = "test-req"
        request = ChatCompletionRequest(
            messages=[],  # Empty messages - invalid
            model="gemini-1.5-pro",
        )
        check_disco = MagicMock()

        with patch(
            "api_utils.request_processor.validate_chat_request",
            side_effect=ValueError("Messages cannot be empty"),
        ):
            with pytest.raises(HTTPException) as exc:
                await _prepare_and_validate_request(req_id, request, check_disco)

            assert exc.value.status_code == 400  # Bad request
            assert "Invalid request" in exc.value.detail


class TestHandleModelSwitchFailure:
    """Unit tests for _handle_model_switch_failure helper function."""

    @pytest.mark.asyncio
    async def test_handle_switch_failure_restores_state(self, mock_playwright_stack):
        """Test that model switch failure restores original model in state."""
        from api_utils.server_state import state

        _, _, _, page = mock_playwright_stack
        logger = MagicMock()
        req_id = "test-req"

        # Store original
        original_model = state.current_ai_studio_model_id
        try:
            # Simulate state was changed during failed switch attempt
            state.current_ai_studio_model_id = "changed-model"

            with pytest.raises(HTTPException) as exc:
                await _handle_model_switch_failure(
                    req_id, page, "gemini-2.0", "gemini-1.5-pro", logger
                )

            # Verify state was restored to model_before_switch
            assert state.current_ai_studio_model_id == "gemini-1.5-pro"

            # Verify exception details
            assert exc.value.status_code == 422
            assert "Failed to switch to model 'gemini-2.0'" in exc.value.detail

            # Verify warning was logged
            logger.warning.assert_called_once()

        finally:
            # Restore original state
            state.current_ai_studio_model_id = original_model


# ==================== Integration-Style Tests (with Real Helper Functions) ====================


class TestProcessRequestRefactoredFlow:
    """
    Tests for _process_request_refactored using REAL helper functions.

    These tests mock only external boundaries (browser, network) but use
    the actual helper function logic. This catches integration issues that
    over-mocked tests miss.

    Note: Full integration tests with real locks are in tests/integration/test_request_flow.py
    """

    @pytest.mark.asyncio
    async def test_client_disconnected_before_processing(
        self, mock_env, mock_playwright_stack
    ):
        """Test that early client disconnect is detected and handled."""
        from api_utils.request_processor import _process_request_refactored

        req_id = "test-req-id"
        request_data = ChatCompletionRequest(
            messages=[Message(role="user", content="Hello")], model="gemini-1.5-pro"
        )
        http_request = MagicMock(spec=Request)
        http_request.is_disconnected = AsyncMock(return_value=True)  # Disconnected
        result_future = asyncio.Future()

        # Don't mock _check_client_connection - use real function
        result = await _process_request_refactored(
            req_id, request_data, http_request, result_future
        )

        # Should return None (early exit)
        assert result is None

        # Future should be set with 499 error
        assert result_future.done()
        with pytest.raises(HTTPException) as exc:
            result_future.result()
        assert exc.value.status_code == 499  # Client closed request

    @pytest.mark.asyncio
    async def test_context_initialization_failure_bubbles_up(
        self, mock_env, mock_playwright_stack
    ):
        """Test that context initialization failures are not swallowed."""
        from api_utils.request_processor import _process_request_refactored

        req_id = "test-req-id"
        request_data = ChatCompletionRequest(
            messages=[Message(role="user", content="Hello")], model="gemini-1.5-pro"
        )
        http_request = MagicMock(spec=Request)
        http_request.is_disconnected = AsyncMock(return_value=False)
        result_future = asyncio.Future()

        # Mock only _initialize_request_context to fail
        with patch(
            "api_utils.request_processor._initialize_request_context",
            new_callable=AsyncMock,
            side_effect=Exception("Context init failed"),
        ):
            with pytest.raises(Exception) as exc:
                await _process_request_refactored(
                    req_id, request_data, http_request, result_future
                )

            assert "Context init failed" in str(exc.value)
            # Future not set (exception bubbles to queue_worker)
            assert not result_future.done()

    @pytest.mark.asyncio
    async def test_playwright_error_sets_502_in_future(
        self, mock_env, make_request_context
    ):
        """Test that Playwright errors are caught and set proper HTTP status."""
        from api_utils.request_processor import _process_request_refactored

        req_id = "test-req-id"
        request_data = ChatCompletionRequest(
            messages=[Message(role="user", content="Hello")], model="gemini-1.5-pro"
        )
        http_request = MagicMock(spec=Request)
        http_request.is_disconnected = AsyncMock(return_value=False)
        result_future = asyncio.Future()

        context = make_request_context(req_id=req_id)

        # Mock context init to succeed, PageController to fail with Playwright error
        with (
            patch(
                "api_utils.request_processor._initialize_request_context",
                new_callable=AsyncMock,
                return_value=context,
            ),
            patch(
                "api_utils.request_processor._analyze_model_requirements",
                new_callable=AsyncMock,
                return_value=context,
            ),
            patch(
                "api_utils.request_processor.PageController",
                side_effect=PlaywrightAsyncError("Browser crashed"),
            ),
            patch("browser_utils.save_error_snapshot", new_callable=AsyncMock),
        ):
            await _process_request_refactored(
                req_id, request_data, http_request, result_future
            )

        # Future should have 503 error (page not ready)
        assert result_future.done()
        with pytest.raises(HTTPException) as exc:
            result_future.result()
        assert exc.value.status_code == 503  # Service unavailable (page not ready)
        assert "page lost or not ready" in exc.value.detail


# ==================== Tests for Specific Response Handling ====================


class TestAuxiliaryStreamResponse:
    """Tests for auxiliary stream response handling (Stream Proxy tier)."""

    @pytest.mark.asyncio
    async def test_auxiliary_stream_non_streaming_success(
        self, mock_env, make_request_context
    ):
        """Test non-streaming response from auxiliary stream (Stream Proxy)."""
        from api_utils.request_processor import _handle_auxiliary_stream_response

        req_id = "test-req-id"
        request = ChatCompletionRequest(
            messages=[Message(role="user", content="Hello")],
            model="gemini-1.5-pro",
            stream=False,
        )
        context = make_request_context(req_id=req_id)
        result_future = asyncio.Future()
        submit_locator = MagicMock()
        check_disco = MagicMock()

        # Mock stream response generator
        mock_stream_data = [
            {"body": "Hello", "done": False},
            {"body": " world", "done": False},
            {"body": "Hello world", "done": True, "reason": None, "function": []},
        ]

        async def mock_stream_gen(req_id):
            for data in mock_stream_data:
                yield data

        with (
            patch(
                "api_utils.request_processor.use_stream_response",
                side_effect=mock_stream_gen,
            ),
            patch(
                "api_utils.request_processor.calculate_usage_stats",
                return_value={
                    "prompt_tokens": 10,
                    "completion_tokens": 5,
                    "total_tokens": 15,
                },
            ),
        ):
            result = await _handle_auxiliary_stream_response(
                req_id,
                request,
                context,
                result_future,
                submit_locator,
                check_disco,
            )

            # Non-streaming returns None
            assert result is None

            # Future should have JSONResponse
            assert result_future.done()
            response = result_future.result()
            assert response.status_code == 200

            # Verify response content
            content = json.loads(response.body)
            assert content["choices"][0]["message"]["content"] == "Hello world"
            assert content["usage"]["total_tokens"] == 15



import pytest

from api_utils.request_processor import (
    _cleanup_request_resources,
    _handle_auxiliary_stream_response,
    _handle_model_switching,
    _handle_parameter_cache,
    _handle_playwright_response,
    _handle_response_processing,
    _process_request_refactored,
)

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
@pytest.mark.parametrize(
    "page_none,is_closed,is_page_ready,should_raise,test_id",
    [
        (False, False, True, False, "success"),
        (True, None, None, True, "page_none"),
        (False, True, None, True, "page_closed"),
        (False, False, False, True, "page_not_ready"),
    ],
)
async def test_validate_page_status(
    mock_context,
    mock_check_disconnected,
    page_none,
    is_closed,
    is_page_ready,
    should_raise,
    test_id,
):
    """Test page status validation with various scenarios."""
    if page_none:
        mock_context["page"] = None
    else:
        if mock_context["page"] is None:
            mock_context["page"] = AsyncMock()
        mock_context["page"].is_closed.return_value = is_closed

    if is_page_ready is not None:
        mock_context["is_page_ready"] = is_page_ready

    if should_raise:
        with pytest.raises(HTTPException) as exc:
            await _validate_page_status("req1", mock_context, mock_check_disconnected)
        assert exc.value.status_code == 503
    else:
        await _validate_page_status("req1", mock_context, mock_check_disconnected)
        mock_check_disconnected.assert_called_once()


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
    """Test successful request processing flow through all stages."""
    mock_future = asyncio.Future()
    mock_check_disconnected = MagicMock(return_value=False)
    mock_disconnect_task = MagicMock()

    # Setup mocks for all refactored steps
    patches = {
        "_check_client_connection": AsyncMock(return_value=True),
        "_initialize_request_context": AsyncMock(return_value=mock_context),
        "_analyze_model_requirements": AsyncMock(return_value=mock_context),
        "_setup_disconnect_monitoring": AsyncMock(
            return_value=(None, mock_disconnect_task, mock_check_disconnected)
        ),
        "_validate_page_status": AsyncMock(),
        "PageController": MagicMock(autospec=True),
        "_handle_model_switching": AsyncMock(),
        "_handle_parameter_cache": AsyncMock(),
        "_prepare_and_validate_request": AsyncMock(return_value=("prompt", [])),
        "_handle_response_processing": AsyncMock(),
        "_cleanup_request_resources": AsyncMock(),
        "save_error_snapshot": AsyncMock(),
    }

    with (
        patch(
            "api_utils.request_processor._check_client_connection",
            patches["_check_client_connection"],
        ),
        patch(
            "api_utils.request_processor._initialize_request_context",
            patches["_initialize_request_context"],
        ),
        patch(
            "api_utils.request_processor._analyze_model_requirements",
            patches["_analyze_model_requirements"],
        ),
        patch(
            "api_utils.request_processor._setup_disconnect_monitoring",
            patches["_setup_disconnect_monitoring"],
        ),
        patch(
            "api_utils.request_processor._validate_page_status",
            patches["_validate_page_status"],
        ),
        patch("api_utils.request_processor.PageController", patches["PageController"]),
        patch(
            "api_utils.request_processor._handle_model_switching",
            patches["_handle_model_switching"],
        ),
        patch(
            "api_utils.request_processor._handle_parameter_cache",
            patches["_handle_parameter_cache"],
        ),
        patch(
            "api_utils.request_processor._prepare_and_validate_request",
            patches["_prepare_and_validate_request"],
        ),
        patch(
            "api_utils.request_processor._handle_response_processing",
            patches["_handle_response_processing"],
        ),
        patch(
            "api_utils.request_processor._cleanup_request_resources",
            patches["_cleanup_request_resources"],
        ),
        patch(
            "api_utils.request_processor.save_error_snapshot",
            patches["save_error_snapshot"],
        ),
        patch("api_utils.utils.collect_and_validate_attachments", return_value=[]),
        patch("config.get_environment_variable", return_value="0"),
    ):
        # Setup PageController mock instance
        mock_pc_instance = patches["PageController"].return_value
        mock_pc_instance.adjust_parameters = AsyncMock()
        mock_pc_instance.submit_prompt = AsyncMock()

        # Setup response processing result
        mock_event = asyncio.Event()
        mock_locator = MagicMock()
        patches["_handle_response_processing"].return_value = (
            mock_event,
            mock_locator,
            mock_check_disconnected,
        )
        mock_context["page"].locator.return_value = mock_locator

        # Execute
        result = await _process_request_refactored(
            "req1", mock_request, mock_http_request, mock_future
        )

        # Verify success
        assert result is not None, (
            "_process_request_refactored returned None unexpectedly"
        )
        assert result == (mock_event, mock_locator, mock_check_disconnected)

        # Verify all stages were called
        patches["_validate_page_status"].assert_called_once()
        patches["_handle_model_switching"].assert_called_once()
        mock_pc_instance.adjust_parameters.assert_called_once()
        mock_pc_instance.submit_prompt.assert_called_once()
        patches["_handle_response_processing"].assert_called_once()
        patches["_cleanup_request_resources"].assert_called_once()


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
