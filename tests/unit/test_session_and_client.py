"""Unit tests for tpluci session caching and RouterClient."""

import json
import time
from pathlib import Path
import pytest
import respx
import httpx
from cryptography.hazmat.primitives.asymmetric import rsa

from tpluci.client import RouterClient
from tpluci.config import ResolvedCredentials
from tpluci.crypto import aes_decrypt, aes_encrypt
from tpluci.exceptions import AuthError, LuciApiError, NetworkError
from tpluci.session import SessionCache, SessionData


@pytest.fixture(scope="module")
def mock_rsa_keys():
    """Generate 1024-bit RSA key for keys and auth mocking."""
    priv = rsa.generate_private_key(public_exponent=65537, key_size=1024)
    pub_nums = priv.public_key().public_numbers()
    nn = f"{pub_nums.n:0256x}"
    ee = f"{pub_nums.e:06x}"
    return priv, nn, ee


@pytest.fixture
def test_creds():
    return ResolvedCredentials(
        profile="test_profile",
        url="http://192.0.2.1",
        username="admin",
        password="TestPassword123",
        timeout=2.0,
        source="test",
    )


def test_session_cache_lifecycle(tmp_path, monkeypatch):
    monkeypatch.setattr("tempfile.gettempdir", lambda: str(tmp_path))

    # Initial state: no cache
    assert SessionCache.load("test_profile") is None

    session = SessionData(
        stok="test_stok_12345",
        aes_key="1234567890123456",
        aes_iv="6543210987654321",
        seq=5000,
        password_hash="testhash",
        nn_auth="AA" * 64,
        ee_auth="010001",
        cookies={"sysauth": "token123"},
        updated_at=time.time(),
    )

    SessionCache.save("test_profile", session)
    cache_path = SessionCache.get_cache_path("test_profile")
    assert cache_path.is_file()
    assert oct(cache_path.stat().st_mode & 0o777) == "0o600"

    # Load back
    loaded = SessionCache.load("test_profile")
    assert loaded is not None
    assert loaded.stok == "test_stok_12345"
    assert loaded.aes_key == "1234567890123456"

    # Expired TTL
    expired = SessionCache.load("test_profile", ttl=0.001)
    time.sleep(0.01)
    assert SessionCache.load("test_profile", ttl=0.001) is None

    # Clear
    SessionCache.save("test_profile", session)
    assert SessionCache.clear("test_profile") is True
    assert not cache_path.is_file()


@respx.mock
def test_client_full_login_and_call(test_creds, mock_rsa_keys, tmp_path, monkeypatch):
    monkeypatch.setattr("tempfile.gettempdir", lambda: str(tmp_path))
    priv, nn, ee = mock_rsa_keys

    # 1. Mock /login?form=keys
    respx.post("http://192.0.2.1/cgi-bin/luci/;stok=/login?form=keys").respond(
        status_code=200,
        json={"success": True, "data": {"password": [nn, ee]}},
    )

    # 2. Mock /login?form=auth
    respx.post("http://192.0.2.1/cgi-bin/luci/;stok=/login?form=auth").respond(
        status_code=200,
        json={"success": True, "data": {"key": [nn, ee], "seq": 1000}},
    )

    # 3. Dynamic Mock /login?form=login (extracts client's AES key to encrypt response)
    def login_side_effect(request):
        form_data = dict(urllib_parse_qsl(request.content.decode("utf-8")))
        sign = form_data["sign"]
        # Decrypt first chunk of signature to get aes key & iv
        raw_first_chunk = bytes.fromhex(sign[:256])
        from cryptography.hazmat.primitives.asymmetric import padding as asym_padding

        sign_plain_part = priv.decrypt(raw_first_chunk, asym_padding.PKCS1v15()).decode("utf-8")
        # sign_plain starts with k=<key>&i=<iv>
        parts = sign_plain_part.split("&")
        key = parts[0].split("=")[1]
        iv = parts[1].split("=")[1]

        # Return encrypted stok
        resp_payload = json.dumps({"success": True, "data": {"stok": "mocked_stok_999"}})
        resp_enc = aes_encrypt(resp_payload, key, iv)
        return httpx.Response(200, json={"success": True, "data": resp_enc})

    def urllib_parse_qsl(qs):
        import urllib.parse
        return urllib.parse.parse_qsl(qs)

    respx.post("http://192.0.2.1/cgi-bin/luci/;stok=/login?form=login").mock(side_effect=login_side_effect)

    # 4. Mock /admin/status?form=internet
    def status_side_effect(request):
        # We need the client's AES key; let's inspect active session cache
        session = SessionCache.load("test_profile")
        resp_payload = json.dumps({
            "success": True,
            "data": {"wan_internet_status": "connected"},
        })
        resp_enc = aes_encrypt(resp_payload, session.aes_key, session.aes_iv)
        return httpx.Response(200, json={"success": True, "data": resp_enc})

    respx.post("http://192.0.2.1/cgi-bin/luci/;stok=mocked_stok_999/admin/status?form=internet").mock(
        side_effect=status_side_effect
    )

    client = RouterClient(creds=test_creds, rate_limit_delay=0.0)
    data = client.call("status", "internet")
    assert data == {"wan_internet_status": "connected"}

    # Second call should use session cache
    data2 = client.call("status", "internet")
    assert data2 == {"wan_internet_status": "connected"}


@respx.mock
def test_client_read_modify_write_dry_run(test_creds, mock_rsa_keys, tmp_path, monkeypatch):
    monkeypatch.setattr("tempfile.gettempdir", lambda: str(tmp_path))
    priv, nn, ee = mock_rsa_keys

    # Seed an active session into cache
    session = SessionData(
        stok="stok_rmw",
        aes_key="1111222233334444",
        aes_iv="5555666677778888",
        seq=2000,
        password_hash="pwd_hash",
        nn_auth=nn,
        ee_auth=ee,
        cookies={},
        updated_at=time.time(),
    )
    SessionCache.save("test_profile", session)

    current_state = {"enable": "off", "ssid": "OldGuest", "channel": "6"}

    # Mock read
    def read_side_effect(request):
        payload = json.dumps({"success": True, "data": current_state})
        enc = aes_encrypt(payload, session.aes_key, session.aes_iv)
        return httpx.Response(200, json={"success": True, "data": enc})

    respx.post("http://192.0.2.1/cgi-bin/luci/;stok=stok_rmw/admin/wireless?form=guest_2g").mock(
        side_effect=read_side_effect
    )

    client = RouterClient(creds=test_creds, rate_limit_delay=0.0)

    # Dry-run update
    result_dry = client.read_modify_write(
        "wireless",
        "guest_2g",
        updates={"enable": "on", "ssid": "NewGuest"},
        dry_run=True,
    )
    assert result_dry["dry_run"] is True
    assert result_dry["changed"] is True
    assert result_dry["diff"] == {
        "enable": {"before": "off", "after": "on"},
        "ssid": {"before": "OldGuest", "after": "NewGuest"},
    }
    assert result_dry["state"]["channel"] == "6"


@respx.mock
def test_client_no_such_callback(test_creds, mock_rsa_keys, tmp_path, monkeypatch):
    monkeypatch.setattr("tempfile.gettempdir", lambda: str(tmp_path))
    priv, nn, ee = mock_rsa_keys

    session = SessionData(
        stok="stok_err",
        aes_key="1111222233334444",
        aes_iv="5555666677778888",
        seq=2000,
        password_hash="pwd_hash",
        nn_auth=nn,
        ee_auth=ee,
        cookies={},
        updated_at=time.time(),
    )
    SessionCache.save("test_profile", session)

    respx.post("http://192.0.2.1/cgi-bin/luci/;stok=stok_err/admin/invalid?form=bad").respond(
        status_code=200,
        json={"errorcode": "no such callback", "success": False},
    )

    client = RouterClient(creds=test_creds, rate_limit_delay=0.0)
    with pytest.raises(LuciApiError) as exc_info:
        client.call("invalid", "bad")

    err = exc_info.value
    assert err.error_code == "LUCI_NO_CALLBACK"
    assert "not supported" in err.message
    assert "call --list" in err.hint


@respx.mock
def test_client_rmw_strips_nested_extinfo_on_write(test_creds, mock_rsa_keys, tmp_path, monkeypatch):
    monkeypatch.setattr("tempfile.gettempdir", lambda: str(tmp_path))
    priv, nn, ee = mock_rsa_keys

    session = SessionData(
        stok="stok_rmw2",
        aes_key="1111222233334444",
        aes_iv="5555666677778888",
        seq=2000,
        password_hash="pwd_hash",
        nn_auth=nn,
        ee_auth=ee,
        cookies={},
        updated_at=time.time(),
    )
    SessionCache.save("test_profile", session)

    current_state = {
        "enable": "off",
        "ssid": "OldGuest",
        "extinfo": {"support_band": "both", "wds_guest_compatible": "yes"},
    }
    captured_writes = []

    def rw_side_effect(request):
        import urllib.parse
        form_data = dict(urllib.parse.parse_qsl(request.content.decode("utf-8")))
        dec_body = aes_decrypt(form_data["data"], session.aes_key, session.aes_iv)
        parsed_params = dict(urllib.parse.parse_qsl(dec_body))
        if parsed_params.get("operation") == "write":
            captured_writes.append(parsed_params)
        payload = json.dumps({"success": True, "data": current_state})
        enc = aes_encrypt(payload, session.aes_key, session.aes_iv)
        return httpx.Response(200, json={"success": True, "data": enc})

    respx.post("http://192.0.2.1/cgi-bin/luci/;stok=stok_rmw2/admin/wireless?form=guest_2g").mock(
        side_effect=rw_side_effect
    )

    client = RouterClient(creds=test_creds, rate_limit_delay=0.0)
    client.read_modify_write("wireless", "guest_2g", updates={"enable": "on"}, dry_run=False)
    assert len(captured_writes) == 1
    assert "extinfo" not in captured_writes[0]
    assert captured_writes[0]["enable"] == "on"


@respx.mock
def test_client_auth_timeout_raises_network_error(test_creds, mock_rsa_keys, tmp_path, monkeypatch):
    monkeypatch.setattr("tempfile.gettempdir", lambda: str(tmp_path))
    priv, nn, ee = mock_rsa_keys

    respx.post("http://192.0.2.1/cgi-bin/luci/;stok=/login?form=keys").respond(
        status_code=200,
        json={"success": True, "data": {"password": [nn, ee]}},
    )
    respx.post("http://192.0.2.1/cgi-bin/luci/;stok=/login?form=auth").mock(
        side_effect=httpx.ReadTimeout("timed out")
    )

    client = RouterClient(creds=test_creds, use_cache=False, rate_limit_delay=0.0)
    with pytest.raises(NetworkError) as exc_info:
        client.login()
    assert exc_info.value.error_code == "NETWORK_TIMEOUT"
