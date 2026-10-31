"""Verified LuCI endpoint catalog and radio mappings for TP-Link Archer routers."""

from __future__ import annotations

from typing import Any

WIFI_RADIO_MAP: dict[str, tuple[str, str, str]] = {
    "2g": ("wireless", "wireless_2g", "Main 2.4 GHz"),
    "5g": ("wireless", "wireless_5g", "Main 5 GHz"),
    "guest-2g": ("wireless", "guest_2g", "Guest 2.4 GHz"),
    "guest-5g": ("wireless", "guest_5g", "Guest 5 GHz"),
    "iot-2g": ("wireless", "iot_2g", "IoT 2.4 GHz"),
    "iot-5g": ("wireless", "iot_5g", "IoT 5 GHz"),
}

VERIFIED_ENDPOINTS: list[dict[str, str]] = [
    # System, Status & Telemetry
    {
        "module": "status",
        "form": "all",
        "category": "System",
        "description": "Master endpoint returning 199 telemetry & status keys",
    },
    {
        "module": "status",
        "form": "internet",
        "category": "System",
        "description": "Quick WAN internet connection status",
    },
    {
        "module": "status",
        "form": "menu_status",
        "category": "System",
        "description": "Menu patrol status flag",
    },
    {
        "module": "status",
        "form": "cloud_login_window_pop",
        "category": "System",
        "description": "Cloud binding status and popup counts",
    },
    {
        "module": "system",
        "form": "sysmode",
        "category": "System",
        "description": "Router operation mode (Router / Bridge)",
    },
    {
        "module": "cloud_account",
        "form": "get_deviceInfo",
        "category": "System",
        "description": "Device model string (Archer AX23)",
    },
    {
        "module": "cloud_account",
        "form": "check_upgrade",
        "category": "System",
        "description": "Cloud firmware upgrade notification",
    },
    {
        "module": "firmware",
        "form": "upgrade",
        "category": "System",
        "description": "Firmware version, hardware revision, build date",
    },
    {
        "module": "firmware",
        "form": "auto_upgrade",
        "category": "System",
        "description": "Auto firmware update settings",
    },
    {
        "module": "time",
        "form": "settings",
        "category": "System",
        "description": "System clock, NTP servers, and timezone",
    },
    # Network (LAN, WAN, IPTV & DDNS)
    {
        "module": "network",
        "form": "wan_ipv4_status",
        "category": "Network",
        "description": "WAN IPv4 connection status and protocol",
    },
    {
        "module": "network",
        "form": "wan_ipv6_status",
        "category": "Network",
        "description": "WAN IPv6 status",
    },
    {
        "module": "network",
        "form": "lan_ipv4",
        "category": "Network",
        "description": "LAN IP address, subnet mask, and MAC address",
    },
    {
        "module": "network",
        "form": "lan_agg",
        "category": "Network",
        "description": "Link Aggregation (LACP) status and port assignments",
    },
    {
        "module": "dhcps",
        "form": "setting",
        "category": "Network",
        "description": "DHCP Server status, pool bounds, and lease time",
    },
    {
        "module": "iptv",
        "form": "setting",
        "category": "Network",
        "description": "IPTV / VLAN port mappings and IGMP snooping",
    },
    {
        "module": "ddns",
        "form": "provider",
        "category": "Network",
        "description": "Dynamic DNS provider status",
    },
    # Wireless & Mesh (Wi-Fi)
    {
        "module": "wireless",
        "form": "wireless_2g",
        "category": "Wireless",
        "description": "Main 2.4 GHz Wi-Fi radio configuration",
    },
    {
        "module": "wireless",
        "form": "wireless_5g",
        "category": "Wireless",
        "description": "Main 5 GHz Wi-Fi radio configuration",
    },
    {
        "module": "wireless",
        "form": "guest_2g",
        "category": "Wireless",
        "description": "Guest 2.4 GHz Wi-Fi radio configuration",
    },
    {
        "module": "wireless",
        "form": "guest_5g",
        "category": "Wireless",
        "description": "Guest 5 GHz Wi-Fi radio configuration",
    },
    {
        "module": "wireless",
        "form": "iot_2g",
        "category": "Wireless",
        "description": "IoT 2.4 GHz Wi-Fi radio configuration",
    },
    {
        "module": "wireless",
        "form": "iot_5g",
        "category": "Wireless",
        "description": "IoT 5 GHz Wi-Fi radio configuration",
    },
    {
        "module": "wireless",
        "form": "smart_connect",
        "category": "Wireless",
        "description": "Smart Connect band-steering setting",
    },
    {
        "module": "easymesh_network",
        "form": "mesh_sclient_list_all",
        "category": "Wireless",
        "description": "EasyMesh nodes and clients list",
    },
    # NAT, Forwarding & Security
    {
        "module": "nat",
        "form": "dmz",
        "category": "Security",
        "description": "DMZ host status and IP",
    },
    {
        "module": "nat",
        "form": "alg",
        "category": "Security",
        "description": "Application Layer Gateway (ALG) passthrough toggles",
    },
    {
        "module": "access_control",
        "form": "enable",
        "category": "Security",
        "description": "Access Control engine toggle and host MAC",
    },
    {
        "module": "access_control",
        "form": "mode",
        "category": "Security",
        "description": "Access Control mode (black / white list)",
    },
    {
        "module": "qos",
        "form": "settings",
        "category": "Security",
        "description": "Quality of Service bandwidth limits and prioritization",
    },
]
