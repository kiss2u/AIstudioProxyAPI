import pytest
import asyncio
import json
from unittest.mock import AsyncMock, Mock, patch
from asyncio import Event

from api_utils.response_generators import gen_sse_from_aux_stream, gen_sse_from_playwright
from models import ChatCompletionRequest, ClientDisconnectedError, Message

@pytest.fixture
def mock_request():
    return ChatCompletionRequest(
        messages=[Message(role="user", content="test")],
        model="test-model"
    )

@pytest.fixture
def mock_check_disconnected():
    return Mock()

@pytest.fixture
def mock_event():
    return Event()

@pytest.mark.asyncio
async def test_gen_sse_from_aux_stream_success(mock_request, mock_check_disconnected, mock_event):
    """Test successful SSE generation from auxiliary stream."""
    req_id = "test-req-id"
    model_name = "test-model"
    
    # Mock stream data
    stream_data = [
        json.dumps({"reason": "Thinking...", "body": "", "done": False}),
        json.dumps({"reason": "Thinking...", "body": "Hello", "done": False}),
        json.dumps({"reason": "Thinking...", "body": "Hello World", "done": True})
    ]
    
    async def mock_stream_generator(req_id):
        for data in stream_data:
            yield data
            
    with patch("api_utils.response_generators.use_stream_response", side_effect=mock_stream_generator):
        chunks = []
        async for chunk in gen_sse_from_aux_stream(
            req_id, mock_request, model_name, mock_check_disconnected, mock_event
        ):
            chunks.append(chunk)
            
        assert len(chunks) > 0
        assert mock_event.is_set()
        
        # Verify content in chunks
        content_found = False
        for chunk in chunks:
            if "Hello" in chunk:
                content_found = True
                break
        assert content_found

@pytest.mark.asyncio
async def test_gen_sse_from_aux_stream_client_disconnect(mock_request, mock_check_disconnected, mock_event):
    """Test handling of client disconnection during stream."""
    req_id = "test-req-id"
    model_name = "test-model"
    
    # Mock check_disconnected to raise error on second call
    mock_check_disconnected.side_effect = [None, ClientDisconnectedError("Disconnected")]
    
    async def mock_stream_generator(req_id):
        yield json.dumps({"body": "chunk1"})
        yield json.dumps({"body": "chunk2"})
            
    with patch("api_utils.response_generators.use_stream_response", side_effect=mock_stream_generator):
        chunks = []
        async for chunk in gen_sse_from_aux_stream(
            req_id, mock_request, model_name, mock_check_disconnected, mock_event
        ):
            chunks.append(chunk)
            
        # Should have stopped early and set event
        assert mock_event.is_set()

@pytest.mark.asyncio
async def test_gen_sse_from_aux_stream_json_error(mock_request, mock_check_disconnected, mock_event):
    """Test handling of invalid JSON in stream."""
    req_id = "test-req-id"
    model_name = "test-model"
    
    async def mock_stream_generator(req_id):
        yield "invalid-json"
        yield json.dumps({"body": "valid", "done": True})
            
    with patch("api_utils.response_generators.use_stream_response", side_effect=mock_stream_generator):
        chunks = []
        async for chunk in gen_sse_from_aux_stream(
            req_id, mock_request, model_name, mock_check_disconnected, mock_event
        ):
            chunks.append(chunk)
            
        assert len(chunks) > 0
        assert mock_event.is_set()

@pytest.mark.asyncio
async def test_gen_sse_from_aux_stream_tool_calls(mock_request, mock_check_disconnected, mock_event):
    """Test SSE generation with tool calls."""
    req_id = "test-req-id"
    model_name = "test-model"
    
    tool_data = {
        "body": "Calling tool",
        "done": True,
        "function": [{
            "name": "test_tool",
            "params": {"arg": "value"}
        }]
    }
    
    async def mock_stream_generator(req_id):
        yield json.dumps(tool_data)
            
    with patch("api_utils.response_generators.use_stream_response", side_effect=mock_stream_generator):
        chunks = []
        async for chunk in gen_sse_from_aux_stream(
            req_id, mock_request, model_name, mock_check_disconnected, mock_event
        ):
            chunks.append(chunk)
            
        # Verify tool call in chunks
        tool_call_found = False
        for chunk in chunks:
            if "tool_calls" in chunk and "test_tool" in chunk:
                tool_call_found = True
                break
        assert tool_call_found

@pytest.mark.asyncio
async def test_gen_sse_from_playwright_success(mock_request, mock_check_disconnected, mock_event):
    """Test successful SSE generation from Playwright."""
    req_id = "test-req-id"
    model_name = "test-model"
    mock_page = AsyncMock()
    mock_logger = Mock()
    
    # The PageController is imported inside the function, so we need to patch it where it's imported
    # or patch the class in the module where it's defined if it's imported directly.
    # In api_utils/response_generators.py: from browser_utils.page_controller import PageController
    with patch("browser_utils.page_controller.PageController") as MockController:
        mock_instance = MockController.return_value
        mock_instance.get_response = AsyncMock(return_value="Test response content")
        
        chunks = []
        async for chunk in gen_sse_from_playwright(
            mock_page, mock_logger, req_id, model_name, mock_request,
            mock_check_disconnected, mock_event
        ):
            chunks.append(chunk)
            
        assert len(chunks) > 0
        assert mock_event.is_set()
        
        # Verify content
        content_found = False
        for chunk in chunks:
            if "Test response content" in chunk or "Test" in chunk: # Chunked
                content_found = True
                break
        assert content_found

@pytest.mark.asyncio
async def test_gen_sse_from_playwright_disconnect(mock_request, mock_check_disconnected, mock_event):
    """Test client disconnect during Playwright generation."""
    req_id = "test-req-id"
    model_name = "test-model"
    mock_page = AsyncMock()
    mock_logger = Mock()
    
    # Mock check_disconnected to raise error
    mock_check_disconnected.side_effect = ClientDisconnectedError("Disconnected")
    
    with patch("browser_utils.page_controller.PageController") as MockController:
        mock_instance = MockController.return_value
        mock_instance.get_response = AsyncMock(return_value="Test response")
        
        chunks = []
        async for chunk in gen_sse_from_playwright(
            mock_page, mock_logger, req_id, model_name, mock_request,
            mock_check_disconnected, mock_event
        ):
            chunks.append(chunk)
            
        assert mock_event.is_set()

@pytest.mark.asyncio
async def test_gen_sse_from_playwright_error(mock_request, mock_check_disconnected, mock_event):
    """Test error handling in Playwright generation."""
    req_id = "test-req-id"
    model_name = "test-model"
    mock_page = AsyncMock()
    mock_logger = Mock()
    
    with patch("browser_utils.page_controller.PageController") as MockController:
        mock_instance = MockController.return_value
        mock_instance.get_response = AsyncMock(side_effect=Exception("Page error"))
        
        chunks = []
        async for chunk in gen_sse_from_playwright(
            mock_page, mock_logger, req_id, model_name, mock_request,
            mock_check_disconnected, mock_event
        ):
            chunks.append(chunk)
            
        # Should contain error message
        error_found = False
        for chunk in chunks:
            if "Page error" in chunk:
                error_found = True
                break
        assert error_found
        assert mock_event.is_set()