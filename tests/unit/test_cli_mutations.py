"""Unit tests for tpluci mutations, safety guards, and config management."""

import json
from click.testing import CliRunner
import pytest

from tpluci.cli import cli
from tpluci.exceptions import EXIT_SAFETY_ABORT
from tpluci.session import SessionCache, SessionData


@pytest.fixture
def mock_client_rmw(monkeypatch):
    """Mock RouterClient.read_modify_write and call."""
    calls_made = []

    def fake_rmw(self, module, form, updates, dry_run=False):
        calls_made.append(("rmw", module, form, updates, dry_run))
        diff = {k: {"before": "off" if k == "enable" else "old", "after": v} for k, v in updates.items()}
        return {
            "dry_run": dry_run,
            "changed": True,
            "diff": diff,
            "state": updates,
        }

    def fake_call(self, module, form, operation="read", params=None, retrying_after_relogin=False):
        calls_made.append(("call", module, form, operation, params))
        if module == "system" and form == "reboot":
            return {"success": True}
        if module == "status" and form == "internet":
            return {"wan_internet_status": "connected"}
        return {"mock": "ok"}

    monkeypatch.setattr("tpluci.client.RouterClient.read_modify_write", fake_rmw)
    monkeypatch.setattr("tpluci.client.RouterClient.call", fake_call)
    monkeypatch.setattr(
        "tpluci.cli.get_client",
        lambda ctx: type("MockClient", (), {
            "read_modify_write": fake_rmw,
            "call": fake_call,
            "creds": type("Creds", (), {"profile": "default", "url": "http://192.168.7.250"})(),
        })(),
    )
    return calls_made


def test_wifi_set_dry_run(mock_client_rmw):
    runner = CliRunner()
    res = runner.invoke(cli, ["wifi", "set", "guest-2g", "--enable", "--dry-run", "--json"])
    assert res.exit_code == 0
    receipt = json.loads(res.output)
    assert receipt["dry_run"] is True
    assert receipt["changed"] is True
    assert receipt["diff"]["enable"]["after"] == "on"


def test_wifi_set_password_validation():
    runner = CliRunner()
    res = runner.invoke(cli, ["wifi", "set", "guest-2g", "--password", "short", "--json"])
    assert res.exit_code == 1
    envelope = json.loads(res.output)
    assert envelope["ok"] is False
    assert envelope["error_code"] == "INVALID_PASSWORD"


def test_system_reboot_safety_abort_non_interactive():
    runner = CliRunner()
    # Non-interactive without --confirm must abort with exit code 5
    res = runner.invoke(cli, ["system", "reboot", "--json"])
    assert res.exit_code == EXIT_SAFETY_ABORT
    # In Click CliRunner, stderr is in res.stderr if separate, or in res.output
    output_str = res.stderr if res.stderr else res.output
    envelope = json.loads(output_str)
    assert envelope["ok"] is False
    assert envelope["error_code"] == "SAFETY_ABORT"
    assert "--confirm" in envelope["hint"]


def test_system_reboot_dry_run_with_confirm(mock_client_rmw):
    runner = CliRunner()
    res = runner.invoke(cli, ["system", "reboot", "--confirm", "--dry-run", "--json"])
    assert res.exit_code == 0
    data = json.loads(res.output)
    assert data["ok"] is True
    assert data["dry_run"] is True
    # Verify no real hardware reboot call was issued
    reboot_calls = [c for c in mock_client_rmw if c[0] == "call" and c[1] == "system" and c[2] == "reboot"]
    assert len(reboot_calls) == 0


def test_system_reboot_confirmed_execution(mock_client_rmw):
    runner = CliRunner()
    res = runner.invoke(cli, ["system", "reboot", "--confirm", "--json"])
    assert res.exit_code == 0
    data = json.loads(res.output)
    assert data["ok"] is True
    assert data["dry_run"] is False
    reboot_calls = [c for c in mock_client_rmw if c[0] == "call" and c[1] == "system" and c[2] == "reboot"]
    assert len(reboot_calls) == 1


def test_config_crud_and_test(tmp_path, monkeypatch):
    monkeypatch.setenv("TPLUCI_CONFIG_DIR", str(tmp_path))
    monkeypatch.setattr("keyring.set_password", lambda s, u, p: None)
    monkeypatch.setattr("keyring.get_password", lambda s, u: "pass123")
    monkeypatch.setattr("keyring.delete_password", lambda s, u: None)

    runner = CliRunner()

    # Add profile
    res_add = runner.invoke(cli, [
        "config", "add",
        "--name", "office",
        "--url", "http://10.0.0.1",
        "--timeout", "12.5",
        "--password", "OfficePass123",
        "--no-keyring",
        "--json",
    ])
    assert res_add.exit_code == 0
    add_data = json.loads(res_add.output)
    assert add_data["profile"] == "office"
    assert add_data["url"] == "http://10.0.0.1"
    assert add_data["timeout"] == 12.5

    # List profiles
    res_list = runner.invoke(cli, ["config", "list", "--json"])
    assert res_list.exit_code == 0
    list_data = json.loads(res_list.output)
    assert "office" in list_data["profiles"]
    assert list_data["profiles"]["office"]["url"] == "http://10.0.0.1"
    assert list_data["profiles"]["office"]["timeout"] == 12.5

    # Set default
    res_def = runner.invoke(cli, ["config", "default", "--name", "office", "--json"])
    assert res_def.exit_code == 0

    # Delete profile
    res_del = runner.invoke(cli, ["config", "delete", "--name", "office", "--json"])
    assert res_del.exit_code == 0


def test_logout_command(tmp_path, monkeypatch):
    monkeypatch.setattr("tempfile.gettempdir", lambda: str(tmp_path))
    runner = CliRunner()

    res = runner.invoke(cli, ["logout", "--json"])
    assert res.exit_code == 0
    data = json.loads(res.output)
    assert data["ok"] is True
    assert "cleared" in data
