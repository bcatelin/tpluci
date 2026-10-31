"""Unit tests for tpluci FastMCP server tools."""

import json
from pathlib import Path
import pytest

from tpluci.mcp_server import (
    router_get_network_info,
    router_get_status,
    router_get_wifi,
    router_list_clients,
    router_raw_call,
    router_reboot,
    router_set_wifi,
)


@pytest.fixture
def mock_fixture_status():
    fixture_path = Path(__file__).parent.parent / "fixtures" / "sanitized_status_all.json"
    with open(fixture_path, "r", encoding="utf-8") as f:
        return json.load(f)


@pytest.fixture(autouse=True)
def mock_mcp_client(monkeypatch, mock_fixture_status):
    calls_made = []

    def fake_call(self, module, form, operation="read", params=None, retrying_after_relogin=False):
        calls_made.append(("call", module, form, operation, params))
        if module == "status" and form == "all":
            return mock_fixture_status
        if module == "network" and form == "wan_ipv4_status":
            return {"wan_ipv4_ipaddr": "203.0.113.42", "conntype": "pppoe"}
        if module == "network" and form == "lan_ipv4":
            return {"ipaddr": "192.168.7.250", "mask_type": "255.255.255.0", "macaddr": "AA-BB-CC-11-22-33"}
        if module == "dhcps" and form == "setting":
            return {"enable": "on", "ipaddr_start": "192.168.7.100", "ipaddr_end": "192.168.7.200"}
        if module == "wireless" and form == "wireless_2g":
            return {"ssid": "TestNet_2G", "enable": "on"}
        if module == "system" and form == "reboot":
            return {"success": True}
        return {"mock": "ok"}

    def fake_rmw(self, module, form, updates, dry_run=False):
        calls_made.append(("rmw", module, form, updates, dry_run))
        diff = {k: {"before": "old", "after": v} for k, v in updates.items()}
        return {"dry_run": dry_run, "changed": True, "diff": diff, "state": updates}

    mock_client = type("MockClient", (), {
        "call": fake_call,
        "read_modify_write": fake_rmw,
    })()

    monkeypatch.setattr("tpluci.mcp_server._get_client", lambda: mock_client)
    return calls_made


def test_mcp_router_get_status():
    # Summary
    summary = router_get_status()
    assert summary["model"] == "Archer AX23"
    assert summary["wan_ip"] == "203.0.113.42"

    # Field
    field_res = router_get_status(field="wan_ipv4_ipaddr")
    assert field_res == {"wan_ipv4_ipaddr": "203.0.113.42"}

    # Full
    full_res = router_get_status(full=True)
    assert "access_devices_wireless_host" in full_res


def test_mcp_router_list_clients():
    clients = router_list_clients(query="laptop")
    assert len(clients) == 1
    assert clients[0]["hostname"] == "Test-Laptop"


def test_mcp_router_get_wifi():
    all_wifi = router_get_wifi(radio="all")
    assert len(all_wifi) == 6

    single = router_get_wifi(radio="2g")
    assert single["ssid"] == "TestNet_2G"


def test_mcp_router_set_wifi():
    # Dry run
    res = router_set_wifi(radio="guest-2g", enable=True, dry_run=True)
    assert res["dry_run"] is True
    assert res["changed"] is True

    # Bad password
    bad_res = router_set_wifi(radio="guest-2g", password="short")
    assert bad_res["ok"] is False
    assert "between 8 and 63" in bad_res["error"]


def test_mcp_router_get_network_info():
    net = router_get_network_info()
    assert net["wan"]["ipaddr"] == "203.0.113.42"
    assert net["lan"]["ipaddr"] == "192.168.7.250"


def test_mcp_router_reboot_safety_guard(mock_mcp_client):
    # Without confirm
    res_block = router_reboot(confirm=False)
    assert res_block["ok"] is False
    assert res_block["error_code"] == "SAFETY_ABORT"

    # With confirm
    res_ok = router_reboot(confirm=True)
    assert res_ok["ok"] is True
    reboot_calls = [c for c in mock_mcp_client if c[0] == "call" and c[1] == "system" and c[2] == "reboot"]
    assert len(reboot_calls) == 1


def test_mcp_router_raw_call():
    res = router_raw_call(module="status", form="all")
    assert "model" in res


def test_mcp_tools_return_error_envelope_on_tpluci_error(monkeypatch):
    from tpluci.exceptions import NetworkError

    def failing_client():
        raise NetworkError("Router unreachable", error_code="NETWORK_UNREACHABLE")

    monkeypatch.setattr("tpluci.mcp_server._get_client", failing_client)
    res = router_get_status()
    assert res["ok"] is False
    assert res["error_code"] == "NETWORK_UNREACHABLE"
