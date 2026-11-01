"""Pure-Python Command-Line Interface for TP-Link Archer LuCI routers.

Designed for <50ms startup latency (pure Click, zero heavy imports like rich or typer).
Accepts global flags (--json, --plain, --profile, --url, --no-cache, --timeout) in any position.
"""

from __future__ import annotations

import json
import sys
from typing import Any

import click

from tpluci import __version__
from tpluci.config import (
    DEFAULT_ROUTER_URL,
    DEFAULT_TIMEOUT,
    delete_profile,
    list_profiles,
    resolve_credentials,
    resolve_profile_name,
    resolve_satellite_credentials,
    save_profile,
    set_default_profile,
)
from tpluci.endpoints import VERIFIED_ENDPOINTS, WIFI_RADIO_MAP
from tpluci.exceptions import LuciApiError, SafetyAbortError, TpluciError
from tpluci.formatters import emit_error, emit_output, format_key_value, format_table
from tpluci.models import (
    WEEKDAY_MAP,
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


class ClientsGroup(click.Group):
    """Click Group that defaults unknown/missing subcommands to 'list' for backward compatibility."""

    def parse_args(self, ctx: click.Context, args: list[str]) -> list[str]:
        if args and args[0] in ("--help", "-h"):
            return super().parse_args(ctx, args)

        cmd_idx = -1
        for idx, arg in enumerate(args):
            if not arg.startswith("-"):
                cmd_idx = idx
                break

        if cmd_idx == -1:
            args = ["list"] + args
        elif args[cmd_idx] not in self.commands:
            args = ["list"] + args

        return super().parse_args(ctx, args)

    def resolve_command(
        self, ctx: click.Context, args: list[str]
    ) -> tuple[str | None, click.Command | None, list[str]]:
        if args and args[0] in ("--help", "-h"):
            return super().resolve_command(ctx, args)

        cmd_idx = -1
        for idx, arg in enumerate(args):
            if not arg.startswith("-"):
                cmd_idx = idx
                break

        if cmd_idx == -1:
            args = ["list"] + args
        elif args[cmd_idx] not in self.commands:
            args = ["list"] + args

        return super().resolve_command(ctx, args)


class MeshGroup(click.Group):
    """Click Group that defaults bare 'tpluci mesh' to 'list'."""

    def parse_args(self, ctx: click.Context, args: list[str]) -> list[str]:
        if not args:
            args = ["list"]
        return super().parse_args(ctx, args)

    def resolve_command(
        self, ctx: click.Context, args: list[str]
    ) -> tuple[str | None, click.Command | None, list[str]]:
        if not args:
            args = ["list"]
        return super().resolve_command(ctx, args)


class OrderIndependentGroup(click.Group):
    """Click Group that intercepts global options at any position before command parsing."""

    def parse_args(self, ctx: click.Context, args: list[str]) -> list[str]:
        ctx.ensure_object(dict)
        filtered_args: list[str] = []
        i = 0
        while i < len(args):
            arg = args[i]
            if arg == "--json":
                ctx.obj["json"] = True
            elif arg == "--plain":
                ctx.obj["plain"] = True
            elif arg == "--no-cache":
                ctx.obj["no_cache"] = True
            elif arg.startswith("--profile="):
                ctx.obj["profile"] = arg.split("=", 1)[1]
            elif arg == "--profile":
                if i + 1 >= len(args):
                    raise click.BadParameter("Option requires an argument.", param_hint="'--profile'")
                ctx.obj["profile"] = args[i + 1]
                i += 1
            elif arg.startswith("--url="):
                ctx.obj["url"] = arg.split("=", 1)[1]
            elif arg == "--url":
                if i + 1 >= len(args):
                    raise click.BadParameter("Option requires an argument.", param_hint="'--url'")
                ctx.obj["url"] = args[i + 1]
                i += 1
            elif arg.startswith("--timeout="):
                raw_val = arg.split("=", 1)[1]
                try:
                    ctx.obj["timeout"] = float(raw_val)
                except ValueError as exc:
                    raise click.BadParameter(f"'{raw_val}' is not a valid float.", param_hint="'--timeout'") from exc
            elif arg == "--timeout":
                if i + 1 >= len(args):
                    raise click.BadParameter("Option requires an argument.", param_hint="'--timeout'")
                raw_val = args[i + 1]
                try:
                    ctx.obj["timeout"] = float(raw_val)
                except ValueError as exc:
                    raise click.BadParameter(f"'{raw_val}' is not a valid float.", param_hint="'--timeout'") from exc
                i += 1
            else:
                filtered_args.append(arg)
            i += 1

        return super().parse_args(ctx, filtered_args)


def get_client(ctx: click.Context) -> Any:
    """Instantiate a RouterClient from CLI context parameters."""
    from tpluci.client import RouterClient

    ctx.ensure_object(dict)
    obj = ctx.obj
    profile = obj.get("profile")
    url = obj.get("url")
    timeout = obj.get("timeout")
    no_cache = obj.get("no_cache", False)

    try:
        creds = resolve_credentials(
            profile=profile,
            url_override=url,
            timeout_override=timeout,
        )
        if creds.warning and not obj.get("json", False):
            sys.stderr.write(f"{creds.warning}\n")
        return RouterClient(creds=creds, use_cache=not no_cache)
    except TpluciError as err:
        emit_error(err, json_mode=obj.get("json", False))
        sys.exit(err.exit_code)


@click.group(
    cls=OrderIndependentGroup,
    context_settings={"help_option_names": ["-h", "--help"]},
)
@click.option("--json", "json_flag", is_flag=True, help="Output machine-readable JSON to stdout")
@click.option("--plain", "plain_flag", is_flag=True, help="Output raw plaintext without ANSI styling")
@click.option("--no-cache", is_flag=True, help="Bypass cached session token and force re-login")
@click.option("--profile", type=str, help="Configuration profile to use")
@click.option("--url", type=str, help="Override router base URL (default: http://192.168.7.250)")
@click.option("--timeout", type=float, help="Request timeout in seconds (default: 5.0)")
@click.version_option(__version__, "-v", "--version", message="%(prog)s %(version)s")
@click.pass_context
def cli(
    ctx: click.Context,
    json_flag: bool,
    plain_flag: bool,
    no_cache: bool,
    profile: str | None,
    url: str | None,
    timeout: float | None,
) -> None:
    """Fast, lightweight CLI to monitor and control TP-Link Archer LuCI routers."""
    ctx.ensure_object(dict)
    if json_flag:
        ctx.obj["json"] = True
    if plain_flag:
        ctx.obj["plain"] = True
    if no_cache:
        ctx.obj["no_cache"] = True
    if profile:
        ctx.obj["profile"] = profile
    if url:
        ctx.obj["url"] = url
    if timeout is not None:
        ctx.obj["timeout"] = timeout


# =====================================================================
# Command: status
# =====================================================================
@cli.command("status")
@click.option("--full", is_flag=True, help="Output all 199 raw keys from status?form=all")
@click.option("--field", type=str, help="Extract a single field from status?form=all")
@click.pass_context
def cmd_status(ctx: click.Context, full: bool, field: str | None) -> None:
    """Show router system, internet, and hardware status."""
    json_mode = ctx.obj.get("json", False)
    client = get_client(ctx)

    try:
        raw_all = client.call("status", "all")
    except TpluciError as err:
        emit_error(err, json_mode=json_mode)

    if field:
        if field in raw_all:
            val = raw_all[field]
            emit_output({field: val}, str(val), json_mode=json_mode)
            return
        err = LuciApiError(
            message=f"Field '{field}' not found in status?form=all.",
            error_code="LUCI_FIELD_NOT_FOUND",
            hint="Run 'tpluci status --full --json' to inspect all 199 field keys.",
            exit_code=1,
        )
        emit_error(err, json_mode=json_mode)

    if full:
        emit_output(raw_all, json.dumps(raw_all, indent=2), json_mode=json_mode)
        return

    summary = parse_status_summary(raw_all)

    # Human-formatted summary
    uptime_sec = summary["uptime_seconds"]
    hours = uptime_sec // 3600
    minutes = (uptime_sec % 3600) // 60
    seconds = uptime_sec % 60
    uptime_str = f"{hours}h {minutes:02d}m {seconds:02d}s"

    wifi_info = summary["wifi"]
    wifi_str = (
        f"2.4G [{'on' if wifi_info['2g']['enabled'] else 'off'}] ({wifi_info['2g']['ssid']}), "
        f"5G [{'on' if wifi_info['5g']['enabled'] else 'off'}] ({wifi_info['5g']['ssid']})"
    )

    counts = summary["clients_count"]
    clients_str = f"{counts['total']} total ({counts['wireless']} wireless, {counts['wired']} wired)"

    pairs = [
        ("Model", summary["model"]),
        ("Internet Status", summary["internet_status"]),
        ("WAN IP", f"{summary['wan_ip']} ({summary['wan_conntype']}, gw {summary['wan_gateway']})"),
        ("LAN IP", summary["lan_ip"]),
        ("CPU / Memory", f"{summary['cpu_usage']}% CPU, {summary['mem_usage']}% RAM"),
        ("Uptime", uptime_str),
        ("Connected Hosts", clients_str),
        ("Wi-Fi Status", wifi_str),
    ]

    emit_output(summary, format_key_value(pairs), json_mode=json_mode)


# =====================================================================
# Command Group: clients
# =====================================================================
@cli.group("clients", cls=ClientsGroup)
@click.pass_context
def cmd_clients_group(ctx: click.Context) -> None:
    """List, filter, rename, speed-limit, and block connected devices."""
    pass


@cmd_clients_group.command("list")
@click.argument("query", required=False)
@click.option("--detailed", is_flag=True, help="Include mesh node, throughput, signal, and traffic telemetry")
@click.option("--node", "node_filter", type=str, help="Filter clients by mesh node name or MAC")
@click.option("--wireless-only", "wireless_only", is_flag=True, help="List only wireless clients")
@click.option("--wired-only", "wired_only", is_flag=True, help="List only wired clients")
@click.option("--band", type=click.Choice(["2g", "5g"], case_sensitive=False), help="Filter by Wi-Fi band")
@click.option(
    "--sort",
    "sort_by",
    type=click.Choice(
        ["hostname", "ip", "band", "mac", "medium", "signal", "traffic", "node"],
        case_sensitive=False,
    ),
    default="hostname",
    help="Sort output column",
)
@click.pass_context
def cmd_clients_list(
    ctx: click.Context,
    query: str | None,
    detailed: bool,
    node_filter: str | None,
    wireless_only: bool,
    wired_only: bool,
    band: str | None,
    sort_by: str,
) -> None:
    """List and filter connected wired and wireless devices."""
    json_mode = ctx.obj.get("json", False)
    client = get_client(ctx)

    medium = "all"
    if wireless_only:
        medium = "wireless"
    elif wired_only:
        medium = "wired"

    if detailed or node_filter:
        try:
            raw_topo = client.call("easymesh_network", "mesh_topology")
            raw_accel = client.call("smart_network", "game_accelerator", operation="loadDevice")
            raw_all = client.call("status", "all")
        except TpluciError as err:
            emit_error(err, json_mode=json_mode)

        clients = parse_clients_detailed(raw_topo, raw_accel, raw_all)

        if medium != "all":
            clients = [c for c in clients if c["medium"] == medium.lower()]

        if band:
            b_target = band.lower()
            if b_target in ("2g", "2.4g"):
                clients = [c for c in clients if "2.4" in str(c.get("band", "")).lower()]
            elif b_target in ("5g",):
                clients = [c for c in clients if "5" in str(c.get("band", "")).lower()]

        if node_filter:
            nf = node_filter.strip().lower()
            clients = [c for c in clients if nf in str(c.get("node", "")).lower()]

        if query:
            q = query.strip().lower()
            clients = [
                c for c in clients
                if q in str(c.get("hostname", "")).lower()
                or q in str(c.get("ipaddr", "")).lower()
                or q in str(c.get("macaddr", "")).lower()
                or q in str(c.get("node", "")).lower()
            ]

        if sort_by in ("ip", "ipaddr"):
            def _ip_sort(c: dict[str, Any]) -> tuple[int, ...]:
                parts = str(c.get("ipaddr", "")).split(".")
                if len(parts) == 4 and all(p.isdigit() for p in parts):
                    return tuple(int(p) for p in parts)
                return (999, 999, 999, 999)

            clients.sort(key=_ip_sort)
        elif sort_by == "signal":
            def _sig_sort(c: dict[str, Any]) -> int:
                sig = c.get("signal")
                if not sig:
                    return -999
                try:
                    return int(str(sig).replace("dBm", "").strip())
                except ValueError:
                    return -999

            clients.sort(key=_sig_sort, reverse=True)
        elif sort_by == "traffic":
            clients.sort(key=lambda c: int(c.get("traffic_bytes", 0)), reverse=True)
        elif sort_by == "node":
            clients.sort(key=lambda c: str(c.get("node", "")).lower())
        else:
            k = sort_by if sort_by in ("band", "medium") else ("macaddr" if sort_by == "mac" else "hostname")
            clients.sort(key=lambda c: str(c.get(k, "")).lower())

        if json_mode:
            emit_output(clients, "", json_mode=True)
            return

        headers = ["HOSTNAME", "IP", "MAC", "NODE", "SIGNAL", "TX/RX", "SPEED (D/U)", "TRAFFIC", "LIMIT"]
        rows = []
        for c in clients:
            sig_str = c.get("signal") or "-"
            tx_rx = f"{c.get('txrate_mbps', 0)}/{c.get('rxrate_mbps', 0)}M"
            speed = f"{c.get('down_speed_kbps', 0)}/{c.get('up_speed_kbps', 0)}K"
            tb = c.get("traffic_bytes", 0)
            if tb > 1024 * 1024 * 1024:
                traf_str = f"{tb / (1024**3):.1f} GB"
            elif tb > 1024 * 1024:
                traf_str = f"{tb / (1024**2):.1f} MB"
            else:
                traf_str = f"{tb // 1024} KB"
            lim = c.get("speed_limit", {})
            lim_str = f"{lim.get('down_kbps', -1)}/{lim.get('up_kbps', -1)}K" if lim.get("enabled") else "None"
            rows.append([
                c.get("hostname") or "<unknown>",
                c.get("ipaddr", ""),
                c.get("macaddr", ""),
                c.get("node", ""),
                sig_str,
                tx_rx,
                speed,
                traf_str,
                lim_str,
            ])
        table = format_table(headers, rows)
        footer = f"\nTotal: {len(clients)} clients"
        emit_output(clients, table + footer, json_mode=False)
        return

    # Fast path
    try:
        raw_all = client.call("status", "all")
    except TpluciError as err:
        emit_error(err, json_mode=json_mode)

    clients = parse_clients(
        raw_all,
        query=query,
        medium=medium,
        band=band,
        sort_by=sort_by,
    )

    if json_mode:
        emit_output(clients, "", json_mode=True)
        return

    headers = ["HOSTNAME", "IP", "MAC", "MEDIUM", "BAND"]
    rows = [
        [c["hostname"] or "<unknown>", c["ipaddr"], c["macaddr"], c["medium"], c["band"]]
        for c in clients
    ]
    table = format_table(headers, rows)
    w_count = sum(1 for c in clients if c["medium"] == "wireless")
    e_count = sum(1 for c in clients if c["medium"] == "wired")
    footer = f"\nTotal: {len(clients)} clients ({w_count} wireless, {e_count} wired)"

    emit_output(clients, table + footer, json_mode=False)


@cmd_clients_group.command("rename")
@click.argument("target")
@click.argument("new_name")
@click.option("--dry-run", is_flag=True, help="Simulate renaming without writing to router")
@click.pass_context
def cmd_clients_rename(ctx: click.Context, target: str, new_name: str, dry_run: bool) -> None:
    """Set custom display name (alias) for a connected client."""
    json_mode = ctx.obj.get("json", False)
    if not (1 <= len(new_name) <= 64):
        err = LuciApiError(
            message="Client alias must be between 1 and 64 characters.",
            error_code="CLI_USAGE_ERROR",
            hint="Provide a name between 1 and 64 characters long.",
            exit_code=1,
        )
        emit_error(err, json_mode=json_mode)

    client = get_client(ctx)
    try:
        raw_all = client.call("status", "all")
    except TpluciError as err:
        emit_error(err, json_mode=json_mode)

    clients = parse_clients(raw_all)
    resolved = resolve_client_target(clients, target)
    if not resolved:
        try:
            raw_accel = client.call("smart_network", "game_accelerator", operation="loadDevice")
            clients_accel = parse_clients_detailed(None, raw_accel)
            resolved = resolve_client_target(clients_accel, target)
        except Exception:
            pass

    if not resolved:
        err = LuciApiError(
            message=f"Client '{target}' not found on router.",
            error_code="CLIENT_NOT_FOUND",
            hint="Run 'tpluci clients' to view connected device hostnames, IPs, and MACs.",
            exit_code=1,
        )
        emit_error(err, json_mode=json_mode)

    mac = resolved["macaddr"]
    old_name = resolved.get("hostname", "")

    if dry_run:
        receipt = {
            "ok": True,
            "dry_run": True,
            "changed": True,
            "mac": mac,
            "diff": {"alias": {"before": old_name, "after": new_name}},
        }
        msg = f"[DRY-RUN] Simulated rename for client {mac}: '{old_name}' -> '{new_name}'"
        emit_output(receipt, msg, json_mode=json_mode)
        return

    try:
        client.call("traffic", "dev_name", operation="write", params={"mac": mac, "alias": new_name})
    except TpluciError as err:
        emit_error(err, json_mode=json_mode)

    receipt = {
        "ok": True,
        "dry_run": False,
        "changed": True,
        "mac": mac,
        "diff": {"alias": {"before": old_name, "after": new_name}},
    }
    msg = f"Renamed client {mac} ({old_name}) to '{new_name}'."
    emit_output(receipt, msg, json_mode=json_mode)


@cmd_clients_group.command("limit")
@click.argument("target")
@click.option("--down", type=int, help="Download limit in Kbps (1-1024000)")
@click.option("--up", type=int, help="Upload limit in Kbps (1-1024000)")
@click.option("--disable", is_flag=True, help="Disable speed limit for client")
@click.option("--dry-run", is_flag=True, help="Simulate without applying limit to router")
@click.pass_context
def cmd_clients_limit(
    ctx: click.Context,
    target: str,
    down: int | None,
    up: int | None,
    disable: bool,
    dry_run: bool,
) -> None:
    """Configure bandwidth speed limit for a connected client."""
    json_mode = ctx.obj.get("json", False)

    if not disable and down is None and up is None:
        err = LuciApiError(
            message="Specify at least one of --down, --up, or --disable.",
            error_code="CLI_USAGE_ERROR",
            hint="Example: tpluci clients limit iphone --down 5000 --up 1000",
            exit_code=1,
        )
        emit_error(err, json_mode=json_mode)

    if down is not None and not (1 <= down <= 1024000):
        err = LuciApiError(
            message="Download limit must be between 1 and 1024000 Kbps.",
            error_code="CLI_USAGE_ERROR",
            hint="Specify a valid Kbps value (e.g. 1000 for 1 Mbps).",
            exit_code=1,
        )
        emit_error(err, json_mode=json_mode)

    if up is not None and not (1 <= up <= 1024000):
        err = LuciApiError(
            message="Upload limit must be between 1 and 1024000 Kbps.",
            error_code="CLI_USAGE_ERROR",
            hint="Specify a valid Kbps value (e.g. 1000 for 1 Mbps).",
            exit_code=1,
        )
        emit_error(err, json_mode=json_mode)

    client = get_client(ctx)
    try:
        raw_accel = client.call("smart_network", "game_accelerator", operation="loadDevice")
        clients = parse_clients_detailed(None, raw_accel)
    except TpluciError:
        clients = []

    resolved = resolve_client_target(clients, target)
    if not resolved:
        try:
            raw_all = client.call("status", "all")
            clients_all = parse_clients(raw_all)
            resolved = resolve_client_target(clients_all, target)
        except TpluciError as err:
            emit_error(err, json_mode=json_mode)

    if not resolved:
        err = LuciApiError(
            message=f"Client '{target}' not found on router.",
            error_code="CLIENT_NOT_FOUND",
            hint="Run 'tpluci clients' to check connected devices.",
            exit_code=1,
        )
        emit_error(err, json_mode=json_mode)

    mac = resolved["macaddr"]
    old_limit = resolved.get("speed_limit", {"enabled": False, "down_kbps": -1, "up_kbps": -1})

    if disable:
        payload = {"mac": mac, "enableLimit": "off"}
        new_limit = {"enabled": False, "down_kbps": -1, "up_kbps": -1}
    else:
        d_val = str(down) if down is not None else "-1"
        u_val = str(up) if up is not None else "-1"
        payload = {
            "mac": mac,
            "enableLimit": "on",
            "downloadLimit": d_val,
            "uploadLimit": u_val,
        }
        new_limit = {"enabled": True, "down_kbps": int(d_val), "up_kbps": int(u_val)}

    diff = {
        "limit_enabled": {"before": old_limit.get("enabled"), "after": new_limit["enabled"]},
        "download_limit": {"before": old_limit.get("down_kbps"), "after": new_limit["down_kbps"]},
        "upload_limit": {"before": old_limit.get("up_kbps"), "after": new_limit["up_kbps"]},
    }

    if dry_run:
        receipt = {"ok": True, "dry_run": True, "changed": True, "mac": mac, "diff": diff}
        emit_output(receipt, f"[DRY-RUN] Simulated speed limit update for client {mac}.", json_mode=json_mode)
        return

    try:
        client.call("smart_network", "client_speed_limit", operation="write", params=payload)
    except TpluciError as err:
        emit_error(err, json_mode=json_mode)

    receipt = {"ok": True, "dry_run": False, "changed": True, "mac": mac, "diff": diff}
    msg = f"Updated speed limits for client {mac}: down={new_limit['down_kbps']}K, up={new_limit['up_kbps']}K"
    emit_output(receipt, msg, json_mode=json_mode)


@cmd_clients_group.command("block")
@click.argument("target")
@click.option("--confirm", is_flag=True, help="Explicit confirmation required to block client")
@click.option("--dry-run", is_flag=True, help="Simulate block without writing to router")
@click.pass_context
def cmd_clients_block(ctx: click.Context, target: str, confirm: bool, dry_run: bool) -> None:
    """Block a connected client from accessing the network."""
    json_mode = ctx.obj.get("json", False)
    client = get_client(ctx)

    try:
        raw_devs = client.call("access_control", "black_devices", operation="load")
        enable_info = client.call("access_control", "enable", operation="read")
    except TpluciError as err:
        emit_error(err, json_mode=json_mode)

    dev_list = raw_devs if isinstance(raw_devs, list) else raw_devs.get("data", [])
    host_mac = str(enable_info.get("host_mac", "")).lower().replace("-", ":")

    matched_dev = None
    t_clean = target.strip().lower()
    t_mac = t_clean.replace("-", ":")

    for dev in dev_list:
        d_mac = str(dev.get("mac", "")).lower().replace("-", ":")
        d_name = str(dev.get("name") or dev.get("hostname", "")).lower()
        d_ip = str(dev.get("ip", "")).lower()
        if d_mac == t_mac or d_ip == t_clean or d_name == t_clean or t_clean in d_name:
            matched_dev = dev
            break

    if not matched_dev:
        try:
            raw_all = client.call("status", "all")
            clients_all = parse_clients(raw_all)
            matched_all = resolve_client_target(clients_all, target)
            if matched_all:
                matched_dev = {"name": matched_all.get("hostname", ""), "mac": matched_all["macaddr"]}
        except Exception:
            pass

    if not matched_dev:
        err = LuciApiError(
            message=f"Client '{target}' not found.",
            error_code="CLIENT_NOT_FOUND",
            hint="Run 'tpluci clients' to check connected devices.",
            exit_code=1,
        )
        emit_error(err, json_mode=json_mode)

    target_mac = str(matched_dev.get("mac", ""))
    target_name = str(matched_dev.get("name") or matched_dev.get("hostname", ""))
    mac_normalized = target_mac.lower().replace("-", ":")

    is_host_tag = matched_dev.get("host") == "HOST"
    is_host_mac = bool(host_mac and mac_normalized == host_mac)
    if is_host_tag or is_host_mac:
        err = SafetyAbortError(
            message="Refusing to block the current host device (HOST) to prevent router lockout.",
            error_code="SAFETY_ABORT",
            hint="The current administering machine cannot be added to the access control blacklist.",
            exit_code=5,
        )
        emit_error(err, json_mode=json_mode)

    if not confirm:
        if not sys.stdin.isatty():
            err = SafetyAbortError(
                message="Refusing to block client in non-interactive environment without --confirm.",
                hint=f"Pass --confirm to authorize blocking device: tpluci clients block {target} --confirm",
                exit_code=5,
            )
            emit_error(err, json_mode=json_mode)
        else:
            if not click.confirm(f"Are you sure you want to block client '{target_name}' ({target_mac})?", default=False):
                err = SafetyAbortError(
                    message="Client block aborted by user.",
                    hint="Re-run with --confirm when ready.",
                    exit_code=5,
                )
                emit_error(err, json_mode=json_mode)

    if dry_run:
        receipt = {
            "ok": True,
            "dry_run": True,
            "blocked": True,
            "mac": target_mac,
            "name": target_name,
            "message": f"[DRY-RUN] Simulated block of {target_name} ({target_mac}).",
        }
        emit_output(receipt, receipt["message"], json_mode=json_mode)
        return

    try:
        if enable_info.get("enable") != "on":
            client.call("access_control", "enable", operation="write", params={"enable": "on"})
        mode_info = client.call("access_control", "mode", operation="read")
        if mode_info.get("access_mode") != "black":
            client.call("access_control", "mode", operation="write", params={"access_mode": "black"})

        new_entry = json.dumps({"name": target_name, "mac": target_mac})
        client.call(
            "access_control",
            "black_list",
            operation="insert",
            params={"key": "add", "old": "add", "index": "0", "new": new_entry},
        )
    except TpluciError as err:
        emit_error(err, json_mode=json_mode)

    receipt = {
        "ok": True,
        "dry_run": False,
        "blocked": True,
        "mac": target_mac,
        "name": target_name,
        "message": f"Successfully blocked {target_name} ({target_mac}).",
    }
    emit_output(receipt, receipt["message"], json_mode=json_mode)


@cmd_clients_group.command("unblock")
@click.argument("target")
@click.option("--dry-run", is_flag=True, help="Simulate unblock without writing to router")
@click.pass_context
def cmd_clients_unblock(ctx: click.Context, target: str, dry_run: bool) -> None:
    """Unblock a previously blocked client device."""
    json_mode = ctx.obj.get("json", False)
    client = get_client(ctx)

    try:
        raw_bl = client.call("access_control", "black_list", operation="load")
    except TpluciError as err:
        emit_error(err, json_mode=json_mode)

    bl_list = raw_bl if isinstance(raw_bl, list) else raw_bl.get("data", [])
    t_clean = target.strip().lower()
    t_mac = t_clean.replace("-", ":")

    matched_idx = -1
    matched_item = None
    for idx, item in enumerate(bl_list):
        i_mac = str(item.get("mac", "")).lower().replace("-", ":")
        i_name = str(item.get("name", "")).lower()
        if i_mac == t_mac or i_name == t_clean or t_clean in i_name:
            matched_idx = idx
            matched_item = item
            break

    if not matched_item:
        err = LuciApiError(
            message=f"Client '{target}' is not in the access control blacklist.",
            error_code="CLIENT_NOT_FOUND",
            hint="Check blocked devices with 'tpluci call access_control black_list --op load'",
            exit_code=1,
        )
        emit_error(err, json_mode=json_mode)

    item_key = matched_item.get("key", str(matched_idx))
    target_mac = matched_item.get("mac", "")
    target_name = matched_item.get("name", "")

    if dry_run:
        receipt = {
            "ok": True,
            "dry_run": True,
            "unblocked": True,
            "mac": target_mac,
            "name": target_name,
            "message": f"[DRY-RUN] Simulated unblock of {target_name} ({target_mac}).",
        }
        emit_output(receipt, receipt["message"], json_mode=json_mode)
        return

    try:
        client.call(
            "access_control",
            "black_list",
            operation="remove",
            params={"key": item_key, "index": str(matched_idx)},
        )
    except TpluciError as err:
        emit_error(err, json_mode=json_mode)

    receipt = {
        "ok": True,
        "dry_run": False,
        "unblocked": True,
        "mac": target_mac,
        "name": target_name,
        "message": f"Successfully unblocked {target_name} ({target_mac}).",
    }
    emit_output(receipt, receipt["message"], json_mode=json_mode)


# =====================================================================
# Command Group: mesh
# =====================================================================
@cli.group("mesh", cls=MeshGroup)
@click.pass_context
def cmd_mesh_group(ctx: click.Context) -> None:
    """Inspect and manage EasyMesh satellites, topology, and firmware."""
    pass


@cmd_mesh_group.command("list")
@click.pass_context
def cmd_mesh_list(ctx: click.Context) -> None:
    """List all connected EasyMesh satellite nodes."""
    json_mode = ctx.obj.get("json", False)
    client = get_client(ctx)

    try:
        raw_sclient_list = client.call("easymesh_network", "mesh_sclient_list_all", operation="read")
    except TpluciError as err:
        emit_error(err, json_mode=json_mode)

    satellites = parse_mesh_satellites(raw_sclient_list)
    if json_mode:
        emit_output(satellites, "", json_mode=True)
        return

    headers = ["NAME", "MODEL", "IP", "MAC", "LOCATION", "BACKHAUL", "SIGNAL", "CLIENTS", "STATUS"]
    rows = [
        [
            s["name"] or "<unnamed>",
            s["model"] or "<unknown>",
            s["ip"],
            s["mac"],
            s["location"] or "<none>",
            s["backhaul"],
            s["signal_strength"],
            str(s["clients_count"]),
            s["status"],
        ]
        for s in satellites
    ]
    table = format_table(headers, rows)
    footer = f"\nTotal: {len(satellites)} EasyMesh satellite(s)"
    emit_output(satellites, table + footer, json_mode=False)


@cmd_mesh_group.command("status", hidden=True)
@click.pass_context
def cmd_mesh_status(ctx: click.Context) -> None:
    """Alias for 'tpluci mesh list'."""
    ctx.forward(cmd_mesh_list)


@cmd_mesh_group.command("topology")
@click.pass_context
def cmd_mesh_topology(ctx: click.Context) -> None:
    """Display full hierarchical mesh tree topology."""
    json_mode = ctx.obj.get("json", False)
    client = get_client(ctx)

    try:
        raw_topo = client.call("easymesh_network", "mesh_topology", operation="read")
    except TpluciError as err:
        emit_error(err, json_mode=json_mode)

    tree = parse_mesh_topology(raw_topo)
    if json_mode:
        emit_output(tree, "", json_mode=True)
        return

    lines = []
    root = tree["root"]
    lines.append(f"Root: {root['name']} ({root['model']}) — IP: {root['ip'] or '<none>'}, MAC: {root['mac']}")
    if root["clients"]:
        lines.append("  Connected Clients:")
        for c in root["clients"]:
            lines.append(f"    * {c['name']} ({c['ip'] or 'no-ip'}, {c['mac']}) [{c['connection_type']}]")
    else:
        lines.append("  No direct clients.")

    for s in tree["satellites"]:
        lines.append(f"\nSatellite: {s['name']} ({s['model']}) — IP: {s['ip']}, MAC: {s['mac']}")
        lines.append(
            f"  Location: {s['location'] or '<none>'} | Backhaul: {s['backhaul']} | Signal: {s['signal_strength']}"
        )
        if s["clients"]:
            lines.append("  Connected Clients:")
            for c in s["clients"]:
                lines.append(
                    f"    * {c['name']} ({c['ip'] or 'no-ip'}, {c['mac']}) [{c['connection_type']}] "
                    f"Signal: {c['signal_strength']} TX/RX: {c['txrate_mbps']}/{c['rxrate_mbps']} Mbps"
                )
        else:
            lines.append("  No connected clients.")

    emit_output(tree, "\n".join(lines), json_mode=False)


@cmd_mesh_group.command("get")
@click.argument("node")
@click.pass_context
def cmd_mesh_get(ctx: click.Context, node: str) -> None:
    """Inspect detailed metrics and backhaul speeds for a specific mesh satellite."""
    json_mode = ctx.obj.get("json", False)
    client = get_client(ctx)

    try:
        raw_list = client.call("easymesh_network", "mesh_sclient_list_all", operation="read")
    except TpluciError as err:
        emit_error(err, json_mode=json_mode)

    satellites = parse_mesh_satellites(raw_list)
    resolved = resolve_mesh_node(satellites, node)
    if not resolved:
        err = LuciApiError(
            message=f"Mesh satellite node '{node}' not found.",
            error_code="NODE_NOT_FOUND",
            hint="Run 'tpluci mesh list' to see available satellite names, IPs, and MACs.",
            exit_code=1,
        )
        emit_error(err, json_mode=json_mode)

    target_mac = resolved["mac"]
    try:
        raw_detail = client.call(
            "easymesh_network", "mesh_sclient_detail", operation="read", params={"mac": target_mac}
        )
    except TpluciError as err:
        emit_error(err, json_mode=json_mode)

    detail = parse_mesh_satellite_detail(raw_detail)
    if json_mode:
        emit_output(detail, "", json_mode=True)
        return

    pairs = [
        ("Node Name", detail["name"] or "<unnamed>"),
        ("Model", detail["model"] or "<unknown>"),
        ("IP Address", detail["ip"]),
        ("MAC Address", detail["mac"]),
        ("Location", detail["location"] or "<none>"),
        ("Firmware Version", detail["firmware_version"] or "<unknown>"),
        ("Parent Router MAC", detail["parent_device_mac"] or "<none>"),
        ("Backhaul Connection", detail["backhaul"]),
        (
            "Link Speed 2.4 GHz",
            f"{detail['link_speed_24g_mbps']} Mbps" if detail["link_speed_24g_mbps"] else "N/A",
        ),
        (
            "Link Speed 5 GHz",
            f"{detail['link_speed_5g_mbps']} Mbps" if detail["link_speed_5g_mbps"] else "N/A",
        ),
        ("Signal 2.4 GHz", detail["signal_strength_24g"]),
        ("Signal 5 GHz", detail["signal_strength_5g"]),
        ("Connected Clients", str(len(detail["clients"]))),
    ]
    info_text = format_key_value(pairs)

    if detail["clients"]:
        headers = ["CLIENT NAME", "IP", "MAC", "MEDIUM", "SIGNAL", "TX/RX (Mbps)"]
        rows = [
            [
                c["name"] or "<unknown>",
                c["ip"] or "<none>",
                c["mac"],
                c["connection_type"],
                c["signal_strength"],
                f"{c['txrate_mbps']}/{c['rxrate_mbps']}",
            ]
            for c in detail["clients"]
        ]
        clients_table = "\n\nConnected Clients:\n" + format_table(headers, rows)
        info_text += clients_table

    emit_output(detail, info_text, json_mode=False)


@cmd_mesh_group.command("set")
@click.argument("node")
@click.option("--name", "new_name", type=str, help="New name for the mesh satellite")
@click.option("--location", "new_location", type=str, help="New location for the mesh satellite")
@click.option("--dry-run", is_flag=True, help="Simulate mutation without writing to router")
@click.pass_context
def cmd_mesh_set(
    ctx: click.Context,
    node: str,
    new_name: str | None,
    new_location: str | None,
    dry_run: bool,
) -> None:
    """Rename or update location of a mesh satellite node."""
    json_mode = ctx.obj.get("json", False)

    if new_name is None and new_location is None:
        err = LuciApiError(
            message="Specify at least one of --name or --location to update.",
            error_code="CLI_USAGE_ERROR",
            hint="Example: tpluci mesh set RE705X --name Office-AP --location office",
            exit_code=1,
        )
        emit_error(err, json_mode=json_mode)

    client = get_client(ctx)
    try:
        raw_list = client.call("easymesh_network", "mesh_sclient_list_all", operation="read")
    except TpluciError as err:
        emit_error(err, json_mode=json_mode)

    satellites = parse_mesh_satellites(raw_list)
    resolved = resolve_mesh_node(satellites, node)
    if not resolved:
        err = LuciApiError(
            message=f"Mesh satellite node '{node}' not found.",
            error_code="NODE_NOT_FOUND",
            hint="Run 'tpluci mesh list' to see available satellite nodes.",
            exit_code=1,
        )
        emit_error(err, json_mode=json_mode)

    target_mac = resolved["mac"]
    try:
        raw_detail = client.call(
            "easymesh_network", "mesh_sclient_detail", operation="read", params={"mac": target_mac}
        )
    except TpluciError as err:
        emit_error(err, json_mode=json_mode)

    old_name = raw_detail.get("name", resolved.get("name", ""))
    old_loc = raw_detail.get("location", resolved.get("location", ""))

    final_name = new_name if new_name is not None else old_name
    final_loc = new_location if new_location is not None else old_loc

    diff = {}
    if new_name is not None:
        diff["name"] = {"before": old_name, "after": final_name}
    if new_location is not None:
        diff["location"] = {"before": old_loc, "after": final_loc}

    payload = {
        "mac": target_mac,
        "name": final_name,
        "location": final_loc,
    }

    if dry_run:
        receipt = {
            "ok": True,
            "dry_run": True,
            "changed": True,
            "mac": target_mac,
            "diff": diff,
        }
        msg = f"[DRY-RUN] Simulated update for satellite {target_mac}:"
        for k, v in diff.items():
            msg += f"\n  {k}: {v['before']} -> {v['after']}"
        emit_output(receipt, msg, json_mode=json_mode)
        return

    try:
        client.call("easymesh_network", "mesh_sclient_detail", operation="write", params=payload)
    except TpluciError as err:
        emit_error(err, json_mode=json_mode)

    receipt = {
        "ok": True,
        "dry_run": False,
        "changed": True,
        "mac": target_mac,
        "diff": diff,
    }
    msg = f"Updated settings for satellite {target_mac}:"
    for k, v in diff.items():
        msg += f"\n  {k}: {v['before']} -> {v['after']}"
    emit_output(receipt, msg, json_mode=json_mode)


@cmd_mesh_group.command("firmware")
@click.option("--upgrade", "upgrade_target", type=str, help="Upgrade firmware on target satellite node")
@click.option("--confirm", is_flag=True, help="Explicit confirmation required to trigger firmware upgrade")
@click.option("--dry-run", is_flag=True, help="Simulate upgrade without calling hardware")
@click.pass_context
def cmd_mesh_firmware(
    ctx: click.Context,
    upgrade_target: str | None,
    confirm: bool,
    dry_run: bool,
) -> None:
    """Check or trigger firmware upgrades on EasyMesh satellite extenders."""
    json_mode = ctx.obj.get("json", False)
    client = get_client(ctx)

    if not upgrade_target:
        try:
            raw_fw = client.call("firmware", "slave_cmd", operation="slave_get_info")
        except TpluciError as err:
            emit_error(err, json_mode=json_mode)

        slaves = raw_fw if isinstance(raw_fw, list) else raw_fw.get("slaves", raw_fw.get("data", []))
        if json_mode:
            emit_output(slaves, "", json_mode=True)
            return

        headers = ["NAME", "MODEL", "IP", "MAC", "VERSION", "LATEST", "UP-TO-DATE"]
        rows = [
            [
                s.get("name") or "<unnamed>",
                s.get("model", ""),
                s.get("ip", ""),
                s.get("mac", ""),
                s.get("version") or s.get("current_version", ""),
                s.get("latest_version", ""),
                "Yes" if s.get("is_latest") or s.get("isLatest") else "No (Update available)",
            ]
            for s in slaves
        ]
        table = format_table(headers, rows)
        emit_output(slaves, table, json_mode=False)
        return

    try:
        raw_list = client.call("easymesh_network", "mesh_sclient_list_all", operation="read")
    except TpluciError as err:
        emit_error(err, json_mode=json_mode)

    satellites = parse_mesh_satellites(raw_list)
    resolved = resolve_mesh_node(satellites, upgrade_target)
    if not resolved:
        err = LuciApiError(
            message=f"Mesh satellite node '{upgrade_target}' not found.",
            error_code="NODE_NOT_FOUND",
            hint="Run 'tpluci mesh list' to check satellite nodes.",
            exit_code=1,
        )
        emit_error(err, json_mode=json_mode)

    node_ip = resolved["ip"]
    node_mac = resolved["mac"]
    node_name = resolved.get("name") or resolved.get("model", "")

    if not confirm:
        if not sys.stdin.isatty():
            err = SafetyAbortError(
                message="Refusing to trigger satellite firmware upgrade in non-interactive environment without --confirm.",
                hint=f"Pass --confirm to authorize: tpluci mesh firmware --upgrade {upgrade_target} --confirm",
                exit_code=5,
            )
            emit_error(err, json_mode=json_mode)
        else:
            if not click.confirm(f"Are you sure you want to upgrade firmware on '{node_name}' ({node_ip})?", default=False):
                err = SafetyAbortError(
                    message="Satellite firmware upgrade aborted by user.",
                    hint="Re-run with --confirm when ready.",
                    exit_code=5,
                )
                emit_error(err, json_mode=json_mode)

    if dry_run:
        receipt = {
            "ok": True,
            "dry_run": True,
            "upgrading": True,
            "node": node_name,
            "ip": node_ip,
            "mac": node_mac,
            "message": f"[DRY-RUN] Simulated firmware upgrade for {node_name} ({node_ip}).",
        }
        emit_output(receipt, receipt["message"], json_mode=json_mode)
        return

    try:
        client.call(
            "firmware",
            "slave_cmd",
            operation="slave_upgrade_firmware",
            params={"ip": node_ip, "mac": node_mac},
        )
    except TpluciError as err:
        emit_error(err, json_mode=json_mode)

    receipt = {
        "ok": True,
        "dry_run": False,
        "upgrading": True,
        "node": node_name,
        "ip": node_ip,
        "mac": node_mac,
        "message": f"Firmware upgrade command accepted for {node_name} ({node_ip}).",
    }
    emit_output(receipt, receipt["message"], json_mode=json_mode)


@cmd_mesh_group.command("remove")
@click.argument("node")
@click.option("--confirm", is_flag=True, help="Explicit confirmation required to remove satellite")
@click.option("--dry-run", is_flag=True, help="Simulate removal without unlinking")
@click.pass_context
def cmd_mesh_remove(ctx: click.Context, node: str, confirm: bool, dry_run: bool) -> None:
    """Unlink and remove an EasyMesh satellite extender from the network."""
    json_mode = ctx.obj.get("json", False)
    client = get_client(ctx)

    try:
        raw_list = client.call("easymesh_network", "mesh_sclient_list_all", operation="read")
    except TpluciError as err:
        emit_error(err, json_mode=json_mode)

    satellites = parse_mesh_satellites(raw_list)
    resolved = resolve_mesh_node(satellites, node)
    if not resolved:
        err = LuciApiError(
            message=f"Mesh satellite node '{node}' not found.",
            error_code="NODE_NOT_FOUND",
            hint="Run 'tpluci mesh list' to check satellite nodes.",
            exit_code=1,
        )
        emit_error(err, json_mode=json_mode)

    node_mac = resolved["mac"]
    node_name = resolved.get("name") or resolved.get("model", "")

    if not confirm:
        if not sys.stdin.isatty():
            err = SafetyAbortError(
                message="Refusing to unlink mesh satellite in non-interactive environment without --confirm.",
                hint=f"Pass --confirm to authorize removal: tpluci mesh remove {node} --confirm",
                exit_code=5,
            )
            emit_error(err, json_mode=json_mode)
        else:
            if not click.confirm(f"Are you sure you want to unlink and remove satellite '{node_name}' ({node_mac})?", default=False):
                err = SafetyAbortError(
                    message="Satellite removal aborted by user.",
                    hint="Re-run with --confirm when ready.",
                    exit_code=5,
                )
                emit_error(err, json_mode=json_mode)

    if dry_run:
        receipt = {
            "ok": True,
            "dry_run": True,
            "removed": True,
            "node": node_name,
            "mac": node_mac,
            "message": f"[DRY-RUN] Simulated unlinking of satellite {node_name} ({node_mac}).",
        }
        emit_output(receipt, receipt["message"], json_mode=json_mode)
        return

    try:
        client.call(
            "easymesh_network",
            "available_mesh_device_manage",
            operation="unlink",
            params={"mac": node_mac},
        )
    except TpluciError as err:
        emit_error(err, json_mode=json_mode)

    receipt = {
        "ok": True,
        "dry_run": False,
        "removed": True,
        "node": node_name,
        "mac": node_mac,
        "message": f"Successfully unlinked and removed satellite {node_name} ({node_mac}).",
    }
    emit_output(receipt, receipt["message"], json_mode=json_mode)


def _resolve_and_connect_satellite(
    ctx: click.Context,
    node: str,
    sat_user: str | None = None,
    sat_password: str | None = None,
) -> tuple[Any, str, str]:
    """Helper to resolve satellite node IP, credentials, and return connected client."""
    from tpluci.satellites import connect_satellite
    json_mode = ctx.obj.get("json", False)
    client = get_client(ctx)

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
            err = LuciApiError(
                message=f"Mesh satellite node '{node}' not found.",
                error_code="NODE_NOT_FOUND",
                hint="Run 'tpluci mesh list' to check satellite nodes.",
                exit_code=1,
            )
            emit_error(err, json_mode=json_mode)

    resolved_user, resolved_pwd = resolve_satellite_credentials(
        node_name=node_name,
        node_ip=node_ip,
        base_creds=client.creds,
        cli_user=sat_user,
        cli_password=sat_password,
    )

    try:
        sat_client = connect_satellite(
            ip=node_ip,
            password=resolved_pwd,
            username=resolved_user,
            timeout=client.creds.timeout,
        )
    except TpluciError as err:
        emit_error(err, json_mode=json_mode)
    except Exception as exc:
        err = LuciApiError(
            message=f"Failed to connect to satellite '{node_name}' ({node_ip}): {exc}",
            error_code="SATELLITE_CONNECTION_FAILED",
            exit_code=1,
        )
        emit_error(err, json_mode=json_mode)

    return sat_client, node_name, node_ip


@cmd_mesh_group.command("reboot")
@click.argument("node")
@click.option("--confirm", is_flag=True, help="Explicit confirmation required to reboot satellite")
@click.option("--dry-run", is_flag=True, help="Simulate reboot without issuing hardware command")
@click.option("--satellite-user", "sat_user", type=str, help="Username / TP-Link Cloud ID for satellite")
@click.option("--satellite-password", "sat_password", type=str, help="Password for satellite extender")
@click.pass_context
def cmd_mesh_reboot(
    ctx: click.Context,
    node: str,
    confirm: bool,
    dry_run: bool,
    sat_user: str | None,
    sat_password: str | None,
) -> None:
    """Reboot an individual mesh satellite extender."""
    json_mode = ctx.obj.get("json", False)

    if not confirm:
        if not sys.stdin.isatty():
            err = SafetyAbortError(
                message=f"Refusing to reboot satellite '{node}' in non-interactive environment without --confirm.",
                hint=f"Pass --confirm to authorize: tpluci mesh reboot {node} --confirm",
                exit_code=5,
            )
            emit_error(err, json_mode=json_mode)
        else:
            if not click.confirm(f"Are you sure you want to reboot mesh satellite '{node}'?", default=False):
                err = SafetyAbortError(
                    message="Satellite reboot aborted by user.",
                    hint="Re-run with --confirm when ready.",
                    exit_code=5,
                )
                emit_error(err, json_mode=json_mode)

    # Resolve node info
    client = get_client(ctx)
    satellites = []
    try:
        raw_list = client.call("easymesh_network", "mesh_sclient_list_all", operation="read")
        satellites = parse_mesh_satellites(raw_list)
    except Exception:
        pass
    resolved = resolve_mesh_node(satellites, node)
    node_name = resolved.get("name") or resolved.get("model", "") if resolved else node
    node_ip = resolved["ip"] if resolved else node

    if dry_run:
        receipt = {
            "ok": True,
            "dry_run": True,
            "reboot": True,
            "node": node_name,
            "ip": node_ip,
            "message": f"[DRY-RUN] Simulated reboot for satellite {node_name} ({node_ip}).",
        }
        emit_output(receipt, receipt["message"], json_mode=json_mode)
        return

    sat_client, node_name, node_ip = _resolve_and_connect_satellite(
        ctx, node, sat_user=sat_user, sat_password=sat_password
    )
    try:
        res = sat_client.reboot()
        res["node"] = node_name
        msg = f"Reboot command sent to satellite '{node_name}' ({node_ip})."
        emit_output(res, msg, json_mode=json_mode)
    except TpluciError as err:
        emit_error(err, json_mode=json_mode)
    finally:
        sat_client.logout()


@cmd_mesh_group.command("led")
@click.argument("node")
@click.option("--on/--off", "led_on", default=None, help="Turn satellite status LEDs on or off")
@click.option("--night-mode", type=click.Choice(["on", "off"], case_sensitive=False), default=None, help="Enable or disable LED Night Mode schedule")
@click.option("--start", "night_start", type=str, help="Night Mode start time (HH:MM)")
@click.option("--end", "night_end", type=str, help="Night Mode end time (HH:MM)")
@click.option("--dry-run", is_flag=True, help="Simulate LED changes without writing to satellite")
@click.option("--satellite-user", "sat_user", type=str, help="Username / TP-Link Cloud ID for satellite")
@click.option("--satellite-password", "sat_password", type=str, help="Password for satellite extender")
@click.pass_context
def cmd_mesh_led(
    ctx: click.Context,
    node: str,
    led_on: bool | None,
    night_mode: str | None,
    night_start: str | None,
    night_end: str | None,
    dry_run: bool,
    sat_user: str | None,
    sat_password: str | None,
) -> None:
    """Inspect or configure status LED and Night Mode schedule on a satellite."""
    json_mode = ctx.obj.get("json", False)
    nm_bool = (night_mode.lower() == "on") if night_mode is not None else None
    has_mutation = any(x is not None for x in (led_on, nm_bool, night_start, night_end))

    sat_client, node_name, node_ip = _resolve_and_connect_satellite(
        ctx, node, sat_user=sat_user, sat_password=sat_password
    )
    try:
        if not has_mutation:
            led_info = sat_client.get_led()
            if json_mode:
                emit_output(led_info, "", json_mode=True)
                return
            pairs = [
                ("Node", f"{node_name} ({node_ip})"),
                ("Status LED", "ON" if led_info["led_enable"] else "OFF"),
                ("Night Mode", "ON" if led_info["night_mode"] else "OFF"),
                ("Night Mode Start", led_info.get("time_start") or "N/A"),
                ("Night Mode End", led_info.get("time_end") or "N/A"),
            ]
            if "led_sync_enable" in led_info:
                pairs.append(("Mesh LED Sync", "ON" if led_info["led_sync_enable"] else "OFF"))
            out_text = format_key_value(pairs)
            if led_info.get("led_sync_enable"):
                out_text += "\n\nNote: Mesh LED sync is enabled on controller. Changes may be overwritten by the mesh controller."
            emit_output(led_info, out_text, json_mode=False)
            return

        res = sat_client.set_led(
            enable=led_on,
            night_mode=nm_bool,
            start=night_start,
            end=night_end,
            dry_run=dry_run,
        )
        res["node"] = node_name
        res["ip"] = node_ip
        prefix = "[DRY-RUN] " if dry_run else ""
        msg = f"{prefix}Updated LED settings for satellite '{node_name}' ({node_ip}):"
        for k, v in res.get("diff", {}).items():
            msg += f"\n  {k}: {v['before']} -> {v['after']}"
        if res.get("warning"):
            msg += f"\nWarning: {res['warning']}"
        emit_output(res, msg, json_mode=json_mode)
    except TpluciError as err:
        emit_error(err, json_mode=json_mode)
    finally:
        sat_client.logout()


@cmd_mesh_group.command("reboot-schedule")
@click.argument("node")
@click.option("--enable/--disable", "schedule_enable", default=None, help="Enable or disable satellite reboot schedule")
@click.option("--cycle", type=click.Choice(["day", "week", "month"], case_sensitive=False), default=None, help="Reboot frequency cycle")
@click.option("--day", type=str, default=None, help="Day of week (Mon..Sun) or day of month (1..28)")
@click.option("--time", "schedule_time", type=str, default=None, help="Scheduled reboot time (HH:MM)")
@click.option("--dry-run", is_flag=True, help="Simulate schedule changes without writing")
@click.option("--satellite-user", "sat_user", type=str, help="Username / TP-Link Cloud ID for satellite")
@click.option("--satellite-password", "sat_password", type=str, help="Password for satellite extender")
@click.pass_context
def cmd_mesh_reboot_schedule(
    ctx: click.Context,
    node: str,
    schedule_enable: bool | None,
    cycle: str | None,
    day: str | None,
    schedule_time: str | None,
    dry_run: bool,
    sat_user: str | None,
    sat_password: str | None,
) -> None:
    """Inspect or configure automatic reboot or power schedule on a satellite."""
    json_mode = ctx.obj.get("json", False)
    has_mutation = any(x is not None for x in (schedule_enable, cycle, day, schedule_time))

    sat_client, node_name, node_ip = _resolve_and_connect_satellite(
        ctx, node, sat_user=sat_user, sat_password=sat_password
    )
    try:
        if not has_mutation:
            sched_info = sat_client.get_schedule()
            if json_mode:
                emit_output(sched_info, "", json_mode=True)
                return
            pairs = [
                ("Node", f"{node_name} ({node_ip})"),
                ("Schedule Type", sched_info.get("type", "unknown")),
                ("Enabled", "ON" if sched_info.get("enabled") else "OFF"),
            ]
            if "cycle" in sched_info:
                pairs.append(("Cycle", sched_info.get("cycle", "N/A")))
            if "day" in sched_info:
                pairs.append(("Day", sched_info.get("day", "N/A")))
            if "time" in sched_info:
                pairs.append(("Time", sched_info.get("time", "N/A")))
            out_text = format_key_value(pairs)
            emit_output(sched_info, out_text, json_mode=False)
            return

        from tpluci.satellites import TddpSatelliteClient
        if isinstance(sat_client, TddpSatelliteClient):
            res = sat_client.set_schedule(
                enable=schedule_enable,
                cycle=cycle,
                day=day,
                time=schedule_time,
                dry_run=dry_run,
            )
        else:
            params = {}
            if schedule_time:
                params["time"] = schedule_time
            if day:
                params["day"] = normalize_weekday(day)
            res = sat_client.set_schedule(
                enable=schedule_enable,
                schedule_params=params if params else None,
                dry_run=dry_run,
            )

        res["node"] = node_name
        res["ip"] = node_ip
        prefix = "[DRY-RUN] " if dry_run else ""
        msg = f"{prefix}Updated schedule for satellite '{node_name}' ({node_ip}):"
        for k, v in res.get("diff", {}).items():
            msg += f"\n  {k}: {v['before']} -> {v['after']}"
        emit_output(res, msg, json_mode=json_mode)
    except TpluciError as err:
        emit_error(err, json_mode=json_mode)
    finally:
        sat_client.logout()


# =====================================================================
# Command Group: wifi
# =====================================================================
@cli.group("wifi")
def cmd_wifi_group() -> None:
    """Inspect and control Wi-Fi radios, Guest, and IoT networks."""
    pass


@cmd_wifi_group.command("list")
@click.pass_context
def cmd_wifi_list(ctx: click.Context) -> None:
    """List all 6 Wi-Fi radio networks and configurations."""
    json_mode = ctx.obj.get("json", False)
    client = get_client(ctx)

    try:
        raw_all = client.call("status", "all")
    except TpluciError as err:
        emit_error(err, json_mode=json_mode)

    summary = parse_wifi_summary(raw_all)
    if json_mode:
        emit_output(summary, "", json_mode=True)
        return

    headers = ["RADIO", "NAME", "SSID", "STATUS", "CHANNEL", "ENCRYPTION", "HIDDEN"]
    rows = [
        [
            r["radio"],
            r["name"],
            r["ssid"] or "<empty>",
            "on" if r["enabled"] else "off",
            str(r["channel"]) if r["channel"] else "-",
            r["encryption"],
            "yes" if r["hidden"] else "no",
        ]
        for r in summary
    ]
    emit_output(summary, format_table(headers, rows), json_mode=False)


@cmd_wifi_group.command("status")
@click.pass_context
def cmd_wifi_status(ctx: click.Context) -> None:
    """Alias for 'wifi list'."""
    ctx.forward(cmd_wifi_list)


@cmd_wifi_group.command("get")
@click.argument("radio", type=click.Choice(list(WIFI_RADIO_MAP.keys()) + ["all"], case_sensitive=False))
@click.pass_context
def cmd_wifi_get(ctx: click.Context, radio: str) -> None:
    """Get detailed settings for a specific radio or all radios."""
    json_mode = ctx.obj.get("json", False)
    client = get_client(ctx)

    if radio == "all":
        ctx.forward(cmd_wifi_list)
        return

    module, form, desc = WIFI_RADIO_MAP[radio]
    try:
        data = client.call(module, form, operation="read")
    except TpluciError as err:
        emit_error(err, json_mode=json_mode)

    if json_mode:
        emit_output(data, "", json_mode=True)
        return

    pairs = [
        ("Radio", radio),
        ("Name", desc),
        ("SSID", data.get("ssid", "")),
        ("Enabled", data.get("enable", "")),
        ("Channel", data.get("channel", "")),
        ("Bandwidth", data.get("htmode", data.get("bandwidth", ""))),
        ("Encryption", data.get("encryption", "")),
        ("Hidden", data.get("hidden", "")),
        ("MU-MIMO", data.get("mu_mimo", "")),
    ]
    emit_output(data, format_key_value(pairs), json_mode=False)


@cmd_wifi_group.command("set")
@click.argument("radio", type=click.Choice(list(WIFI_RADIO_MAP.keys()), case_sensitive=False))
@click.option("--enable/--disable", "is_enabled", default=None, help="Enable or disable radio")
@click.option("--ssid", type=str, help="Set Wi-Fi network SSID")
@click.option("--password", type=str, help="Set WPA/WPA2 pre-shared key (8-63 characters)")
@click.option("--hide/--broadcast", "is_hidden", default=None, help="Hide or broadcast SSID")
@click.option("--channel", type=str, help="Set wireless channel")
@click.option("--dry-run", is_flag=True, help="Simulate changes without applying them")
@click.pass_context
def cmd_wifi_set(
    ctx: click.Context,
    radio: str,
    is_enabled: bool | None,
    ssid: str | None,
    password: str | None,
    is_hidden: bool | None,
    channel: str | None,
    dry_run: bool,
) -> None:
    """Safely configure Wi-Fi radio settings with diff receipt and dry-run."""
    json_mode = ctx.obj.get("json", False)

    updates: dict[str, Any] = {}
    if is_enabled is not None:
        updates["enable"] = "on" if is_enabled else "off"
    if ssid is not None:
        updates["ssid"] = ssid
    if password is not None:
        if not (8 <= len(password) <= 63):
            err = LuciApiError(
                message="Wi-Fi password must be between 8 and 63 characters.",
                error_code="INVALID_PASSWORD",
                hint="Provide a valid WPA2/WPA3 password between 8 and 63 characters.",
                exit_code=1,
            )
            emit_error(err, json_mode=json_mode)
        updates["psk_key"] = password
    if is_hidden is not None:
        updates["hidden"] = "on" if is_hidden else "off"
    if channel is not None:
        updates["channel"] = channel

    if not updates:
        err = LuciApiError(
            message="No configuration changes specified.",
            error_code="CLI_USAGE_ERROR",
            hint="Specify at least one option: --enable/--disable, --ssid, --password, --hide/--broadcast, --channel.",
            exit_code=1,
        )
        emit_error(err, json_mode=json_mode)

    client = get_client(ctx)
    module, form, desc = WIFI_RADIO_MAP[radio]
    try:
        receipt = client.read_modify_write(module, form, updates, dry_run=dry_run)
    except TpluciError as err:
        emit_error(err, json_mode=json_mode)

    receipt["radio"] = radio
    receipt["name"] = desc

    if json_mode:
        emit_output(receipt, "", json_mode=True)
        return

    lines = []
    if receipt["dry_run"]:
        lines.append(f"[DRY-RUN] Simulated changes for {desc} ({radio}):")
    else:
        lines.append(f"Updated Wi-Fi settings for {desc} ({radio}):")

    if receipt["changed"]:
        for field, change in receipt["diff"].items():
            lines.append(f"  {field}: {change['before']} -> {change['after']}")
        if receipt["dry_run"]:
            lines.append("\n(Dry-run: No changes were applied to the router)")
        else:
            lines.append("\nChanges successfully applied to router.")
    else:
        lines.append("  No changes needed; router already matches requested configuration.")

    emit_output(receipt, "\n".join(lines), json_mode=False)


# =====================================================================
# Command: wan
# =====================================================================
@cli.command("wan")
@click.pass_context
def cmd_wan(ctx: click.Context) -> None:
    """Inspect WAN connection, IP, and gateway configuration."""
    json_mode = ctx.obj.get("json", False)
    client = get_client(ctx)

    try:
        raw_wan = client.call("network", "wan_ipv4_status")
        raw_all = client.call("status", "all")
    except TpluciError as err:
        emit_error(err, json_mode=json_mode)

    info = parse_wan_info(raw_wan, raw_all)
    if json_mode:
        emit_output(info, "", json_mode=True)
        return

    pairs = [
        ("Internet Status", info["status"]),
        ("IP Address", info["ipaddr"] or "<none>"),
        ("Subnet Mask", info["netmask"] or "<none>"),
        ("Gateway", info["gateway"] or "<none>"),
        ("Protocol", info["conntype"]),
        ("DNS Servers", info["dns"] or "<none>"),
        ("MAC Address", info["macaddr"] or "<none>"),
        ("Uptime", f"{info['uptime']}s" if info["uptime"] else "<none>"),
    ]
    emit_output(info, format_key_value(pairs), json_mode=False)


# =====================================================================
# Command: lan
# =====================================================================
@cli.command("lan")
@click.pass_context
def cmd_lan(ctx: click.Context) -> None:
    """Inspect LAN IP, subnet, and DHCP server parameters."""
    json_mode = ctx.obj.get("json", False)
    client = get_client(ctx)

    try:
        raw_lan = client.call("network", "lan_ipv4")
        raw_dhcp = client.call("dhcps", "setting")
    except TpluciError as err:
        emit_error(err, json_mode=json_mode)

    info = parse_lan_info(raw_lan, raw_dhcp)
    if json_mode:
        emit_output(info, "", json_mode=True)
        return

    dhcp = info.get("dhcp", {})
    pairs = [
        ("LAN IP Address", info["ipaddr"]),
        ("Subnet Mask", info["netmask"]),
        ("MAC Address", info["macaddr"]),
        ("DHCP Server", "Enabled" if dhcp.get("enabled") else "Disabled"),
        ("DHCP Pool", f"{dhcp.get('ipaddr_start')} - {dhcp.get('ipaddr_end')}"),
        ("Lease Time", f"{dhcp.get('leasetime')} minutes"),
        ("Default Gateway", dhcp.get("gateway", info["ipaddr"])),
    ]
    emit_output(info, format_key_value(pairs), json_mode=False)


# =====================================================================
# Command Group: system
# =====================================================================
@cli.group("system")
def cmd_system_group() -> None:
    """System maintenance, firmware info, and reboot."""
    pass


@cmd_system_group.command("info")
@click.pass_context
def cmd_system_info(ctx: click.Context) -> None:
    """Show router model, hardware version, and firmware build."""
    json_mode = ctx.obj.get("json", False)
    client = get_client(ctx)

    try:
        fw = client.call("firmware", "upgrade")
        mode = client.call("system", "sysmode")
    except TpluciError as err:
        emit_error(err, json_mode=json_mode)

    info = {
        "model": fw.get("model", "Archer AX23"),
        "hardware_version": fw.get("hardware_version", ""),
        "firmware_version": fw.get("firmware_version", ""),
        "operation_mode": mode.get("mode", "Router"),
    }

    if json_mode:
        emit_output(info, "", json_mode=True)
        return

    pairs = [
        ("Model", info["model"]),
        ("Hardware Version", info["hardware_version"] or "V1"),
        ("Firmware Version", info["firmware_version"] or "<installed>"),
        ("Operation Mode", info["operation_mode"]),
    ]
    emit_output(info, format_key_value(pairs), json_mode=False)


@cmd_system_group.command("time")
@click.pass_context
def cmd_system_time(ctx: click.Context) -> None:
    """Show router system time and NTP synchronization settings."""
    json_mode = ctx.obj.get("json", False)
    client = get_client(ctx)

    try:
        time_data = client.call("time", "settings")
    except TpluciError as err:
        emit_error(err, json_mode=json_mode)

    if json_mode:
        emit_output(time_data, "", json_mode=True)
        return

    pairs = [
        ("Date", time_data.get("date", "")),
        ("Time", time_data.get("time", "")),
        ("Timezone", time_data.get("timezone", "")),
        ("24h Format", "Yes" if time_data.get("hour24_enable") == "on" else "No"),
        ("NTP Server 1", time_data.get("ntp_svr1", "")),
        ("NTP Server 2", time_data.get("ntp_svr2", "")),
    ]
    emit_output(time_data, format_key_value(pairs), json_mode=False)


@cmd_system_group.command("reboot-schedule")
@click.option("--enable/--disable", "is_enabled", default=None, help="Enable or disable scheduled router reboot")
@click.option("--cycle", type=click.Choice(["day", "week", "month"], case_sensitive=False), help="Reboot recurrence cycle")
@click.option("--day", type=str, help="Day of week (Mon..Sun) or day of month (1..28)")
@click.option("--time", "time_val", type=str, help="Scheduled reboot time (HH:MM)")
@click.option("--dry-run", is_flag=True, help="Simulate update without writing to router")
@click.pass_context
def cmd_system_reboot_schedule(
    ctx: click.Context,
    is_enabled: bool | None,
    cycle: str | None,
    day: str | None,
    time_val: str | None,
    dry_run: bool,
) -> None:
    """Inspect or configure scheduled automatic router reboot."""
    json_mode = ctx.obj.get("json", False)
    client = get_client(ctx)

    has_mutation = any(x is not None for x in (is_enabled, cycle, day, time_val))

    if not has_mutation:
        try:
            raw_data = client.call("reboot", "set", operation="read")
        except TpluciError as err:
            emit_error(err, json_mode=json_mode)

        if json_mode:
            emit_output(raw_data, "", json_mode=True)
            return

        pairs = [
            ("Scheduled Reboot", "Enabled" if raw_data.get("enable") == "on" else "Disabled"),
            ("Cycle", raw_data.get("cycle", "week")),
            ("Day", raw_data.get("day", "")),
            ("Time", raw_data.get("time", "")),
        ]
        emit_output(raw_data, format_key_value(pairs), json_mode=False)
        return

    updates: dict[str, Any] = {}
    if is_enabled is not None:
        updates["enable"] = "on" if is_enabled else "off"
    if cycle is not None:
        updates["cycle"] = cycle.lower()
    if day is not None:
        try:
            updates["day"] = normalize_weekday(day)
        except ValueError as exc:
            err = LuciApiError(str(exc), error_code="CLI_USAGE_ERROR", exit_code=1)
            emit_error(err, json_mode=json_mode)
    if time_val is not None:
        updates["time"] = time_val

    try:
        receipt = client.read_modify_write("reboot", "set", updates, dry_run=dry_run)
    except TpluciError as err:
        emit_error(err, json_mode=json_mode)

    if json_mode:
        emit_output(receipt, "", json_mode=True)
        return

    lines = []
    if receipt["dry_run"]:
        lines.append("[DRY-RUN] Simulated changes for scheduled reboot:")
    else:
        lines.append("Updated scheduled reboot settings:")

    if receipt["changed"]:
        for field, change in receipt["diff"].items():
            lines.append(f"  {field}: {change['before']} -> {change['after']}")
        if receipt["dry_run"]:
            lines.append("\n(Dry-run: No changes were applied to the router)")
        else:
            lines.append("\nChanges successfully applied to router.")
    else:
        lines.append("  No changes needed; router already matches requested configuration.")

    emit_output(receipt, "\n".join(lines), json_mode=False)


@cmd_system_group.command("led")
@click.option("--on/--off", "led_on", default=None, help="Turn router LEDs on or off")
@click.option(
    "--night-mode",
    "night_mode",
    type=click.Choice(["on", "off"], case_sensitive=False),
    help="Enable or disable Night Mode",
)
@click.option("--start", "night_start", type=str, help="Night mode start time (HH:MM)")
@click.option("--end", "night_end", type=str, help="Night mode end time (HH:MM)")
@click.option("--dry-run", is_flag=True, help="Simulate update without writing to router")
@click.pass_context
def cmd_system_led(
    ctx: click.Context,
    led_on: bool | None,
    night_mode: str | None,
    night_start: str | None,
    night_end: str | None,
    dry_run: bool,
) -> None:
    """Inspect or configure router status LEDs and Night Mode schedule."""
    json_mode = ctx.obj.get("json", False)
    client = get_client(ctx)

    has_mutation = any(x is not None for x in (led_on, night_mode, night_start, night_end))

    if not has_mutation:
        try:
            raw_gen = client.call("ledgeneral", "setting", operation="read")
            raw_pm = client.call("ledpm", "setting", operation="read")
        except TpluciError as err:
            emit_error(err, json_mode=json_mode)

        info = {
            "led_enable": raw_gen.get("enable") == "on",
            "night_mode": raw_pm.get("enable") == "on",
            "night_start": raw_pm.get("time_start", ""),
            "night_end": raw_pm.get("time_end", ""),
        }
        if json_mode:
            emit_output(info, "", json_mode=True)
            return

        pairs = [
            ("Status LEDs", "On" if info["led_enable"] else "Off"),
            ("Night Mode", "Enabled" if info["night_mode"] else "Disabled"),
            ("Night Mode Start", info["night_start"] or "<none>"),
            ("Night Mode End", info["night_end"] or "<none>"),
        ]
        emit_output(info, format_key_value(pairs), json_mode=False)
        return

    combined_diff: dict[str, Any] = {}
    changed = False

    if led_on is not None:
        try:
            receipt_gen = client.read_modify_write(
                "ledgeneral", "setting", {"enable": "on" if led_on else "off"}, dry_run=dry_run
            )
            combined_diff.update(receipt_gen.get("diff", {}))
            if receipt_gen.get("changed"):
                changed = True
        except TpluciError as err:
            emit_error(err, json_mode=json_mode)

    pm_updates: dict[str, Any] = {}
    if night_mode is not None:
        pm_updates["enable"] = "on" if night_mode.lower() == "on" else "off"
    if night_start is not None:
        pm_updates["time_start"] = night_start
    if night_end is not None:
        pm_updates["time_end"] = night_end

    if pm_updates:
        try:
            receipt_pm = client.read_modify_write("ledpm", "setting", pm_updates, dry_run=dry_run)
            combined_diff.update(receipt_pm.get("diff", {}))
            if receipt_pm.get("changed"):
                changed = True
        except TpluciError as err:
            emit_error(err, json_mode=json_mode)

    receipt = {
        "ok": True,
        "dry_run": dry_run,
        "changed": changed,
        "diff": combined_diff,
    }

    if json_mode:
        emit_output(receipt, "", json_mode=True)
        return

    lines = []
    if dry_run:
        lines.append("[DRY-RUN] Simulated changes for router LED / Night Mode:")
    else:
        lines.append("Updated router LED / Night Mode settings:")

    if changed:
        for field, change in combined_diff.items():
            lines.append(f"  {field}: {change['before']} -> {change['after']}")
        if dry_run:
            lines.append("\n(Dry-run: No changes were applied to the router)")
        else:
            lines.append("\nChanges successfully applied to router.")
    else:
        lines.append("  No changes needed; router already matches requested configuration.")

    emit_output(receipt, "\n".join(lines), json_mode=False)


@cmd_system_group.command("reboot")
@click.option("--confirm", is_flag=True, help="Explicit confirmation required to reboot")
@click.option("--dry-run", is_flag=True, help="Simulate reboot without issuing command to hardware")
@click.pass_context
def cmd_system_reboot(ctx: click.Context, confirm: bool, dry_run: bool) -> None:
    """Safely reboot the router hardware."""
    json_mode = ctx.obj.get("json", False)

    if not confirm:
        if not sys.stdin.isatty():
            err = SafetyAbortError(
                message="Refusing to reboot router in non-interactive environment without --confirm.",
                hint="Pass --confirm to authorize router reboot: tpluci system reboot --confirm",
            )
            emit_error(err, json_mode=json_mode)
        else:
            if not click.confirm("Are you sure you want to reboot the router?", default=False):
                err = SafetyAbortError(
                    message="Router reboot aborted by user.",
                    hint="Re-run with --confirm when ready.",
                )
                emit_error(err, json_mode=json_mode)

    if dry_run:
        result = {
            "ok": True,
            "dry_run": True,
            "message": "[DRY-RUN] Router reboot simulated. No command sent to hardware.",
        }
        emit_output(result, result["message"], json_mode=json_mode)
        return

    client = get_client(ctx)
    try:
        client.call("system", "reboot", operation="reboot")
    except TpluciError as err:
        emit_error(err, json_mode=json_mode)

    result = {
        "ok": True,
        "dry_run": False,
        "message": "Reboot command accepted. Router is now restarting.",
    }
    emit_output(result, result["message"], json_mode=json_mode)


# =====================================================================
# Command: call
# =====================================================================
@cli.command("call")
@click.argument("module", required=False)
@click.argument("form", required=False)
@click.option("--module", "module_opt", type=str, help="LuCI module name (alternative to positional)")
@click.option("--form", "form_opt", type=str, help="LuCI form name (alternative to positional)")
@click.option("--list", "list_endpoints", is_flag=True, help="List all verified LuCI endpoints")
@click.option("--op", default="read", type=str, help="LuCI operation (default: read)")
@click.option(
    "--param",
    "params",
    multiple=True,
    help="Endpoint parameters in key=value format (can be specified multiple times)",
)
@click.pass_context
def cmd_call(
    ctx: click.Context,
    module: str | None,
    form: str | None,
    module_opt: str | None,
    form_opt: str | None,
    list_endpoints: bool,
    op: str,
    params: tuple[str, ...],
) -> None:
    """Execute or list raw LuCI CGI endpoints."""
    json_mode = ctx.obj.get("json", False)

    if list_endpoints:
        if json_mode:
            emit_output(VERIFIED_ENDPOINTS, "", json_mode=True)
            return

        headers = ["CATEGORY", "MODULE", "FORM", "DEFAULT OP", "DESCRIPTION"]
        rows = [
            [ep["category"], ep["module"], ep["form"], ep.get("operation", "read"), ep["description"]]
            for ep in VERIFIED_ENDPOINTS
        ]
        emit_output(VERIFIED_ENDPOINTS, format_table(headers, rows), json_mode=False)
        return

    target_module = module or module_opt
    target_form = form or form_opt
    if not target_module or not target_form:
        err = LuciApiError(
            message="Both MODULE and FORM are required when calling an endpoint.",
            error_code="CLI_USAGE_ERROR",
            hint="Usage: tpluci call <MODULE> <FORM> [--op read|write] [--param key=val] or 'tpluci call --list'",
            exit_code=1,
        )
        emit_error(err, json_mode=json_mode)

    client = get_client(ctx)
    param_dict: dict[str, Any] = {}
    for p in params:
        if "=" in p:
            k, v = p.split("=", 1)
            param_dict[k.strip()] = v.strip()

    try:
        result = client.call(target_module, target_form, operation=op, params=param_dict)
    except TpluciError as err:
        emit_error(err, json_mode=json_mode)

    emit_output(result, json.dumps(result, indent=2), json_mode=json_mode)


# =====================================================================
# Command Group: config
# =====================================================================
@cli.group("config", invoke_without_command=True)
@click.pass_context
def cmd_config_group(ctx: click.Context) -> None:
    """Manage router profiles and secure credentials."""
    if ctx.invoked_subcommand is None:
        if not sys.stdin.isatty():
            ctx.invoke(cmd_config_list)
        else:
            interactive_config_wizard(ctx)


def interactive_config_wizard(ctx: click.Context) -> None:
    """Interactive rclone-style configuration menu."""
    while True:
        click.echo("\n--- tpluci Configuration ---")
        click.echo("  n) Add / New profile")
        click.echo("  e) Edit existing profile")
        click.echo("  l) List profiles")
        click.echo("  d) Delete profile")
        click.echo("  s) Set default profile")
        click.echo("  t) Test connection")
        click.echo("  q) Quit")
        choice = click.prompt("Choose an option", type=str, default="q").strip().lower()

        if choice in ("n", "e"):
            name = click.prompt("Profile name", default="default").strip()
            url = click.prompt("Router URL", default=DEFAULT_ROUTER_URL).strip()
            password = click.prompt("Router password", hide_input=True).strip()
            use_keyring = click.confirm("Store password in OS keyring?", default=True)
            storage = save_profile(name, url, password, use_keyring=use_keyring)
            click.echo(f"Profile '{name}' saved using {storage}.")
        elif choice == "l":
            ctx.invoke(cmd_config_list)
        elif choice == "d":
            name = click.prompt("Profile name to delete").strip()
            delete_profile(name)
            click.echo(f"Profile '{name}' deleted.")
        elif choice == "s":
            name = click.prompt("Default profile name").strip()
            set_default_profile(name)
            click.echo(f"Default profile set to '{name}'.")
        elif choice == "t":
            ctx.invoke(cmd_config_test)
        elif choice in ("q", "quit", "exit"):
            break


@cmd_config_group.command("list")
@click.pass_context
def cmd_config_list(ctx: click.Context) -> None:
    """List all configured router profiles."""
    json_mode = ctx.obj.get("json", False)
    cfg = list_profiles()

    if json_mode:
        emit_output(cfg, "", json_mode=True)
        return

    default_prof = cfg.get("default_profile", "default")
    profiles = cfg.get("profiles", {})
    if not profiles:
        click.echo("No profiles configured in config.json. Using environment / .env variables.")
        return

    headers = ["DEFAULT", "PROFILE", "URL", "KEYRING", "TIMEOUT"]
    rows = []
    for name, p in profiles.items():
        is_def = "*" if name == default_prof else ""
        rows.append([
            is_def,
            name,
            p.get("url", DEFAULT_ROUTER_URL),
            "yes" if p.get("use_keyring", True) else "no",
            f"{p.get('timeout', DEFAULT_TIMEOUT)}s",
        ])
    emit_output(cfg, format_table(headers, rows), json_mode=False)


@cmd_config_group.command("add")
@click.option("--name", required=True, help="Profile name (e.g. default, office)")
@click.option("--url", default=None, help="Router management URL")
@click.option("--password", required=True, prompt=True, hide_input=True, help="Router admin password")
@click.option("--username", default="", help="Username (default: empty for AX23)")
@click.option("--timeout", default=None, type=float, help="Timeout in seconds")
@click.option("--no-keyring", is_flag=True, help="Disable OS keyring and use 0600 config file")
@click.pass_context
def cmd_config_add(
    ctx: click.Context,
    name: str,
    url: str | None,
    password: str,
    username: str,
    timeout: float | None,
    no_keyring: bool,
) -> None:
    """Add or update a profile."""
    json_mode = ctx.obj.get("json", False)
    effective_url = url or ctx.obj.get("url") or DEFAULT_ROUTER_URL
    effective_timeout = timeout if timeout is not None else ctx.obj.get("timeout", DEFAULT_TIMEOUT)
    storage = save_profile(
        name=name,
        url=effective_url,
        password=password,
        username=username,
        timeout=effective_timeout,
        use_keyring=not no_keyring,
    )
    result = {
        "ok": True,
        "profile": name,
        "url": effective_url,
        "timeout": effective_timeout,
        "storage": storage,
        "message": f"Profile '{name}' saved successfully using {storage} storage.",
    }
    emit_output(result, result["message"], json_mode=json_mode)


@cmd_config_group.command("delete")
@click.option("--name", required=True, help="Profile name to remove")
@click.pass_context
def cmd_config_delete(ctx: click.Context, name: str) -> None:
    """Delete a configuration profile."""
    json_mode = ctx.obj.get("json", False)
    delete_profile(name)
    result = {
        "ok": True,
        "profile": name,
        "message": f"Profile '{name}' deleted.",
    }
    emit_output(result, result["message"], json_mode=json_mode)


@cmd_config_group.command("default")
@click.option("--name", required=True, help="Profile name to set as default")
@click.pass_context
def cmd_config_default(ctx: click.Context, name: str) -> None:
    """Set the default profile."""
    json_mode = ctx.obj.get("json", False)
    set_default_profile(name)
    result = {
        "ok": True,
        "default_profile": name,
        "message": f"Default profile set to '{name}'.",
    }
    emit_output(result, result["message"], json_mode=json_mode)


@cmd_config_group.command("test")
@click.pass_context
def cmd_config_test(ctx: click.Context) -> None:
    """Test credentials and router connectivity."""
    json_mode = ctx.obj.get("json", False)
    client = get_client(ctx)

    try:
        data = client.call("status", "internet")
        result = {
            "ok": True,
            "connected": True,
            "wan_status": data.get("wan_internet_status") or data.get("internet_status", "connected"),
            "profile": client.creds.profile,
            "url": client.creds.url,
            "message": f"Success: Connected and authenticated with router at {client.creds.url}.",
        }
        emit_output(result, result["message"], json_mode=json_mode)
    except TpluciError as err:
        emit_error(err, json_mode=json_mode)


# =====================================================================
# Command: logout
# =====================================================================
@cli.command("logout")
@click.pass_context
def cmd_logout(ctx: click.Context) -> None:
    """Terminate active router session and clear local cache."""
    from tpluci.session import SessionCache

    json_mode = ctx.obj.get("json", False)
    target_profile = resolve_profile_name(ctx.obj.get("profile"))
    cleared = SessionCache.clear(target_profile)

    result = {
        "ok": True,
        "cleared": cleared,
        "profile": target_profile,
        "message": f"Local session cache cleared for profile '{target_profile}'.",
    }
    emit_output(result, result["message"], json_mode=json_mode)


def main() -> None:
    """Main CLI entrypoint with top-level error handling."""
    try:
        cli(obj={})
    except TpluciError as err:
        emit_error(err, json_mode="--json" in sys.argv)
        sys.exit(err.exit_code)
    except Exception as exc:
        sys.stderr.write(f"Unexpected error: {exc}\n")
        sys.exit(1)


if __name__ == "__main__":
    main()
