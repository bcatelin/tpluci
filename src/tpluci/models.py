"""Data models and response normalizers for TP-Link LuCI telemetry and settings."""

from __future__ import annotations

from typing import Any

from tpluci.endpoints import WIFI_RADIO_MAP


def _normalize_percentage(val: Any) -> int | float:
    """Normalize router CPU/memory telemetry (0.0-1.0 float or 0-100 int) to integer percentage."""
    if isinstance(val, float):
        if 0.0 < val <= 1.0:
            return round(val * 100)
        return round(val)
    if isinstance(val, int):
        return val
    try:
        fval = float(val)
        if 0.0 < fval <= 1.0:
            return round(fval * 100)
        return round(fval)
    except (TypeError, ValueError):
        return 0


def parse_status_summary(raw_all: dict[str, Any]) -> dict[str, Any]:
    """Extract a curated, token-efficient dashboard summary (~120 tokens) from status?form=all."""
    wireless_hosts = raw_all.get("access_devices_wireless_host", [])
    wired_hosts = raw_all.get("access_devices_wired", [])

    wifi_summary: dict[str, dict[str, Any]] = {}
    radio_keys = [
        ("2g", "wireless_2g"),
        ("5g", "wireless_5g"),
        ("guest-2g", "guest_2g"),
        ("guest-5g", "guest_5g"),
        ("iot-2g", "iot_2g"),
        ("iot-5g", "iot_5g"),
    ]
    for key, prefix in radio_keys:
        wifi_summary[key] = {
            "enabled": raw_all.get(f"{prefix}_enable") == "on",
            "ssid": raw_all.get(f"{prefix}_ssid", ""),
        }

    wan_ip = raw_all.get("wan_ipv4_ipaddr", "")
    internet_status = raw_all.get("wan_internet_status") or raw_all.get("internet_status")
    if not internet_status:
        if wan_ip and wan_ip != "0.0.0.0":
            internet_status = "connected"
        elif wan_ip == "0.0.0.0":
            internet_status = "disconnected"
        else:
            internet_status = "unknown"

    raw_cpu = raw_all.get("cpu1_usage", raw_all.get("cpu_usage", 0))
    raw_mem = raw_all.get("mem_usage", 0)

    return {
        "model": raw_all.get("model", "Archer AX23"),
        "cpu_usage": _normalize_percentage(raw_cpu),
        "mem_usage": _normalize_percentage(raw_mem),
        "uptime_seconds": raw_all.get("wan_ipv4_uptime", 0),
        "internet_status": internet_status,
        "wan_ip": wan_ip,
        "wan_gateway": raw_all.get("wan_ipv4_gateway", ""),
        "wan_conntype": raw_all.get("wan_ipv4_conntype", ""),
        "lan_ip": raw_all.get("lan_ipv4_ipaddr", ""),
        "wifi": wifi_summary,
        "clients_count": {
            "wireless": len(wireless_hosts),
            "wired": len(wired_hosts),
            "total": len(wireless_hosts) + len(wired_hosts),
        },
    }


def parse_clients(
    raw_all: dict[str, Any],
    query: str | None = None,
    medium: str = "all",
    band: str | None = None,
    sort_by: str = "hostname",
) -> list[dict[str, Any]]:
    """Parse and filter connected clients from status?form=all."""
    clients: list[dict[str, Any]] = []

    # Wireless clients
    for item in raw_all.get("access_devices_wireless_host", []):
        wire_type = item.get("wire_type", "")
        clients.append({
            "hostname": item.get("hostname", ""),
            "ipaddr": item.get("ipaddr", ""),
            "macaddr": item.get("macaddr", ""),
            "medium": "wireless",
            "band": wire_type,
        })

    # Wired clients
    for item in raw_all.get("access_devices_wired", []):
        clients.append({
            "hostname": item.get("hostname", ""),
            "ipaddr": item.get("ipaddr", ""),
            "macaddr": item.get("macaddr", ""),
            "medium": "wired",
            "band": "wired",
        })

    # Filter by medium
    if medium != "all":
        clients = [c for c in clients if c["medium"] == medium.lower()]

    # Filter by band (e.g. "2g" matches "2.4G", "5g" matches "5G")
    if band:
        b_target = band.lower()
        if b_target in ("2g", "2.4g"):
            clients = [c for c in clients if "2.4" in c["band"].lower()]
        elif b_target in ("5g",):
            clients = [c for c in clients if "5" in c["band"].lower()]

    # Filter by query substring (hostname, ip, or mac)
    if query:
        q = query.strip().lower()
        clients = [
            c for c in clients
            if q in c["hostname"].lower() or q in c["ipaddr"].lower() or q in c["macaddr"].lower()
        ]

    # Sort
    if sort_by in ("ip", "ipaddr"):
        def _ip_sort_key(c: dict[str, Any]) -> tuple[int, ...]:
            ip = str(c.get("ipaddr", ""))
            parts = ip.split(".")
            if len(parts) == 4 and all(p.isdigit() for p in parts):
                return tuple(int(p) for p in parts)
            return (999, 999, 999, 999)

        clients.sort(key=_ip_sort_key)
        return clients

    sort_key = "hostname"
    if sort_by in ("mac", "macaddr"):
        sort_key = "macaddr"
    elif sort_by in ("band",):
        sort_key = "band"
    elif sort_by in ("medium",):
        sort_key = "medium"

    clients.sort(key=lambda c: str(c.get(sort_key, "")).lower())
    return clients


def parse_wifi_summary(raw_all: dict[str, Any]) -> list[dict[str, Any]]:
    """Extract standard summary of all 6 Wi-Fi radios."""
    results: list[dict[str, Any]] = []
    for radio_code, (module, form, desc) in WIFI_RADIO_MAP.items():
        prefix = form
        channel = raw_all.get(f"{prefix}_channel", "") or raw_all.get(f"{prefix}_current_channel", "")
        results.append({
            "radio": radio_code,
            "name": desc,
            "type": desc,
            "module": module,
            "form": form,
            "ssid": raw_all.get(f"{prefix}_ssid", ""),
            "enabled": raw_all.get(f"{prefix}_enable") == "on",
            "channel": channel,
            "encryption": raw_all.get(f"{prefix}_encryption", "psk"),
            "hidden": raw_all.get(f"{prefix}_hidden") == "on",
        })
    return results


def parse_wan_info(
    raw_wan: dict[str, Any],
    raw_all: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Normalize WAN IPv4/IPv6 status dictionary combining wan_ipv4_status and status?form=all."""
    merged: dict[str, Any] = {}
    if raw_all:
        merged.update(raw_all)
    if raw_wan:
        merged.update(raw_wan)

    ipaddr = merged.get("ipaddr") or merged.get("wan_ipv4_ipaddr", "")
    gateway = merged.get("gateway") or merged.get("wan_ipv4_gateway", "")
    netmask = merged.get("netmask") or merged.get("wan_ipv4_netmask", "")

    dns = merged.get("dns") or merged.get("wan_ipv4_dns", "")
    if not dns:
        dns_parts = [
            d for d in (merged.get("wan_ipv4_pridns", ""), merged.get("wan_ipv4_snddns", ""))
            if d and d != "0.0.0.0"
        ]
        dns = ", ".join(dns_parts)

    conntype = merged.get("conntype") or merged.get("wan_ipv4_conntype", "")
    uptime = merged.get("uptime", merged.get("wan_ipv4_uptime", 0))
    macaddr = merged.get("macaddr") or merged.get("wan_macaddr", "")

    status = merged.get("status") or merged.get("wan_internet_status") or merged.get("internet_status")
    if not status:
        status = "disconnected" if ipaddr == "0.0.0.0" else "connected"

    return {
        "ipaddr": ipaddr,
        "gateway": gateway,
        "netmask": netmask,
        "dns": dns,
        "macaddr": macaddr,
        "conntype": conntype,
        "uptime": uptime,
        "status": status,
    }


def parse_lan_info(raw_lan: dict[str, Any], raw_dhcp: dict[str, Any] | None = None) -> dict[str, Any]:
    """Normalize LAN network parameters and DHCP pool configuration."""
    info: dict[str, Any] = {
        "ipaddr": raw_lan.get("ipaddr", raw_lan.get("lan_ipv4_ipaddr", "")),
        "netmask": raw_lan.get("mask_type", raw_lan.get("lan_ipv4_netmask", "")),
        "macaddr": raw_lan.get("macaddr", raw_lan.get("lan_ipv4_macaddr", "")),
    }
    if raw_dhcp:
        info["dhcp"] = {
            "enabled": str(raw_dhcp.get("enable", "")).lower() == "on",
            "ipaddr_start": raw_dhcp.get("ipaddr_start", ""),
            "ipaddr_end": raw_dhcp.get("ipaddr_end", ""),
            "leasetime": raw_dhcp.get("leasetime", ""),
            "gateway": raw_dhcp.get("gateway", ""),
        }
    return info
