"""Unit tests for tpluci data models and normalizers."""

import json
from pathlib import Path
import pytest

from tpluci.endpoints import VERIFIED_ENDPOINTS, WIFI_RADIO_MAP
from tpluci.models import (
    parse_clients,
    parse_lan_info,
    parse_status_summary,
    parse_wan_info,
    parse_wifi_summary,
)


@pytest.fixture
def sanitized_status():
    fixture_path = Path(__file__).parent.parent / "fixtures" / "sanitized_status_all.json"
    with open(fixture_path, "r", encoding="utf-8") as f:
        return json.load(f)


def test_verified_endpoints_count():
    assert len(VERIFIED_ENDPOINTS) == 30
    categories = {ep["category"] for ep in VERIFIED_ENDPOINTS}
    assert categories == {"System", "Network", "Wireless", "Security"}
    # Check all 6 Wi-Fi radios in radio map
    assert set(WIFI_RADIO_MAP.keys()) == {"2g", "5g", "guest-2g", "guest-5g", "iot-2g", "iot-5g"}


def test_parse_status_summary(sanitized_status):
    summary = parse_status_summary(sanitized_status)
    assert summary["model"] == "Archer AX23"
    assert summary["cpu_usage"] == 18
    assert summary["mem_usage"] == 42
    assert summary["wan_ip"] == "203.0.113.42"
    assert summary["lan_ip"] == "192.168.7.250"
    assert summary["clients_count"] == {"wireless": 3, "wired": 1, "total": 4}

    # Verify wifi radios
    assert summary["wifi"]["2g"]["enabled"] is True
    assert summary["wifi"]["2g"]["ssid"] == "TestNet_2G"
    assert summary["wifi"]["guest-2g"]["enabled"] is False

    # Check token footprint (approx < 200 tokens formatted JSON)
    dumped = json.dumps(summary)
    assert len(dumped) < 1000


def test_parse_clients_all(sanitized_status):
    clients = parse_clients(sanitized_status)
    assert len(clients) == 4
    hostnames = [c["hostname"] for c in clients]
    assert "NAS-Server" in hostnames
    assert "Test-Laptop" in hostnames


def test_parse_clients_filtering(sanitized_status):
    # Wireless only
    wireless = parse_clients(sanitized_status, medium="wireless")
    assert len(wireless) == 3
    assert all(c["medium"] == "wireless" for c in wireless)

    # Wired only
    wired = parse_clients(sanitized_status, medium="wired")
    assert len(wired) == 1
    assert wired[0]["hostname"] == "NAS-Server"

    # Band filtering: 5G
    five_g = parse_clients(sanitized_status, band="5g")
    assert len(five_g) == 1
    assert five_g[0]["hostname"] == "Test-Laptop"

    # Band filtering: 2G
    two_g = parse_clients(sanitized_status, band="2g")
    assert len(two_g) == 2
    assert {c["hostname"] for c in two_g} == {"Test-Phone", "Smart-Plug"}

    # Search query
    phone = parse_clients(sanitized_status, query="phone")
    assert len(phone) == 1
    assert phone[0]["hostname"] == "Test-Phone"

    by_ip = parse_clients(sanitized_status, query="192.168.7.101")
    assert len(by_ip) == 1
    assert by_ip[0]["hostname"] == "Test-Laptop"
    by_mac = parse_clients(sanitized_status, query="EE-01")
    assert len(by_mac) == 1
    assert by_mac[0]["hostname"] == "Test-Laptop"


def test_parse_wifi_summary(sanitized_status):
    radios = parse_wifi_summary(sanitized_status)
    assert len(radios) == 6
    radio_by_code = {r["radio"]: r for r in radios}
    assert radio_by_code["2g"]["ssid"] == "TestNet_2G"
    assert radio_by_code["2g"]["enabled"] is True
    assert radio_by_code["guest-5g"]["ssid"] == "TestGuest_5G"
    assert radio_by_code["guest-5g"]["enabled"] is False


def test_parse_wan_and_lan_info():
    wan_status = {"autodetect": "on", "conntype": "pppoe"}
    raw_all = {
        "wan_ipv4_ipaddr": "203.0.113.42",
        "wan_ipv4_gateway": "203.0.113.1",
        "wan_ipv4_netmask": "255.255.255.255",
        "wan_ipv4_pridns": "1.1.1.1",
        "wan_ipv4_snddns": "8.8.8.8",
        "wan_macaddr": "AA-BB-CC-11-22-34",
        "wan_ipv4_uptime": 3600,
    }
    wan = parse_wan_info(wan_status, raw_all)
    assert wan["ipaddr"] == "203.0.113.42"
    assert wan["conntype"] == "pppoe"
    assert wan["dns"] == "1.1.1.1, 8.8.8.8"
    assert wan["macaddr"] == "AA-BB-CC-11-22-34"
    assert wan["status"] == "connected"

    lan_data = {
        "lan_ipv4_ipaddr": "192.168.7.250",
        "lan_ipv4_netmask": "255.255.255.0",
        "lan_ipv4_macaddr": "AA-BB-CC-11-22-33",
    }
    dhcp_data = {
        "enable": "on",
        "ipaddr_start": "192.168.7.100",
        "ipaddr_end": "192.168.7.200",
        "leasetime": "120",
    }
    lan = parse_lan_info(lan_data, dhcp_data)
    assert lan["ipaddr"] == "192.168.7.250"
    assert lan["dhcp"]["enabled"] is True
    assert lan["dhcp"]["ipaddr_start"] == "192.168.7.100"


def test_parse_status_float_cpu_mem_and_inferred_status():
    raw_live_like = {
        "cpu1_usage": 0.05,
        "mem_usage": 0.58,
        "wan_ipv4_ipaddr": "203.0.113.42",
        "wan_ipv4_gateway": "203.0.113.1",
        "wan_ipv4_conntype": "pppoe",
    }
    summary = parse_status_summary(raw_live_like)
    assert summary["cpu_usage"] == 5
    assert summary["mem_usage"] == 58
    assert summary["internet_status"] == "connected"


def test_parse_clients_natural_ip_sort(sanitized_status):
    sorted_clients = parse_clients(sanitized_status, sort_by="ip")
    ips = [c["ipaddr"] for c in sorted_clients]
    # 192.168.7.10 must come before 192.168.7.101
    assert ips == ["192.168.7.10", "192.168.7.101", "192.168.7.102", "192.168.7.103"]
