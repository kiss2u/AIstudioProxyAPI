"""
Extended tests for api_utils/routers/queue.py - Coverage completion.

Focus: Cover the last 2 uncovered lines (62-63).
Strategy: Test exception handling when accessing queue._queue fails.
"""

import asyncio
from unittest.mock import MagicMock, PropertyMock

import pytest

from api_utils.routers.queue import get_queue_status


@pytest.mark.asyncio
async def test_get_queue_status_queue_access_exception():
    """
    测试场景: 访问 queue._queue 抛出异常
    预期: 返回空列表,不中断 (lines 62-63)
    """
    # Create a mock queue that raises exception when _queue is accessed
    mock_queue = MagicMock(spec=asyncio.Queue)
    type(mock_queue)._queue = PropertyMock(side_effect=Exception("Queue access error"))

    mock_lock = MagicMock()
    mock_lock.locked.return_value = False

    # 执行: 调用 get_queue_status
    response = await get_queue_status(mock_queue, mock_lock)

    # 验证: 返回成功响应,但 queue_items 为空 (line 63 executed)
    assert response.status_code == 200
    import json

    data = json.loads(response.body)

    # 验证: queue_length 为 0 (因为 queue_items = [])
    assert data["queue_length"] == 0
    assert data["items"] == []
    assert data["is_processing_locked"] is False
