import pytest
from fastapi import status
from unittest.mock import MagicMock
from api_utils.routers.health import health_check

@pytest.mark.asyncio
async def test_health_check_ok(mock_env):
    # Mock dependencies
    server_state = {
        "is_initializing": False,
        "is_playwright_ready": True,
        "is_browser_connected": True,
        "is_page_ready": True
    }
    worker_task = MagicMock()
    worker_task.done.return_value = False
    
    request_queue = MagicMock()
    request_queue.qsize.return_value = 0
    
    response = await health_check(
        server_state=server_state,
        worker_task=worker_task,
        request_queue=request_queue
    )
    
    assert response.status_code == status.HTTP_200_OK
    body = response.body.decode()
    assert '"status":"OK"' in body

@pytest.mark.asyncio
async def test_health_check_initializing(mock_env):
    server_state = {
        "is_initializing": True,
        "is_playwright_ready": False,
        "is_browser_connected": False,
        "is_page_ready": False
    }
    worker_task = MagicMock()
    worker_task.done.return_value = False
    request_queue = MagicMock()
    request_queue.qsize.return_value = 0
    
    response = await health_check(
        server_state=server_state,
        worker_task=worker_task,
        request_queue=request_queue
    )
    
    assert response.status_code == status.HTTP_503_SERVICE_UNAVAILABLE
    body = response.body.decode()
    assert '"status":"Error"' in body
    assert "初始化进行中" in body

@pytest.mark.asyncio
async def test_health_check_worker_down(mock_env):
    server_state = {
        "is_initializing": False,
        "is_playwright_ready": True,
        "is_browser_connected": True,
        "is_page_ready": True
    }
    worker_task = MagicMock()
    worker_task.done.return_value = True # Worker is done/dead
    request_queue = MagicMock()
    request_queue.qsize.return_value = 0
    
    response = await health_check(
        server_state=server_state,
        worker_task=worker_task,
        request_queue=request_queue
    )
    
    assert response.status_code == status.HTTP_503_SERVICE_UNAVAILABLE
    body = response.body.decode()
    assert "Worker 未运行" in body