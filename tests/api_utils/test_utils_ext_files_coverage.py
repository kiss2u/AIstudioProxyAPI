"""
Extended tests for api_utils/utils_ext/files.py - Final coverage completion.

Focus: Cover lines 78-80 (IOError in extract_data_url_to_local),
       107-108 (file exists in save_blob_to_local),
       114-116 (IOError in save_blob_to_local).
Strategy: Mock file operations to trigger error paths.
"""

import base64
from unittest.mock import mock_open, patch

from api_utils.utils_ext.files import extract_data_url_to_local, save_blob_to_local


def test_extract_data_url_to_local_write_failure():
    """
    测试场景: 写入文件时发生 IOError
    预期: 记录错误,返回 None (lines 78-80)
    """
    data = b"test data"
    b64_data = base64.b64encode(data).decode()
    data_url = f"data:text/plain;base64,{b64_data}"

    with (
        patch("server.logger") as mock_logger,
        patch("config.UPLOAD_FILES_DIR", "/tmp/uploads"),
        patch("os.makedirs"),
        patch("os.path.exists", return_value=False),
        patch("builtins.open", side_effect=IOError("Disk full")),
    ):
        # 执行
        result = extract_data_url_to_local(data_url, "req1")

        # 验证: 返回 None (line 80)
        assert result is None

        # 验证: logger.error 被调用 (line 79)
        mock_logger.error.assert_called()
        error_msg = mock_logger.error.call_args[0][0]
        assert "保存文件失败" in error_msg
        assert "Disk full" in error_msg


def test_save_blob_to_local_file_exists():
    """
    测试场景: 文件已存在,跳过保存
    预期: 记录日志,返回文件路径 (lines 106-108)
    """
    data = b"binary data"

    with (
        patch("server.logger") as mock_logger,
        patch("config.UPLOAD_FILES_DIR", "/tmp/uploads"),
        patch("os.makedirs"),
        patch("os.path.exists", return_value=True),  # 文件存在
    ):
        # 执行
        result = save_blob_to_local(data, mime_type="image/png", req_id="req1")

        # 验证: 返回路径 (line 108)
        assert result is not None
        assert result.endswith(".png")

        # 验证: logger.info 被调用 (line 107)
        mock_logger.info.assert_called()
        info_msg = mock_logger.info.call_args[0][0]
        assert "文件已存在，跳过保存" in info_msg


def test_save_blob_to_local_write_failure():
    """
    测试场景: 写入二进制文件时发生 IOError
    预期: 记录错误,返回 None (lines 114-116)
    """
    data = b"test binary"

    with (
        patch("server.logger") as mock_logger,
        patch("config.UPLOAD_FILES_DIR", "/tmp/uploads"),
        patch("os.makedirs"),
        patch("os.path.exists", return_value=False),
        patch("builtins.open", side_effect=IOError("Permission denied")),
    ):
        # 执行
        result = save_blob_to_local(data, mime_type="application/pdf")

        # 验证: 返回 None (line 116)
        assert result is None

        # 验证: logger.error 被调用 (line 115)
        mock_logger.error.assert_called()
        error_msg = mock_logger.error.call_args[0][0]
        assert "保存二进制失败" in error_msg
        assert "Permission denied" in error_msg
