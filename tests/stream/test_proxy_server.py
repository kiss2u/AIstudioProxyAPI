import pytest
import asyncio
from unittest.mock import MagicMock, AsyncMock, patch
from stream.proxy_server import ProxyServer

@pytest.fixture
def proxy_server():
    return ProxyServer(host='127.0.0.1', port=0)

@pytest.mark.asyncio
async def test_proxy_server_initialization(proxy_server):
    """Test ProxyServer initialization."""
    assert proxy_server.host == '127.0.0.1'
    assert proxy_server.port == 0
    assert proxy_server.intercept_domains == []
    assert proxy_server.upstream_proxy is None
    assert proxy_server.queue is None

@pytest.mark.asyncio
async def test_should_intercept(proxy_server):
    """Test domain interception logic."""
    proxy_server.intercept_domains = ['example.com', '*.test.com']
    
    assert proxy_server.should_intercept('example.com') is True
    assert proxy_server.should_intercept('sub.test.com') is True
    assert proxy_server.should_intercept('google.com') is False
    assert proxy_server.should_intercept('test.com') is False  # Wildcard requires subdomain

@pytest.mark.asyncio
async def test_handle_client_connect(proxy_server):
    """Test handling of CONNECT method."""
    reader = AsyncMock()
    writer = MagicMock()
    writer.drain = AsyncMock()
    writer.close = MagicMock()
    
    # Mock request line
    reader.readline.return_value = b"CONNECT example.com:443 HTTP/1.1\r\n"
    
    # Mock _handle_connect
    proxy_server._handle_connect = AsyncMock()
    
    await proxy_server.handle_client(reader, writer)
    
    proxy_server._handle_connect.assert_called_with(reader, writer, "example.com:443")
    writer.close.assert_called()

@pytest.mark.asyncio
async def test_handle_client_invalid_request(proxy_server):
    """Test handling of invalid request."""
    reader = AsyncMock()
    writer = MagicMock()
    writer.close = MagicMock()
    
    # Mock empty request line
    reader.readline.return_value = b""
    
    await proxy_server.handle_client(reader, writer)
    
    writer.close.assert_called()

@pytest.mark.asyncio
async def test_handle_connect_no_interception(proxy_server):
    """Test CONNECT handling without interception."""
    reader = AsyncMock()
    writer = MagicMock()
    writer.drain = AsyncMock()
    writer.write = MagicMock()
    target = "example.com:443"
    
    proxy_server.should_intercept = MagicMock(return_value=False)
    proxy_server.proxy_connector.create_connection = AsyncMock(return_value=(AsyncMock(), AsyncMock()))
    proxy_server._forward_data = AsyncMock()
    
    await proxy_server._handle_connect(reader, writer, target)
    
    # Verify connection established response
    writer.write.assert_any_call(b'HTTP/1.1 200 Connection Established\r\n\r\n')
    
    # Verify forwarding called
    proxy_server._forward_data.assert_called()

@pytest.mark.asyncio
async def test_handle_connect_with_interception(proxy_server):
    """Test CONNECT handling with interception."""
    reader = AsyncMock()
    writer = MagicMock()
    writer.drain = AsyncMock()
    writer.write = MagicMock()
    writer.close = MagicMock()
    target = "example.com:443"
    
    proxy_server.should_intercept = MagicMock(return_value=True)
    proxy_server.cert_manager.get_domain_cert = MagicMock()
    
    # Mock SSL context and transport
    mock_transport = MagicMock()
    writer.transport = mock_transport
    
    # Mock loop.start_tls
    mock_new_transport = MagicMock()
    with patch('asyncio.get_running_loop') as mock_loop:
        mock_loop.return_value.start_tls = AsyncMock(return_value=mock_new_transport)
        
        proxy_server.proxy_connector.create_connection = AsyncMock(return_value=(AsyncMock(), AsyncMock()))
        proxy_server._forward_data_with_interception = AsyncMock()
        
        # Mock SSL context creation
        with patch('ssl.create_default_context') as mock_ssl_ctx:
            # Mock reader to be a proper StreamReader
            reader = AsyncMock(spec=asyncio.StreamReader)
            reader.readline.return_value = b"CONNECT example.com:443 HTTP/1.1\r\n"
            
            await proxy_server._handle_connect(reader, writer, target)
            
            # Verify interception flow
            proxy_server.cert_manager.get_domain_cert.assert_called_with("example.com")
            writer.write.assert_any_call(b'HTTP/1.1 200 Connection Established\r\n\r\n')
            proxy_server._forward_data_with_interception.assert_called()

@pytest.mark.asyncio
async def test_forward_data(proxy_server):
    """Test data forwarding."""
    client_reader = AsyncMock()
    client_writer = MagicMock()
    client_writer.drain = AsyncMock()
    client_writer.write = MagicMock()
    client_writer.close = MagicMock()
    
    server_reader = AsyncMock()
    server_writer = MagicMock()
    server_writer.drain = AsyncMock()
    server_writer.write = MagicMock()
    server_writer.close = MagicMock()
    
    # Simulate some data
    client_reader.read.side_effect = [b"data1", b""]
    server_reader.read.side_effect = [b"data2", b""]
    
    await proxy_server._forward_data(client_reader, client_writer, server_reader, server_writer)
    
    # Verify data transfer
    server_writer.write.assert_called_with(b"data1")
    client_writer.write.assert_called_with(b"data2")
    
    # Verify closing
    server_writer.close.assert_called()
    client_writer.close.assert_called()

@pytest.mark.asyncio
async def test_forward_data_with_interception(proxy_server):
    """Test data forwarding with interception."""
    client_reader = AsyncMock()
    client_writer = MagicMock()
    client_writer.drain = AsyncMock()
    client_writer.write = MagicMock()
    client_writer.close = MagicMock()
    
    server_reader = AsyncMock()
    server_writer = MagicMock()
    server_writer.drain = AsyncMock()
    server_writer.write = MagicMock()
    server_writer.close = MagicMock()
    
    # Mock interceptor
    proxy_server.interceptor.process_request = AsyncMock(return_value=b"processed_body")
    proxy_server.interceptor.process_response = AsyncMock(return_value={"status": "ok"})
    proxy_server.queue = MagicMock()
    
    # Simulate client request (GenerateContent)
    client_request = b"POST /v1beta/models/gemini-pro:generateContent HTTP/1.1\r\nHost: example.com\r\n\r\nbody"
    client_reader.read.side_effect = [client_request, b""]
    
    # Simulate server response
    server_response = b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\n\r\nresponse_body"
    
    # We need to delay the server response to ensure client request is processed first
    # Use a side_effect function that handles the sequence
    call_count = 0
    async def server_read_side_effect(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            # Wait for process_request to be called
            # Increase wait time and check frequency
            for _ in range(100):
                if proxy_server.interceptor.process_request.called:
                    break
                await asyncio.sleep(0.01)
            return server_response
        return b""

    server_reader.read.side_effect = server_read_side_effect
    
    await proxy_server._forward_data_with_interception(
        client_reader, client_writer, server_reader, server_writer, "example.com"
    )
    
    # Verify request interception
    # Wait a bit for async tasks to complete
    await asyncio.sleep(0.2)
    
    # Let's verify that at least some data was written to server_writer
    assert server_writer.write.called
    
    # Verify response interception
    # The interceptor.process_response is called inside _process_server_data task
    # We need to ensure that task has run enough to call it.
    # Since we are mocking server_reader.read, we control when data is available.
    
    # Wait for process_response to be called
    for _ in range(50):
        if proxy_server.interceptor.process_response.called:
            break
        await asyncio.sleep(0.05)
        
    # Verify request interception happened
    assert proxy_server.interceptor.process_request.called, "process_request was not called"
            
    # Verify response interception happened
    assert proxy_server.interceptor.process_response.called, "process_response was not called"
    assert proxy_server.queue.put.called

@pytest.mark.asyncio
async def test_start_server(proxy_server):
    """Test server startup."""
    proxy_server.queue = MagicMock()
    
    mock_server = AsyncMock()
    mock_server.sockets = [MagicMock()]
    mock_server.sockets[0].getsockname.return_value = ('127.0.0.1', 12345)
    
    with patch('asyncio.start_server', return_value=mock_server) as mock_start:
        # Run start in a task to avoid blocking
        task = asyncio.create_task(proxy_server.start())
        await asyncio.sleep(0.1)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        
        mock_start.assert_called_with(proxy_server.handle_client, '127.0.0.1', 0)
        proxy_server.queue.put.assert_called_with("READY")