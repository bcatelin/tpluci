"""Unit tests for Phase 10: Direct Mesh Satellite Protocol Adapters (RE705X & RE300)."""

from __future__ import annotations

import hashlib
import json
from typing import Any
import pytest
import respx
import httpx
from click.testing import CliRunner
from cryptography.hazmat.primitives.asymmetric import padding, rsa

from tpluci.cli import cli
from tpluci.client import RouterClient
from tpluci.config import ResolvedCredentials, resolve_satellite_credentials
from tpluci.crypto import (
    DEFAULT_DICT,
    DEFAULT_KEY,
    aes_decrypt,
    aes_encrypt,
    rsa_encrypt_pkcs1_v15,
    sha256_hash,
    tp_xor_encrypt,
)
from tpluci.exceptions import AuthError, LuciApiError, SafetyAbortError
from tpluci.mcp_server import router_reboot_mesh_node
from tpluci.satellites import (
    HttpsLuciSatelliteClient,
    TddpSatelliteClient,
    connect_satellite,
)


@pytest.fixture(scope="module")
def rsa_test_key_pair():
    """Generate a test RSA 1024-bit key pair for verifying PKCS#1 v1.5 padding."""
    priv = rsa.generate_private_key(public_exponent=65537, key_size=1024)
    pub_nums = priv.public_key().public_numbers()
    nn_hex = f"{pub_nums.n:0256x}"
    ee_hex = f"{pub_nums.e:06x}"
    return priv, nn_hex, ee_hex


@pytest.fixture
def base_creds():
    return ResolvedCredentials(
        profile="default",
        url="http://192.168.1.1",
        username="admin",
        password="RouterPassword123",
        timeout=3.0,
        source="test",
    )


# =====================================================================
# 1. Crypto Extensions
# =====================================================================

def test_sha256_hash():
    sample = "adminPassword123"
    expected = hashlib.sha256(sample.encode("utf-8")).hexdigest().lower()
    assert sha256_hash(sample) == expected
    assert len(sha256_hash(sample)) == 64


def test_tp_xor_encrypt_default():
    enc = tp_xor_encrypt("admin")
    assert enc == "WaQ7xbhc9TefbwK"
    assert len(enc) == len(DEFAULT_KEY)


def test_tp_xor_encrypt_custom():
    custom_key = "SecretKey123"
    custom_dict = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
    enc = tp_xor_encrypt("testPassword", custom_key, custom_dict)
    assert isinstance(enc, str)
    assert len(enc) == max(len("testPassword"), len(custom_key))
    for c in enc:
        assert c in custom_dict


def test_rsa_encrypt_pkcs1_v15_decrypt(rsa_test_key_pair):
    priv, nn_hex, ee_hex = rsa_test_key_pair
    plaintext = "superSecretPassword"

    enc_hex = rsa_encrypt_pkcs1_v15(plaintext, nn_hex, ee_hex, chunk_size=53)
    assert len(enc_hex) == len(nn_hex)

    # Decrypt using cryptography's PKCS1v15 padding to verify compliance
    ciphertext_bytes = bytes.fromhex(enc_hex)
    decrypted_bytes = priv.decrypt(ciphertext_bytes, padding.PKCS1v15())
    assert decrypted_bytes.decode("utf-8") == plaintext


def test_rsa_encrypt_pkcs1_v15_chunking(rsa_test_key_pair):
    _, nn_hex, ee_hex = rsa_test_key_pair
    # A string longer than 53 bytes triggers chunking
    long_text = "A" * 75
    enc_hex = rsa_encrypt_pkcs1_v15(long_text, nn_hex, ee_hex, chunk_size=53)
    # Two chunks => 2 * len(nn_hex)
    assert len(enc_hex) == 2 * len(nn_hex)


# =====================================================================
# 2. Credential Resolution Hierarchy
# =====================================================================

def test_resolve_satellite_credentials_tier1_cli(base_creds):
    user, pwd = resolve_satellite_credentials(
        node_name="RE705X",
        node_ip="192.168.1.2",
        base_creds=base_creds,
        cli_user="sat_user@example.com",
        cli_password="SatPassword999",
    )
    assert user == "sat_user@example.com"
    assert pwd == "SatPassword999"


def test_resolve_satellite_credentials_tier1_env(monkeypatch, base_creds):
    monkeypatch.setenv("TPLUCI_SATELLITE_USER", "env_user@example.com")
    monkeypatch.setenv("TPLUCI_SATELLITE_PASSWORD", "EnvPassword888")

    user, pwd = resolve_satellite_credentials(
        node_name="RE705X",
        node_ip="192.168.1.2",
        base_creds=base_creds,
    )
    assert user == "env_user@example.com"
    assert pwd == "EnvPassword888"


def test_resolve_satellite_credentials_tier2_profile(monkeypatch, base_creds):
    monkeypatch.delenv("TPLUCI_SATELLITE_USER", raising=False)
    monkeypatch.delenv("TPLUCI_SATELLITE_PASSWORD", raising=False)
    monkeypatch.setattr(
        "tpluci.config.load_config",
        lambda: {
            "profiles": {
                "re705x": {
                    "username": "profile_user@example.com",
                    "password": "ProfilePassword777",
                    "use_keyring": False,
                }
            }
        },
    )

    user, pwd = resolve_satellite_credentials(
        node_name="RE705X",
        node_ip="192.168.1.2",
        base_creds=base_creds,
    )
    assert user == "profile_user@example.com"
    assert pwd == "ProfilePassword777"


def test_resolve_satellite_credentials_tier3_fallback(monkeypatch, base_creds):
    monkeypatch.delenv("TPLUCI_SATELLITE_USER", raising=False)
    monkeypatch.delenv("TPLUCI_SATELLITE_PASSWORD", raising=False)
    monkeypatch.setattr("tpluci.config.load_config", lambda: {"profiles": {}})

    user, pwd = resolve_satellite_credentials(
        node_name="RE705X",
        node_ip="192.168.1.2",
        base_creds=base_creds,
    )
    assert user == base_creds.username
    assert pwd == base_creds.password


# =====================================================================
# 3. HttpsLuciSatelliteClient (RE705X)
# =====================================================================

@respx.mock
def test_https_luci_satellite_client_local_flow(rsa_test_key_pair):
    _, nn_hex, ee_hex = rsa_test_key_pair
    extender_ip = "192.168.1.2"
    base = f"https://{extender_ip}"

    # Pre-flight
    respx.post(f"{base}/cgi-bin/luci/;stok=/login?form=check_factory_default").respond(
        json={"success": True, "data": {"cloud_ever_login": False}}
    )
    # RSA keys
    respx.post(f"{base}/cgi-bin/luci/;stok=/login?form=login", data={"operation": "read"}).respond(
        json={"success": True, "data": {"password": [nn_hex, ee_hex]}}
    )
    # Login
    respx.post(f"{base}/cgi-bin/luci/;stok=/login?form=login").respond(
        json={"success": True, "data": {"stok": "STOK_RE705X_123"}}
    )
    # Endpoints
    respx.post(f"{base}/cgi-bin/luci/;stok=STOK_RE705X_123/admin/system?form=reboot").respond(
        json={"success": True, "data": {}}
    )
    respx.post(f"{base}/cgi-bin/luci/;stok=STOK_RE705X_123/admin/ledgeneral?form=setting").respond(
        json={"success": True, "data": {"enable": "on"}}
    )
    respx.post(f"{base}/cgi-bin/luci/;stok=STOK_RE705X_123/admin/ledpm?form=setting").respond(
        json={"success": True, "data": {"enable": "off", "time_start": "22:00", "time_end": "07:00"}}
    )
    respx.post(f"{base}/cgi-bin/luci/;stok=STOK_RE705X_123/admin/easy_mesh?form=mesh_info").respond(
        json={"success": True, "data": {"led_sync_enable": "off"}}
    )
    respx.post(f"{base}/cgi-bin/luci/;stok=STOK_RE705X_123/admin/power?form=settings").respond(
        json={"success": True, "data": {"enable_power_schedule": "off"}}
    )
    respx.post(f"{base}/cgi-bin/luci/;stok=STOK_RE705X_123/admin/power?form=power_schedule").respond(
        json={"success": True, "data": {}}
    )
    respx.post(f"{base}/cgi-bin/luci/;stok=STOK_RE705X_123/admin/system?form=logout").respond(
        json={"success": True, "data": {}}
    )

    client = HttpsLuciSatelliteClient(ip=extender_ip, password="TestExtenderPassword")
    with client:
        assert client.stok == "STOK_RE705X_123"
        assert not client.cloud_ever_login

        # Reboot
        rb_res = client.reboot()
        assert rb_res["ok"] is True
        assert rb_res["reboot"] is True

        # LED Get
        led = client.get_led()
        assert led["led_enable"] is True
        assert led["night_mode"] is False
        assert led["time_start"] == "22:00"

        # LED Set (dry-run)
        led_dry = client.set_led(enable=False, night_mode=True, start="23:00", end="06:00", dry_run=True)
        assert led_dry["ok"] is True
        assert led_dry["dry_run"] is True
        assert led_dry["diff"]["led_enable"]["after"] is False

        # Schedule Get
        sched = client.get_schedule()
        assert sched["type"] == "power_schedule"
        assert sched["enabled"] is False

        # Schedule Set (dry-run)
        sched_dry = client.set_schedule(enable=True, dry_run=True)
        assert sched_dry["ok"] is True
        assert sched_dry["dry_run"] is True


@respx.mock
def test_https_luci_satellite_cloud_login_and_conflict(rsa_test_key_pair):
    _, nn_hex, ee_hex = rsa_test_key_pair
    extender_ip = "192.168.1.2"
    base = f"https://{extender_ip}"

    # Pre-flight returns cloud_ever_login = True
    respx.post(f"{base}/cgi-bin/luci/;stok=/login?form=check_factory_default").respond(
        json={"success": True, "data": {"cloud_ever_login": True}}
    )
    respx.post(f"{base}/cgi-bin/luci/;stok=/login?form=login", data={"operation": "read"}).respond(
        json={"success": True, "data": {"password": [nn_hex, ee_hex]}}
    )

    # First cloud_login attempt returns user conflict
    respx.post(f"{base}/cgi-bin/luci/;stok=/login?form=cloud_login").side_effect = [
        httpx.Response(200, json={"success": False, "errorcode": "user conflict"}),
        httpx.Response(200, json={"success": True, "data": {"stok": "STOK_CONFIRMED_777"}}),
    ]

    client = HttpsLuciSatelliteClient(
        ip=extender_ip,
        password="TestPassword",
        username="user@example.com",
    )
    client.login()
    assert client.stok == "STOK_CONFIRMED_777"
    assert client.cloud_ever_login is True


@respx.mock
def test_https_luci_satellite_auth_failure_cloud_hint(rsa_test_key_pair):
    _, nn_hex, ee_hex = rsa_test_key_pair
    extender_ip = "192.168.1.2"
    base = f"https://{extender_ip}"

    respx.post(f"{base}/cgi-bin/luci/;stok=/login?form=check_factory_default").respond(
        json={"success": True, "data": {"cloud_ever_login": True}}
    )
    respx.post(f"{base}/cgi-bin/luci/;stok=/login?form=login", data={"operation": "read"}).respond(
        json={"success": True, "data": {"password": [nn_hex, ee_hex]}}
    )
    # Login fails
    respx.post(f"{base}/cgi-bin/luci/;stok=/login?form=login").respond(
        json={"success": False, "errorcode": "login fail"}
    )

    client = HttpsLuciSatelliteClient(ip=extender_ip, password="WrongPassword")
    with pytest.raises(AuthError) as exc_info:
        client.login()

    assert "cloud_ever_login: true" in exc_info.value.hint
    assert "--satellite-user" in exc_info.value.hint


# =====================================================================
# 4. TddpSatelliteClient (RE300)
# =====================================================================

@respx.mock
def test_tddp_satellite_client_flow(rsa_test_key_pair):
    _, nn_hex, ee_hex = rsa_test_key_pair
    extender_ip = "192.168.1.3"
    base = f"http://{extender_ip}"

    respx.post(f"{base}/?code=16&asyn=0", content="enable").respond(text="00000\r\n")
    respx.post(f"{base}/?code=16&asyn=0", content="get").respond(
        text=f"00000\r\n{ee_hex}\r\n{nn_hex}\r\n1000\r\n"
    )
    respx.post(f"{base}/?code=7&asyn=1").respond(
        status_code=401,
        text="00001\r\nstatus\r\nmsg\r\nAUTH_KEY_TEST\r\nAUTH_DICT_TEST\r\n",
    )
    # Successful local challenge auth
    respx.post(url__regex=rf"{base}/\?code=7&asyn=0&id=.+").respond(text="00000\r\n")
    # AES key sync
    respx.post(url__regex=rf"{base}/\?code=16&asyn=0&id=.+").respond(text="00000\r\n")

    # Mocks for TDDP operations (read/write/reboot/logout)
    client = TddpSatelliteClient(ip=extender_ip, password="ExtenderPassword300")
    client.login()
    assert client.token is not None

    def tddp_read_handler(request: httpx.Request) -> httpx.Response:
        body = request.content.decode("utf-8")
        pairs = dict(l.split("=", 1) for l in body.splitlines() if "=" in l)
        data_enc = pairs.get("data", "")
        plain = aes_decrypt(data_enc, client.aes_key, client.aes_iv)
        if "112|" in plain:
            enc = aes_encrypt("id 112|1,0,0\r\nenable 1\r\n", client.aes_key, client.aes_iv)
        elif "113|" in plain:
            enc = aes_encrypt(
                "id 113|1,0,0\r\nenable 0\r\ntimeStart 22:30\r\ntimeEnd 06:30\r\n",
                client.aes_key,
                client.aes_iv,
            )
        elif "114|" in plain:
            enc = aes_encrypt(
                "id 114|1,0,0\r\nenable 1\r\ncycle 2\r\ntime 04:00\r\nday Tues\r\n",
                client.aes_key,
                client.aes_iv,
            )
        else:
            enc = aes_encrypt("00000\r\n", client.aes_key, client.aes_iv)
        return httpx.Response(200, text=f"00000\r\n{enc}\r\n")

    respx.post(url__regex=rf"{base}/\?code=2&asyn=0&id=.+").mock(side_effect=tddp_read_handler)
    respx.post(url__regex=rf"{base}/\?code=1&asyn=0&id=.+").respond(text="00000\r\n")
    respx.post(url__regex=rf"{base}/\?code=6&asyn=1&id=.+").respond(text="00000\r\n")
    respx.post(url__regex=rf"{base}/\?code=11&asyn=0&id=.+").respond(text="00000\r\n")

    # LED Get
    led = client.get_led()
    assert led["led_enable"] is True
    assert led["night_mode"] is False
    assert led["time_start"] == "22:30"
    assert led["time_end"] == "06:30"

    # LED Set (dry run and live)
    diff_dry = client.set_led(enable=False, dry_run=True)
    assert diff_dry["ok"] is True
    assert diff_dry["dry_run"] is True

    # Reboot schedule Get
    sched = client.get_schedule()
    assert sched["type"] == "reboot_schedule"
    assert sched["enabled"] is True
    assert sched["cycle"] == "week"
    assert sched["day"] == "Tues"
    assert sched["time"] == "04:00"

    # Reboot schedule Set (dry run and live)
    sched_dry = client.set_schedule(enable=False, dry_run=True)
    assert sched_dry["ok"] is True
    assert sched_dry["dry_run"] is True

    # Reboot
    rb = client.reboot()
    assert rb["ok"] is True
    assert rb["reboot"] is True

    client.logout()


@respx.mock
def test_tddp_satellite_cloud_binded_error(rsa_test_key_pair):
    _, nn_hex, ee_hex = rsa_test_key_pair
    extender_ip = "192.168.1.3"
    base = f"http://{extender_ip}"

    respx.post(f"{base}/?code=16&asyn=0", content="enable").respond(text="00000\r\n")
    respx.post(f"{base}/?code=16&asyn=0", content="get").respond(
        text=f"00000\r\n{ee_hex}\r\n{nn_hex}\r\n1000\r\n"
    )
    respx.post(f"{base}/?code=7&asyn=1").respond(
        status_code=401,
        text="00001\r\nstatus\r\nmsg\r\nAUTH_KEY_TEST\r\nAUTH_DICT_TEST\r\n",
    )
    # Auth fails
    respx.post(url__regex=rf"{base}/\?code=7&asyn=0&id=.+").respond(
        status_code=200, text="00001\r\nAuth Error\r\n"
    )
    # Probe block 68 returns isBinded 1
    respx.post(f"{base}/?code=2&asyn=0", content="68|1,0,0\r\n").respond(
        status_code=200, text="68|1,0,0\r\nisBinded 1\r\n"
    )

    client = TddpSatelliteClient(ip=extender_ip, password="WrongPassword")
    with pytest.raises(AuthError) as exc_info:
        client.login()

    assert "isBinded: 1" in exc_info.value.hint
    assert "--satellite-user" in exc_info.value.hint


# =====================================================================
# 5. connect_satellite Auto-Detection
# =====================================================================

@respx.mock
def test_connect_satellite_auto_detect_https(rsa_test_key_pair):
    _, nn_hex, ee_hex = rsa_test_key_pair
    extender_ip = "192.168.1.2"
    base = f"https://{extender_ip}"

    # Probe succeeds on HTTPS
    respx.post(f"{base}/cgi-bin/luci/;stok=/login?form=login", data={"operation": "read"}).respond(
        json={"success": True, "data": {"password": [nn_hex, ee_hex]}}
    )
    respx.post(f"{base}/cgi-bin/luci/;stok=/login?form=check_factory_default").respond(
        json={"success": True, "data": {"cloud_ever_login": False}}
    )
    respx.post(f"{base}/cgi-bin/luci/;stok=/login?form=login").respond(
        json={"success": True, "data": {"stok": "STOK_DETECT_123"}}
    )

    sat = connect_satellite(extender_ip, password="ExtenderPassword")
    assert isinstance(sat, HttpsLuciSatelliteClient)
    assert sat.stok == "STOK_DETECT_123"


@respx.mock
def test_connect_satellite_auto_detect_tddp(rsa_test_key_pair):
    _, nn_hex, ee_hex = rsa_test_key_pair
    extender_ip = "192.168.1.3"
    base_http = f"http://{extender_ip}"
    base_https = f"https://{extender_ip}"

    # HTTPS probe fails
    respx.post(f"{base_https}/cgi-bin/luci/;stok=/login?form=login").side_effect = httpx.ConnectError("refused")

    # HTTP probe succeeds
    respx.post(f"{base_http}/?code=2&asyn=0", content="0|1,0,0\r\n").respond(text="00000\r\n")
    respx.post(f"{base_http}/?code=16&asyn=0", content="enable").respond(text="00000\r\n")
    respx.post(f"{base_http}/?code=16&asyn=0", content="get").respond(
        text=f"00000\r\n{ee_hex}\r\n{nn_hex}\r\n1000\r\n"
    )
    respx.post(f"{base_http}/?code=7&asyn=1").respond(
        status_code=401,
        text="00001\r\nstatus\r\nmsg\r\nKEY\r\nDICT\r\n",
    )
    respx.post(url__regex=rf"{base_http}/\?code=7&asyn=0&id=.+").respond(text="00000\r\n")
    respx.post(url__regex=rf"{base_http}/\?code=16&asyn=0&id=.+").respond(text="00000\r\n")

    sat = connect_satellite(extender_ip, password="ExtenderPassword")
    assert isinstance(sat, TddpSatelliteClient)
    assert sat.token is not None


@respx.mock
def test_connect_satellite_unreachable():
    extender_ip = "192.168.1.99"
    respx.post(f"https://{extender_ip}/cgi-bin/luci/;stok=/login?form=login").side_effect = httpx.ConnectError("refused")
    respx.post(f"http://{extender_ip}/?code=2&asyn=0").side_effect = httpx.ConnectError("refused")

    with pytest.raises(LuciApiError) as exc_info:
        connect_satellite(extender_ip, password="ExtenderPassword")

    assert exc_info.value.error_code == "SATELLITE_NOT_REACHABLE"


# =====================================================================
# 6. CLI Mesh Satellite Commands
# =====================================================================

@pytest.fixture
def mock_router_client(monkeypatch):
    class FakeClient:
        def __init__(self, *args, **kwargs):
            self.creds = ResolvedCredentials(
                profile="default",
                url="http://192.168.1.1",
                username="admin",
                password="RouterPassword123",
                timeout=3.0,
                source="test",
            )

        def call(self, module, form, operation="read", params=None):
            if module == "easymesh_network" and form == "mesh_sclient_list_all":
                return [
                    {
                        "name": "RE705X",
                        "model": "RE705X",
                        "ip": "192.168.1.2",
                        "mac": "00:11:22:33:44:02",
                        "location": "office",
                        "connect_type": "wire",
                        "signal_strength": -254,
                        "client_num": 2,
                        "status": "online",
                    },
                    {
                        "name": "RE300",
                        "model": "RE300",
                        "ip": "192.168.1.3",
                        "mac": "00:11:22:33:44:03",
                        "location": "bedroom",
                        "connect_type": "wireless",
                        "signal_strength": -55,
                        "client_num": 1,
                        "status": "online",
                    },
                ]
            return {}

    monkeypatch.setattr("tpluci.cli.get_client", lambda ctx: FakeClient())
    return FakeClient()


def test_cli_mesh_reboot_non_interactive_aborts(mock_router_client):
    runner = CliRunner()
    result = runner.invoke(cli, ["mesh", "reboot", "RE705X"])
    assert result.exit_code == 5
    assert "Refusing to reboot satellite 'RE705X' in non-interactive environment without --confirm" in result.output


def test_cli_mesh_reboot_dry_run(mock_router_client):
    runner = CliRunner()
    result = runner.invoke(cli, ["mesh", "reboot", "RE705X", "--confirm", "--dry-run"])
    assert result.exit_code == 0
    assert "[DRY-RUN] Simulated reboot for satellite RE705X (192.168.1.2)" in result.output


def test_cli_mesh_reboot_dry_run_json(mock_router_client):
    runner = CliRunner()
    result = runner.invoke(cli, ["mesh", "reboot", "RE705X", "--confirm", "--dry-run", "--json"])
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["ok"] is True
    assert data["dry_run"] is True
    assert data["reboot"] is True
    assert data["node"] == "RE705X"


def test_cli_mesh_led_inspect(mock_router_client, monkeypatch):
    class FakeSatellite:
        def get_led(self):
            return {
                "led_enable": True,
                "night_mode": True,
                "time_start": "22:00",
                "time_end": "07:00",
                "led_sync_enable": False,
            }

        def logout(self):
            pass

    monkeypatch.setattr("tpluci.satellites.connect_satellite", lambda *args, **kwargs: FakeSatellite())

    runner = CliRunner()
    result = runner.invoke(cli, ["mesh", "led", "RE705X"])
    assert result.exit_code == 0
    assert "Status LED" in result.output
    assert "Night Mode" in result.output


def test_cli_mesh_led_mutation_dry_run(mock_router_client, monkeypatch):
    class FakeSatellite:
        def get_led(self):
            return {"led_enable": True, "night_mode": False, "time_start": "", "time_end": ""}

        def set_led(self, **kwargs):
            return {
                "ok": True,
                "dry_run": True,
                "changed": True,
                "diff": {"led_enable": {"before": True, "after": False}},
            }

        def logout(self):
            pass

    monkeypatch.setattr("tpluci.satellites.connect_satellite", lambda *args, **kwargs: FakeSatellite())

    runner = CliRunner()
    result = runner.invoke(cli, ["mesh", "led", "RE705X", "--off", "--dry-run"])
    assert result.exit_code == 0
    assert "[DRY-RUN]" in result.output
    assert "led_enable: True -> False" in result.output


def test_cli_mesh_reboot_schedule_inspect(mock_router_client, monkeypatch):
    class FakeSatellite:
        def get_schedule(self):
            return {
                "type": "reboot_schedule",
                "enabled": True,
                "cycle": "week",
                "day": "Tues",
                "time": "03:00",
            }

        def logout(self):
            pass

    monkeypatch.setattr("tpluci.satellites.connect_satellite", lambda *args, **kwargs: FakeSatellite())

    runner = CliRunner()
    result = runner.invoke(cli, ["mesh", "reboot-schedule", "RE300"])
    assert result.exit_code == 0
    assert "Schedule Type" in result.output
    assert "Tues" in result.output


def test_cli_mesh_reboot_schedule_mutation_dry_run(mock_router_client, monkeypatch):
    class FakeSatellite(TddpSatelliteClient):
        def __init__(self):
            pass

        def get_schedule(self):
            return {"type": "reboot_schedule", "enabled": False, "cycle": "day", "day": "", "time": ""}

        def set_schedule(self, **kwargs):
            return {
                "ok": True,
                "dry_run": True,
                "changed": True,
                "diff": {"enabled": {"before": False, "after": True}},
            }

        def logout(self):
            pass

    monkeypatch.setattr("tpluci.satellites.connect_satellite", lambda *args, **kwargs: FakeSatellite())

    runner = CliRunner()
    result = runner.invoke(cli, ["mesh", "reboot-schedule", "RE300", "--enable", "--dry-run"])
    assert result.exit_code == 0
    assert "[DRY-RUN]" in result.output
    assert "enabled: False -> True" in result.output


# =====================================================================
# 7. MCP Tool: router_reboot_mesh_node
# =====================================================================

def test_mcp_router_reboot_mesh_node_confirm_guard():
    res = router_reboot_mesh_node("RE705X", confirm=False)
    assert res["ok"] is False
    assert res["error_code"] == "SAFETY_ABORT"


def test_mcp_router_reboot_mesh_node_dry_run(monkeypatch):
    class FakeClient:
        def __init__(self, *args, **kwargs):
            self.creds = ResolvedCredentials(
                profile="default",
                url="http://192.168.1.1",
                username="admin",
                password="RouterPassword123",
                timeout=3.0,
                source="test",
            )

        def call(self, module, form, operation="read", params=None):
            return [
                {
                    "name": "RE705X",
                    "model": "RE705X",
                    "ip": "192.168.1.2",
                    "mac": "00:11:22:33:44:02",
                    "status": "online",
                }
            ]

    monkeypatch.setattr("tpluci.mcp_server._get_client", lambda: FakeClient())

    res = router_reboot_mesh_node("RE705X", confirm=True, dry_run=True)
    assert res["ok"] is True
    assert res["dry_run"] is True
    assert res["reboot"] is True
    assert res["node"] == "RE705X"


def test_mcp_router_reboot_mesh_node_live(monkeypatch):
    class FakeClient:
        def __init__(self, *args, **kwargs):
            self.creds = ResolvedCredentials(
                profile="default",
                url="http://192.168.1.1",
                username="admin",
                password="RouterPassword123",
                timeout=3.0,
                source="test",
            )

        def call(self, module, form, operation="read", params=None):
            return [
                {
                    "name": "RE705X",
                    "model": "RE705X",
                    "ip": "192.168.1.2",
                    "mac": "00:11:22:33:44:02",
                    "status": "online",
                }
            ]

    class FakeSatellite:
        def reboot(self):
            return {"ok": True, "reboot": True, "message": "Reboot command sent to satellite."}

        def logout(self):
            pass

    monkeypatch.setattr("tpluci.mcp_server._get_client", lambda: FakeClient())
    monkeypatch.setattr("tpluci.mcp_server.connect_satellite", lambda *args, **kwargs: FakeSatellite())

    res = router_reboot_mesh_node("RE705X", confirm=True, dry_run=False)
    assert res["ok"] is True
    assert res["reboot"] is True
    assert res["node"] == "RE705X"
