from unittest.mock import AsyncMock, MagicMock

import pytest

from api_utils.routers.models import list_models
from config import DEFAULT_FALLBACK_MODEL_ID


@pytest.mark.asyncio
async def test_list_models_success(mock_env):
    # Mock dependencies
    logger = MagicMock()
    model_list_fetch_event = MagicMock()
    model_list_fetch_event.is_set.return_value = True

    page_instance = AsyncMock()
    page_instance.is_closed.return_value = False

    parsed_model_list = [
        {"id": "gemini-1.5-pro", "object": "model"},
        {"id": "gemini-1.5-flash", "object": "model"},
    ]
    excluded_model_ids = {"gemini-1.5-flash"}

    response = await list_models(
        logger=logger,
        model_list_fetch_event=model_list_fetch_event,
        page_instance=page_instance,
        parsed_model_list=parsed_model_list,
        excluded_model_ids=excluded_model_ids,
    )

    assert response["object"] == "list"
    assert len(response["data"]) == 1
    assert response["data"][0]["id"] == "gemini-1.5-pro"


@pytest.mark.asyncio
async def test_list_models_fallback(mock_env):
    logger = MagicMock()
    model_list_fetch_event = MagicMock()
    model_list_fetch_event.is_set.return_value = True

    page_instance = AsyncMock()
    parsed_model_list = []  # Empty list
    excluded_model_ids = set()

    response = await list_models(
        logger=logger,
        model_list_fetch_event=model_list_fetch_event,
        page_instance=page_instance,
        parsed_model_list=parsed_model_list,
        excluded_model_ids=excluded_model_ids,
    )

    assert response["object"] == "list"
    assert len(response["data"]) == 1
    assert response["data"][0]["id"] == DEFAULT_FALLBACK_MODEL_ID


@pytest.mark.asyncio
async def test_list_models_fetch_timeout(mock_env):
    logger = MagicMock()
    model_list_fetch_event = AsyncMock()
    model_list_fetch_event.is_set.return_value = False
    # Simulate wait timeout
    model_list_fetch_event.wait.side_effect = TimeoutError("Timeout")

    page_instance = AsyncMock()
    page_instance.is_closed.return_value = False

    parsed_model_list = []
    excluded_model_ids = set()

    # Should handle exception gracefully and return fallback
    response = await list_models(
        logger=logger,
        model_list_fetch_event=model_list_fetch_event,
        page_instance=page_instance,
        parsed_model_list=parsed_model_list,
        excluded_model_ids=excluded_model_ids,
    )

    assert response["object"] == "list"
    assert len(response["data"]) == 1
    assert response["data"][0]["id"] == DEFAULT_FALLBACK_MODEL_ID
