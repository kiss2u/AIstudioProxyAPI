"""
High-quality tests for stream/interceptors.py - Edge cases and exception paths.

Focus: Hit uncovered lines (62-64, 78-79, 98-99, 139-140, 177) with targeted tests.
Strategy: Trigger exception paths and boundary conditions not covered by main test file.
"""

import json
import zlib

import pytest

from stream.interceptors import HttpInterceptor


class TestHttpInterceptorEdgeCases:
    @pytest.fixture
    def interceptor(self):
        return HttpInterceptor()

    @pytest.mark.asyncio
    async def test_process_response_raises_on_invalid_chunking(self, interceptor):
        """
        测试场景: process_response 遇到无效的分块数据时抛出异常
        预期: 异常被重新抛出 (lines 78-79)
        """
        # 创建看起来像有效分块但会导致解压失败的数据
        # _decode_chunked 会处理它,但 _decompress_zlib_stream 会失败
        fake_chunk = b"not compressed data"
        chunked = (
            hex(len(fake_chunk))[2:].encode()
            + b"\r\n"
            + fake_chunk
            + b"\r\n"
            + b"0\r\n\r\n"
        )

        # _decompress_zlib_stream 会因为不是有效的 zlib 数据而抛出异常
        with pytest.raises(zlib.error):
            await interceptor.process_response(
                chunked, "example.com", "/GenerateContent", {}
            )

    @pytest.mark.asyncio
    async def test_process_response_raises_on_decompression_error(self, interceptor):
        """
        测试场景: 解压缩失败时抛出异常
        预期: zlib.error 被重新抛出 (lines 78-79)
        """
        # 创建有效的分块数据,但压缩数据是无效的
        invalid_compressed = b"not a valid zlib stream"
        chunked = (
            hex(len(invalid_compressed))[2:].encode()
            + b"\r\n"
            + invalid_compressed
            + b"\r\n"
            + b"0\r\n\r\n"
        )

        with pytest.raises(zlib.error):
            await interceptor.process_response(
                chunked, "example.com", "/GenerateContent", {}
            )

    def test_parse_response_with_malformed_json(self, interceptor):
        """
        测试场景: 正则匹配到的数据不是有效的 JSON
        预期: json.loads 失败,continue 跳过 (lines 98-99)
        """
        # 创建符合正则的字符串,但 JSON 格式错误
        # 正则: rb'\[\[\[null,.*?]],"model"]'
        # 需要匹配模式但 JSON 无效: [[[null,{invalid}]],"model"]
        malformed_match = b'[[[null,{not valid json}]],"model"]'  # 格式错误的 JSON
        valid_match = b'[[[null,"valid"]],"model"]'

        # 组合数据: 先是错误的,后是正确的
        data = malformed_match + valid_match

        result = interceptor.parse_response(data)

        # 只应解析出有效的部分
        assert result["body"] == "valid"
        # 错误的 JSON 应该被跳过,不影响结果

    def test_parse_response_with_multiple_malformed_json(self, interceptor):
        """
        测试场景: 所有匹配都是无效 JSON
        预期: 返回空结果 (lines 98-99 全部 continue)
        """
        # 多个符合正则但 JSON 无效的字符串
        malformed1 = b'[[[null,invalid}]],"model"]'  # 不是 JSON
        malformed2 = b'[[[null,{broken],"model"]'  # 格式错误

        data = malformed1 + malformed2

        result = interceptor.parse_response(data)

        # 所有都被跳过,返回空值
        assert result["body"] == ""
        assert result["reason"] == ""
        assert result["function"] == []

    def test_parse_toolcall_params_with_invalid_structure(self, interceptor):
        """
        测试场景: parse_toolcall_params 遇到无效参数结构
        预期: 抛出异常 (lines 139-140)
        """
        # 传入格式错误的 args (期望是嵌套列表,但只给字符串)
        invalid_args = "not a list"

        with pytest.raises(Exception):
            interceptor.parse_toolcall_params(invalid_args)

    def test_parse_toolcall_params_with_malformed_nested_structure(self, interceptor):
        """
        测试场景: 嵌套对象参数格式错误
        预期: 递归调用时抛出异常 (lines 139-140)
        """
        # 外层格式正确,但嵌套对象的参数格式错误
        malformed_args = [
            [
                [
                    "p_obj",
                    [1, 2, 3, 4, "should be list not string"],  # 第5个元素应该是列表
                ]
            ]
        ]

        with pytest.raises(Exception):
            interceptor.parse_toolcall_params(malformed_args)

    def test_parse_toolcall_params_with_index_error(self, interceptor):
        """
        测试场景: 参数列表索引越界
        预期: IndexError 被抛出 (lines 139-140)
        """
        # args[0] 期望是参数列表,但 args 为空
        invalid_args = []

        with pytest.raises(Exception):
            interceptor.parse_toolcall_params(invalid_args)

    def test_decode_chunked_edge_case_truncated_end(self):
        """
        测试场景: 分块数据在末尾被截断 (line 177)
        预期: 检测到 length_crlf_idx + 2 + length + 2 > len(response_body), break
        """
        # 创建一个完整的块,但最后的 \r\n 被截断
        chunk = b"Hello"
        length_hex = hex(len(chunk))[2:].encode()

        # 正常应该是: length_hex + \r\n + chunk + \r\n
        # 但我们只提供到 chunk 结尾,缺少最后的 \r\n
        data = length_hex + b"\r\n" + chunk  # 缺少最后的 \r\n

        decoded, is_done = HttpInterceptor._decode_chunked(data)

        # 应该解析出 Hello, 但 is_done 为 False (因为没有遇到 0\r\n\r\n)
        assert decoded == b"Hello"
        assert is_done is False

    def test_decode_chunked_edge_case_partial_final_chunk(self):
        """
        测试场景: 最后一个块的数据不完整 (line 177)
        预期: length + 2 > len(response_body), break
        """
        # 声明一个10字节的块,但只提供5字节数据
        declared_length = 10
        actual_data = b"12345"  # 只有5字节

        data = (
            hex(declared_length)[2:].encode() + b"\r\n" + actual_data
        )  # 没有后续的 \r\n 和数据

        decoded, is_done = HttpInterceptor._decode_chunked(data)

        # 因为 length(10) + 2 > len(response_body), 会在 line 170-171 break
        assert decoded == b""
        assert is_done is False

    def test_decode_chunked_zero_length_chunk_without_final_marker(self):
        """
        测试场景: 遇到 0 长度块但没有 0\r\n\r\n 标记
        预期: 返回 chunked_data, is_done=False
        """
        # 正常的零长度块应该是 0\r\n\r\n
        # 但这里只有 0\r\n (缺少后续的 \r\n)
        data = b"0\r\n"

        decoded, is_done = HttpInterceptor._decode_chunked(data)

        # 应该识别到 length=0, 但没找到 0\r\n\r\n, 所以 is_done=False
        assert decoded == b""
        assert is_done is False

    def test_decode_chunked_multiple_chunks_with_truncation(self):
        """
        测试场景: 多个块,最后一个被截断 (line 177)
        预期: 前面的块被解析,最后一个被丢弃
        """
        chunk1 = b"First"
        chunk2 = b"Second"

        # 第一个块完整
        data = hex(len(chunk1))[2:].encode() + b"\r\n" + chunk1 + b"\r\n"

        # 第二个块声明了长度,但数据不完整
        data += hex(len(chunk2))[2:].encode() + b"\r\n" + b"Sec"  # 只有3字节,不是6

        decoded, is_done = HttpInterceptor._decode_chunked(data)

        # 第一个块应该被解析
        assert decoded == b"First"
        # 第二个块因为数据不足而被跳过
        assert is_done is False

    def test_decode_chunked_chunk_exactly_at_buffer_end(self):
        """
        测试场景: 块数据正好到缓冲区末尾,没有结束标记
        预期: 解析块,但 is_done=False
        """
        chunk = b"Exact"
        data = hex(len(chunk))[2:].encode() + b"\r\n" + chunk + b"\r\n"

        # 没有 0\r\n\r\n 结束标记
        decoded, is_done = HttpInterceptor._decode_chunked(data)

        assert decoded == b"Exact"
        assert is_done is False

    @pytest.mark.asyncio
    async def test_process_request_with_non_intercepted_path(self, interceptor):
        """
        测试场景: 请求路径不应被拦截
        预期: 直接返回原始数据,不进入 try-except 块
        """
        data = b"regular request data"
        result = await interceptor.process_request(data, "example.com", "/api/other")

        assert result == data

    @pytest.mark.asyncio
    async def test_process_request_with_intercepted_path_returns_data(
        self, interceptor
    ):
        """
        测试场景: 拦截路径的请求正常处理
        预期: 返回原始数据 (try 块执行)
        """
        data = b'{"key": "value"}'
        result = await interceptor.process_request(
            data, "example.com", "/GenerateContent"
        )

        assert result == data

    def test_parse_response_with_json_array_parsing_error(self, interceptor):
        """
        测试场景: JSON 解析成功但结构不符合预期 (json_data[0][0] 索引失败)
        预期: except 捕获 IndexError/TypeError, continue
        """
        # 符合正则,但结构不对: json_data 不是预期的嵌套结构
        invalid_structure = b'[[],"model"]'  # json_data[0][0] 会失败

        result = interceptor.parse_response(invalid_structure)

        # 应该被跳过,返回空值
        assert result["body"] == ""

    def test_parse_response_empty_matches(self, interceptor):
        """
        测试场景: 没有符合正则的数据
        预期: 返回空结果
        """
        data = b"no matching pattern here"

        result = interceptor.parse_response(data)

        assert result["body"] == ""
        assert result["reason"] == ""
        assert result["function"] == []
