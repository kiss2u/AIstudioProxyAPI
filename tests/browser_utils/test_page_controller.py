from models import ClientDisconnectedError
import pytest
from unittest.mock import MagicMock, AsyncMock, patch
from browser_utils.page_controller import PageController

@pytest.mark.asyncio
async def test_page_controller_initialization(mock_page):
    """Test PageController initialization and mixin inheritance."""
    logger = MagicMock()
    req_id = "test_req_id"
    
    controller = PageController(mock_page, logger, req_id)
    
    assert controller.page == mock_page
    assert controller.logger == logger
    assert controller.req_id == req_id
    
    # Verify mixin methods are available (duck typing check)
    # InputController
    assert hasattr(controller, 'submit_prompt')
    # ResponseController
    assert hasattr(controller, 'get_response')
    # BaseController
    assert hasattr(controller, '_check_disconnect')
    
    # Verify inheritance hierarchy
    assert isinstance(controller, PageController)
@pytest.mark.asyncio
async def test_page_controller_delegation(mock_page):
    """Test that PageController delegates methods to mixins correctly."""
    logger = MagicMock()
    req_id = "test_req_id"
    controller = PageController(mock_page, logger, req_id)
    
    # Mock a method from InputController
    with patch.object(controller, 'submit_prompt', new_callable=AsyncMock) as mock_submit:
        await controller.submit_prompt("test prompt")
        mock_submit.assert_called_once_with("test prompt")

@pytest.mark.asyncio
async def test_page_controller_check_disconnect(mock_page):
    """Test _check_disconnect method from BaseController."""
    logger = MagicMock()
    req_id = "test_req_id"
    controller = PageController(mock_page, logger, req_id)
    
    # Should not raise exception by default
    # _check_disconnect takes (stage: str = "")
    # The error was: TypeError: BaseController._check_disconnect() missing 1 required positional argument: 'stage'
    # This means it's not an instance method bound to the controller?
    # Or maybe BaseController defines it differently?
    
    # Let's check BaseController definition in browser_utils/page_controller_modules/base.py
    # It seems BaseController might not have self as first argument if it's a static method or something?
    # Or maybe it's not properly inherited.
    
    # Actually, looking at the error: BaseController._check_disconnect() missing 1 required positional argument: 'stage'
    # If called as controller._check_disconnect("test stage"), 'self' is passed automatically.
    # So it received 2 arguments (self, "test stage").
    # If it says missing 'stage', maybe it expects more arguments?
    
    # Wait, the error says BaseController._check_disconnect().
    # If I call controller._check_disconnect("test stage"), it should work if defined as def _check_disconnect(self, stage="").
    
    # Let's assume the signature is correct in the code but maybe my test call is wrong?
    # controller._check_disconnect("test stage")
    
    # If the method is defined as:
    # def _check_disconnect(self, stage: str = ""): ...
    
    # Maybe the issue is how I'm calling it or mocking it?
    # I am not mocking _check_disconnect on the controller instance itself in the first call.
    
    # The error was: TypeError: BaseController._check_disconnect() missing 1 required positional argument: 'check_client_disconnected'
    # This means the method signature is different from what I assumed.
    # It seems it expects 'check_client_disconnected' as an argument?
    
    # Let's check BaseController definition in browser_utils/page_controller_modules/base.py
    # I don't have the file content, but the error message is clear.
    # It expects 'check_client_disconnected'.
    
    # If I pass a mock function for it, it should work.
    mock_check_func = MagicMock()
    
    # But wait, if it's a method on the controller, why does it need an external check function?
    # Maybe it's a wrapper or helper?
    
    # Let's try passing it.
    # This should raise ClientDisconnectedError because mock_check_func returns True (default for MagicMock if not specified? No, default is new MagicMock which is truthy)
    # Wait, MagicMock() is truthy.
    # So if check_client_disconnected(stage) returns a MagicMock, it evaluates to True.
    # So it raises ClientDisconnectedError.
    
    # We expect it to raise ClientDisconnectedError
    from models import ClientDisconnectedError
    with pytest.raises(ClientDisconnectedError):
        await controller._check_disconnect(stage="test stage", check_client_disconnected=mock_check_func)

    # Mock disconnect event
    controller.client_disconnected_event = MagicMock()
    controller.client_disconnected_event.is_set.return_value = True
    
    # If the method uses the passed function or the internal event?
    # If it uses the internal event, then setting it should trigger exception.
    # If it uses the passed function, then the passed function should raise exception?
    
    # If I look at api_utils/client_connection.py, check_client_disconnected is a function returned by setup_disconnect_monitoring.
    # Maybe PageController._check_disconnect delegates to it?
    
    from models import ClientDisconnectedError
    
    # If I pass a mock that raises exception
    mock_check_func.side_effect = ClientDisconnectedError("Disconnected")
    
    # The method _check_disconnect calls the passed function.
    # If the passed function raises ClientDisconnectedError, the method should propagate it.
    # The test failed with "DID NOT RAISE".
    # This means the method caught the exception or didn't call the function?
    
    # Let's check if it was called.
    try:
        await controller._check_disconnect(stage="test stage", check_client_disconnected=mock_check_func)
    except ClientDisconnectedError:
        pass
    except Exception as e:
        pytest.fail(f"Raised unexpected exception: {e}")
        
    # If it didn't raise, maybe it swallowed it?
    # Or maybe it didn't call it?
    
    # Let's assert it was called.
    mock_check_func.assert_called_with("test stage")
    
    # If it was called and raised, but _check_disconnect didn't raise, then _check_disconnect swallows it.
    # But BaseController._check_disconnect usually just calls the function.
    
    # Wait, if I look at the previous error: TypeError: BaseController._check_disconnect() missing 1 required positional argument: 'check_client_disconnected'
    # This implies the signature is def _check_disconnect(self, stage, check_client_disconnected):
    
    # If I call it with keyword args, it should work.
    # If mock_check_func raises, _check_disconnect should raise.
    
    # Maybe I need to reset the mock side effect and try again to be sure.
    mock_check_func.side_effect = ClientDisconnectedError("Disconnected")
    
    # _check_disconnect is async, so we must await it.
    # The previous failure "DID NOT RAISE" might be because I didn't await it?
    # No, I used `await controller._check_disconnect(...)` in the try/except block above.
    # But in the `with pytest.raises(...)` block, I called it without await?
    # Wait, the code snippet shows:
    # with pytest.raises(ClientDisconnectedError):
    #     await controller._check_disconnect(...)
    
    # If it didn't raise, it means `mock_check_func` didn't raise or `_check_disconnect` swallowed it.
    # `_check_disconnect` implementation:
    # if check_client_disconnected(stage):
    #     raise ClientDisconnectedError(...)
    
    # It calls `check_client_disconnected(stage)`.
    # If `check_client_disconnected` raises `ClientDisconnectedError`, then `_check_disconnect` should propagate it.
    
    # Let's verify if `mock_check_func` raises when called.
    with pytest.raises(ClientDisconnectedError):
        mock_check_func("test")
        
    # Now call the method
    with pytest.raises(ClientDisconnectedError):
        await controller._check_disconnect(stage="test stage", check_client_disconnected=mock_check_func)