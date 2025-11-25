import pytest
from unittest.mock import MagicMock, AsyncMock, patch
from browser_utils.page_controller_modules.response import ResponseController
from models import ClientDisconnectedError
from config import RESPONSE_CONTAINER_SELECTOR, RESPONSE_TEXT_SELECTOR

@pytest.fixture
def response_controller(mock_page):
    logger = MagicMock()
    req_id = "test_req_id"
    return ResponseController(mock_page, logger, req_id)

@pytest.mark.asyncio
async def test_get_response_success(response_controller, mock_page):
    """Test successful response retrieval."""
    check_client_disconnected = MagicMock(return_value=False)
    expected_content = "Test response content"
    
    # Mock locators
    response_container = AsyncMock()
    response_element = AsyncMock()
    
    mock_page.locator.return_value.last = response_container
    response_container.locator.return_value = response_element
    
    # Mock helper functions
    with patch('browser_utils.page_controller_modules.response.expect_async', new_callable=MagicMock) as mock_expect, \
         patch('browser_utils.page_controller_modules.response._wait_for_response_completion', new_callable=AsyncMock) as mock_wait, \
         patch('browser_utils.page_controller_modules.response._get_final_response_content', new_callable=AsyncMock) as mock_get_content:
        
        mock_expect.return_value.to_be_attached = AsyncMock()
        mock_wait.return_value = True
        mock_get_content.return_value = expected_content
        
        result = await response_controller.get_response(check_client_disconnected)
        
        assert result == expected_content
        mock_expect.return_value.to_be_attached.assert_called()
        mock_wait.assert_called()
        mock_get_content.assert_called()

@pytest.mark.asyncio
async def test_get_response_client_disconnected(response_controller, mock_page):
    """Test response retrieval with client disconnection."""
    check_client_disconnected = MagicMock(side_effect=lambda x: True if "获取响应 - 响应元素已附加" in x else False)
    
    # Mock locators
    response_container = AsyncMock()
    response_element = AsyncMock()
    
    mock_page.locator.return_value.last = response_container
    response_container.locator.return_value = response_element
    
    with patch('browser_utils.page_controller_modules.response.expect_async', new_callable=MagicMock) as mock_expect:
        mock_expect.return_value.to_be_attached = AsyncMock()
        
        with pytest.raises(ClientDisconnectedError):
            await response_controller.get_response(check_client_disconnected)

@pytest.mark.asyncio
async def test_get_response_empty_content(response_controller, mock_page):
    """Test response retrieval when content is empty."""
    check_client_disconnected = MagicMock(return_value=False)
    
    # Mock locators
    response_container = AsyncMock()
    response_element = AsyncMock()
    
    mock_page.locator.return_value.last = response_container
    response_container.locator.return_value = response_element
    
    with patch('browser_utils.page_controller_modules.response.expect_async', new_callable=MagicMock) as mock_expect, \
         patch('browser_utils.page_controller_modules.response._wait_for_response_completion', new_callable=AsyncMock) as mock_wait, \
         patch('browser_utils.page_controller_modules.response._get_final_response_content', new_callable=AsyncMock) as mock_get_content, \
         patch('browser_utils.page_controller_modules.response.save_error_snapshot', new_callable=AsyncMock) as mock_save_snapshot:
        
        mock_expect.return_value.to_be_attached = AsyncMock()
        mock_wait.return_value = True
        mock_get_content.return_value = ""
        
        result = await response_controller.get_response(check_client_disconnected)
        
        assert result == ""
        mock_save_snapshot.assert_called()

@pytest.mark.asyncio
async def test_get_response_completion_timeout(response_controller, mock_page):
    """Test response retrieval when completion detection times out."""
    check_client_disconnected = MagicMock(return_value=False)
    expected_content = "Partial content"
    
    # Mock locators
    response_container = AsyncMock()
    response_element = AsyncMock()
    
    mock_page.locator.return_value.last = response_container
    response_container.locator.return_value = response_element
    
    with patch('browser_utils.page_controller_modules.response.expect_async', new_callable=MagicMock) as mock_expect, \
         patch('browser_utils.page_controller_modules.response._wait_for_response_completion', new_callable=AsyncMock) as mock_wait, \
         patch('browser_utils.page_controller_modules.response._get_final_response_content', new_callable=AsyncMock) as mock_get_content:
        
        mock_expect.return_value.to_be_attached = AsyncMock()
        mock_wait.return_value = False  # Simulate timeout/failure
        mock_get_content.return_value = expected_content
        
        result = await response_controller.get_response(check_client_disconnected)
        
        assert result == expected_content
        # Should still try to get content even if completion check failed
        mock_get_content.assert_called()