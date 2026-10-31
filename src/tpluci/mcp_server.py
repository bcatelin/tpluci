"""Model Context Protocol (MCP) server for TP-Link Archer LuCI routers.

Exposes router monitoring and control tools to AI agents using FastMCP.
"""

from __future__ import annotations

from typing import Any

from mcp.server.fastmcp import FastMCP

from tpluci.client import RouterClient
from tpluci.endpoints import WIFI_RADIO_MAP
from tpluci.exceptions import SafetyAbortError, TpluciError
from tpluci.models import (
    parse_clients,
    parse_lan_info,
    parse_status_summary,
    parse_wan_info,
    parse_wifi_summary,
)

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
def router_list_clients(query: str | None = None, medium: str = "all") -> list[dict[str, Any]] | dict[str, Any]:
    """List connected wired and wireless devices with hostnames, IP, and MAC addresses.

    Args:
        query: Optional case-insensitive search string matching hostname, IP, or MAC.
        medium: Filter by connection medium ('all', 'wireless', or 'wired').
    """
    try:
        client = _get_client()
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
