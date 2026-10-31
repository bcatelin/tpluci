"""Unit tests for tpluci read-only CLI commands."""

import json
from pathlib import Path
from click.testing import CliRunner
import pytest

from tpluci.cli import cli


@pytest.fixture
def mock_fixture_status():
    fixture_path = Path(__file__).parent.parent / "fixtures" / "sanitized_status_all.json"
    with open(fixture_path, "r", encoding="utf-8") as f:
        return json.load(f)


@pytest.fixture(autouse=True)
def mock_client_calls(monkeypatch, mock_fixture_status):
    """Mock RouterClient.call to return sanitized fixture responses."""
    def fake_call(self, module, form, operation="read", params=None, retrying_after_relogin=False):
        if module == "status" and form == "all":
            return mock_fixture_status
        if module == "network" and form == "wan_ipv4_status":
            return {
                "conntype": "pppoe",
                "wan_ipv4_ipaddr": "203.0.113.42",
                "wan_ipv4_gateway": "203.0.113.1",
                "wan_ipv4_uptime": 7200,
            }
        if module == "network" and form == "lan_ipv4":
            return {
                "ipaddr": "192.168.7.250",
                "mask_type": "255.255.255.0",
                "macaddr": "AA-BB-CC-11-22-33",
            }
        if module == "dhcps" and form == "setting":
            return {
                "enable": "on",
                "ipaddr_start": "192.168.7.100",
                "ipaddr_end": "192.168.7.200",
                "leasetime": "120",
                "gateway": "192.168.7.250",
            }
        if module == "firmware" and form == "upgrade":
            return {
                "model": "Archer AX23",
                "hardware_version": "Archer AX23 v1.0",
                "firmware_version": "1.1.0 Build 20261031",
            }
        if module == "system" and form == "sysmode":
            return {"mode": "Router"}
        if module == "time" and form == "settings":
            return {
                "date": "10/31/2026",
                "time": "21:45:00",
                "timezone": "49",
                "hour24_enable": "on",
                "ntp_svr1": "pool.ntp.org",
            }
        if module == "wireless" and form == "wireless_2g":
            return {
                "ssid": "TestNet_2G",
                "enable": "on",
                "channel": "6",
                "htmode": "20/40",
                "encryption": "psk",
            }
        return {"mock": "ok"}

    monkeypatch.setattr("tpluci.client.RouterClient.call", fake_call)
    monkeypatch.setattr("tpluci.cli.get_client", lambda ctx: type("MockClient", (), {"call": fake_call})())


def test_cli_status_text_and_json():
    runner = CliRunner()

    # Text mode
    res_text = runner.invoke(cli, ["status"])
    assert res_text.exit_code == 0
    assert "Archer AX23" in res_text.output
    assert "203.0.113.42" in res_text.output
    assert "CPU / Memory" in res_text.output

    # JSON mode
    res_json = runner.invoke(cli, ["status", "--json"])
    assert res_json.exit_code == 0
    data = json.loads(res_json.output)
    assert data["model"] == "Archer AX23"
    assert data["wan_ip"] == "203.0.113.42"
    assert data["clients_count"]["total"] == 4


def test_cli_status_field_and_full():
    runner = CliRunner()

    res_field = runner.invoke(cli, ["status", "--field", "wan_ipv4_ipaddr"])
    assert res_field.exit_code == 0
    assert "203.0.113.42" in res_field.output

    res_full = runner.invoke(cli, ["status", "--full", "--json"])
    assert res_full.exit_code == 0
    full_data = json.loads(res_full.output)
    assert "access_devices_wireless_host" in full_data


def test_cli_clients_text_and_json():
    runner = CliRunner()

    res = runner.invoke(cli, ["clients"])
    assert res.exit_code == 0
    assert "Test-Laptop" in res.output
    assert "NAS-Server" in res.output
    assert "Total: 4 clients" in res.output

    res_json = runner.invoke(cli, ["clients", "--json"])
    assert res_json.exit_code == 0
    clients = json.loads(res_json.output)
    assert len(clients) == 4


def test_cli_clients_filters():
    runner = CliRunner()

    # Search query
    res_q = runner.invoke(cli, ["clients", "laptop", "--json"])
    assert res_q.exit_code == 0
    assert len(json.loads(res_q.output)) == 1

    # Wireless only
    res_w = runner.invoke(cli, ["clients", "--wireless-only", "--json"])
    assert res_w.exit_code == 0
    assert len(json.loads(res_w.output)) == 3

    # Wired only
    res_wired = runner.invoke(cli, ["clients", "--wired-only", "--json"])
    assert res_wired.exit_code == 0
    assert len(json.loads(res_wired.output)) == 1


def test_cli_wifi_list_and_get():
    runner = CliRunner()

    res_list = runner.invoke(cli, ["wifi", "list"])
    assert res_list.exit_code == 0
    assert "2g" in res_list.output
    assert "guest-2g" in res_list.output

    res_get = runner.invoke(cli, ["wifi", "get", "2g", "--json"])
    assert res_get.exit_code == 0
    data = json.loads(res_get.output)
    assert data["ssid"] == "TestNet_2G"


def test_cli_wan_and_lan():
    runner = CliRunner()

    res_wan = runner.invoke(cli, ["wan", "--json"])
    assert res_wan.exit_code == 0
    wan = json.loads(res_wan.output)
    assert wan["ipaddr"] == "203.0.113.42"
    assert wan["conntype"] == "pppoe"

    res_lan = runner.invoke(cli, ["lan", "--json"])
    assert res_lan.exit_code == 0
    lan = json.loads(res_lan.output)
    assert lan["ipaddr"] == "192.168.7.250"
    assert lan["dhcp"]["enabled"] is True


def test_cli_system_info_and_time():
    runner = CliRunner()

    res_info = runner.invoke(cli, ["system", "info", "--json"])
    assert res_info.exit_code == 0
    info = json.loads(res_info.output)
    assert info["model"] == "Archer AX23"
    assert info["operation_mode"] == "Router"

    res_time = runner.invoke(cli, ["system", "time", "--json"])
    assert res_time.exit_code == 0
    t = json.loads(res_time.output)
    assert t["date"] == "10/31/2026"


def test_cli_call_list_and_exec():
    runner = CliRunner()

    res_list = runner.invoke(cli, ["call", "--list", "--json"])
    assert res_list.exit_code == 0
    eps = json.loads(res_list.output)
    assert len(eps) == 30

    res_call = runner.invoke(cli, ["call", "status", "all", "--json"])
    assert res_call.exit_code == 0
    data = json.loads(res_call.output)
    assert "model" in data

    res_call_opts = runner.invoke(cli, ["call", "--module", "status", "--form", "all", "--json"])
    assert res_call_opts.exit_code == 0
    assert "model" in json.loads(res_call_opts.output)
