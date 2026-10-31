# `tpluci` User & AI Agent Guide

This guide covers every CLI command, global option, output mode, and Model Context Protocol (MCP) tool provided by `tpluci` and `tpluci-mcp`.

---

## 1. Global Flags & Output Ergonomics

`tpluci` uses a custom `OrderIndependentGroup` command parser. **Global flags can be placed anywhere on the command line**—before the subcommand, between subcommands, or at the very end—so both human muscle memory and AI agent command builders succeed on the first try.

```bash
# All three invocations are 100% equivalent:
tpluci --json wifi list
tpluci wifi --json list
tpluci wifi list --json
```

### Global Options Reference

| Flag | Environment Variable | Default | Description |
| :--- | :--- | :--- | :--- |
| `--json` | `TPLUCI_OUTPUT=json` | `False` | Emit deterministic, indented JSON to `stdout` (and structured JSON error envelopes to `stderr`). |
| `--plain` | `NO_COLOR=1` / `TPLUCI_COLOR=0` | Auto-detected | Force plain space-aligned text without ANSI sequences (automatically enabled when `stdout` is piped). |
| `--profile <NAME>` | `TPLUCI_PROFILE` / `ROUTER_PROFILE` | `default` | Select the named router profile from `~/.config/tpluci/config.json` or OS Keyring. |
| `--url <URL>` | `ROUTER_URL` / `TPLUCI_URL` | `http://192.168.7.250` | Override the target router base URL for this invocation. |
| `--timeout <FLOAT>` | `ROUTER_TIMEOUT` / `TPLUCI_TIMEOUT` | `5.0` | HTTP request timeout in seconds. |
| `--no-cache` | — | `False` | Bypass the `/tmp` ephemeral session cache and force a fresh RSA+AES login handshake. |
| `-v`, `--version` | — | — | Print `tpluci 0.1.0` and exit. |
| `-h`, `--help` | — | — | Show command help and exit. |

### Stream Separation Contract

- **`stdout`**: Exclusively carries command data payloads (human tables, key-value summaries, raw `--field` values, or `--json` objects).
- **`stderr`**: Exclusively carries warnings (such as Tier 4 plaintext password fallback notices) and structured or human error diagnostics.

---

## 2. Command Reference

### 2.1 `tpluci status` — System, Internet & Hardware Dashboard

Queries the master endpoint (`status?form=all`) and normalizes hardware metrics (converting floating-point ratios like `0.18` into `18%` and inferring connection status when needed).

#### Curated Dashboard (Default — ~120 Tokens)

```bash
$ tpluci status
Model:            Archer AX23
Internet Status:  connected
WAN IP:           203.0.113.42 (pppoe, gw 203.0.113.1)
LAN IP:           192.168.7.250
CPU / Memory:     18% CPU, 42% RAM
Uptime:           24h 00m 00s
Connected Hosts:  4 total (3 wireless, 1 wired)
Wi-Fi Status:     2.4G [on] (HomeNet_2G), 5G [on] (HomeNet_5G)
```

#### Curated Dashboard (`--json`)

```bash
$ tpluci status --json
{
  "model": "Archer AX23",
  "cpu_usage": 18,
  "mem_usage": 42,
  "uptime_seconds": 86400,
  "internet_status": "connected",
  "wan_ip": "203.0.113.42",
  "wan_gateway": "203.0.113.1",
  "wan_conntype": "pppoe",
  "lan_ip": "192.168.7.250",
  "wifi": {
    "2g": {
      "enabled": true,
      "ssid": "HomeNet_2G"
    },
    "5g": {
      "enabled": true,
      "ssid": "HomeNet_5G"
    },
    "guest-2g": {
      "enabled": false,
      "ssid": "GuestNet_2G"
    },
    "guest-5g": {
      "enabled": false,
      "ssid": "GuestNet_5G"
    },
    "iot-2g": {
      "enabled": true,
      "ssid": "IoTNet_2G"
    },
    "iot-5g": {
      "enabled": false,
      "ssid": "IoTNet_5G"
    }
  },
  "clients_count": {
    "wireless": 3,
    "wired": 1,
    "total": 4
  }
}
```

#### Single-Field Extraction (`--field <KEY>`)

Extract any of the 199 raw keys from `status?form=all` directly without piping to `jq`:

```bash
$ tpluci status --field wan_ipv4_ipaddr
203.0.113.42

$ tpluci status --field wan_ipv4_ipaddr --json
{
  "wan_ipv4_ipaddr": "203.0.113.42"
}
```

#### Complete 199-Key Dump (`--full`)

```bash
$ tpluci status --full --json
```

---

### 2.2 `tpluci clients` — Connected Device Inventory & Search

Lists active wired and wireless clients from `status?form=all` (`access_devices_wireless_host` and `access_devices_wired`).

```text
Usage: tpluci clients [OPTIONS] [QUERY]

Options:
  --wireless-only                           List only wireless clients
  --wired-only                              List only wired clients
  --band [2g|5g]                            Filter by Wi-Fi band
  --sort [hostname|ip|band|mac|medium]      Sort output column (default: hostname)
```

#### Default Client Table

```bash
$ tpluci clients
HOSTNAME     IP             MAC                MEDIUM    BAND 
-----------  -------------  -----------------  --------  -----
NAS-Server   192.168.7.10   AA-BB-CC-DD-EE-10  wired     wired
Smart-Plug   192.168.7.103  AA-BB-CC-DD-EE-03  wireless  2.4G 
Test-Laptop  192.168.7.101  AA-BB-CC-DD-EE-01  wireless  5G   
Test-Phone   192.168.7.102  AA-BB-CC-DD-EE-02  wireless  2.4G 

Total: 4 clients (3 wireless, 1 wired)
```

#### Substring Search Across Hostname, IP, or MAC

Pass an optional positional `QUERY` to perform a case-insensitive substring match against `hostname`, `ipaddr`, or `macaddr`:

```bash
$ tpluci clients laptop
HOSTNAME     IP             MAC                MEDIUM    BAND
-----------  -------------  -----------------  --------  ----
Test-Laptop  192.168.7.101  AA-BB-CC-DD-EE-01  wireless  5G  

Total: 1 clients (1 wireless, 0 wired)
```

#### Filtering by Band / Medium & Natural IPv4 Sorting

`--sort ip` sorts IPv4 octets numerically (`192.168.7.10` before `192.168.7.101`) rather than lexicographically:

```bash
$ tpluci clients --wireless-only --band 2g --sort ip --json
[
  {
    "hostname": "Test-Phone",
    "ipaddr": "192.168.7.102",
    "macaddr": "AA-BB-CC-DD-EE-02",
    "medium": "wireless",
    "band": "2.4G"
  },
  {
    "hostname": "Smart-Plug",
    "ipaddr": "192.168.7.103",
    "macaddr": "AA-BB-CC-DD-EE-03",
    "medium": "wireless",
    "band": "2.4G"
  }
]
```

---

### 2.3 `tpluci wifi` — Main, Guest & IoT Wireless Control

`tpluci` manages all **6 independent Wi-Fi radio forms** exposed by TP-Link Archer firmware:

| Radio Identifier | LuCI Module & Form | Network Type |
| :--- | :--- | :--- |
| `2g` | `wireless?form=wireless_2g` | Main 2.4 GHz Network |
| `5g` | `wireless?form=wireless_5g` | Main 5 GHz Network |
| `guest-2g` | `wireless?form=guest_2g` | Guest 2.4 GHz Network |
| `guest-5g` | `wireless?form=guest_5g` | Guest 5 GHz Network |
| `iot-2g` | `wireless?form=iot_2g` | Dedicated IoT 2.4 GHz Network |
| `iot-5g` | `wireless?form=iot_5g` | Dedicated IoT 5 GHz Network |

#### `tpluci wifi list` (alias: `tpluci wifi status`)

```bash
$ tpluci wifi list
RADIO     NAME           SSID          STATUS  CHANNEL  ENCRYPTION  HIDDEN
--------  -------------  ------------  ------  -------  ----------  ------
2g        Main 2.4 GHz   HomeNet_2G    on      6        psk         no    
5g        Main 5 GHz     HomeNet_5G    on      36       psk         no    
guest-2g  Guest 2.4 GHz  GuestNet_2G   off     6        psk         no    
guest-5g  Guest 5 GHz    GuestNet_5G   off     36       psk         no    
iot-2g    IoT 2.4 GHz    IoTNet_2G     on      6        psk         no    
iot-5g    IoT 5 GHz      IoTNet_5G     off     36       psk         no    
```

#### `tpluci wifi get <radio>`

Inspect detailed configuration for a single radio (`2g`, `5g`, `guest-2g`, `guest-5g`, `iot-2g`, `iot-5g`, or `all`):

```bash
$ tpluci wifi get 5g
Radio:       5g
Name:        Main 5 GHz
SSID:        HomeNet_5G
Enabled:     on
Channel:     36
Bandwidth:   80
Encryption:  psk
Hidden:      off
MU-MIMO:     on
```

```bash
$ tpluci wifi get guest-2g --json
{
  "ssid": "GuestNet_2G",
  "enable": "off",
  "psk_key": "GuestPass2026!",
  "encryption": "psk",
  "psk_cipher": "aes",
  "hidden": "off"
}
```

#### `tpluci wifi set <radio>` — Safe Read-Modify-Write Mutations

```text
Usage: tpluci wifi set [OPTIONS] [2g|5g|guest-2g|guest-5g|iot-2g|iot-5g]

Options:
  --enable / --disable    Enable or disable radio
  --ssid TEXT             Set Wi-Fi network SSID
  --password TEXT         Set WPA/WPA2 pre-shared key (8-63 characters)
  --hide / --broadcast    Hide or broadcast SSID
  --channel TEXT          Set wireless channel
  --dry-run               Simulate changes without applying them
```

When you run `tpluci wifi set`, `tpluci` performs a 4-step **Read-Modify-Write** transaction:
1. Reads the current form dictionary from the router (`operation=read`).
2. Computes the exact diff between current values and requested changes.
3. Strips read-only nested metadata dicts/lists (such as `extinfo`) and writes the merged payload (`operation=write`) unless `--dry-run` is active.
4. Prints a clear **mutation receipt** showing `before -> after` for every modified key.

##### Example: Simulate Enabling Guest 2.4 GHz (`--dry-run`)

```bash
$ tpluci wifi set guest-2g --enable --ssid "Visitors_2G" --dry-run
[DRY-RUN] Simulated changes for Guest 2.4 GHz (guest-2g):
  enable: off -> on
  ssid: GuestNet_2G -> Visitors_2G

(Dry-run: No changes were applied to the router)
```

##### Example: Apply Changes & Receive JSON Receipt (`--json`)

```bash
$ tpluci wifi set guest-2g --enable --ssid "Visitors_2G" --json
{
  "dry_run": false,
  "changed": true,
  "diff": {
    "enable": {
      "before": "off",
      "after": "on"
    },
    "ssid": {
      "before": "GuestNet_2G",
      "after": "Visitors_2G"
    }
  },
  "state": {
    "enable": "on",
    "ssid": "Visitors_2G",
    "psk_key": "GuestPass2026!",
    "encryption": "psk",
    "hidden": "off"
  },
  "radio": "guest-2g",
  "name": "Guest 2.4 GHz"
}
```

---

### 2.4 `tpluci wan` & `tpluci lan` — Network & DHCP Inspection

#### `tpluci wan`

Combines `network?form=wan_ipv4_status` and `status?form=all` to report full WAN IPv4 telemetry, including PPPoE/DHCP connection type, gateway, primary/secondary DNS servers, WAN MAC address, and uptime:

```bash
$ tpluci wan
Internet Status:  connected
IP Address:       203.0.113.42
Subnet Mask:      255.255.255.255
Gateway:          203.0.113.1
Protocol:         pppoe
DNS Servers:      1.1.1.1, 8.8.8.8
MAC Address:      AA-BB-CC-11-22-30
Uptime:           86400s
```

```bash
$ tpluci wan --json
{
  "ipaddr": "203.0.113.42",
  "gateway": "203.0.113.1",
  "netmask": "255.255.255.255",
  "dns": "1.1.1.1, 8.8.8.8",
  "macaddr": "AA-BB-CC-11-22-30",
  "conntype": "pppoe",
  "uptime": 86400,
  "status": "connected"
}
```

#### `tpluci lan`

Combines `network?form=lan_ipv4` and `dhcps?form=setting` to display LAN IP, subnet mask, router MAC, and DHCP server pool parameters:

```bash
$ tpluci lan
LAN IP Address:   192.168.7.250
Subnet Mask:      255.255.255.0
MAC Address:      AA-BB-CC-11-22-33
DHCP Server:      Enabled
DHCP Pool:        192.168.7.100 - 192.168.7.249
Lease Time:       120 minutes
Default Gateway:  192.168.7.250
```

```bash
$ tpluci lan --json
{
  "ipaddr": "192.168.7.250",
  "netmask": "255.255.255.0",
  "macaddr": "AA-BB-CC-11-22-33",
  "dhcp": {
    "enabled": true,
    "ipaddr_start": "192.168.7.100",
    "ipaddr_end": "192.168.7.249",
    "leasetime": "120",
    "gateway": "192.168.7.250"
  }
}
```

---

### 2.5 `tpluci system` — Hardware Info, Clock & Safety-Guarded Reboot

#### `tpluci system info`

Queries `firmware?form=upgrade` and `system?form=sysmode`:

```bash
$ tpluci system info
Model:             Archer AX23
Hardware Version:  Archer AX23 v1.0
Firmware Version:  1.1.1 Build 20230725 Rel. 54211(4555)
Operation Mode:    Router
```

#### `tpluci system time`

Queries `time?form=settings`:

```bash
$ tpluci system time
Date:          31/10/2026
Time:          22:15:04
Timezone:      (GMT+01:00) Amsterdam, Berlin, Bern, Rome, Stockholm, Vienna
24h Format:    Yes
NTP Server 1:  time.nist.gov
NTP Server 2:  time-nw.nist.gov
```

#### `tpluci system reboot [--confirm] [--dry-run]`

Reboots the router via `system?form=reboot` (`operation=reboot`).
- **Interactive TTY**: Prompts `Are you sure you want to reboot the router? [y/N]` unless `--confirm` is passed.
- **Non-Interactive Pipe / Agent**: Immediately aborts with exit code `5` (`SAFETY_ABORT`) unless `--confirm` is passed.

```bash
# Simulate reboot without restarting hardware
$ tpluci system reboot --confirm --dry-run
[DRY-RUN] Router reboot simulated. No command sent to hardware.

# Execute real hardware reboot
$ tpluci system reboot --confirm
Reboot command accepted. Router is now restarting.
```

---

### 2.6 `tpluci call` — Endpoint Registry & Raw LuCI Escape Hatch

Provides direct access to all 30 verified LuCI endpoints and arbitrary `<module>?form=<form>` testing.

#### List All 30 Verified Endpoints (`tpluci call --list`)

```bash
$ tpluci call --list
CATEGORY  MODULE            FORM                    DESCRIPTION                                             
--------  ----------------  ----------------------  --------------------------------------------------------
System    status            all                     Master endpoint returning 199 telemetry & status keys   
System    status            internet                Quick WAN internet connection status                    
System    status            menu_status             Menu patrol status flag                                 
System    status            cloud_login_window_pop  Cloud binding status and popup counts                   
System    system            sysmode                 Router operation mode (Router / Bridge)                 
System    cloud_account     get_deviceInfo          Device model string (Archer AX23)                       
System    cloud_account     check_upgrade           Cloud firmware upgrade notification                     
System    firmware          upgrade                 Firmware version, hardware revision, build date         
System    firmware          auto_upgrade            Auto firmware update settings                           
System    time              settings                System clock, NTP servers, and timezone                 
Network   network           wan_ipv4_status         WAN IPv4 connection status and protocol                 
Network   network           wan_ipv6_status         WAN IPv6 status                                         
Network   network           lan_ipv4                LAN IP address, subnet mask, and MAC address            
Network   network           lan_agg                 Link Aggregation (LACP) status and port assignments     
Network   dhcps             setting                 DHCP Server status, pool bounds, and lease time         
Network   iptv              setting                 IPTV / VLAN port mappings and IGMP snooping             
Network   ddns              provider                Dynamic DNS provider status                             
Wireless  wireless          wireless_2g             Main 2.4 GHz Wi-Fi radio configuration                  
Wireless  wireless          wireless_5g             Main 5 GHz Wi-Fi radio configuration                    
Wireless  wireless          guest_2g                Guest 2.4 GHz Wi-Fi radio configuration                 
Wireless  wireless          guest_5g                Guest 5 GHz Wi-Fi radio configuration                   
Wireless  wireless          iot_2g                  IoT 2.4 GHz Wi-Fi radio configuration                   
Wireless  wireless          iot_5g                  IoT 5 GHz Wi-Fi radio configuration                     
Wireless  wireless          smart_connect           Smart Connect band-steering setting                     
Wireless  easymesh_network  mesh_sclient_list_all   EasyMesh nodes and clients list                         
Security  nat               dmz                     DMZ host status and IP                                  
Security  nat               alg                     Application Layer Gateway (ALG) passthrough toggles     
Security  access_control    enable                  Access Control engine toggle and host MAC               
Security  access_control    mode                    Access Control mode (black / white list)                
Security  qos               settings                Quality of Service bandwidth limits and prioritization  
```

#### Execute Raw Read/Write Calls

You can pass `<module>` and `<form>` either positionally or via `--module` and `--form`:

```bash
# Inspect NAT Application Layer Gateway toggles
$ tpluci call nat alg
{
  "pptp": "on",
  "l2tp": "on",
  "ipsec": "on",
  "ftp": "on",
  "tftp": "on",
  "h323": "on",
  "rtsp": "on",
  "sip": "on"
}

# Equivalent using explicit flags
$ tpluci call --module easymesh_network --form mesh_sclient_list_all

# Write parameters to an endpoint
$ tpluci call nat dmz --op write --param enable=off --param ipaddr=192.168.7.50
```

---

## 3. Model Context Protocol (MCP) Server (`tpluci-mcp`)

`tpluci-mcp` exposes the core `tpluci` library over standard input/output (stdio) using `FastMCP`. It shares the exact same 4-tier credential hierarchy and `/tmp` ephemeral session cache as the `tpluci` CLI.

### 3.1 Wiring `tpluci-mcp` into MCP Hosts

Add the following server definition to your MCP client configuration file:
- **Claude Desktop (macOS)**: `~/Library/Application Support/Claude/claude_desktop_config.json`
- **Antigravity (`agy`)**: `~/.gemini/antigravity-cli/mcp.json` (or workspace `.gemini/settings.json`)
- **Cursor**: `.cursor/mcp.json`

#### Option A: Installed via `uv tool install .` (Using OS Keyring Profile)

If you have already saved your credentials via `tpluci config`, no plaintext password is required in the MCP JSON config:

```json
{
  "mcpServers": {
    "tpluci": {
      "command": "tpluci-mcp",
      "args": []
    }
  }
}
```

#### Option B: Running Directly from a Repository Checkout with `env` Variables

```json
{
  "mcpServers": {
    "tpluci": {
      "command": "uv",
      "args": [
        "--directory",
        "/path/to/tpluci",
        "run",
        "tpluci-mcp"
      ],
      "env": {
        "ROUTER_URL": "http://192.168.7.250",
        "ROUTER_PASSWORD": "YourRouterPassword"
      }
    }
  }
}
```

### 3.2 Exposed MCP Tools Reference (7 Tools)

All 7 MCP tools catch `TpluciError` exceptions and return structured JSON dictionaries (`{"ok": false, "error_code": "...", "message": "...", "hint": "..."}`) so LLM agents can self-correct without crashing the MCP server.

| Tool Name | Parameters & Defaults | Return Payload & Behavior |
| :--- | :--- | :--- |
| **`router_get_status`** | `full: bool = False`<br/>`field: str \| None = None` | By default returns the ~120-token curated status summary (`model`, `cpu_usage`, `mem_usage`, `uptime_seconds`, `internet_status`, `wan_ip`, `lan_ip`, `wifi`, `clients_count`). If `field` is provided, returns `{field: value}`. If `full=True`, returns all 199 raw keys from `status?form=all`. |
| **`router_list_clients`** | `query: str \| None = None`<br/>`medium: str = "all"` | Returns a list of connected client dictionaries (`hostname`, `ipaddr`, `macaddr`, `medium`, `band`). Filters by case-insensitive substring `query` (hostname, IP, or MAC) and `medium` (`"all"`, `"wireless"`, `"wired"`). |
| **`router_get_wifi`** | `radio: str = "all"` | When `radio="all"`, returns the 6-element summary list across `2g`, `5g`, `guest-2g`, `guest-5g`, `iot-2g`, and `iot-5g`. When a specific radio is passed, calls `wireless?form=<form>` (`operation=read`) and returns full radio parameters. |
| **`router_set_wifi`** | `radio: str`<br/>`enable: bool \| None = None`<br/>`ssid: str \| None = None`<br/>`password: str \| None = None`<br/>`hidden: bool \| None = None`<br/>`dry_run: bool = False` | Performs a safe Read-Modify-Write on the target radio (`2g`, `5g`, `guest-2g`, `guest-5g`, `iot-2g`, `iot-5g`). Validates WPA password length (8–63 chars), strips read-only nested metadata, and returns a mutation receipt (`dry_run`, `changed`, `diff`, `state`). |
| **`router_get_network_info`** | *(none)* | Queries `network?form=wan_ipv4_status`, `status?form=all`, `network?form=lan_ipv4`, and `dhcps?form=setting`, returning `{"wan": {...}, "lan": {...}}`. |
| **`router_reboot`** | `confirm: bool = False` | Reboots the physical router hardware. **Safety Guard**: Returns `error_code="SAFETY_ABORT"` unless `confirm=True` is explicitly passed by the caller. |
| **`router_raw_call`** | `module: str`<br/>`form: str`<br/>`operation: str = "read"`<br/>`params: dict \| None = None` | Executes any signed, AES-encrypted LuCI CGI request to `/cgi-bin/luci/;stok=<TOKEN>/admin/<module>?form=<form>` and returns the decrypted JSON dictionary. |
