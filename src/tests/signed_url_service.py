import os
import time
import pytest
from fastapi import HTTPException
from sandbox.services.signed_url_service import SignedUrlService, SignedUrlRequest


@pytest.fixture
def signed_url_service(tmpdir):
    # Setup a temporary directory for testing
    storage_path = tmpdir.mkdir("secure_storage")
    secret_key = "test_secret_key"
    return SignedUrlService(secret_key=secret_key, storage_path=str(storage_path))


@pytest.fixture
def test_file(tmp_path):
    # Create a temporary directory for tests
    test_dir = tmp_path / "secure_storage"
    test_dir.mkdir(exist_ok=True)

    # Create an actual test file
    file_path = test_dir / "test_file.txt"
    file_path.write_text("This is test content")

    # Return the path to the test file
    return str(file_path)


def test_generate_signed_url_valid_file(signed_url_service, test_file):
    # Test generating a signed URL for a valid file
    request = SignedUrlRequest(filename=os.path.basename(test_file))
    signed_url = signed_url_service.generate_signed_url(request)

    # Check if the signed URL contains the expected components
    assert "/files/test_file.txt?" in signed_url
    assert "sig=" in signed_url
    assert "exp=" in signed_url


def test_generate_signed_url_file_not_found(signed_url_service):
    # Test generating a signed URL for a non-existent file
    request = SignedUrlRequest(filename="non_existent_file.txt")

    with pytest.raises(HTTPException) as exc_info:
        signed_url_service.generate_signed_url(request)

    assert exc_info.value.status_code == 404
    assert "File not found" in str(exc_info.value.detail)


def test_generate_signed_url_invalid_filename(signed_url_service):
    # Test generating a signed URL with an invalid filename
    request = SignedUrlRequest(filename="../invalid_path.txt")

    with pytest.raises(HTTPException) as exc_info:
        signed_url_service.generate_signed_url(request)

    assert exc_info.value.status_code == 404
    assert "File not found" in str(exc_info.value.detail)


def test_validate_signed_url_valid(signed_url_service, test_file):
    # Test validating a correctly signed URL
    request = SignedUrlRequest(filename=os.path.basename(test_file))
    signed_url = signed_url_service.generate_signed_url(request)

    # Extract signature and expiry from the signed URL
    sig = signed_url.split("sig=")[1].split("&")[0]
    exp = int(signed_url.split("exp=")[1])

    # Check validation
    assert signed_url_service.validate_url(os.path.basename(test_file), sig, exp)


def test_validate_signed_url_expired(signed_url_service, test_file):
    # Test validating an expired signed URL
    request = SignedUrlRequest(filename=os.path.basename(test_file))
    signed_url = signed_url_service.generate_signed_url(request)

    # Extract signature and expiry from the signed URL
    sig = signed_url.split("sig=")[1].split("&")[0]
    exp = int(signed_url.split("exp=")[1])

    # Simulate time passing
    time.sleep(2)  # Ensure the URL expires

    with pytest.raises(HTTPException) as exc_info:
        signed_url_service.validate_url(os.path.basename(test_file), sig, exp)

    assert exc_info.value.status_code == 403
    assert "URL expired" in str(exc_info.value.detail)


def test_validate_signed_url_invalid_signature(signed_url_service, test_file):
    # Test validating a signed URL with an invalid signature
    request = SignedUrlRequest(filename=os.path.basename(test_file))
    signed_url = signed_url_service.generate_signed_url(request)

    # Extract expiry from the signed URL
    exp = int(signed_url.split("exp=")[1])

    # Use an invalid signature
    invalid_sig = "invalid_signature"

    with pytest.raises(HTTPException) as exc_info:
        signed_url_service.validate_url(os.path.basename(test_file), invalid_sig, exp)

    assert exc_info.value.status_code == 403
    assert "Invalid signature" in str(exc_info.value.detail)


def test_validate_signed_url_file_not_found(signed_url_service):
    # Test validating a signed URL for a non-existent file
    with pytest.raises(HTTPException) as exc_info:
        signed_url_service.validate_url(
            "non_existent_file.txt", "fake_sig", int(time.time()) + 3600
        )

    assert exc_info.value.status_code == 404
    assert "File not found" in str(exc_info.value.detail)


def test_rate_limiting(signed_url_service, test_file):
    # Test rate limiting
    request = SignedUrlRequest(filename=os.path.basename(test_file), client_ip="192.168.1.1")

    # Generate URLs until rate limit is exceeded
    for _ in range(100):
        signed_url_service.generate_signed_url(request)

    # The 101st request should fail
    with pytest.raises(HTTPException) as exc_info:
        signed_url_service.generate_signed_url(request)

    assert exc_info.value.status_code == 429
    assert "Rate limit exceeded" in str(exc_info.value.detail)


def test_custom_expiry(signed_url_service, test_file):
    # Test custom expiry time
    custom_expiry = 60  # 1 minute
    request = SignedUrlRequest(filename=os.path.basename(test_file), custom_expiry=custom_expiry)
    signed_url = signed_url_service.generate_signed_url(request)

    # Extract expiry from the signed URL
    exp = int(signed_url.split("exp=")[1])

    # Check if the expiry time is within the expected range
    assert exp == int(time.time()) + custom_expiry


def test_max_expiry(signed_url_service, test_file):
    # Test maximum expiry time
    custom_expiry = 100000  # Exceeds the default max_expiry of 86400
    request = SignedUrlRequest(filename=os.path.basename(test_file), custom_expiry=custom_expiry)
    signed_url = signed_url_service.generate_signed_url(request)

    # Extract expiry from the signed URL
    exp = int(signed_url.split("exp=")[1])

    # Check if the expiry time is capped at max_expiry
    assert exp == int(time.time()) + 86400
