from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from api_utils.model_switching import (
    analyze_model_requirements,
    handle_model_switching,
    handle_parameter_cache,
)

# We rely on the 'mock_server_module' fixture from conftest.py which patches sys.modules['server']
# But api_utils.model_switching uses server_state.state


@pytest.fixture
def mock_server_obj():
    """Mock server_state.state"""
    with patch("api_utils.model_switching.state") as mock_state:
        mock_state.current_ai_studio_model_id = "gemini-1.5-pro"
        yield mock_state


@pytest.fixture
def mock_logger():
    return MagicMock()


@pytest.fixture
def mock_page():
    return AsyncMock()


@pytest.fixture
def mock_lock():
    lock = AsyncMock()
    lock.__aenter__.return_value = None
    lock.__aexit__.return_value = None
    return lock


@pytest.fixture
def base_context(mock_logger, mock_page, mock_lock):
    return {
        "logger": mock_logger,
        "current_ai_studio_model_id": "gemini-1.5-pro",
        "parsed_model_list": [{"id": "gemini-1.5-pro"}, {"id": "gemini-1.5-flash"}],
        "page": mock_page,
        "model_switching_lock": mock_lock,
        "params_cache_lock": mock_lock,
        "page_params_cache": {},
        "needs_model_switching": False,
        "model_id_to_use": "gemini-1.5-pro",
        "model_actually_switched": False,
    }


@pytest.mark.asyncio
async def test_analyze_model_requirements_no_requested_model(base_context):
    req_id = "test-req"
    requested_model = None
    proxy_model_name = "proxy-model"

    result = await analyze_model_requirements(
        req_id, base_context, requested_model, proxy_model_name
    )

    assert result["needs_model_switching"] is False
    assert result["model_id_to_use"] == "gemini-1.5-pro"


@pytest.mark.asyncio
async def test_analyze_model_requirements_same_as_proxy(base_context):
    req_id = "test-req"
    requested_model = "proxy-model"
    proxy_model_name = "proxy-model"

    result = await analyze_model_requirements(
        req_id, base_context, requested_model, proxy_model_name
    )

    assert result["needs_model_switching"] is False


@pytest.mark.asyncio
async def test_analyze_model_requirements_valid_switch(base_context):
    req_id = "test-req"
    requested_model = "gemini-1.5-flash"
    proxy_model_name = "proxy-model"

    result = await analyze_model_requirements(
        req_id, base_context, requested_model, proxy_model_name
    )

    assert result["needs_model_switching"] is True
    assert result["model_id_to_use"] == "gemini-1.5-flash"


@pytest.mark.asyncio
async def test_analyze_model_requirements_invalid_model(base_context):
    req_id = "test-req"
    requested_model = "invalid-model"
    proxy_model_name = "proxy-model"

    with pytest.raises(HTTPException) as exc:
        await analyze_model_requirements(
            req_id, base_context, requested_model, proxy_model_name
        )

    assert exc.value.status_code == 400
    assert "Invalid model" in exc.value.detail


@pytest.mark.asyncio
async def test_analyze_model_requirements_no_parsed_list(base_context):
    req_id = "test-req"
    requested_model = "any-model"
    proxy_model_name = "proxy-model"
    base_context["parsed_model_list"] = []

    # Should not raise error if list is empty (validation skipped)
    result = await analyze_model_requirements(
        req_id, base_context, requested_model, proxy_model_name
    )

    assert result["model_id_to_use"] == "any-model"


@pytest.mark.asyncio
async def test_handle_model_switching_not_needed(base_context):
    req_id = "test-req"
    base_context["needs_model_switching"] = False

    result = await handle_model_switching(req_id, base_context)

    assert result == base_context
    base_context["model_switching_lock"].__aenter__.assert_not_called()


@pytest.mark.asyncio
async def test_handle_model_switching_success(base_context, mock_server_obj):
    req_id = "test-req"
    base_context["needs_model_switching"] = True
    base_context["model_id_to_use"] = "gemini-1.5-flash"
    mock_server_obj.current_ai_studio_model_id = "gemini-1.5-pro"

    with patch(
        "browser_utils.switch_ai_studio_model", new_callable=AsyncMock
    ) as mock_switch:
        mock_switch.return_value = True

        result = await handle_model_switching(req_id, base_context)

        mock_switch.assert_called_once_with(
            base_context["page"], "gemini-1.5-flash", req_id
        )
        assert mock_server_obj.current_ai_studio_model_id == "gemini-1.5-flash"
        assert result["model_actually_switched"] is True
        assert result["current_ai_studio_model_id"] == "gemini-1.5-flash"


@pytest.mark.asyncio
async def test_handle_model_switching_failure(base_context, mock_server_obj):
    req_id = "test-req"
    base_context["needs_model_switching"] = True
    base_context["model_id_to_use"] = "gemini-1.5-flash"
    mock_server_obj.current_ai_studio_model_id = "gemini-1.5-pro"

    with patch(
        "browser_utils.switch_ai_studio_model", new_callable=AsyncMock
    ) as mock_switch:
        mock_switch.return_value = False

        with pytest.raises(HTTPException) as exc:
            await handle_model_switching(req_id, base_context)

        assert exc.value.status_code == 422
        assert (
            mock_server_obj.current_ai_studio_model_id == "gemini-1.5-pro"
        )  # Should revert/stay same


@pytest.mark.asyncio
async def test_handle_model_switching_already_switched(base_context, mock_server_obj):
    req_id = "test-req"
    base_context["needs_model_switching"] = True
    base_context["model_id_to_use"] = "gemini-1.5-flash"
    mock_server_obj.current_ai_studio_model_id = "gemini-1.5-flash"  # Already matches

    with patch(
        "browser_utils.switch_ai_studio_model", new_callable=AsyncMock
    ) as mock_switch:
        result = await handle_model_switching(req_id, base_context)

        mock_switch.assert_not_called()
        assert result["model_actually_switched"] is False  # Default value


@pytest.mark.asyncio
async def test_handle_parameter_cache_switched(base_context):
    req_id = "test-req"
    base_context["model_actually_switched"] = True
    base_context["current_ai_studio_model_id"] = "gemini-1.5-flash"
    base_context["page_params_cache"] = {
        "some": "cache",
        "last_known_model_id_for_params": "gemini-1.5-pro",
    }

    await handle_parameter_cache(req_id, base_context)

    assert base_context["page_params_cache"] == {
        "last_known_model_id_for_params": "gemini-1.5-flash"
    }


@pytest.mark.asyncio
async def test_handle_parameter_cache_stale(base_context):
    req_id = "test-req"
    base_context["model_actually_switched"] = False
    base_context["current_ai_studio_model_id"] = "gemini-1.5-flash"
    base_context["page_params_cache"] = {
        "some": "cache",
        "last_known_model_id_for_params": "gemini-1.5-pro",
    }

    await handle_parameter_cache(req_id, base_context)

    assert base_context["page_params_cache"] == {
        "last_known_model_id_for_params": "gemini-1.5-flash"
    }


@pytest.mark.asyncio
async def test_handle_parameter_cache_valid(base_context):
    req_id = "test-req"
    base_context["model_actually_switched"] = False
    base_context["current_ai_studio_model_id"] = "gemini-1.5-pro"
    base_context["page_params_cache"] = {
        "some": "cache",
        "last_known_model_id_for_params": "gemini-1.5-pro",
    }

    await handle_parameter_cache(req_id, base_context)

    assert base_context["page_params_cache"]["some"] == "cache"
    assert (
        base_context["page_params_cache"]["last_known_model_id_for_params"]
        == "gemini-1.5-pro"
    )
