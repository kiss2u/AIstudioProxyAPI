import asyncio
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException

from api_utils.routers.chat import chat_completions
from models import ChatCompletionRequest


@pytest.mark.asyncio
async def test_chat_completions_success():
    request = ChatCompletionRequest(
        messages=[{"role": "user", "content": "hello"}], model="gpt-4"
    )
    http_request = MagicMock()
    logger = MagicMock()
    request_queue = asyncio.Queue()
    server_state = {
        "is_initializing": False,
        "is_playwright_ready": True,
        "is_page_ready": True,
        "is_browser_connected": True,
    }
    worker_task = MagicMock()
    worker_task.done.return_value = False

    # Simulate worker processing
    async def process_queue():
        item = await request_queue.get()
        item["result_future"].set_result({"response": "ok"})

    asyncio.create_task(process_queue())

    response = await chat_completions(
        request=request,
        http_request=http_request,
        logger=logger,
        request_queue=request_queue,
        server_state=server_state,
        worker_task=worker_task,
    )

    assert response == {"response": "ok"}


@pytest.mark.asyncio
async def test_chat_completions_service_unavailable():
    request = ChatCompletionRequest(
        messages=[{"role": "user", "content": "hello"}], model="gpt-4"
    )
    http_request = MagicMock()
    logger = MagicMock()
    request_queue = asyncio.Queue()
    server_state = {
        "is_initializing": True,  # Service unavailable
        "is_playwright_ready": True,
        "is_page_ready": True,
        "is_browser_connected": True,
    }
    worker_task = MagicMock()
    worker_task.done.return_value = False

    with pytest.raises(HTTPException) as excinfo:
        await chat_completions(
            request=request,
            http_request=http_request,
            logger=logger,
            request_queue=request_queue,
            server_state=server_state,
            worker_task=worker_task,
        )
    assert excinfo.value.status_code == 503


@pytest.mark.asyncio
async def test_chat_completions_timeout():
    # Mock asyncio.wait_for to raise TimeoutError immediately
    async def mock_wait_for(fut, timeout):
        raise asyncio.TimeoutError()

    request = ChatCompletionRequest(
        messages=[{"role": "user", "content": "hello"}], model="gpt-4"
    )
    http_request = MagicMock()
    logger = MagicMock()
    request_queue = asyncio.Queue()
    server_state = {
        "is_initializing": False,
        "is_playwright_ready": True,
        "is_page_ready": True,
        "is_browser_connected": True,
    }
    worker_task = MagicMock()
    worker_task.done.return_value = False

    with patch("asyncio.wait_for", new=mock_wait_for):
        with pytest.raises(HTTPException) as excinfo:
            await chat_completions(
                request=request,
                http_request=http_request,
                logger=logger,
                request_queue=request_queue,
                server_state=server_state,
                worker_task=worker_task,
            )
    assert excinfo.value.status_code == 504


@pytest.mark.asyncio
async def test_chat_completions_cancelled():
    request = ChatCompletionRequest(
        messages=[{"role": "user", "content": "hello"}], model="gpt-4"
    )
    http_request = MagicMock()
    logger = MagicMock()
    request_queue = asyncio.Queue()
    server_state = {
        "is_initializing": False,
        "is_playwright_ready": True,
        "is_page_ready": True,
        "is_browser_connected": True,
    }
    worker_task = MagicMock()
    worker_task.done.return_value = False

    # Simulate cancellation
    async def cancel_request():
        item = await request_queue.get()
        item["result_future"].cancel()

    asyncio.create_task(cancel_request())

    with pytest.raises(HTTPException) as excinfo:
        await chat_completions(
            request=request,
            http_request=http_request,
            logger=logger,
            request_queue=request_queue,
            server_state=server_state,
            worker_task=worker_task,
        )
    assert excinfo.value.status_code == 499
