"""
Coverage tests for stream/interceptors.py - Exception paths

Targets:
- Lines 78-79: process_response exception handler
- Lines 98-99: parse_response json.loads exception
- Lines 139-140: parse_toolcall_params exception handler
- Line 177: _decode_chunked final break condition
"""

import json
from unittest.mock import MagicMock, patch

import pytest

from stream.interceptors import HttpInterceptor


class TestInterceptorExceptionPaths:
    @pytest.fixture
    def interceptor(self):
        return HttpInterceptor()

    @pytest.mark.asyncio
    async def test_process_response_raises_exception(self, interceptor):
        """
        测试场景: process_response 内部方法抛出异常
        预期: 异常被重新抛出 (lines 78-79)
        """
        # Mock _decode_chunked to raise exception
        with patch.object(
            interceptor,
            "_decode_chunked",
            side_effect=ValueError("Decoding failed"),
        ):
            with pytest.raises(ValueError, match="Decoding failed"):
                await interceptor.process_response(b"data", "host", "/path", {})

    def test_parse_response_invalid_json(self, interceptor):
        """
        测试场景: 正则匹配成功但 JSON 解析失败
        预期: 捕获异常并 continue (lines 98-99)
        """
        # Create data that matches regex but has invalid JSON
        # Pattern: rb'\[\[\[null,.*?]],"model"]'
        # Valid match format but invalid JSON inside
        invalid_match = b'[[[null,"unclosed string]],"model"]'

        result = interceptor.parse_response(invalid_match)

        # Should skip invalid match and return empty result
        assert result["body"] == ""
        assert result["reason"] == ""
        assert result["function"] == []

    def test_parse_toolcall_params_exception(self, interceptor):
        """
        测试场景: parse_toolcall_params 解析参数时抛出异常
        预期: 异常被重新抛出 (lines 139-140)
        """
        # Pass malformed args that cause exception during parsing
        # Expected structure: [[param1, param2, ...]]
        # Malformed: missing nested list
        malformed_args = None  # This will cause args[0] to raise TypeError

        with pytest.raises(TypeError):
            interceptor.parse_toolcall_params(malformed_args)

    def test_decode_chunked_final_break(self):
        """
        测试场景: _decode_chunked 在最后的 break 条件下退出
        预期: 覆盖 line 177 的 break 语句
        """
        # Create chunked data where:
        # length_crlf_idx + 2 + length + 2 > len(response_body)
        # This happens when we have a chunk header but incomplete trailing CRLF

        chunk_data = b"Hello"
        # Format: hex_length\r\ndata
        # Missing trailing \r\n after data
        data = hex(len(chunk_data))[2:].encode() + b"\r\n" + chunk_data

        # This should trigger the break at line 177
        # because after reading the chunk, there's no trailing CRLF
        decoded, is_done = HttpInterceptor._decode_chunked(data)

        # Should have decoded the chunk but not be done
        assert decoded == b"Hello"
        assert is_done is False


class TestInterceptorEdgeCases:
    @pytest.fixture
    def interceptor(self):
        return HttpInterceptor()

    def test_parse_response_malformed_payload_access(self, interceptor):
        """
        测试场景: payload 访问时出现 IndexError
        预期: 异常被捕获,继续处理 (lines 98-99)
        """
        # Create valid JSON but with unexpected structure
        # This will pass json.loads but fail on payload access
        malformed_json = json.dumps([[[]]])  # Missing expected payload structure
        match_str = f'[[{malformed_json}],"model"]'

        result = interceptor.parse_response(match_str.encode())

        # Should handle gracefully and return empty result
        assert result["body"] == ""
        assert result["reason"] == ""
        assert result["function"] == []

    def test_parse_toolcall_params_index_error(self, interceptor):
        """
        测试场景: parse_toolcall_params 访问 args[0] 时出现 IndexError
        预期: 异常被重新抛出 (lines 139-140)
        """
        # Pass empty list (args[0] will raise IndexError)
        with pytest.raises(IndexError):
            interceptor.parse_toolcall_params([])
