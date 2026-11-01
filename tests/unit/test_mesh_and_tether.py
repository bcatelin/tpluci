"""Unit tests for Phase 9: Mesh, Rich Client Management & Tether System Features."""

from __future__ import annotations

import json
from typing import Any
import pytest
from click.testing import CliRunner

from tpluci.cli import cli
from tpluci.endpoints import VERIFIED_ENDPOINTS
from tpluci.exceptions import SafetyAbortError
from tpluci.models import (
    normalize_weekday,
    parse_clients_detailed,
    parse_mesh_satellite_detail,
    parse_mesh_satellites,
    parse_mesh_topology,
    resolve_client_target,
    resolve_mesh_node,
)
from tpluci.mcp_server import (
    router_get_mesh,
    router_list_clients,
    router_manage_client,
    router_set_mesh_node,
    router_system_settings,
)


# =====================================================================
# Fixtures & Mocks
# =====================================================================

@pytest.fixture
def sample_mesh_sclient_list() -> list[dict[str, Any]]:
    return [
        {
            "name": "Extender-LivingRoom",
            "model": "RE705X",
            "ip": "192.168.1.2",
            "mac": "00:11:22:33:44:02",
            "location": "living_room",
            "connect_type": "wireless",
            "signal_strength": -52,
            "client_num": 3,
            "status": "online",
            "device_type": "extender",
        },
        {
            "name": "Extender-Office",
            "model": "RE300",
            "ip": "192.168.1.3",
            "mac": "00:11:22:33:44:03",
            "location": "office",
            "connect_type": "wire",
            "signal_strength": -254,
            "client_num": 1,
            "status": "online",
            "device_type": "extender",
        },
    ]


@pytest.fixture
def sample_mesh_topology() -> dict[str, Any]:
    return {
        "name": "Main Router",
        "model": "Archer AX23",
        "ip": "192.168.1.1",
        "mac": "00:11:22:33:44:01",
        "mesh_nclient_list": [
            {
                "hostname": "Desktop-PC",
                "ip": "192.168.1.100",
                "mac": "AA:BB:CC:DD:EE:01",
                "wire_type": "wired",
                "device_type": "pc",
            }
        ],
        "mesh_sclient_list": [
            {
                "name": "Extender-LivingRoom",
                "model": "RE705X",
                "ip": "192.168.1.2",
                "mac": "00:11:22:33:44:02",
                "location": "living_room",
                "connect_type": "wireless",
                "signal_strength": -52,
                "mesh_nclient_list": [
                    {
                        "name": "Smartphone",
                        "ip": "192.168.1.101",
                        "mac": "AA:BB:CC:DD:EE:02",
                        "connection_type": "wireless",
                        "signal_strength": -45,
                        "txrate": 866000,
                        "rxrate": 866000,
                    }
                ],
            }
        ],
    }


@pytest.fixture
def sample_satellite_detail() -> dict[str, Any]:
    return {
        "name": "Extender-LivingRoom",
        "location": "living_room",
        "model": "RE705X",
        "mac": "00:11:22:33:44:02",
        "ip": "192.168.1.2",
        "firmware_version": "1.0.5 Build 20230508",
        "parent_device_mac": "00:11:22:33:44:01",
        "connect_type": "wireless",
        "link_speed_24g": "286720",  # 280 Mbps in Kbps
        "link_speed_5g": "665600",   # 650 Mbps in Kbps
        "signal_strength_24g": -55,
        "signal_strength_5g": -50,
        "mesh_nclient_list": [
            {
                "name": "Smartphone",
                "ip": "192.168.1.101",
                "mac": "AA:BB:CC:DD:EE:02",
                "connection_type": "wireless",
                "signal_strength": -45,
                "txrate": 866000,
                "rxrate": 866000,
            }
        ],
    }


@pytest.fixture
def sample_game_accelerator_devices() -> list[dict[str, Any]]:
    return [
        {
            "deviceName": "Desktop-PC",
            "ip": "192.168.1.100",
            "mac": "AA:BB:CC:DD:EE:01",
            "deviceTag": "wired",
            "deviceType": "pc",
            "signal": 0,
            "txrate": 1000,
            "rxrate": 1000,
            "downloadSpeed": 128000,  # 128000 * 8 // 1024 = 1000 Kbps
            "uploadSpeed": 64000,     # 64000 * 8 // 1024 = 500 Kbps
            "trafficUsage": 10485760, # 10 MB
            "onlineTime": 3600,
            "enableLimit": "off",
            "downloadLimit": -1,
            "uploadLimit": -1,
        },
        {
            "deviceName": "Smartphone",
            "ip": "192.168.1.101",
            "mac": "AA:BB:CC:DD:EE:02",
            "deviceTag": "5G",
            "deviceType": "phone",
            "signal": -45,
            "txrate": 866000,         # > 2000 => 866 Mbps
            "rxrate": 866000,
            "downloadSpeed": 256000,  # 2000 Kbps
            "uploadSpeed": 128000,    # 1000 Kbps
            "trafficUsage": 52428800, # 50 MB
            "onlineTime": 7200,
            "enableLimit": "on",
            "downloadLimit": 5000,
            "uploadLimit": 2000,
        },
    ]


# =====================================================================
# Unit Tests: Models & Normalizers
# =====================================================================

def test_normalize_weekday():
    # Weekday mapping to Tues and Thur
    assert normalize_weekday("mon") == "Mon"
    assert normalize_weekday("monday") == "Mon"
    assert normalize_weekday("tue") == "Tues"
    assert normalize_weekday("tues") == "Tues"
    assert normalize_weekday("tuesday") == "Tues"
    assert normalize_weekday("wed") == "Wed"
    assert normalize_weekday("wednesday") == "Wed"
    assert normalize_weekday("thu") == "Thur"
    assert normalize_weekday("thur") == "Thur"
    assert normalize_weekday("thursday") == "Thur"
    assert normalize_weekday("fri") == "Fri"
    assert normalize_weekday("sat") == "Sat"
    assert normalize_weekday("sun") == "Sun"
    assert normalize_weekday("Tues") == "Tues"
    assert normalize_weekday("Thur") == "Thur"

    # Monthly cycle 1..28
    assert normalize_weekday("1") == "1"
    assert normalize_weekday("15") == "15"
    assert normalize_weekday("28") == "28"

    # Invalid cases
    with pytest.raises(ValueError):
        normalize_weekday("Funday")
    with pytest.raises(ValueError):
        normalize_weekday("0")
    with pytest.raises(ValueError):
        normalize_weekday("29")


def test_parse_mesh_satellites(sample_mesh_sclient_list):
    satellites = parse_mesh_satellites(sample_mesh_sclient_list)
    assert len(satellites) == 2

    re705x = satellites[0]
    assert re705x["name"] == "Extender-LivingRoom"
    assert re705x["backhaul"] == "wireless"
    assert re705x["signal_strength"] == "-52 dBm"
    assert re705x["clients_count"] == 3

    re300 = satellites[1]
    assert re300["name"] == "Extender-Office"
    assert re300["backhaul"] == "wired"
    assert re300["signal_strength"] == "N/A"
    assert re300["clients_count"] == 1


def test_parse_mesh_topology(sample_mesh_topology):
    tree = parse_mesh_topology(sample_mesh_topology)
    assert tree["root"]["name"] == "Main Router"
    assert len(tree["root"]["clients"]) == 1
    assert tree["root"]["clients"][0]["name"] == "Desktop-PC"

    assert len(tree["satellites"]) == 1
    sat = tree["satellites"][0]
    assert sat["name"] == "Extender-LivingRoom"
    assert sat["backhaul"] == "wireless"
    assert len(sat["clients"]) == 1

    client = sat["clients"][0]
    assert client["name"] == "Smartphone"
    assert client["signal_strength"] == "-45 dBm"
    assert client["txrate_mbps"] == 866
    assert client["rxrate_mbps"] == 866


def test_parse_mesh_satellite_detail(sample_satellite_detail):
    detail = parse_mesh_satellite_detail(sample_satellite_detail)
    assert detail["name"] == "Extender-LivingRoom"
    assert detail["link_speed_24g_mbps"] == 280  # 286720 // 1024
    assert detail["link_speed_5g_mbps"] == 650   # 665600 // 1024
    assert detail["signal_strength_24g"] == "-55 dBm"
    assert detail["signal_strength_5g"] == "-50 dBm"
    assert len(detail["clients"]) == 1
    assert detail["clients"][0]["txrate_mbps"] == 866


def test_resolve_mesh_node(sample_mesh_sclient_list):
    satellites = parse_mesh_satellites(sample_mesh_sclient_list)

    # By name
    assert resolve_mesh_node(satellites, "Extender-Office")["mac"] == "00:11:22:33:44:03"
    assert resolve_mesh_node(satellites, "office")["mac"] == "00:11:22:33:44:03"

    # By IP
    assert resolve_mesh_node(satellites, "192.168.1.2")["name"] == "Extender-LivingRoom"

    # By MAC (dash or colon)
    assert resolve_mesh_node(satellites, "00-11-22-33-44-02")["name"] == "Extender-LivingRoom"
    assert resolve_mesh_node(satellites, "00:11:22:33:44:03")["name"] == "Extender-Office"

    # Not found
    assert resolve_mesh_node(satellites, "NonExistent") is None


def test_parse_clients_detailed(sample_mesh_topology, sample_game_accelerator_devices):
    clients = parse_clients_detailed(sample_mesh_topology, sample_game_accelerator_devices)
    assert len(clients) == 2

    pc = [c for c in clients if c["hostname"] == "Desktop-PC"][0]
    assert pc["node"] == "Main Router"
    assert pc["medium"] == "wired"
    assert pc["signal"] is None
    assert pc["down_speed_kbps"] == 1000
    assert pc["up_speed_kbps"] == 500
    assert pc["speed_limit"]["enabled"] is False

    phone = [c for c in clients if c["hostname"] == "Smartphone"][0]
    assert phone["node"] == "Extender-LivingRoom"
    assert phone["medium"] == "wireless"
    assert phone["signal"] == "-45 dBm"
    assert phone["txrate_mbps"] == 866
    assert phone["down_speed_kbps"] == 2000
    assert phone["up_speed_kbps"] == 1000
    assert phone["speed_limit"]["enabled"] is True
    assert phone["speed_limit"]["down_kbps"] == 5000
    assert phone["speed_limit"]["up_kbps"] == 2000


def test_resolve_client_target(sample_game_accelerator_devices):
    clients = [
        {"hostname": d["deviceName"], "ipaddr": d["ip"], "macaddr": d["mac"]}
        for d in sample_game_accelerator_devices
    ]

    # By exact IP
    assert resolve_client_target(clients, "192.168.1.100")["hostname"] == "Desktop-PC"
    # By exact MAC
    assert resolve_client_target(clients, "AA-BB-CC-DD-EE-02")["hostname"] == "Smartphone"
    # By name substring
    assert resolve_client_target(clients, "smart")["hostname"] == "Smartphone"
    # Not found
    assert resolve_client_target(clients, "tablet") is None


# =====================================================================
# Unit Tests: CLI Commands & Routing
# =====================================================================

def test_cli_clients_group_backward_compatibility(monkeypatch, sample_mesh_topology, sample_game_accelerator_devices):
    calls_made = []

    def mock_call(self, module, form, operation="read", params=None):
        calls_made.append((module, form, operation, params))
        if module == "status" and form == "all":
            return {
                "access_devices_wireless_host": [
                    {"hostname": "Smartphone", "ipaddr": "192.168.1.101", "macaddr": "AA:BB:CC:DD:EE:02", "wire_type": "5G"}
                ],
                "access_devices_wired": [
                    {"hostname": "Desktop-PC", "ipaddr": "192.168.1.100", "macaddr": "AA:BB:CC:DD:EE:01"}
                ],
            }
        if module == "easymesh_network" and form == "mesh_topology":
            return sample_mesh_topology
        if module == "smart_network" and form == "game_accelerator":
            return sample_game_accelerator_devices
        return {}

    monkeypatch.setattr("tpluci.client.RouterClient.call", mock_call)
    runner = CliRunner()

    # 1. Bare `tpluci clients`
    res1 = runner.invoke(cli, ["clients"])
    assert res1.exit_code == 0
    assert "Smartphone" in res1.output
    assert "Desktop-PC" in res1.output

    # 2. Positional query: `tpluci clients smart`
    res2 = runner.invoke(cli, ["clients", "smart", "--json"])
    assert res2.exit_code == 0
    data2 = json.loads(res2.output)
    assert len(data2) == 1
    assert data2[0]["hostname"] == "Smartphone"

    # 3. Flag-only: `tpluci clients --wireless-only --json`
    res3 = runner.invoke(cli, ["clients", "--wireless-only", "--json"])
    assert res3.exit_code == 0
    data3 = json.loads(res3.output)
    assert len(data3) == 1
    assert data3[0]["medium"] == "wireless"

    # 4. Detailed list: `tpluci clients list --detailed --json`
    res4 = runner.invoke(cli, ["clients", "list", "--detailed", "--json"])
    assert res4.exit_code == 0
    data4 = json.loads(res4.output)
    assert len(data4) == 2
    assert any(c["node"] == "Extender-LivingRoom" for c in data4)


def test_cli_clients_rename(monkeypatch):
    calls_made = []

    def mock_call(self, module, form, operation="read", params=None):
        calls_made.append((module, form, operation, params))
        if module == "status" and form == "all":
            return {
                "access_devices_wireless_host": [
                    {"hostname": "OldPhone", "ipaddr": "192.168.1.101", "macaddr": "AA:BB:CC:DD:EE:02", "wire_type": "5G"}
                ],
                "access_devices_wired": [],
            }
        return {}

    monkeypatch.setattr("tpluci.client.RouterClient.call", mock_call)
    runner = CliRunner()

    # Dry-run
    res_dry = runner.invoke(cli, ["clients", "rename", "192.168.1.101", "NewPhone", "--dry-run", "--json"])
    assert res_dry.exit_code == 0
    data_dry = json.loads(res_dry.output)
    assert data_dry["dry_run"] is True
    assert data_dry["diff"]["alias"]["after"] == "NewPhone"

    # Actual rename
    res_live = runner.invoke(cli, ["clients", "rename", "AA:BB:CC:DD:EE:02", "NewPhone", "--json"])
    assert res_live.exit_code == 0
    write_calls = [c for c in calls_made if c[0] == "traffic" and c[1] == "dev_name" and c[2] == "write"]
    assert len(write_calls) == 1
    assert write_calls[0][3] == {"mac": "AA:BB:CC:DD:EE:02", "alias": "NewPhone"}


def test_cli_clients_limit(monkeypatch, sample_game_accelerator_devices):
    calls_made = []

    def mock_call(self, module, form, operation="read", params=None):
        calls_made.append((module, form, operation, params))
        if module == "smart_network" and form == "game_accelerator":
            return sample_game_accelerator_devices
        return {}

    monkeypatch.setattr("tpluci.client.RouterClient.call", mock_call)
    runner = CliRunner()

    # Apply limits
    res = runner.invoke(cli, ["clients", "limit", "Desktop-PC", "--down", "5000", "--up", "1000", "--json"])
    assert res.exit_code == 0
    write_calls = [c for c in calls_made if c[0] == "smart_network" and c[1] == "client_speed_limit"]
    assert len(write_calls) == 1
    assert write_calls[0][3] == {
        "mac": "AA:BB:CC:DD:EE:01",
        "enableLimit": "on",
        "downloadLimit": "5000",
        "uploadLimit": "1000",
    }

    # Disable limit
    res_dis = runner.invoke(cli, ["clients", "limit", "Smartphone", "--disable", "--json"])
    assert res_dis.exit_code == 0
    dis_calls = [c for c in calls_made if c[3] and c[3].get("enableLimit") == "off"]
    assert len(dis_calls) == 1


def test_cli_clients_block_host_protection(monkeypatch):
    calls_made = []

    def mock_call(self, module, form, operation="read", params=None):
        calls_made.append((module, form, operation, params))
        if module == "access_control" and form == "black_devices":
            return [
                {"name": "Admin-Laptop", "ip": "192.168.1.50", "mac": "11:22:33:44:55:66", "host": "HOST"},
                {"name": "Guest-Device", "ip": "192.168.1.60", "mac": "99:88:77:66:55:44", "host": "NON_HOST"},
            ]
        if module == "access_control" and form == "enable":
            return {"enable": "on", "host_mac": "11:22:33:44:55:66"}
        if module == "access_control" and form == "mode":
            return {"access_mode": "black"}
        return {}

    monkeypatch.setattr("tpluci.client.RouterClient.call", mock_call)
    runner = CliRunner()

    # Attempt to block current HOST device -> must raise exit code 5 (SAFETY_ABORT)
    res_host = runner.invoke(cli, ["clients", "block", "Admin-Laptop", "--confirm", "--json"])
    assert res_host.exit_code == 5
    data_host = json.loads(res_host.output)
    assert data_host["error_code"] == "SAFETY_ABORT"
    assert "prevent router lockout" in data_host["message"]

    # Attempt to block without --confirm in non-interactive mode -> exit code 5
    res_no_confirm = runner.invoke(cli, ["clients", "block", "Guest-Device", "--json"])
    assert res_no_confirm.exit_code == 5
    assert json.loads(res_no_confirm.output)["error_code"] == "SAFETY_ABORT"

    # Legitimate block with --confirm
    res_block = runner.invoke(cli, ["clients", "block", "Guest-Device", "--confirm", "--json"])
    assert res_block.exit_code == 0
    insert_calls = [c for c in calls_made if c[0] == "access_control" and c[1] == "black_list" and c[2] == "insert"]
    assert len(insert_calls) == 1


def test_cli_mesh_commands(monkeypatch, sample_mesh_sclient_list, sample_mesh_topology, sample_satellite_detail):
    calls_made = []

    def mock_call(self, module, form, operation="read", params=None):
        calls_made.append((module, form, operation, params))
        if module == "easymesh_network" and form == "mesh_sclient_list_all":
            return sample_mesh_sclient_list
        if module == "easymesh_network" and form == "mesh_topology":
            return sample_mesh_topology
        if module == "easymesh_network" and form == "mesh_sclient_detail":
            return sample_satellite_detail
        if module == "firmware" and form == "slave_cmd":
            return [
                {"name": "Extender-LivingRoom", "model": "RE705X", "ip": "192.168.1.2", "mac": "00:11:22:33:44:02", "version": "1.0.5", "latest_version": "1.0.6", "is_latest": False}
            ]
        return {}

    monkeypatch.setattr("tpluci.client.RouterClient.call", mock_call)
    runner = CliRunner()

    # 1. Mesh list
    res_list = runner.invoke(cli, ["mesh", "list", "--json"])
    assert res_list.exit_code == 0
    sats = json.loads(res_list.output)
    assert len(sats) == 2

    # 2. Mesh topology
    res_topo = runner.invoke(cli, ["mesh", "topology", "--json"])
    assert res_topo.exit_code == 0
    tree = json.loads(res_topo.output)
    assert tree["root"]["name"] == "Main Router"

    # 3. Mesh get
    res_get = runner.invoke(cli, ["mesh", "get", "RE705X", "--json"])
    assert res_get.exit_code == 0
    detail = json.loads(res_get.output)
    assert detail["link_speed_5g_mbps"] == 650

    # 4. Mesh set (minimal write contract)
    res_set = runner.invoke(cli, ["mesh", "set", "RE705X", "--name", "Office-AP", "--location", "office", "--json"])
    assert res_set.exit_code == 0
    write_calls = [c for c in calls_made if c[0] == "easymesh_network" and c[1] == "mesh_sclient_detail" and c[2] == "write"]
    assert len(write_calls) == 1
    # Verify minimal payload has only mac, name, location
    assert write_calls[0][3] == {"mac": "00:11:22:33:44:02", "name": "Office-AP", "location": "office"}

    # 5. Mesh firmware
    res_fw = runner.invoke(cli, ["mesh", "firmware", "--json"])
    assert res_fw.exit_code == 0
    fw_data = json.loads(res_fw.output)
    assert len(fw_data) == 1
    assert fw_data[0]["is_latest"] is False

    # 6. Mesh remove with --confirm guard
    res_rem_fail = runner.invoke(cli, ["mesh", "remove", "RE705X", "--json"])
    assert res_rem_fail.exit_code == 5
    res_rem_ok = runner.invoke(cli, ["mesh", "remove", "RE705X", "--confirm", "--json"])
    assert res_rem_ok.exit_code == 0


def test_cli_system_reboot_schedule_and_led(monkeypatch):
    rmw_calls = []

    def mock_rmw(self, module, form, updates, dry_run=False):
        rmw_calls.append((module, form, updates, dry_run))
        diff = {k: {"before": "old", "after": v} for k, v in updates.items()}
        return {"ok": True, "dry_run": dry_run, "changed": True, "diff": diff}

    monkeypatch.setattr("tpluci.client.RouterClient.read_modify_write", mock_rmw)
    runner = CliRunner()

    # Reboot schedule with day normalization ("tuesday" -> "Tues")
    res_sched = runner.invoke(cli, ["system", "reboot-schedule", "--enable", "--cycle", "week", "--day", "tuesday", "--time", "03:00", "--json"])
    assert res_sched.exit_code == 0
    assert len(rmw_calls) == 1
    assert rmw_calls[0][0] == "reboot"
    assert rmw_calls[0][1] == "set"
    assert rmw_calls[0][2]["day"] == "Tues"

    # LED and Night Mode
    res_led = runner.invoke(cli, ["system", "led", "--on", "--night-mode", "on", "--start", "22:00", "--end", "07:00", "--json"])
    assert res_led.exit_code == 0
    # Verified both ledgeneral and ledpm updated
    modules_called = [c[0] for c in rmw_calls[1:]]
    assert "ledgeneral" in modules_called
    assert "ledpm" in modules_called


# =====================================================================
# Unit Tests: MCP Server Tools
# =====================================================================

def test_mcp_mesh_and_client_tools(monkeypatch, sample_mesh_sclient_list, sample_mesh_topology, sample_satellite_detail, sample_game_accelerator_devices):
    calls_made = []

    def mock_call(self, module, form, operation="read", params=None):
        calls_made.append((module, form, operation, params))
        if module == "easymesh_network" and form == "mesh_sclient_list_all":
            return sample_mesh_sclient_list
        if module == "easymesh_network" and form == "mesh_topology":
            return sample_mesh_topology
        if module == "easymesh_network" and form == "mesh_sclient_detail":
            return sample_satellite_detail
        if module == "smart_network" and form == "game_accelerator":
            return sample_game_accelerator_devices
        if module == "reboot" and form == "set":
            return {"enable": "on", "cycle": "week", "day": "Tues", "time": "03:00"}
        if module == "ledgeneral" and form == "setting":
            return {"enable": "on"}
        if module == "ledpm" and form == "setting":
            return {"enable": "on", "time_start": "22:00", "time_end": "07:00"}
        return {}

    def mock_rmw(self, module, form, updates, dry_run=False):
        calls_made.append(("rmw", module, form, updates, dry_run))
        return {"ok": True, "dry_run": dry_run, "changed": True, "diff": {}}

    monkeypatch.setattr("tpluci.client.RouterClient.call", mock_call)
    monkeypatch.setattr("tpluci.client.RouterClient.read_modify_write", mock_rmw)

    # 1. router_list_clients with detailed=True
    clients = router_list_clients(detailed=True)
    assert len(clients) == 2
    assert any(c["node"] == "Extender-LivingRoom" for c in clients)

    # 2. router_get_mesh
    mesh_info = router_get_mesh()
    assert len(mesh_info["satellites"]) == 2
    assert mesh_info["topology"]["root"]["name"] == "Main Router"

    # 3. router_set_mesh_node
    res_set = router_set_mesh_node("RE705X", name="New-AP", location="hallway")
    assert res_set["ok"] is True
    assert res_set["diff"]["name"]["after"] == "New-AP"

    # 4. router_manage_client
    res_manage = router_manage_client("Desktop-PC", alias="Gaming-Rig", download_limit_kbps=10000)
    assert res_manage["ok"] is True
    assert res_manage["actions"]["rename"]["after"] == "Gaming-Rig"
    assert res_manage["actions"]["speed_limit"]["downloadLimit"] == 10000

    # 5. router_system_settings (read & mutation)
    read_settings = router_system_settings()
    assert read_settings["reboot_schedule"]["day"] == "Tues"
    assert read_settings["led"]["enabled"] is True

    mutate_settings = router_system_settings(reboot_day="wednesday", led_enable=False)
    assert mutate_settings["ok"] is True
