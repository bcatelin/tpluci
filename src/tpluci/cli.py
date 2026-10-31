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
    save_profile,
    set_default_profile,
)
from tpluci.endpoints import VERIFIED_ENDPOINTS, WIFI_RADIO_MAP
from tpluci.exceptions import LuciApiError, SafetyAbortError, TpluciError
from tpluci.formatters import emit_error, emit_output, format_key_value, format_table
from tpluci.models import (
    parse_clients,
    parse_lan_info,
    parse_status_summary,
    parse_wan_info,
    parse_wifi_summary,
)


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
# Command: clients
# =====================================================================
@cli.command("clients")
@click.argument("query", required=False)
@click.option("--wireless-only", "wireless_only", is_flag=True, help="List only wireless clients")
@click.option("--wired-only", "wired_only", is_flag=True, help="List only wired clients")
@click.option("--band", type=click.Choice(["2g", "5g"], case_sensitive=False), help="Filter by Wi-Fi band")
@click.option(
    "--sort",
    "sort_by",
    type=click.Choice(["hostname", "ip", "band", "mac", "medium"], case_sensitive=False),
    default="hostname",
    help="Sort output column",
)
@click.pass_context
def cmd_clients(
    ctx: click.Context,
    query: str | None,
    wireless_only: bool,
    wired_only: bool,
    band: str | None,
    sort_by: str,
) -> None:
    """List and filter connected wired and wireless devices."""
    json_mode = ctx.obj.get("json", False)
    client = get_client(ctx)

    try:
        raw_all = client.call("status", "all")
    except TpluciError as err:
        emit_error(err, json_mode=json_mode)

    medium = "all"
    if wireless_only:
        medium = "wireless"
    elif wired_only:
        medium = "wired"

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
@click.option("--list", "list_endpoints", is_flag=True, help="List all 30 verified LuCI endpoints")
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

        headers = ["CATEGORY", "MODULE", "FORM", "DESCRIPTION"]
        rows = [
            [ep["category"], ep["module"], ep["form"], ep["description"]]
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
