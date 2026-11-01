"""Model Context Protocol (MCP) server for TP-Link Archer LuCI routers.

Exposes router monitoring and control tools to AI agents using FastMCP.
"""

from __future__ import annotations

from typing import Any

from mcp.server.fastmcp import FastMCP

from tpluci.client import RouterClient
from tpluci.config import resolve_satellite_credentials
from tpluci.endpoints import WIFI_RADIO_MAP
from tpluci.exceptions import SafetyAbortError, TpluciError
from tpluci.models import (
    normalize_weekday,
    parse_clients,
    parse_clients_detailed,
    parse_lan_info,
    parse_mesh_satellite_detail,
    parse_mesh_satellites,
    parse_mesh_topology,
    parse_status_summary,
    parse_wan_info,
    parse_wifi_summary,
    resolve_client_target,
    resolve_mesh_node,
)
from tpluci.satellites import connect_satellite

mcp = FastMCP("tpluci")


def _get_client() -> RouterClient:
    """Instantiate a client using default profile and session caching."""
    return RouterClient(use_cache=True)


@mcp.tool()
def router_get_status(full: bool = False, field: str | None = None) -> dict[str, Any]:
    """Retrieve router system health, CPU, memory, WAN/LAN IPs, and Wi-Fi status.

    Args:
        full: If True, returns all 199 raw LuCI status fields.
        field: If specified, returns only the single named field.
    """
    try:
        client = _get_client()
        raw_all = client.call("status", "all")

        if field:
            if field in raw_all:
                return {field: raw_all[field]}
            return {"ok": False, "error": f"Field '{field}' not found in status?form=all"}

        if full:
            return raw_all

        return parse_status_summary(raw_all)
    except TpluciError as err:
        return err.to_dict()


@mcp.tool()
def router_list_clients(
    query: str | None = None,
    medium: str = "all",
    node: str | None = None,
    detailed: bool = False,
) -> list[dict[str, Any]] | dict[str, Any]:
    """List connected wired and wireless devices with hostnames, IP, MAC, and optional mesh telemetry.

    Args:
        query: Optional case-insensitive search string matching hostname, IP, MAC, or node.
        medium: Filter by connection medium ('all', 'wireless', or 'wired').
        node: Optional filter by connected mesh node name or MAC.
        detailed: If True, fetches rich telemetry (parent mesh node, real-time speeds, signal dBm, traffic).
    """
    try:
        client = _get_client()
        if detailed or node:
            raw_topo = client.call("easymesh_network", "mesh_topology")
            raw_accel = client.call("smart_network", "game_accelerator", operation="loadDevice")
            raw_all = client.call("status", "all")
            clients = parse_clients_detailed(raw_topo, raw_accel, raw_all)
            if medium != "all":
                clients = [c for c in clients if c["medium"] == medium.lower()]
            if node:
                n_clean = node.strip().lower()
                clients = [c for c in clients if n_clean in str(c.get("node", "")).lower()]
            if query:
                q = query.strip().lower()
                clients = [
                    c for c in clients
                    if q in str(c.get("hostname", "")).lower()
                    or q in str(c.get("ipaddr", "")).lower()
                    or q in str(c.get("macaddr", "")).lower()
                    or q in str(c.get("node", "")).lower()
                ]
            return clients

        raw_all = client.call("status", "all")
        return parse_clients(raw_all, query=query, medium=medium)
    except TpluciError as err:
        return err.to_dict()


@mcp.tool()
def router_get_wifi(radio: str = "all") -> Any:
    """Inspect Wi-Fi configuration for main, guest, or IoT radios.

    Args:
        radio: Target radio ('2g', '5g', 'guest-2g', 'guest-5g', 'iot-2g', 'iot-5g', or 'all').
    """
    try:
        client = _get_client()
        if radio == "all":
            raw_all = client.call("status", "all")
            return parse_wifi_summary(raw_all)

        if radio not in WIFI_RADIO_MAP:
            return {
                "ok": False,
                "error": f"Unknown radio '{radio}'. Valid: {list(WIFI_RADIO_MAP.keys()) + ['all']}",
            }

        module, form, _ = WIFI_RADIO_MAP[radio]
        return client.call(module, form, operation="read")
    except TpluciError as err:
        return err.to_dict()


@mcp.tool()
def router_set_wifi(
    radio: str,
    enable: bool | None = None,
    ssid: str | None = None,
    password: str | None = None,
    hidden: bool | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Configure Wi-Fi radio settings with dry-run support and diff receipt.

    Args:
        radio: Target radio ('2g', '5g', 'guest-2g', 'guest-5g', 'iot-2g', 'iot-5g').
        enable: Enable (True) or disable (False) the radio.
        ssid: New network name.
        password: New WPA2/WPA3 password (8-63 characters).
        hidden: Hide SSID broadcast if True.
        dry_run: If True, simulate and return before/after diff without writing to router.
    """
    if radio not in WIFI_RADIO_MAP:
        return {"ok": False, "error": f"Unknown radio '{radio}'"}

    updates: dict[str, Any] = {}
    if enable is not None:
        updates["enable"] = "on" if enable else "off"
    if ssid is not None:
        updates["ssid"] = ssid
    if password is not None:
        if not (8 <= len(password) <= 63):
            return {"ok": False, "error": "Wi-Fi password must be between 8 and 63 characters"}
        updates["psk_key"] = password
    if hidden is not None:
        updates["hidden"] = "on" if hidden else "off"

    if not updates:
        return {"ok": False, "error": "No configuration parameters provided"}

    try:
        client = _get_client()
        module, form, desc = WIFI_RADIO_MAP[radio]
        receipt = client.read_modify_write(module, form, updates, dry_run=dry_run)
        receipt["radio"] = radio
        receipt["name"] = desc
        return receipt
    except TpluciError as err:
        return err.to_dict()


@mcp.tool()
def router_get_network_info() -> dict[str, Any]:
    """Retrieve detailed WAN connection parameters and LAN / DHCP configuration."""
    try:
        client = _get_client()
        raw_wan = client.call("network", "wan_ipv4_status")
        raw_all = client.call("status", "all")
        raw_lan = client.call("network", "lan_ipv4")
        raw_dhcp = client.call("dhcps", "setting")

        return {
            "wan": parse_wan_info(raw_wan, raw_all),
            "lan": parse_lan_info(raw_lan, raw_dhcp),
        }
    except TpluciError as err:
        return err.to_dict()


@mcp.tool()
def router_manage_client(
    target: str,
    alias: str | None = None,
    download_limit_kbps: int | None = None,
    upload_limit_kbps: int | None = None,
    disable_limit: bool = False,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Rename a client device or configure its bandwidth speed limit.

    Args:
        target: Client IP, MAC address, or hostname.
        alias: New custom display name for the client (1-64 characters).
        download_limit_kbps: Bandwidth download throttle in Kbps (1-1024000).
        upload_limit_kbps: Bandwidth upload throttle in Kbps (1-1024000).
        disable_limit: If True, disables existing speed limits for this client.
        dry_run: If True, simulates the mutation without modifying router configuration.
    """
    try:
        client = _get_client()
        try:
            raw_accel = client.call("smart_network", "game_accelerator", operation="loadDevice")
            clients = parse_clients_detailed(None, raw_accel)
        except Exception:
            clients = []

        resolved = resolve_client_target(clients, target)
        if not resolved:
            raw_all = client.call("status", "all")
            resolved = resolve_client_target(parse_clients(raw_all), target)

        if not resolved:
            return {"ok": False, "error": f"Client '{target}' not found."}

        target_mac = resolved["macaddr"]
        results: dict[str, Any] = {
            "ok": True,
            "dry_run": dry_run,
            "target": target,
            "mac": target_mac,
            "actions": {},
        }

        if alias is not None:
            if not (1 <= len(alias) <= 64):
                return {"ok": False, "error": "Client alias must be between 1 and 64 characters."}
            if not dry_run:
                client.call("traffic", "dev_name", operation="write", params={"mac": target_mac, "alias": alias})
            results["actions"]["rename"] = {
                "before": resolved.get("hostname", ""),
                "after": alias,
            }

        if disable_limit:
            if not dry_run:
                client.call(
                    "smart_network",
                    "client_speed_limit",
                    operation="write",
                    params={"mac": target_mac, "enableLimit": "off"},
                )
            results["actions"]["speed_limit"] = {
                "enabled": False,
                "downloadLimit": -1,
                "uploadLimit": -1,
            }
        elif download_limit_kbps is not None or upload_limit_kbps is not None:
            if download_limit_kbps is not None and not (1 <= download_limit_kbps <= 1024000):
                return {"ok": False, "error": "download_limit_kbps must be between 1 and 1024000."}
            if upload_limit_kbps is not None and not (1 <= upload_limit_kbps <= 1024000):
                return {"ok": False, "error": "upload_limit_kbps must be between 1 and 1024000."}

            d_val = str(download_limit_kbps) if download_limit_kbps is not None else "-1"
            u_val = str(upload_limit_kbps) if upload_limit_kbps is not None else "-1"
            if not dry_run:
                client.call(
                    "smart_network",
                    "client_speed_limit",
                    operation="write",
                    params={"mac": target_mac, "enableLimit": "on", "downloadLimit": d_val, "uploadLimit": u_val},
                )
            results["actions"]["speed_limit"] = {
                "enabled": True,
                "downloadLimit": int(d_val),
                "uploadLimit": int(u_val),
            }

        if not results["actions"]:
            return {"ok": False, "error": "No action specified (provide alias, limit, or disable_limit)."}

        return results
    except TpluciError as err:
        return err.to_dict()


@mcp.tool()
def router_get_mesh(node: str | None = None, include_firmware: bool = False) -> dict[str, Any]:
    """Retrieve full EasyMesh topology tree, satellite extender list, and per-node metrics.

    Args:
        node: Optional specific satellite name, IP, or MAC to inspect in detail.
        include_firmware: If True, queries satellite firmware versions and updates.
    """
    try:
        client = _get_client()
        raw_list = client.call("easymesh_network", "mesh_sclient_list_all", operation="read")
        satellites = parse_mesh_satellites(raw_list)

        if node:
            resolved = resolve_mesh_node(satellites, node)
            if not resolved:
                return {"ok": False, "error": f"Mesh satellite '{node}' not found."}
            raw_detail = client.call(
                "easymesh_network", "mesh_sclient_detail", operation="read", params={"mac": resolved["mac"]}
            )
            detail = parse_mesh_satellite_detail(raw_detail)
            if include_firmware:
                try:
                    raw_fw = client.call("firmware", "slave_cmd", operation="slave_get_info")
                    detail["firmware_info"] = raw_fw
                except Exception:
                    pass
            return detail

        raw_topo = client.call("easymesh_network", "mesh_topology", operation="read")
        topo = parse_mesh_topology(raw_topo)

        result: dict[str, Any] = {
            "satellites": satellites,
            "topology": topo,
        }

        if include_firmware:
            try:
                raw_fw = client.call("firmware", "slave_cmd", operation="slave_get_info")
                result["firmware_status"] = raw_fw
            except Exception:
                pass

        return result
    except TpluciError as err:
        return err.to_dict()


@mcp.tool()
def router_set_mesh_node(
    node: str,
    name: str | None = None,
    location: str | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Rename or update the location of an EasyMesh satellite node.

    Args:
        node: Target satellite name, IP, or MAC.
        name: New human-readable name for the satellite node.
        location: New location string (e.g. 'office', 'bedroom', 'living_room').
        dry_run: If True, simulates mutation without writing to router.
    """
    if name is None and location is None:
        return {"ok": False, "error": "Specify at least one of name or location to update."}

    try:
        client = _get_client()
        raw_list = client.call("easymesh_network", "mesh_sclient_list_all", operation="read")
        satellites = parse_mesh_satellites(raw_list)
        resolved = resolve_mesh_node(satellites, node)
        if not resolved:
            return {"ok": False, "error": f"Mesh satellite '{node}' not found."}

        target_mac = resolved["mac"]
        raw_detail = client.call(
            "easymesh_network", "mesh_sclient_detail", operation="read", params={"mac": target_mac}
        )

        old_name = raw_detail.get("name", resolved.get("name", ""))
        old_loc = raw_detail.get("location", resolved.get("location", ""))

        final_name = name if name is not None else old_name
        final_loc = location if location is not None else old_loc

        diff = {}
        if name is not None:
            diff["name"] = {"before": old_name, "after": final_name}
        if location is not None:
            diff["location"] = {"before": old_loc, "after": final_loc}

        payload = {"mac": target_mac, "name": final_name, "location": final_loc}
        if dry_run:
            return {"ok": True, "dry_run": True, "changed": True, "mac": target_mac, "diff": diff}

        client.call("easymesh_network", "mesh_sclient_detail", operation="write", params=payload)
        return {"ok": True, "dry_run": False, "changed": True, "mac": target_mac, "diff": diff}
    except TpluciError as err:
        return err.to_dict()


@mcp.tool()
def router_reboot_mesh_node(
    node: str,
    confirm: bool = False,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Reboot a specific EasyMesh satellite extender. Strictly requires confirm=True.

    Args:
        node: Target satellite name, IP, or MAC address.
        confirm: Must be explicitly set to True to initiate hardware reboot.
        dry_run: If True, simulates reboot without issuing command.
    """
    if not confirm:
        return {
            "ok": False,
            "error_code": "SAFETY_ABORT",
            "message": "Refusing to reboot satellite without explicit confirm=True.",
            "hint": "Set confirm=True to authorize satellite reboot.",
        }

    try:
        client = _get_client()
        satellites = []
        try:
            raw_list = client.call("easymesh_network", "mesh_sclient_list_all", operation="read")
            satellites = parse_mesh_satellites(raw_list)
        except Exception:
            pass

        resolved = resolve_mesh_node(satellites, node)
        if resolved:
            node_name = resolved.get("name") or resolved.get("model", "")
            node_ip = resolved["ip"]
        else:
            clean = node.replace("http://", "").replace("https://", "").split("/")[0]
            if any(c.isdigit() for c in clean) and ("." in clean or ":" in clean):
                node_name = clean
                node_ip = clean
            else:
                return {"ok": False, "error": f"Mesh satellite '{node}' not found."}

        if dry_run:
            return {
                "ok": True,
                "dry_run": True,
                "reboot": True,
                "node": node_name,
                "ip": node_ip,
                "message": f"[DRY-RUN] Simulated reboot for satellite {node_name} ({node_ip}).",
            }

        resolved_user, resolved_pwd = resolve_satellite_credentials(
            node_name=node_name,
            node_ip=node_ip,
            base_creds=client.creds,
        )
        sat_client = connect_satellite(
            ip=node_ip,
            password=resolved_pwd,
            username=resolved_user,
            timeout=client.creds.timeout,
        )
        try:
            res = sat_client.reboot()
            res["node"] = node_name
            return res
        finally:
            sat_client.logout()
    except Exception as err:
        if isinstance(err, TpluciError):
            return err.to_dict()
        return {"ok": False, "error": str(err)}


@mcp.tool()
def router_system_settings(
    reboot_schedule_enable: bool | None = None,
    reboot_cycle: str | None = None,
    reboot_day: str | None = None,
    reboot_time: str | None = None,
    led_enable: bool | None = None,
    night_mode_enable: bool | None = None,
    night_start: str | None = None,
    night_end: str | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Inspect or configure router scheduled reboot and LED / Night Mode settings.

    Args:
        reboot_schedule_enable: Enable or disable scheduled automatic reboot.
        reboot_cycle: 'day', 'week', or 'month'.
        reboot_day: Day of week ('Mon'..'Sun') or day of month (1..28).
        reboot_time: Scheduled time in HH:MM format.
        led_enable: Enable (True) or disable (False) router status LEDs.
        night_mode_enable: Enable or disable LED Night Mode schedule.
        night_start: Night mode start time (HH:MM).
        night_end: Night mode end time (HH:MM).
        dry_run: If True, simulates changes without writing to router.
    """
    has_mutation = any(
        x is not None
        for x in (
            reboot_schedule_enable,
            reboot_cycle,
            reboot_day,
            reboot_time,
            led_enable,
            night_mode_enable,
            night_start,
            night_end,
        )
    )

    try:
        client = _get_client()

        if not has_mutation:
            raw_reboot = client.call("reboot", "set", operation="read")
            raw_gen = client.call("ledgeneral", "setting", operation="read")
            raw_pm = client.call("ledpm", "setting", operation="read")
            return {
                "reboot_schedule": {
                    "enabled": raw_reboot.get("enable") == "on",
                    "cycle": raw_reboot.get("cycle", "week"),
                    "day": raw_reboot.get("day", ""),
                    "time": raw_reboot.get("time", ""),
                },
                "led": {
                    "enabled": raw_gen.get("enable") == "on",
                    "night_mode": raw_pm.get("enable") == "on",
                    "night_start": raw_pm.get("time_start", ""),
                    "night_end": raw_pm.get("time_end", ""),
                },
            }

        diff: dict[str, Any] = {}
        changed = False

        # Reboot schedule
        rb_updates: dict[str, Any] = {}
        if reboot_schedule_enable is not None:
            rb_updates["enable"] = "on" if reboot_schedule_enable else "off"
        if reboot_cycle is not None:
            rb_updates["cycle"] = reboot_cycle.lower()
        if reboot_day is not None:
            rb_updates["day"] = normalize_weekday(reboot_day)
        if reboot_time is not None:
            rb_updates["time"] = reboot_time

        if rb_updates:
            receipt_rb = client.read_modify_write("reboot", "set", rb_updates, dry_run=dry_run)
            diff["reboot_schedule"] = receipt_rb.get("diff", {})
            if receipt_rb.get("changed"):
                changed = True

        # LED general
        if led_enable is not None:
            receipt_gen = client.read_modify_write(
                "ledgeneral", "setting", {"enable": "on" if led_enable else "off"}, dry_run=dry_run
            )
            diff["led"] = receipt_gen.get("diff", {})
            if receipt_gen.get("changed"):
                changed = True

        # Night mode
        pm_updates: dict[str, Any] = {}
        if night_mode_enable is not None:
            pm_updates["enable"] = "on" if night_mode_enable else "off"
        if night_start is not None:
            pm_updates["time_start"] = night_start
        if night_end is not None:
            pm_updates["time_end"] = night_end

        if pm_updates:
            receipt_pm = client.read_modify_write("ledpm", "setting", pm_updates, dry_run=dry_run)
            diff["night_mode"] = receipt_pm.get("diff", {})
            if receipt_pm.get("changed"):
                changed = True

        return {
            "ok": True,
            "dry_run": dry_run,
            "changed": changed,
            "diff": diff,
        }
    except Exception as err:
        if isinstance(err, TpluciError):
            return err.to_dict()
        return {"ok": False, "error": str(err)}


@mcp.tool()
def router_reboot(confirm: bool = False) -> dict[str, Any]:
    """Reboot the physical router hardware. Requires explicit confirm=True.

    Args:
        confirm: Must be explicitly set to True to initiate hardware reboot.
    """
    if not confirm:
        return {
            "ok": False,
            "error_code": "SAFETY_ABORT",
            "message": "Refusing to reboot router without explicit confirm=True.",
            "hint": "Set confirm=True to authorize router reboot.",
        }

    try:
        client = _get_client()
        client.call("system", "reboot", operation="reboot")
        return {"ok": True, "reboot": True, "message": "Reboot command sent to router."}
    except TpluciError as err:
        return err.to_dict()


@mcp.tool()
def router_raw_call(
    module: str,
    form: str,
    operation: str = "read",
    params: dict[str, Any] | None = None,
) -> Any:
    """Execute raw signed LuCI API call to a specific module and form.

    Args:
        module: LuCI module (e.g. 'status', 'network', 'wireless', 'time').
        form: Form callback (e.g. 'all', 'lan_ipv4', 'settings').
        operation: 'read' or 'write'.
        params: Optional URL parameters for write operations.
    """
    try:
        client = _get_client()
        return client.call(module, form, operation=operation, params=params)
    except TpluciError as err:
        return err.to_dict()


def main() -> None:
    """Run FastMCP server."""
    mcp.run()


if __name__ == "__main__":
    main()
