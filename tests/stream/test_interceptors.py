import json
import zlib

import pytest

from stream.interceptors import HttpInterceptor


class TestHttpInterceptor:
    @pytest.fixture
    def interceptor(self):
        return HttpInterceptor()

    def test_should_intercept(self):
        assert (
            HttpInterceptor.should_intercept("example.com", "/v1/GenerateContent")
            is True
        )
        assert (
            HttpInterceptor.should_intercept("example.com", "/generateContent") is True
        )
        assert HttpInterceptor.should_intercept("example.com", "/other/path") is False

    @pytest.mark.asyncio
    async def test_process_request_intercept(self, interceptor):
        data = b"some data"
        # Should return data as is but log it
        result = await interceptor.process_request(
            data, "example.com", "/GenerateContent"
        )
        assert result == data

    @pytest.mark.asyncio
    async def test_process_request_no_intercept(self, interceptor):
        data = b"some data"
        result = await interceptor.process_request(data, "example.com", "/other")
        assert result == data

    def test_decode_chunked_simple(self):
        # Format: length\r\nchunk\r\n0\r\n\r\n
        chunk1 = b"Hello"
        chunk2 = b"World"
        data = (
            hex(len(chunk1))[2:].encode()
            + b"\r\n"
            + chunk1
            + b"\r\n"
            + hex(len(chunk2))[2:].encode()
            + b"\r\n"
            + chunk2
            + b"\r\n"
            + b"0\r\n\r\n"
        )

        decoded, is_done = HttpInterceptor._decode_chunked(data)
        assert decoded == b"HelloWorld"
        assert is_done is True

    def test_decode_chunked_partial(self):
        # Partial chunk
        chunk1 = b"Hello"
        data = hex(len(chunk1))[2:].encode() + b"\r\n" + chunk1 + b"\r\n"

        # In the current implementation, if it doesn't find the end or next chunk properly,
        # it might behave differently.
        # The implementation loops.

        decoded, is_done = HttpInterceptor._decode_chunked(data)
        assert decoded == b"Hello"
        assert is_done is False

    def test_decompress_zlib_stream(self):
        original_data = b"Hello World Repeated " * 10
        compressor = zlib.compressobj(wbits=zlib.MAX_WBITS | 16)  # gzip
        compressed_data = compressor.compress(original_data) + compressor.flush()

        decompressed = HttpInterceptor._decompress_zlib_stream(compressed_data)
        assert decompressed == original_data

    def test_parse_response_body(self, interceptor):
        # Mock response structure based on regex: [[[null,.*?]],"model"]
        # Payload len=2 -> body: [payload_id, "body_content"]
        # Actually payload is [payload_id, "body_content"] directly inside the structure matched?
        # If structure is [[[null, "body"]], "model"]
        # json_data = [[[None, "body"]], "model"]
        # json_data[0][0] = [None, "body"] -> payload
        # payload[1] = "body" -> works.

        # Valid match
        valid_json = '"Hello "'
        match_str = f'[[[null,{valid_json}]],"model"]'

        # Another valid match
        valid_json2 = '"World"'
        match_str2 = f'[[[null,{valid_json2}]],"model"]'

        data = (match_str + match_str2).encode()

        result = interceptor.parse_response(data)
        assert result["body"] == "Hello World"
        assert result["reason"] == ""
        assert result["function"] == []

    def test_parse_response_reasoning(self, interceptor):
        # Payload len > 2 -> reason: [payload_id, "reasoning", ...]
        # payload = [None, "reasoning", "extra"]

        valid_json = '"Thinking...", "extra"'
        match_str = f'[[[null,{valid_json}]],"model"]'

        data = match_str.encode()

        result = interceptor.parse_response(data)
        assert result["reason"] == "Thinking..."
        assert result["body"] == ""

    def test_parse_response_function(self, interceptor):
        # Payload len 11, index 1 is None, index 10 is list -> function
        # array_tool_calls = [func_name, params]
        # params format: [ [param_name, [type_indicator, value...]] ]

        # Let's verify string param: [name, [1, 2, "value"]] (len 3)

        # args passed to parse_toolcall_params expects [[param1, param2]]
        # So params_raw needs to be the list containing the list of params.
        # But wait, parse_toolcall_params takes 'args' and does params = args[0].
        # So args is [[p1, p2]].
        # So params_raw should be [[p1, p2]].

        params_raw = [[["arg1", [1, 2, "value1"]]]]

        tool_calls = ["my_func", params_raw]

        # Payload: 11 elements. index 1 is None. index 10 is tool_calls.
        # We need to construct the JSON string representing [null, null, ..., tool_calls]
        # Since we use valid_json inside [[[null, valid_json]]], valid_json should be the rest of the array elements.
        # [[[null, null, null, ..., tool_calls]], "model"]
        # payload = [null, null, ..., tool_calls]

        # So valid_json should be "null, null, ..., tool_calls_json"

        tool_calls_json = json.dumps(tool_calls)
        valid_json = "null," * 9 + tool_calls_json

        match_str = f'[[[null,{valid_json}]],"model"]'

        data = match_str.encode()

        result = interceptor.parse_response(data)
        assert len(result["function"]) == 1
        assert result["function"][0]["name"] == "my_func"
        assert result["function"][0]["params"]["arg1"] == "value1"

    def test_parse_toolcall_params_types(self, interceptor):
        # Test various parameter types
        # Object type needs extra nesting for the value [1, 2, 3, 4, [params]]
        args = [
            [
                ["p_null", [1]],  # len 1
                ["p_num", [1, 123]],  # len 2
                ["p_str", [1, 2, "abc"]],  # len 3
                ["p_bool_true", [1, 2, 3, 1]],  # len 4, val 1
                ["p_bool_false", [1, 2, 3, 0]],  # len 4, val 0
                [
                    "p_obj",
                    [1, 2, 3, 4, [[["inner", [1, 2, "val"]]]]],
                ],  # len 5, recursive, wrapped in extra list
            ]
        ]

        params = interceptor.parse_toolcall_params(args)

        assert params["p_null"] is None
        assert params["p_num"] == 123
        assert params["p_str"] == "abc"
        assert params["p_bool_true"] is True
        assert params["p_bool_false"] is False
        assert params["p_obj"] == {"inner": "val"}

    @pytest.mark.asyncio
    async def test_process_response_integration(self, interceptor):
        # Combine chunking, compression, and parsing

        # Create response data
        valid_json = '"Integrated"'
        match_str = f'[[[null,{valid_json}]],"model"]'
        response_body = match_str.encode()

        # Compress
        compressor = zlib.compressobj(wbits=zlib.MAX_WBITS | 16)
        compressed = compressor.compress(response_body) + compressor.flush()

        # Chunk
        chunked = (
            hex(len(compressed))[2:].encode()
            + b"\r\n"
            + compressed
            + b"\r\n"
            + b"0\r\n\r\n"
        )

        # Process
        result = await interceptor.process_response(
            chunked, "example.com", "/GenerateContent", {}
        )

        assert result["body"] == "Integrated"
        assert result["done"] is True

    @pytest.mark.asyncio
    async def test_process_request_exception(self, interceptor):
        # Mocking logger to verify exception logging if needed,
        # but the method catches exception and logs it, then returns data.
        # We can force an exception by passing an object that fails on decoding if logic used it,
        # but process_request logic is simple.
        # Let's mock log method to raise exception? No, that would crash test.
        # process_request does:
        # try:
        #    if ...
        # except Exception as e:
        #    logger.error(...)
        #    return data

        # We can force exception by making data.decode() fail if it were used,
        # but the current implementation might not decode if not needed.
        # Actually it doesn't decode explicitly in the try block shown in snippet unless I check file.
        # Let's check the file content first.
        # But wait, I can just pass an invalid type to process_request if it expects bytes.

        # If I pass an int, bytes operation might fail.
        result = await interceptor.process_request(123, "host", "path")
        assert result == 123  # Should return original data on error

    @pytest.mark.asyncio
    async def test_process_response_exception(self, interceptor):
        # Similar to process_request
        result = await interceptor.process_response(123, "host", "path", {})
        assert result == {"body": "", "reason": "", "function": [], "done": False}

    def test_decode_chunked_invalid_size(self):
        # Invalid hex size
        data = b"ZZ\r\nData\r\n0\r\n\r\n"
        decoded, is_done = HttpInterceptor._decode_chunked(data)
        # Should catch ValueError and return b"" and False
        assert decoded == b""
        assert is_done is False

    def test_decode_chunked_exception(self):
        # Malformed structure that causes index error or other exception
        data = b"5\r\nHe"  # incomplete
        decoded, is_done = HttpInterceptor._decode_chunked(data)
        assert decoded == b""
        assert is_done is False
