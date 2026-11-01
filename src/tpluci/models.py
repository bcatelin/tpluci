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


WEEKDAY_MAP: dict[str, str] = {
    "mon": "Mon",
    "monday": "Mon",
    "tue": "Tues",
    "tues": "Tues",
    "tuesday": "Tues",
    "wed": "Wed",
    "wednesday": "Wed",
    "thu": "Thur",
    "thur": "Thur",
    "thurs": "Thur",
    "thursday": "Thur",
    "fri": "Fri",
    "friday": "Fri",
    "sat": "Sat",
    "saturday": "Sat",
    "sun": "Sun",
    "sunday": "Sun",
}


def normalize_weekday(day: str) -> str:
    """Normalize day string to Archer AX23 LuCI reboot weekday format (e.g. 'Tues', 'Thur')."""
    cleaned = day.strip()
    # Check numeric 1..28 for monthly cycle
    if cleaned.isdigit():
        val = int(cleaned)
        if 1 <= val <= 28:
            return str(val)
        raise ValueError(f"Day of month must be between 1 and 28, got: '{day}'")

    low = cleaned.lower()
    if low in WEEKDAY_MAP:
        return WEEKDAY_MAP[low]

    # Already proper case
    if cleaned in ("Mon", "Tues", "Wed", "Thur", "Fri", "Sat", "Sun"):
        return cleaned

    raise ValueError(
        f"Invalid weekday '{day}'. Expected one of: Mon, Tues, Wed, Thur, Fri, Sat, Sun (or 1-28 for monthly)."
    )


def parse_mesh_satellites(
    raw_sclient_list: list[dict[str, Any]] | dict[str, Any],
) -> list[dict[str, Any]]:
    """Normalize mesh satellites list from easymesh_network?form=mesh_sclient_list_all."""
    items: list[dict[str, Any]]
    if isinstance(raw_sclient_list, list):
        items = raw_sclient_list
    elif isinstance(raw_sclient_list, dict):
        items = (
            raw_sclient_list.get("mesh_sclient_list")
            or raw_sclient_list.get("sclient_list")
            or raw_sclient_list.get("data")
            or []
        )
    else:
        items = []

    satellites: list[dict[str, Any]] = []
    for item in items:
        conn = item.get("connect_type", "")
        backhaul = "wired" if conn == "wire" else "wireless"

        raw_sig = item.get("signal_strength", 0)
        try:
            sig_int = int(raw_sig)
        except (TypeError, ValueError):
            sig_int = 0

        if conn == "wire" or sig_int == -254 or str(raw_sig) == "-254":
            signal = "N/A"
        else:
            signal = f"{sig_int} dBm"

        num_clients = item.get("client_num") or item.get("mesh_nclient_num") or 0
        try:
            clients_count = int(num_clients)
        except (TypeError, ValueError):
            clients_count = 0

        satellites.append({
            "name": item.get("name", ""),
            "model": item.get("model", ""),
            "ip": item.get("ip") or item.get("ipaddr", ""),
            "mac": item.get("mac") or item.get("macaddr", ""),
            "location": item.get("location", ""),
            "connect_type": conn,
            "backhaul": backhaul,
            "signal_strength": signal,
            "clients_count": clients_count,
            "status": item.get("status", "online"),
            "device_type": item.get("device_type", ""),
        })

    return satellites


def parse_mesh_topology(raw_topo: dict[str, Any]) -> dict[str, Any]:
    """Parse full mesh topology tree from easymesh_network?form=mesh_topology."""
    root_clients: list[dict[str, Any]] = []
    for c in raw_topo.get("mesh_nclient_list", []):
        root_clients.append({
            "name": c.get("hostname") or c.get("name", ""),
            "ip": c.get("ip") or c.get("ipaddr", ""),
            "mac": c.get("mac") or c.get("macaddr", ""),
            "connection_type": c.get("wire_type") or c.get("connection_type", ""),
            "device_type": c.get("device_type", ""),
        })

    root_node = {
        "name": raw_topo.get("name", "Archer AX23"),
        "model": raw_topo.get("model", "Archer AX23"),
        "ip": raw_topo.get("ip", ""),
        "mac": raw_topo.get("mac", ""),
        "clients": root_clients,
    }

    satellites: list[dict[str, Any]] = []
    for s in raw_topo.get("mesh_sclient_list", []):
        sat_clients: list[dict[str, Any]] = []
        for c in s.get("mesh_nclient_list", []):
            raw_tx = c.get("txrate", 0)
            raw_rx = c.get("rxrate", 0)
            try:
                tx_int = int(raw_tx)
            except (TypeError, ValueError):
                tx_int = 0
            try:
                rx_int = int(raw_rx)
            except (TypeError, ValueError):
                rx_int = 0

            tx_mbps = round(tx_int / 1000) if tx_int > 2000 else tx_int
            rx_mbps = round(rx_int / 1000) if rx_int > 2000 else rx_int

            raw_sig = c.get("signal_strength")
            sig_str = "N/A"
            if raw_sig not in (None, "", -254, "-254"):
                sig_str = f"{raw_sig} dBm" if not str(raw_sig).endswith("dBm") else str(raw_sig)

            sat_clients.append({
                "name": c.get("name") or c.get("hostname", ""),
                "ip": c.get("ip") or c.get("ipaddr", ""),
                "mac": c.get("mac") or c.get("macaddr", ""),
                "connection_type": c.get("connection_type") or c.get("wire_type", ""),
                "signal_strength": sig_str,
                "txrate_mbps": tx_mbps,
                "rxrate_mbps": rx_mbps,
            })

        raw_sat_sig = s.get("signal_strength", 0)
        conn = s.get("connect_type", "")
        if conn == "wire" or str(raw_sat_sig) == "-254" or raw_sat_sig == -254:
            sat_sig = "N/A"
        else:
            sat_sig = f"{raw_sat_sig} dBm"

        satellites.append({
            "name": s.get("name", ""),
            "model": s.get("model", ""),
            "ip": s.get("ip") or s.get("ipaddr", ""),
            "mac": s.get("mac") or s.get("macaddr", ""),
            "location": s.get("location", ""),
            "connect_type": conn,
            "backhaul": "wired" if conn == "wire" else "wireless",
            "signal_strength": sat_sig,
            "clients": sat_clients,
        })

    return {
        "root": root_node,
        "satellites": satellites,
    }


def parse_mesh_satellite_detail(raw_detail: dict[str, Any]) -> dict[str, Any]:
    """Normalize detailed single-node mesh metrics from easymesh_network?form=mesh_sclient_detail."""
    conn = raw_detail.get("connect_type", "")
    backhaul = "wired" if conn == "wire" else "wireless"

    def _to_mbps(raw_val: Any) -> int:
        if raw_val is None:
            return 0
        try:
            return int(raw_val) // 1024
        except (TypeError, ValueError):
            return 0

    def _to_signal(raw_val: Any) -> str:
        if raw_val is None or conn == "wire" or str(raw_val) == "-254" or raw_val == -254:
            return "N/A"
        return f"{raw_val} dBm"

    clients: list[dict[str, Any]] = []
    for c in raw_detail.get("mesh_nclient_list", []):
        raw_tx = c.get("txrate", 0)
        raw_rx = c.get("rxrate", 0)
        try:
            tx_int = int(raw_tx)
        except (TypeError, ValueError):
            tx_int = 0
        try:
            rx_int = int(raw_rx)
        except (TypeError, ValueError):
            rx_int = 0

        clients.append({
            "name": c.get("name") or c.get("hostname", ""),
            "ip": c.get("ip") or c.get("ipaddr", ""),
            "mac": c.get("mac") or c.get("macaddr", ""),
            "connection_type": c.get("connection_type") or c.get("wire_type", ""),
            "signal_strength": _to_signal(c.get("signal_strength")),
            "txrate_mbps": round(tx_int / 1000) if tx_int > 2000 else tx_int,
            "rxrate_mbps": round(rx_int / 1000) if rx_int > 2000 else rx_int,
        })

    return {
        "name": raw_detail.get("name", ""),
        "location": raw_detail.get("location", ""),
        "model": raw_detail.get("model", ""),
        "mac": raw_detail.get("mac", ""),
        "ip": raw_detail.get("ip", ""),
        "firmware_version": raw_detail.get("firmware_version") or raw_detail.get("soft_ver", ""),
        "parent_device_mac": raw_detail.get("parent_device_mac", ""),
        "connect_type": conn,
        "backhaul": backhaul,
        "link_speed_24g_mbps": _to_mbps(raw_detail.get("link_speed_24g")),
        "link_speed_5g_mbps": _to_mbps(raw_detail.get("link_speed_5g")),
        "signal_strength_24g": _to_signal(raw_detail.get("signal_strength_24g")),
        "signal_strength_5g": _to_signal(raw_detail.get("signal_strength_5g")),
        "clients": clients,
    }


def resolve_mesh_node(nodes: list[dict[str, Any]], target: str) -> dict[str, Any] | None:
    """Resolve a target string (name, IP, or MAC) to a mesh node dictionary."""
    t_clean = target.strip().lower()
    t_mac = t_clean.replace("-", ":")

    for node in nodes:
        node_mac = str(node.get("mac", "")).lower().replace("-", ":")
        if node_mac == t_mac:
            return node

    for node in nodes:
        node_ip = str(node.get("ip", "")).lower()
        if node_ip == t_clean:
            return node

    for node in nodes:
        node_name = str(node.get("name", "")).lower()
        if node_name == t_clean:
            return node

    for node in nodes:
        node_model = str(node.get("model", "")).lower()
        if node_model == t_clean:
            return node

    for node in nodes:
        node_name = str(node.get("name", "")).lower()
        node_model = str(node.get("model", "")).lower()
        if t_clean in node_name or t_clean in node_model:
            return node

    return None


def parse_clients_detailed(
    raw_topo: dict[str, Any] | None,
    raw_accel: list[dict[str, Any]] | dict[str, Any],
    raw_all: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Combine mesh topology parent node mapping with game_accelerator rich telemetry."""
    mac_to_node: dict[str, str] = {}
    root_name = "Archer AX23"

    if raw_topo:
        root_name = raw_topo.get("name", "Archer AX23") or "Archer AX23"
        for c in raw_topo.get("mesh_nclient_list", []):
            c_mac = str(c.get("mac") or c.get("macaddr", "")).lower().replace("-", ":")
            if c_mac:
                mac_to_node[c_mac] = root_name

        for s in raw_topo.get("mesh_sclient_list", []):
            sat_name = s.get("name") or s.get("model") or "Satellite"
            for c in s.get("mesh_nclient_list", []):
                c_mac = str(c.get("mac") or c.get("macaddr", "")).lower().replace("-", ":")
                if c_mac:
                    mac_to_node[c_mac] = sat_name

    dev_list: list[dict[str, Any]]
    if isinstance(raw_accel, list):
        dev_list = raw_accel
    elif isinstance(raw_accel, dict):
        dev_list = (
            raw_accel.get("device_list")
            or raw_accel.get("deviceList")
            or raw_accel.get("devices")
            or []
        )
    else:
        dev_list = []

    clients: list[dict[str, Any]] = []
    seen_macs: set[str] = set()

    for dev in dev_list:
        mac = str(dev.get("mac", ""))
        mac_key = mac.lower().replace("-", ":")
        seen_macs.add(mac_key)

        node = mac_to_node.get(mac_key, root_name)

        raw_tx = dev.get("txrate", 0)
        raw_rx = dev.get("rxrate", 0)
        try:
            tx_int = int(raw_tx)
        except (TypeError, ValueError):
            tx_int = 0
        try:
            rx_int = int(raw_rx)
        except (TypeError, ValueError):
            rx_int = 0

        tx_mbps = round(tx_int / 1000) if tx_int > 2000 else tx_int
        rx_mbps = round(rx_int / 1000) if rx_int > 2000 else rx_int

        raw_ds = dev.get("downloadSpeed", 0)
        raw_us = dev.get("uploadSpeed", 0)
        try:
            ds_int = int(raw_ds)
        except (TypeError, ValueError):
            ds_int = 0
        try:
            us_int = int(raw_us)
        except (TypeError, ValueError):
            us_int = 0
        down_kbps = ds_int * 8 // 1024
        up_kbps = us_int * 8 // 1024

        tag = str(dev.get("deviceTag", ""))
        medium = "wired" if tag.lower() == "wired" else "wireless"

        raw_sig = dev.get("signal")
        if medium == "wired" or raw_sig in (None, "", 0, "0", -110, "-110"):
            signal = None
        else:
            signal = f"{raw_sig} dBm" if not str(raw_sig).endswith("dBm") else str(raw_sig)

        enable_limit = dev.get("enableLimit") == "on"
        try:
            dl_limit = int(dev.get("downloadLimit", -1))
        except (TypeError, ValueError):
            dl_limit = -1
        try:
            ul_limit = int(dev.get("uploadLimit", -1))
        except (TypeError, ValueError):
            ul_limit = -1

        try:
            traffic = int(dev.get("trafficUsage", 0) or 0)
        except (TypeError, ValueError):
            traffic = 0

        try:
            online_time = int(dev.get("onlineTime", 0) or 0)
        except (TypeError, ValueError):
            online_time = 0

        clients.append({
            "hostname": dev.get("deviceName", ""),
            "ipaddr": dev.get("ip", ""),
            "macaddr": mac,
            "medium": medium,
            "band": tag,
            "node": node,
            "signal": signal,
            "txrate_mbps": tx_mbps,
            "rxrate_mbps": rx_mbps,
            "down_speed_kbps": down_kbps,
            "up_speed_kbps": up_kbps,
            "traffic_bytes": traffic,
            "online_time_seconds": online_time,
            "speed_limit": {
                "enabled": enable_limit,
                "down_kbps": dl_limit,
                "up_kbps": ul_limit,
            },
            "device_type": dev.get("deviceType", "other"),
        })

    # If raw_all was provided, append any online devices not in game_accelerator
    if raw_all:
        for host in raw_all.get("access_devices_wireless_host", []):
            m = str(host.get("macaddr", "")).lower().replace("-", ":")
            if m and m not in seen_macs:
                seen_macs.add(m)
                clients.append({
                    "hostname": host.get("hostname", ""),
                    "ipaddr": host.get("ipaddr", ""),
                    "macaddr": host.get("macaddr", ""),
                    "medium": "wireless",
                    "band": host.get("wire_type", ""),
                    "node": mac_to_node.get(m, root_name),
                    "signal": None,
                    "txrate_mbps": 0,
                    "rxrate_mbps": 0,
                    "down_speed_kbps": 0,
                    "up_speed_kbps": 0,
                    "traffic_bytes": 0,
                    "online_time_seconds": 0,
                    "speed_limit": {"enabled": False, "down_kbps": -1, "up_kbps": -1},
                    "device_type": "other",
                })
        for host in raw_all.get("access_devices_wired", []):
            m = str(host.get("macaddr", "")).lower().replace("-", ":")
            if m and m not in seen_macs:
                seen_macs.add(m)
                clients.append({
                    "hostname": host.get("hostname", ""),
                    "ipaddr": host.get("ipaddr", ""),
                    "macaddr": host.get("macaddr", ""),
                    "medium": "wired",
                    "band": "wired",
                    "node": mac_to_node.get(m, root_name),
                    "signal": None,
                    "txrate_mbps": 0,
                    "rxrate_mbps": 0,
                    "down_speed_kbps": 0,
                    "up_speed_kbps": 0,
                    "traffic_bytes": 0,
                    "online_time_seconds": 0,
                    "speed_limit": {"enabled": False, "down_kbps": -1, "up_kbps": -1},
                    "device_type": "other",
                })

    return clients


def resolve_client_target(clients: list[dict[str, Any]], target: str) -> dict[str, Any] | None:
    """Resolve a target client by MAC, IP, or hostname."""
    t_clean = target.strip().lower()
    t_mac = t_clean.replace("-", ":")

    for c in clients:
        c_mac = str(c.get("macaddr") or c.get("mac", "")).lower().replace("-", ":")
        if c_mac == t_mac:
            return c

    for c in clients:
        c_ip = str(c.get("ipaddr") or c.get("ip", "")).lower()
        if c_ip == t_clean:
            return c

    for c in clients:
        c_host = str(c.get("hostname") or c.get("name") or c.get("deviceName", "")).lower()
        if c_host == t_clean:
            return c

    for c in clients:
        c_host = str(c.get("hostname") or c.get("name") or c.get("deviceName", "")).lower()
        c_mac = str(c.get("macaddr") or c.get("mac", "")).lower().replace("-", ":")
        c_ip = str(c.get("ipaddr") or c.get("ip", "")).lower()
        if t_clean in c_host or t_clean in c_mac or t_clean in c_ip:
            return c

    return None

