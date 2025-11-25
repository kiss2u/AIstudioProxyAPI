import pytest
import asyncio
import json
import sys
from unittest.mock import MagicMock, AsyncMock, patch
from fastapi import HTTPException, Request
from api_utils.request_processor import _process_request_refactored
from models import ChatCompletionRequest, Message

@pytest.fixture
def mock_request_context():
    page = AsyncMock()
    page.locator = MagicMock()
    return {
        'logger': MagicMock(),
        'page': page,
        'is_page_ready': True,
        'parsed_model_list': [],
        'current_ai_studio_model_id': 'gemini-1.5-pro',
        'model_switching_lock': AsyncMock(),
        'page_params_cache': {},
        'params_cache_lock': AsyncMock(),
        'is_streaming': False,
        'model_actually_switched': False,
        'requested_model': 'gemini-1.5-pro',
        'model_id_to_use': 'gemini-1.5-pro',
        'needs_model_switching': False,
    }

@pytest.mark.asyncio
async def test_process_request_client_disconnected_early(mock_env):
    req_id = "test-req-id"
    request_data = ChatCompletionRequest(
        messages=[Message(role="user", content="Hello")],
        model="gemini-1.5-pro"
    )
    http_request = MagicMock(spec=Request)
    result_future = asyncio.Future()
    
    # Mock client disconnected
    with patch('api_utils.request_processor._check_client_connection', new_callable=AsyncMock) as mock_conn:
        mock_conn.return_value = False
        
        result = await _process_request_refactored(
            req_id, request_data, http_request, result_future
        )
        
        assert result is None
        assert result_future.done()
        with pytest.raises(HTTPException) as exc:
            result_future.result()
        assert exc.value.status_code == 499

@pytest.mark.asyncio
async def test_process_request_success_non_stream(mock_env, mock_request_context):
    req_id = "test-req-id"
    request_data = ChatCompletionRequest(
        messages=[Message(role="user", content="Hello")],
        model="gemini-1.5-pro",
        stream=False
    )
    http_request = MagicMock(spec=Request)
    result_future = asyncio.Future()
    
    # Mock dependencies
    with patch('api_utils.request_processor._check_client_connection', new_callable=AsyncMock) as mock_conn, \
         patch('api_utils.request_processor._initialize_request_context', new_callable=AsyncMock) as mock_init_ctx, \
         patch('api_utils.request_processor._analyze_model_requirements', new_callable=AsyncMock) as mock_analyze, \
         patch('api_utils.request_processor._setup_disconnect_monitoring', new_callable=AsyncMock) as mock_monitor, \
         patch('api_utils.request_processor._validate_page_status', new_callable=AsyncMock) as mock_validate, \
         patch('api_utils.request_processor.PageController') as MockPageController, \
         patch('api_utils.request_processor._handle_model_switching', new_callable=AsyncMock) as mock_switch, \
         patch('api_utils.request_processor._handle_parameter_cache', new_callable=AsyncMock) as mock_cache, \
         patch('api_utils.request_processor._prepare_and_validate_request', new_callable=AsyncMock) as mock_prep, \
         patch('api_utils.request_processor._handle_response_processing', new_callable=AsyncMock) as mock_resp, \
         patch('api_utils.request_processor._cleanup_request_resources', new_callable=AsyncMock) as mock_cleanup:
        
        mock_conn.return_value = True
        mock_init_ctx.return_value = mock_request_context
        mock_analyze.return_value = mock_request_context
        mock_check_disco = MagicMock()
        mock_monitor.return_value = (None, None, mock_check_disco)
        
        mock_controller_instance = MockPageController.return_value
        mock_controller_instance.adjust_parameters = AsyncMock()
        mock_controller_instance.submit_prompt = AsyncMock()
        
        mock_prep.return_value = ("Combined Prompt", [])
        mock_resp.return_value = None # Non-stream returns None
        
        result = await _process_request_refactored(
            req_id, request_data, http_request, result_future
        )
        
        # Non-stream returns (None, submit_locator, check_disco)
        assert isinstance(result, tuple)
        assert result[0] is None
        assert result[2] == mock_check_disco
        
        mock_controller_instance.submit_prompt.assert_called_once()
        mock_resp.assert_called_once()
        mock_cleanup.assert_called_once()

@pytest.mark.asyncio
async def test_process_request_success_stream(mock_env, mock_request_context):
    req_id = "test-req-id"
    request_data = ChatCompletionRequest(
        messages=[Message(role="user", content="Hello")],
        model="gemini-1.5-pro",
        stream=True
    )
    http_request = MagicMock(spec=Request)
    result_future = asyncio.Future()
    
    completion_event = asyncio.Event()
    submit_locator = MagicMock()
    check_disco = MagicMock()
    
    # Mock dependencies
    with patch('api_utils.request_processor._check_client_connection', new_callable=AsyncMock) as mock_conn, \
         patch('api_utils.request_processor._initialize_request_context', new_callable=AsyncMock) as mock_init_ctx, \
         patch('api_utils.request_processor._analyze_model_requirements', new_callable=AsyncMock) as mock_analyze, \
         patch('api_utils.request_processor._setup_disconnect_monitoring', new_callable=AsyncMock) as mock_monitor, \
         patch('api_utils.request_processor._validate_page_status', new_callable=AsyncMock) as mock_validate, \
         patch('api_utils.request_processor.PageController') as MockPageController, \
         patch('api_utils.request_processor._handle_model_switching', new_callable=AsyncMock) as mock_switch, \
         patch('api_utils.request_processor._handle_parameter_cache', new_callable=AsyncMock) as mock_cache, \
         patch('api_utils.request_processor._prepare_and_validate_request', new_callable=AsyncMock) as mock_prep, \
         patch('api_utils.request_processor._handle_response_processing', new_callable=AsyncMock) as mock_resp, \
         patch('api_utils.request_processor._cleanup_request_resources', new_callable=AsyncMock) as mock_cleanup, \
         patch('api_utils.clear_stream_queue', new_callable=AsyncMock) as mock_clear_queue:
        
        mock_conn.return_value = True
        mock_init_ctx.return_value = mock_request_context
        mock_analyze.return_value = mock_request_context
        mock_monitor.return_value = (None, None, check_disco)
        
        mock_controller_instance = MockPageController.return_value
        mock_controller_instance.adjust_parameters = AsyncMock()
        mock_controller_instance.submit_prompt = AsyncMock()
        
        # Ensure page.locator returns the expected submit_locator
        mock_request_context['page'].locator.return_value = submit_locator

        mock_prep.return_value = ("Combined Prompt", [])
        mock_resp.return_value = (completion_event, submit_locator, check_disco)
        
        # Mock STREAM_PORT to trigger clear_stream_queue
        with patch('config.get_environment_variable', return_value="3120"):
             result = await _process_request_refactored(
                req_id, request_data, http_request, result_future
            )
        
        # Assert tuple elements individually to avoid strict tuple comparison issues with mocks
        assert isinstance(result, tuple)
        assert len(result) == 3
        assert result[0] == completion_event
        assert result[1] == submit_locator
        assert result[2] == check_disco
        mock_clear_queue.assert_called_once()
        mock_controller_instance.submit_prompt.assert_called_once()
        mock_resp.assert_called_once()
        mock_cleanup.assert_called_once()

@pytest.mark.asyncio
async def test_process_request_context_init_failure(mock_env):
    req_id = "test-req-id"
    request_data = ChatCompletionRequest(
        messages=[Message(role="user", content="Hello")],
        model="gemini-1.5-pro"
    )
    http_request = MagicMock(spec=Request)
    result_future = asyncio.Future()
    
    with patch('api_utils.request_processor._check_client_connection', new_callable=AsyncMock) as mock_conn, \
         patch('api_utils.request_processor._initialize_request_context', new_callable=AsyncMock) as mock_init_ctx, \
         patch('api_utils.request_processor._cleanup_request_resources', new_callable=AsyncMock) as mock_cleanup:
        
        mock_conn.return_value = True
        mock_init_ctx.side_effect = Exception("Context init failed")
        
        # The exception should bubble up because _initialize_request_context is called before the try/except block
        with pytest.raises(Exception) as exc:
            await _process_request_refactored(
                req_id, request_data, http_request, result_future
            )
        assert "Context init failed" in str(exc.value)
        
        # Future is not set by _process_request_refactored in this case (handled by queue_worker)
        assert not result_future.done()
        # Cleanup is not called because it's in the finally block of the try that wasn't entered
        mock_cleanup.assert_not_called()

@pytest.mark.asyncio
async def test_process_request_playwright_error(mock_env, mock_request_context):
    req_id = "test-req-id"
    request_data = ChatCompletionRequest(
        messages=[Message(role="user", content="Hello")],
        model="gemini-1.5-pro"
    )
    http_request = MagicMock(spec=Request)
    result_future = asyncio.Future()
    
    with patch('api_utils.request_processor._check_client_connection', new_callable=AsyncMock) as mock_conn, \
         patch('api_utils.request_processor._initialize_request_context', new_callable=AsyncMock) as mock_init_ctx, \
         patch('api_utils.request_processor._analyze_model_requirements', new_callable=AsyncMock) as mock_analyze, \
         patch('api_utils.request_processor._setup_disconnect_monitoring', new_callable=AsyncMock) as mock_monitor, \
         patch('api_utils.request_processor._validate_page_status', new_callable=AsyncMock) as mock_validate, \
         patch('api_utils.request_processor.PageController') as MockPageController, \
         patch('api_utils.request_processor._cleanup_request_resources', new_callable=AsyncMock) as mock_cleanup, \
         patch('browser_utils.save_error_snapshot', new_callable=AsyncMock):
        
        mock_conn.return_value = True
        mock_init_ctx.return_value = mock_request_context
        mock_analyze.return_value = mock_request_context
        mock_monitor.return_value = (None, None, MagicMock())
        
        # Simulate Playwright error during PageController init or usage
        from playwright.async_api import Error as PlaywrightAsyncError
        MockPageController.side_effect = PlaywrightAsyncError("Browser crashed")
        
        await _process_request_refactored(
            req_id, request_data, http_request, result_future
        )
        
        assert result_future.done()
        with pytest.raises(HTTPException) as exc:
            result_future.result()
        assert exc.value.status_code == 502
        assert "Playwright interaction failed" in exc.value.detail
        mock_cleanup.assert_called_once()

@pytest.mark.asyncio
async def test_handle_auxiliary_stream_response_non_stream_success(mock_env, mock_request_context):
    req_id = "test-req-id"
    request_data = ChatCompletionRequest(
        messages=[Message(role="user", content="Hello")],
        model="gemini-1.5-pro",
        stream=False
    )
    result_future = asyncio.Future()
    submit_locator = MagicMock()
    check_disco = MagicMock()
    
    # Mock use_stream_response to yield data
    mock_stream_data = [
        {"body": "Hello", "done": False},
        {"body": " world", "done": False},
        {"body": "Hello world", "done": True, "reason": None, "function": []}
    ]
    
    async def mock_stream_gen(req_id):
        for data in mock_stream_data:
            yield data

    with patch('api_utils.request_processor.use_stream_response', side_effect=mock_stream_gen), \
         patch('api_utils.request_processor.calculate_usage_stats') as mock_usage:
        
        mock_usage.return_value = {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}
        
        from api_utils.request_processor import _handle_auxiliary_stream_response
        
        result = await _handle_auxiliary_stream_response(
            req_id, request_data, mock_request_context, result_future, submit_locator, check_disco
        )
        
        assert result is None
        assert result_future.done()
        response = result_future.result()
        assert response.status_code == 200
        content = json.loads(response.body)
        assert content['choices'][0]['message']['content'] == "Hello world"

@pytest.mark.asyncio
async def test_prepare_and_validate_request_with_tools(mock_env):
    req_id = "test-req-id"
    request_data = ChatCompletionRequest(
        messages=[Message(role="user", content="Calculate 2+2")],
        model="gemini-1.5-pro",
        tools=[{"type": "function", "function": {"name": "calculator"}}]
    )
    check_disco = MagicMock()
    
    with patch('api_utils.request_processor.validate_chat_request'), \
         patch('api_utils.request_processor.prepare_combined_prompt', return_value=("Prompt", [])), \
         patch('api_utils.request_processor.maybe_execute_tools', new_callable=AsyncMock) as mock_exec_tools:
        
        mock_exec_tools.return_value = [{
            "name": "calculator",
            "arguments": "2+2",
            "result": "4"
        }]
        
        from api_utils.request_processor import _prepare_and_validate_request
        
        prompt, images = await _prepare_and_validate_request(req_id, request_data, check_disco)
        
        assert "Tool Execution: calculator" in prompt
        assert "Result:\n4" in prompt

@pytest.mark.asyncio
async def test_prepare_and_validate_request_attachments(mock_env):
    req_id = "test-req-id"
    request_data = ChatCompletionRequest(
        messages=[Message(role="user", content="Look at this", attachments=["file:///tmp/test.png"])],
        model="gemini-1.5-pro"
    )
    check_disco = MagicMock()
    
    with patch('api_utils.request_processor.validate_chat_request'), \
         patch('api_utils.request_processor.prepare_combined_prompt', return_value=("Prompt", [])), \
         patch('api_utils.request_processor.maybe_execute_tools', return_value=None), \
         patch('os.path.exists', return_value=True), \
         patch('api_utils.request_processor.ONLY_COLLECT_CURRENT_USER_ATTACHMENTS', True):
        
        from api_utils.request_processor import _prepare_and_validate_request
        
        prompt, images = await _prepare_and_validate_request(req_id, request_data, check_disco)
        
        # Note: The implementation uses urllib.parse.unquote which might handle windows paths differently
        # but here we mocked os.path.exists to True.
        # The logic extracts path from file URL.
        assert len(images) == 1
        assert "test.png" in images[0]

@pytest.mark.asyncio
async def test_handle_model_switch_failure():
    req_id = "test-req-id"
    page = AsyncMock()
    logger = MagicMock()
    
    mock_server = MagicMock()
    mock_server.current_ai_studio_model_id = 'changed'
    
    with patch.dict('sys.modules', {'server': mock_server}):
        from api_utils.request_processor import _handle_model_switch_failure
        
        with pytest.raises(HTTPException) as exc:
            await _handle_model_switch_failure(req_id, page, "new-model", "old-model", logger)
        
        assert exc.value.status_code == 422
        assert mock_server.current_ai_studio_model_id == 'old-model'