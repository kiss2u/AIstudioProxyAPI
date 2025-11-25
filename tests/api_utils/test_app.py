import pytest
from unittest.mock import MagicMock, AsyncMock, patch
from fastapi.testclient import TestClient
from api_utils.app import create_app, APIKeyAuthMiddleware
from api_utils import auth_utils

@pytest.fixture
def app():
    return create_app()

@pytest.fixture
def client(app):
    return TestClient(app)

def test_create_app(app):
    """Test that the app is created correctly."""
    assert app.title == "AI Studio Proxy Server (集成模式)"
    assert app.version == "0.6.0-integrated"

def test_middleware_initialization(app):
    """Test that middleware is added."""
    middleware_types = [m.cls for m in app.user_middleware]
    assert APIKeyAuthMiddleware in middleware_types

@pytest.mark.asyncio
async def test_api_key_auth_middleware_no_keys():
    """Test middleware when no API keys are configured."""
    app = MagicMock()
    middleware = APIKeyAuthMiddleware(app)
    
    request = MagicMock()
    request.url.path = "/v1/chat/completions"
    call_next = AsyncMock()
    
    with patch('api_utils.auth_utils.API_KEYS', {}):
        await middleware.dispatch(request, call_next)
        call_next.assert_called_once_with(request)

@pytest.mark.asyncio
async def test_api_key_auth_middleware_excluded_path():
    """Test middleware with excluded paths."""
    app = MagicMock()
    middleware = APIKeyAuthMiddleware(app)
    
    request = MagicMock()
    request.url.path = "/health"
    call_next = AsyncMock()
    
    # Even with keys configured, excluded paths should pass
    with patch('api_utils.auth_utils.API_KEYS', {"test-key": "user"}):
        await middleware.dispatch(request, call_next)
        call_next.assert_called_once_with(request)

@pytest.mark.asyncio
async def test_api_key_auth_middleware_valid_key():
    """Test middleware with valid API key."""
    app = MagicMock()
    middleware = APIKeyAuthMiddleware(app)
    
    request = MagicMock()
    request.url.path = "/v1/chat/completions"
    request.headers = {"Authorization": "Bearer test-key"}
    call_next = AsyncMock()
    
    with patch('api_utils.auth_utils.API_KEYS', {"test-key": "user"}):
        with patch('api_utils.auth_utils.verify_api_key', return_value=True):
            await middleware.dispatch(request, call_next)
            call_next.assert_called_once_with(request)

@pytest.mark.asyncio
async def test_api_key_auth_middleware_invalid_key():
    """Test middleware with invalid API key."""
    app = MagicMock()
    middleware = APIKeyAuthMiddleware(app)
    
    request = MagicMock()
    request.url.path = "/v1/chat/completions"
    request.headers = {"Authorization": "Bearer invalid-key"}
    call_next = AsyncMock()
    
    with patch('api_utils.auth_utils.API_KEYS', {"test-key": "user"}):
        with patch('api_utils.auth_utils.verify_api_key', return_value=False):
            response = await middleware.dispatch(request, call_next)
            assert response.status_code == 401
            call_next.assert_not_called()

@pytest.mark.asyncio
async def test_api_key_auth_middleware_missing_key():
    """Test middleware with missing API key."""
    app = MagicMock()
    middleware = APIKeyAuthMiddleware(app)
    
    request = MagicMock()
    request.url.path = "/v1/chat/completions"
    request.headers = {}
    call_next = AsyncMock()
    
    with patch('api_utils.auth_utils.API_KEYS', {"test-key": "user"}):
        response = await middleware.dispatch(request, call_next)
        assert response.status_code == 401
        call_next.assert_not_called()

@pytest.mark.asyncio
async def test_lifespan_startup_shutdown():
    """Test application startup and shutdown sequence."""
    app = MagicMock()
    
    # Mock all the dependencies
    with patch('server.logger') as mock_logger, \
         patch('api_utils.app._setup_logging') as mock_setup_logging, \
         patch('api_utils.app._initialize_globals') as mock_init_globals, \
         patch('api_utils.app._initialize_proxy_settings') as mock_init_proxy, \
         patch('api_utils.app.load_excluded_models') as mock_load_models, \
         patch('api_utils.app._start_stream_proxy', new_callable=AsyncMock) as mock_start_proxy, \
         patch('api_utils.app._initialize_browser_and_page', new_callable=AsyncMock) as mock_init_browser, \
         patch('api_utils.app._shutdown_resources', new_callable=AsyncMock) as mock_shutdown, \
         patch('server.queue_worker', new_callable=AsyncMock) as mock_worker, \
         patch('api_utils.app.restore_original_streams') as mock_restore_streams, \
         patch('server.is_page_ready', True):
        
        mock_setup_logging.return_value = (MagicMock(), MagicMock())
        
        # Get the lifespan context manager
        from api_utils.app import lifespan
        
        async with lifespan(app):
            # Verify startup actions
            mock_init_globals.assert_called_once()
            mock_init_proxy.assert_called_once()
            mock_load_models.assert_called_once()
            mock_start_proxy.assert_called_once()
            mock_init_browser.assert_called_once()
            mock_logger.info.assert_any_call("Starting AI Studio Proxy Server...")
            mock_logger.info.assert_any_call("Server startup complete.")
            
        # Verify shutdown actions
        mock_shutdown.assert_called_once()
        mock_restore_streams.assert_called()
        mock_logger.info.assert_any_call("Server shutdown complete.")

@pytest.mark.asyncio
async def test_lifespan_startup_failure():
    """Test application startup failure handling."""
    app = MagicMock()
    
    with patch('server.logger') as mock_logger, \
         patch('api_utils.app._setup_logging') as mock_setup_logging, \
         patch('api_utils.app._initialize_globals'), \
         patch('api_utils.app._initialize_proxy_settings'), \
         patch('api_utils.app.load_excluded_models'), \
         patch('api_utils.app._start_stream_proxy', side_effect=Exception("Startup failed")), \
         patch('api_utils.app._shutdown_resources', new_callable=AsyncMock) as mock_shutdown, \
         patch('api_utils.app.restore_original_streams'):
        
        mock_setup_logging.return_value = (MagicMock(), MagicMock())
        
        from api_utils.app import lifespan
        
        with pytest.raises(RuntimeError, match="Application startup failed"):
            async with lifespan(app):
                pass
        
        # Verify shutdown was called even after failure
        mock_shutdown.assert_called()
        mock_logger.critical.assert_called()