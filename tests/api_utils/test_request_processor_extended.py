import pytest
import asyncio
import json
import os
from unittest.mock import MagicMock, AsyncMock, patch, ANY
from fastapi import HTTPException, Request
from api_utils.request_processor import (
    _validate_page_status,
    _prepare_and_validate_request,
    _handle_auxiliary_stream_response,
    _cleanup_request_resources,
    _process_request_refactored,
    _handle_model_switch_failure
)
from models import ChatCompletionRequest, Message
from api_utils.context_types import RequestContext

@pytest.fixture
def mock_request_context():
    page = AsyncMock()
    page.locator = MagicMock()
    page.is_closed.return_value = False
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
async def test_validate_page_status_failure(mock_request_context):
    req_id = "test-req"
    check_disco = MagicMock()
    
    # Case 1: Page is None
    mock_request_context['page'] = None
    with pytest.raises(HTTPException) as exc:
        await _validate_page_status(req_id, mock_request_context, check_disco)
    assert exc.value.status_code == 503
    
    # Case 2: Page is closed
    mock_request_context['page'] = AsyncMock()
    mock_request_context['page'].is_closed.return_value = True
    with pytest.raises(HTTPException) as exc:
        await _validate_page_status(req_id, mock_request_context, check_disco)
    assert exc.value.status_code == 503

    # Case 3: Page not ready
    mock_request_context['page'].is_closed.return_value = False
    mock_request_context['is_page_ready'] = False
    with pytest.raises(HTTPException) as exc:
        await _validate_page_status(req_id, mock_request_context, check_disco)
    assert exc.value.status_code == 503

@pytest.mark.asyncio
async def test_prepare_and_validate_request_errors():
    req_id = "test-req"
    request = ChatCompletionRequest(messages=[Message(role="user", content="hi")])
    check_disco = MagicMock()
    
    # ValueError in validation
    with patch('api_utils.request_processor.validate_chat_request', side_effect=ValueError("Invalid")):
        with pytest.raises(HTTPException) as exc:
            await _prepare_and_validate_request(req_id, request, check_disco)
        assert exc.value.status_code == 400

@pytest.mark.asyncio
async def test_prepare_and_validate_request_mcp_and_tools():
    req_id = "test-req"
    request = ChatCompletionRequest(
        messages=[Message(role="user", content="hi")],
        tools=[{"type": "function", "function": {"name": "test"}}],
        mcp_endpoint="http://localhost:8080"
    )
    check_disco = MagicMock()
    
    with patch('api_utils.request_processor.validate_chat_request'), \
         patch('api_utils.request_processor.prepare_combined_prompt', return_value=("prompt", [])), \
         patch('api_utils.tools_registry.register_runtime_tools') as mock_register, \
         patch('api_utils.request_processor.maybe_execute_tools', new_callable=AsyncMock) as mock_exec:
        
        mock_exec.return_value = [{"name": "test", "arguments": "{}", "result": "ok"}]
        
        prompt, _ = await _prepare_and_validate_request(req_id, request, check_disco)
        
        mock_register.assert_called_once()
        assert "Tool Execution: test" in prompt

@pytest.mark.asyncio
async def test_prepare_and_validate_request_tool_exception():
    req_id = "test-req"
    request = ChatCompletionRequest(messages=[Message(role="user", content="hi")])
    check_disco = MagicMock()
    
    with patch('api_utils.request_processor.validate_chat_request'), \
         patch('api_utils.request_processor.prepare_combined_prompt', return_value=("prompt", [])), \
         patch('api_utils.request_processor.maybe_execute_tools', side_effect=Exception("Tool error")):
        
        prompt, _ = await _prepare_and_validate_request(req_id, request, check_disco)
        assert prompt == "prompt" # Should continue gracefully

@pytest.mark.asyncio
async def test_handle_auxiliary_stream_response_streaming_error(mock_request_context):
    req_id = "test-req"
    request = ChatCompletionRequest(messages=[Message(role="user", content="hi")], stream=True)
    result_future = asyncio.Future()
    submit_locator = MagicMock()
    check_disco = MagicMock()
    
    with patch('api_utils.request_processor.gen_sse_from_aux_stream', side_effect=Exception("Stream error")):
        with pytest.raises(Exception) as exc:
            await _handle_auxiliary_stream_response(
                req_id, request, mock_request_context, result_future, submit_locator, check_disco
            )
        assert "Stream error" in str(exc.value)

@pytest.mark.asyncio
async def test_handle_auxiliary_stream_response_non_stream_errors(mock_request_context):
    req_id = "test-req"
    request = ChatCompletionRequest(messages=[Message(role="user", content="hi")], stream=False)
    result_future = asyncio.Future()
    submit_locator = MagicMock()
    check_disco = MagicMock()
    
    # Mock stream data with various bad formats
    mock_data = [
        "invalid-json",
        {"not-done": True}, # Missing 'done'
        123, # Not dict or str
        json.dumps({"done": True, "reason": "internal_timeout"}),
    ]
    
    async def mock_gen(rid):
        for d in mock_data:
            yield d
            
    with patch('api_utils.request_processor.use_stream_response', side_effect=mock_gen):
        with pytest.raises(HTTPException) as exc:
            await _handle_auxiliary_stream_response(
                req_id, request, mock_request_context, result_future, submit_locator, check_disco
            )
        assert exc.value.status_code == 502
        assert "Internal Timeout" in exc.value.detail

@pytest.mark.asyncio
async def test_handle_auxiliary_stream_response_non_stream_empty_content(mock_request_context):
    req_id = "test-req"
    request = ChatCompletionRequest(messages=[Message(role="user", content="hi")], stream=False)
    result_future = asyncio.Future()
    submit_locator = MagicMock()
    check_disco = MagicMock()
    
    async def mock_gen(rid):
        yield {"done": True, "body": None}
            
    with patch('api_utils.request_processor.use_stream_response', side_effect=mock_gen):
        with pytest.raises(HTTPException) as exc:
            await _handle_auxiliary_stream_response(
                req_id, request, mock_request_context, result_future, submit_locator, check_disco
            )
        assert exc.value.status_code == 502
        assert "no content provided" in exc.value.detail

@pytest.mark.asyncio
async def test_handle_auxiliary_stream_response_function_calls(mock_request_context):
    req_id = "test-req"
    request = ChatCompletionRequest(messages=[Message(role="user", content="hi")], stream=False)
    result_future = asyncio.Future()
    submit_locator = MagicMock()
    check_disco = MagicMock()
    
    async def mock_gen(rid):
        yield {
            "done": True,
            "body": None,
            "function": [{"name": "fn", "params": {"a": 1}}],
            "reason": "reasoning"
        }
            
    with patch('api_utils.request_processor.use_stream_response', side_effect=mock_gen), \
         patch('api_utils.request_processor.calculate_usage_stats', return_value={}), \
         patch('api_utils.request_processor._random_id', return_value="mock-id"):
        
        # The function returns None, but sets the result on the future
        await _handle_auxiliary_stream_response(
            req_id, request, mock_request_context, result_future, submit_locator, check_disco
        )
        
        assert result_future.done()
        resp = result_future.result()
        content = json.loads(resp.body)
        assert content['choices'][0]['finish_reason'] == "tool_calls"
        assert content['choices'][0]['message']['tool_calls'][0]['function']['name'] == "fn"
        assert content['choices'][0]['message']['reasoning_content'] == "reasoning"

@pytest.mark.asyncio
async def test_cleanup_request_resources_errors():
    req_id = "test-req"
    task = asyncio.create_task(asyncio.sleep(0.1))
    event = asyncio.Event()
    future = asyncio.Future()
    future.set_exception(Exception("Test"))
    
    # Mock shutil.rmtree to raise exception
    with patch('shutil.rmtree', side_effect=Exception("Delete error")), \
         patch('api_utils.request_processor.UPLOAD_FILES_DIR', '/tmp/test'):
        
        await _cleanup_request_resources(req_id, task, event, future, True)
        
        assert task.cancelled()
        assert event.is_set() # Should be set because future has exception

@pytest.mark.asyncio
async def test_process_request_refactored_exceptions(mock_request_context):
    req_id = "test-req"
    request = ChatCompletionRequest(messages=[Message(role="user", content="hi")])
    http_req = MagicMock(spec=Request)
    future = asyncio.Future()
    
    # 1. ClientDisconnectedError
    with patch('api_utils.request_processor._check_client_connection', return_value=True), \
         patch('api_utils.request_processor._initialize_request_context', side_effect=Exception("Should not reach here if we mock earlier")), \
         patch('api_utils.request_processor._setup_disconnect_monitoring', side_effect=Exception("Should not reach here")):
         
         # We need to inject the exception deeper or mock a component to raise it
         pass

    # Let's test specific exception blocks by mocking the main flow
    with patch('api_utils.request_processor._check_client_connection', return_value=True), \
         patch('api_utils.request_processor._initialize_request_context', return_value=mock_request_context), \
         patch('api_utils.request_processor._analyze_model_requirements', return_value=mock_request_context), \
         patch('api_utils.request_processor._setup_disconnect_monitoring', return_value=(None, None, MagicMock())), \
         patch('api_utils.request_processor._validate_page_status', side_effect=HTTPException(status_code=418, detail="Teapot")):
        
        await _process_request_refactored(req_id, request, http_req, future)
        assert future.done()
        with pytest.raises(HTTPException) as exc:
            future.result()
        assert exc.value.status_code == 418

    # Unexpected Exception
    future = asyncio.Future()
    with patch('api_utils.request_processor._check_client_connection', return_value=True), \
         patch('api_utils.request_processor._initialize_request_context', side_effect=Exception("Unexpected")), \
         patch('browser_utils.save_error_snapshot', new_callable=AsyncMock):
        
        # Exception bubbles up because it happens before the try/except block
        with pytest.raises(Exception) as exc:
            await _process_request_refactored(req_id, request, http_req, future)
        assert "Unexpected" in str(exc.value)

@pytest.mark.asyncio
async def test_process_request_refactored_clear_queue_error(mock_request_context):
    req_id = "test-req"
    request = ChatCompletionRequest(messages=[Message(role="user", content="hi")])
    http_req = MagicMock(spec=Request)
    future = asyncio.Future()
    
    with patch('api_utils.request_processor._check_client_connection', return_value=True), \
         patch('config.get_environment_variable', return_value="3000"), \
         patch('api_utils.clear_stream_queue', side_effect=Exception("Queue error")), \
         patch('api_utils.request_processor._initialize_request_context', side_effect=HTTPException(status_code=400)): # Stop early
        
        # Should log warning but continue (until our forced stop)
        # It raises HTTPException because we mocked _initialize_request_context to raise it
        # This confirms it passed the clear_stream_queue step despite the error there
        with pytest.raises(HTTPException) as exc:
            await _process_request_refactored(req_id, request, http_req, future)
        assert exc.value.status_code == 400

@pytest.mark.asyncio
async def test_handle_model_switch_failure_logic():
    req_id = "test-req"
    page = AsyncMock()
    logger = MagicMock()
    
    # Mock server module
    mock_server = MagicMock()
    mock_server.current_ai_studio_model_id = "failed-model"
    
    with patch.dict('sys.modules', {'server': mock_server}):
        with pytest.raises(HTTPException) as exc:
            await _handle_model_switch_failure(req_id, page, "target", "original", logger)
        
        assert exc.value.status_code == 422
        assert mock_server.current_ai_studio_model_id == "original"
