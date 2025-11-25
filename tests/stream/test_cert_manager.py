import pytest
from unittest.mock import MagicMock, patch, mock_open
from pathlib import Path
from stream.cert_manager import CertificateManager
from cryptography import x509
from cryptography.hazmat.primitives.asymmetric import rsa

@pytest.fixture
def mock_path():
    with patch("stream.cert_manager.Path") as mock:
        yield mock

@pytest.fixture
def mock_open_file():
    with patch("builtins.open", mock_open()) as mock:
        yield mock

@pytest.fixture
def mock_rsa():
    with patch("stream.cert_manager.rsa") as mock:
        key = MagicMock()
        key.private_bytes.return_value = b"private_key"
        key.public_key.return_value = MagicMock()
        mock.generate_private_key.return_value = key
        yield mock

@pytest.fixture
def mock_x509():
    with patch("stream.cert_manager.x509") as mock:
        cert = MagicMock()
        cert.public_bytes.return_value = b"certificate"
        mock.CertificateBuilder.return_value.subject_name.return_value \
            .issuer_name.return_value.public_key.return_value \
            .serial_number.return_value.not_valid_before.return_value \
            .not_valid_after.return_value.add_extension.return_value \
            .add_extension.return_value.sign.return_value = cert
        
        mock.load_pem_x509_certificate.return_value = cert
        yield mock

@pytest.fixture
def mock_serialization():
    with patch("stream.cert_manager.serialization") as mock:
        mock.load_pem_private_key.return_value = MagicMock()
        yield mock

def test_init_generates_ca_if_missing(mock_path, mock_open_file, mock_rsa, mock_x509, mock_serialization):
    """Test initialization generates CA if missing."""
    mock_dir = MagicMock()
    mock_path.return_value = mock_dir
    
    # CA files don't exist
    mock_dir.__truediv__.return_value.exists.return_value = False
    
    manager = CertificateManager()
    
    # Verify directory creation
    mock_dir.mkdir.assert_called_with(exist_ok=True)
    
    # Verify CA generation
    mock_rsa.generate_private_key.assert_called()
    mock_x509.CertificateBuilder.assert_called()
    
    # Verify file writing (key and cert)
    assert mock_open_file.call_count >= 4 # write key, write cert, read key, read cert

def test_init_loads_existing_ca(mock_path, mock_open_file, mock_rsa, mock_x509, mock_serialization):
    """Test initialization loads existing CA."""
    mock_dir = MagicMock()
    mock_path.return_value = mock_dir
    
    # CA files exist
    mock_dir.__truediv__.return_value.exists.return_value = True
    
    manager = CertificateManager()
    
    # Verify NO CA generation
    mock_rsa.generate_private_key.assert_not_called()
    
    # Verify loading
    mock_serialization.load_pem_private_key.assert_called()
    mock_x509.load_pem_x509_certificate.assert_called()

def test_get_domain_cert_existing(mock_path, mock_open_file, mock_rsa, mock_x509, mock_serialization):
    """Test getting existing domain certificate."""
    mock_dir = MagicMock()
    mock_path.return_value = mock_dir
    
    # CA exists
    mock_dir.__truediv__.return_value.exists.side_effect = [True, True, True, True] # CA key, CA cert, Domain cert, Domain key
    
    manager = CertificateManager()
    
    # Reset mocks to clear init calls
    mock_open_file.reset_mock()
    mock_serialization.load_pem_private_key.reset_mock()
    mock_x509.load_pem_x509_certificate.reset_mock()
    
    key, cert = manager.get_domain_cert("example.com")
    
    # Verify loading
    assert mock_open_file.call_count == 2 # read key, read cert
    mock_serialization.load_pem_private_key.assert_called()
    mock_x509.load_pem_x509_certificate.assert_called()

def test_get_domain_cert_generate(mock_path, mock_open_file, mock_rsa, mock_x509, mock_serialization):
    """Test generating new domain certificate."""
    mock_dir = MagicMock()
    mock_path.return_value = mock_dir
    
    # CA exists, Domain cert missing
    def exists_side_effect(arg):
        # This is tricky because __truediv__ returns a new mock each time usually
        # But we can check the path string if we could access it
        return True 
        
    # Simpler approach: Mock the paths directly
    ca_key = MagicMock()
    ca_key.exists.return_value = True
    ca_cert = MagicMock()
    ca_cert.exists.return_value = True
    
    domain_crt = MagicMock()
    domain_crt.exists.return_value = False # Trigger generation
    domain_key = MagicMock()
    domain_key.exists.return_value = False
    
    # Map paths
    mock_dir.__truediv__.side_effect = lambda p: {
        'ca.key': ca_key,
        'ca.crt': ca_cert,
        'example.com.crt': domain_crt,
        'example.com.key': domain_key
    }.get(p, MagicMock())

    manager = CertificateManager()
    
    # Reset mocks
    mock_rsa.generate_private_key.reset_mock()
    mock_open_file.reset_mock()
    
    key, cert = manager.get_domain_cert("example.com")
    
    # Verify generation
    mock_rsa.generate_private_key.assert_called()
    
    # Verify writing
    # Should write key and cert
    assert mock_open_file.call_count == 2
    handle = mock_open_file()
    handle.write.assert_called()