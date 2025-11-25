import pytest
from unittest.mock import MagicMock, patch, AsyncMock
from api_utils.utils import (
    _extract_json_from_text,
    _get_latest_user_text,
    maybe_execute_tools,
    generate_sse_stop_chunk_with_usage,
)
from models.chat import Message, MessageContentItem

def test_extract_json_from_text():
    """Test extracting JSON from text."""
    # Valid JSON
    text = 'Some text {"key": "value"} more text'
    assert _extract_json_from_text(text) == '{"key": "value"}'

    # Nested JSON
    text = 'Start {"outer": {"inner": 1}} End'
    assert _extract_json_from_text(text) == '{"outer": {"inner": 1}}'

    # Invalid JSON
    text = 'No JSON here'
    assert _extract_json_from_text(text) is None

    # Malformed JSON
    text = 'Start {key: value} End'
    assert _extract_json_from_text(text) is None

    # Empty text
    assert _extract_json_from_text("") is None

def test_get_latest_user_text():
    """Test getting latest user text from messages."""
    # Simple text message
    messages = [
        Message(role="system", content="sys"),
        Message(role="user", content="hello"),
        Message(role="assistant", content="hi"),
    ]
    assert _get_latest_user_text(messages) == "hello"

    # List content message
    item1 = MessageContentItem(type="text", text="part1")
    item2 = MessageContentItem(type="text", text="part2")
    messages = [
        Message(role="user", content=[item1, item2])
    ]
    assert _get_latest_user_text(messages) == "part1\npart2"

    # No user message
    messages = [Message(role="system", content="sys")]
    assert _get_latest_user_text(messages) == ""

@pytest.mark.asyncio
async def test_maybe_execute_tools():
    """Test maybe_execute_tools function."""
    # Mock execute_tool_call
    with patch("api_utils.utils.execute_tool_call", new_callable=AsyncMock) as mock_exec:
        mock_exec.return_value = "tool_result"
        
        # Case 1: Explicit tool choice
        messages = [Message(role="user", content='{"arg": 1}')]
        tools = [{"type": "function", "function": {"name": "test_tool"}}]
        tool_choice = {"type": "function", "function": {"name": "test_tool"}}
        
        result = await maybe_execute_tools(messages, tools, tool_choice)
        
        assert result is not None
        assert len(result) == 1
        assert result[0]["name"] == "test_tool"
        assert result[0]["result"] == "tool_result"
        mock_exec.assert_called_with("test_tool", '{"arg": 1}')

        # Case 2: Auto tool choice with single tool
        tool_choice = "auto"
        result = await maybe_execute_tools(messages, tools, tool_choice)
        assert result is not None
        assert result[0]["name"] == "test_tool"

        # Case 3: No tool choice
        tool_choice = None
        result = await maybe_execute_tools(messages, tools, tool_choice)
        assert result is None

        # Case 4: Tool role message exists (should not execute)
        messages_with_tool = [
            Message(role="user", content="call"),
            Message(role="tool", content="result")
        ]
        result = await maybe_execute_tools(messages_with_tool, tools, "auto")
        assert result is None

def test_generate_sse_stop_chunk_with_usage():
    """Test generating SSE stop chunk with usage."""
    req_id = "req_123"
    model = "gpt-4"
    usage = {"prompt_tokens": 10, "completion_tokens": 20, "total_tokens": 30}
    
    chunk = generate_sse_stop_chunk_with_usage(req_id, model, usage)
    assert "data: [DONE]" in chunk
    # Note: The exact format depends on generate_sse_stop_chunk implementation,
    # but we check it returns a string containing the stop signal.

def test_prepare_combined_prompt_basic():
    """Test prepare_combined_prompt with basic text messages."""
    from api_utils.utils import prepare_combined_prompt
    
    messages = [
        Message(role="system", content="System prompt"),
        Message(role="user", content="User message"),
        Message(role="assistant", content="Assistant response")
    ]
    
    prompt, files = prepare_combined_prompt(messages, "req_123")
    
    assert "System prompt" in prompt
    assert "User message" in prompt
    assert "Assistant response" in prompt
    assert len(files) == 0

def test_prepare_combined_prompt_with_tools():
    """Test prepare_combined_prompt with tools."""
    from api_utils.utils import prepare_combined_prompt
    
    messages = [Message(role="user", content="Help me")]
    tools = [{
        "type": "function",
        "function": {
            "name": "test_func",
            "parameters": {"type": "object"}
        }
    }]
    
    prompt, files = prepare_combined_prompt(messages, "req_123", tools=tools)
    
    assert "可用工具目录:" in prompt
    assert "test_func" in prompt
    assert len(files) == 0

def test_prepare_combined_prompt_multimodal():
    """Test prepare_combined_prompt with multimodal content."""
    from api_utils.utils import prepare_combined_prompt
    
    # Mock file system operations
    with patch("os.path.exists", return_value=True), \
         patch("api_utils.utils.extract_data_url_to_local", return_value="/tmp/image.png"):
        
        content = [
            {"type": "text", "text": "Look at this"},
            {"type": "image_url", "image_url": {"url": "data:image/png;base64,..."}}
        ]
        messages = [Message(role="user", content=content)]
        
        prompt, files = prepare_combined_prompt(messages, "req_123")
        
        assert "Look at this" in prompt
        assert len(files) == 1
        assert files[0] == "/tmp/image.png"

def test_prepare_combined_prompt_tool_calls():
    """Test prepare_combined_prompt with tool calls and results."""
    from api_utils.utils import prepare_combined_prompt
    from models.chat import ToolCall, FunctionCall
    
    tool_call = ToolCall(
        id="call_123",
        type="function",
        function=FunctionCall(name="test_func", arguments='{"arg": 1}')
    )
    
    messages = [
        Message(role="user", content="call tool"),
        Message(role="assistant", content=None, tool_calls=[tool_call]),
        Message(role="tool", content="result", tool_call_id="call_123")
    ]
    
    prompt, files = prepare_combined_prompt(messages, "req_123")
    
    assert "请求调用函数: test_func" in prompt
    # The formatting might vary slightly, so we check for key parts
    assert '"arg": 1' in prompt
    assert "工具结果 (tool_call_id=call_123):" in prompt
    assert "result" in prompt

def test_prepare_combined_prompt_tool_choice():
    """Test prepare_combined_prompt with tool_choice."""
    from api_utils.utils import prepare_combined_prompt
    
    messages = [Message(role="user", content="Help me")]
    tools = [{
        "type": "function",
        "function": {
            "name": "test_func",
            "parameters": {"type": "object"}
        }
    }]
    
    # Case 1: tool_choice as string
    prompt, _ = prepare_combined_prompt(messages, "req_123", tools=tools, tool_choice="test_func")
    assert "建议优先使用函数: test_func" in prompt
    
    # Case 2: tool_choice as dict
    prompt, _ = prepare_combined_prompt(messages, "req_123", tools=tools, tool_choice={"type": "function", "function": {"name": "test_func"}})
    assert "建议优先使用函数: test_func" in prompt

def test_prepare_combined_prompt_system_messages():
    """Test prepare_combined_prompt with multiple system messages."""
    from api_utils.utils import prepare_combined_prompt
    
    messages = [
        Message(role="system", content="System 1"),
        Message(role="user", content="User 1"),
        Message(role="system", content="System 2"), # Should be skipped
        Message(role="assistant", content="Assistant 1")
    ]
    
    prompt, _ = prepare_combined_prompt(messages, "req_123")
    
    assert "System 1" in prompt
    assert "System 2" not in prompt
    assert "User 1" in prompt
    assert "Assistant 1" in prompt

def test_prepare_combined_prompt_empty_content():
    """Test prepare_combined_prompt with empty content messages."""
    from api_utils.utils import prepare_combined_prompt
    
    messages = [
        Message(role="user", content=""),
        Message(role="assistant", content=None)
    ]
    
    prompt, _ = prepare_combined_prompt(messages, "req_123")
    
    # Should be empty or minimal
    assert len(prompt.strip()) == 0