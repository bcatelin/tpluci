"""Unit tests for tpluci 4-tier configuration and credential resolution."""

import json
import os
from pathlib import Path
import pytest

from tpluci.config import (
    DEFAULT_PROFILE,
    DEFAULT_ROUTER_URL,
    delete_profile,
    get_config_path,
    list_profiles,
    resolve_credentials,
    save_config,
    save_profile,
    set_default_profile,
)
from tpluci.exceptions import AuthError, EXIT_AUTH_ERROR


@pytest.fixture(autouse=True)
def clean_env(monkeypatch, tmp_path):
    """Ensure clean environment for each test pointing to a fresh temporary config directory."""
    config_dir = tmp_path / "tpluci_config"
    config_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("TPLUCI_CONFIG_DIR", str(config_dir))

    # Clear router env vars
    for k in ["ROUTER_PASSWORD", "TPLUCI_PASSWORD", "ROUTER_URL", "TPLUCI_URL", "ROUTER_USERNAME", "TPLUCI_USERNAME", "ROUTER_TIMEOUT", "TPLUCI_TIMEOUT", "TPLUCI_PROFILE", "ROUTER_PROFILE"]:
        monkeypatch.delenv(k, raising=False)

    # Change working directory to empty tmp_path so local ./.env is not found
    work_dir = tmp_path / "work"
    work_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.chdir(work_dir)


def test_tier1_env_vars(monkeypatch):
    monkeypatch.setenv("ROUTER_PASSWORD", "env_secret_123")
    monkeypatch.setenv("ROUTER_URL", "http://192.168.1.1")
    monkeypatch.setenv("ROUTER_USERNAME", "admin_env")
    monkeypatch.setenv("ROUTER_TIMEOUT", "8.5")

    creds = resolve_credentials()
    assert creds.source == "env"
    assert creds.password == "env_secret_123"
    assert creds.url == "http://192.168.1.1"
    assert creds.username == "admin_env"
    assert creds.timeout == 8.5
    assert creds.warning is None


def test_tier2_dotenv_local(monkeypatch, tmp_path):
    work_dir = tmp_path / "work"
    dotenv_file = work_dir / ".env"
    dotenv_file.write_text("PASSWORD=dotenv_secret_456\nROUTER_URL=http://10.0.0.1\n")

    creds = resolve_credentials()
    assert creds.source == "dotenv"
    assert creds.password == "dotenv_secret_456"
    assert creds.url == "http://10.0.0.1"


def test_tier2_dotenv_config_dir(monkeypatch, tmp_path):
    cfg_dir = tmp_path / "tpluci_config"
    dotenv_file = cfg_dir / ".env"
    dotenv_file.write_text("ROUTER_PASSWORD=cfg_dotenv_pwd\n")

    creds = resolve_credentials()
    assert creds.source == "dotenv"
    assert creds.password == "cfg_dotenv_pwd"
    assert creds.url == DEFAULT_ROUTER_URL


def test_tier3_keyring(monkeypatch):
    # Simulate keyring storing password
    mock_vault = {"default": "keyring_secret_789"}
    monkeypatch.setattr("keyring.get_password", lambda service, user: mock_vault.get(user))

    # Profile exists in config pointing to keyring
    save_config({
        "default_profile": "default",
        "profiles": {
            "default": {
                "url": "http://192.168.7.250",
                "use_keyring": True,
            }
        },
    })

    creds = resolve_credentials()
    assert creds.source == "keyring"
    assert creds.password == "keyring_secret_789"
    assert creds.url == "http://192.168.7.250"
    assert creds.warning is None


def test_tier4_config_file_fallback(monkeypatch):
    # Keyring throws an error or is unavailable
    monkeypatch.setattr("keyring.get_password", lambda service, user: (_ for _ in ()).throw(RuntimeError("No D-Bus")))

    save_config({
        "default_profile": "default",
        "profiles": {
            "default": {
                "url": "http://192.168.7.250",
                "password": "plaintext_conf_password",
                "use_keyring": True,
            }
        },
    })

    creds = resolve_credentials()
    assert creds.source == "config_file"
    assert creds.password == "plaintext_conf_password"
    assert creds.warning is not None
    assert "plaintext password storage" in creds.warning


def test_auth_missing_raises_actionable_error():
    with pytest.raises(AuthError) as exc_info:
        resolve_credentials()

    err = exc_info.value
    assert err.exit_code == EXIT_AUTH_ERROR
    assert err.error_code == "AUTH_MISSING"
    assert "tpluci config add" in err.hint


def test_url_and_timeout_overrides(monkeypatch):
    monkeypatch.setenv("ROUTER_PASSWORD", "secret")
    creds = resolve_credentials(url_override="http://custom-router.lan", timeout_override=12.0)
    assert creds.url == "http://custom-router.lan"
    assert creds.timeout == 12.0


def test_profile_crud(monkeypatch):
    mock_vault = {}
    monkeypatch.setattr("keyring.set_password", lambda svc, u, p: mock_vault.update({u: p}))
    monkeypatch.setattr("keyring.get_password", lambda svc, u: mock_vault.get(u))
    monkeypatch.setattr("keyring.delete_password", lambda svc, u: mock_vault.pop(u, None))

    backend = save_profile(
        name="home",
        url="http://192.168.1.1",
        password="home_password",
        username="admin",
        timeout=6.0,
        use_keyring=True,
    )
    assert backend == "keyring"
    assert mock_vault.get("home") == "home_password"

    listed = list_profiles()
    assert "home" in listed["profiles"]
    assert "password" not in listed["profiles"]["home"] or listed["profiles"]["home"]["password"] == "******"

    set_default_profile("home")
    creds = resolve_credentials()
    assert creds.profile == "home"
    assert creds.url == "http://192.168.1.1"
    assert creds.password == "home_password"

    delete_profile("home")
    assert "home" not in list_profiles()["profiles"]
    assert "home" not in mock_vault


def test_config_file_permissions(tmp_path):
    save_config({"default_profile": "default", "profiles": {}})
    cfg_file = get_config_path()
    assert cfg_file.is_file()
    mode = oct(cfg_file.stat().st_mode & 0o777)
    # 0o600: read/write by owner only
    assert mode == "0o600"


def test_tpluci_profile_env_var(monkeypatch):
    monkeypatch.setenv("TPLUCI_PROFILE", "branch_office")
    monkeypatch.setenv("ROUTER_PASSWORD", "branch_secret")
    creds = resolve_credentials()
    assert creds.profile == "branch_office"
