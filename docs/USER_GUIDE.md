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
| `-v`, `--version` | — | — | Print `tpluci 0.2.0` and exit. |
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

### 2.2 `tpluci clients` — Connected Device Inventory, Telemetry & Tether Controls

`tpluci` provides full Tether-grade connected client management. Using an intelligent `ClientsGroup` parser, `tpluci clients` remains 100% backward-compatible with v0.1.0 (auto-routing queries to `list`) while enabling device renaming, bandwidth speed-limiting, and safety-guarded access control blocking.

```text
Usage: tpluci clients [OPTIONS] [list|rename|limit|block|unblock] [ARGS]...
```

#### 2.2.1 `tpluci clients` / `tpluci clients list` — Device Inventory & Search

```text
Usage: tpluci clients list [OPTIONS] [QUERY]

Options:
  --detailed                                Include mesh node, throughput, signal, and traffic telemetry
  --node TEXT                               Filter clients by mesh node name or MAC
  --wireless-only                           List only wireless clients
  --wired-only                              List only wired clients
  --band [2g|5g]                            Filter by Wi-Fi band
  --sort [hostname|ip|band|mac|medium|signal|traffic|node]
                                            Sort output column (default: hostname)
```

##### Default Client Table

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

##### Enriched Telemetry with Mesh Association (`--detailed`)

Passing `--detailed` queries the hardware game accelerator (`smart_network?form=game_accelerator&operation=loadDevice`) and EasyMesh topology to resolve each client's parent node, live throughput, RSSI signal in dBm, and total cumulative traffic:

```bash
$ tpluci clients --detailed
HOSTNAME     IP             MAC                NODE              SIGNAL   DOWN SPEED  UP SPEED  TRAFFIC
-----------  -------------  -----------------  ----------------  -------  ----------  --------  -------
NAS-Server   192.168.7.10   AA-BB-CC-DD-EE-10  Archer AX23       wired    0 Kbps      0 Kbps    4.2 GB
Smart-Plug   192.168.7.103  AA-BB-CC-DD-EE-03  Satellite-Hall    -67 dBm  12 Kbps     4 Kbps    120 MB
Test-Laptop  192.168.7.101  AA-BB-CC-DD-EE-01  Archer AX23       -52 dBm  450 Kbps    85 Kbps   1.8 GB
Test-Phone   192.168.7.102  AA-BB-CC-DD-EE-02  Satellite-Office  -61 dBm  85 Kbps     15 Kbps   950 MB

Total: 4 clients (3 wireless, 1 wired)
```

##### Filter by Substring, Parent Node, or Band

```bash
# Substring search across hostname, IP, MAC, or node
tpluci clients laptop

# Filter to clients associated with a specific satellite
tpluci clients --node Satellite-Office --detailed

# Natural IPv4 sorting in JSON mode
tpluci clients --wireless-only --sort ip --json
```

#### 2.2.2 `tpluci clients rename` — Custom Device Aliases

Assigns a custom display name (1–64 characters) to any connected device via `traffic?form=dev_name`:

```bash
# Target by IP, MAC, or current hostname
$ tpluci clients rename 192.168.7.101 "Workstation-Pro" --dry-run
[DRY-RUN] Simulated rename for Test-Laptop (AA-BB-CC-DD-EE-01):
  name: Test-Laptop -> Workstation-Pro

# Apply change to router
$ tpluci clients rename 192.168.7.101 "Workstation-Pro"
Renamed client AA-BB-CC-DD-EE-01 (Test-Laptop) to 'Workstation-Pro'.
```

#### 2.2.3 `tpluci clients limit` — Bandwidth Throttling

Controls upload and download speed limits (1–1,024,000 Kbps) per client via `smart_network?form=client_speed_limit`:

```bash
# Throttle download to 5 Mbps (5000 Kbps)
$ tpluci clients limit 192.168.7.103 --down 5000
Speed limit applied to AA-BB-CC-DD-EE-03: download limit = 5000 Kbps, upload limit = unlimited.

# Throttle both upload and download with --json output
$ tpluci clients limit AA-BB-CC-DD-EE-03 --down 10000 --up 2000 --json
{
  "ok": true,
  "dry_run": false,
  "target": "AA-BB-CC-DD-EE-03",
  "mac": "AA-BB-CC-DD-EE-03",
  "speed_limit": {
    "enabled": true,
    "download_kbps": 10000,
    "upload_kbps": 2000
  }
}

# Remove speed limits
$ tpluci clients limit 192.168.7.103 --disable
Speed limit disabled for AA-BB-CC-DD-EE-03.
```

#### 2.2.4 `tpluci clients block` & `unblock` — Safety-Guarded Access Control

Blocks or unblocks network access for devices using TP-Link's Access Control blacklist (`access_control?form=black_list`):

- **Self-Lockout Protection (`HOST` Guard):** If `<TARGET>` resolves to the device making the API request (`host == "HOST"` in `access_control?form=black_devices` or matching `host_mac` in `access_control?form=enable`), `tpluci` **immediately aborts** with exit code `5` (`SafetyAbortError`), preventing accidental self-lockout from the router.
- **Safety Confirmation:** `block` requires `--confirm` in non-interactive scripts; interactive shells will prompt for confirmation.

```bash
# Block an unauthorized device
$ tpluci clients block AA-BB-CC-DD-EE-99 --confirm
Client 'Unknown-Device' (AA-BB-CC-DD-EE-99) added to access control blacklist.

# Attempting to block the managing host device triggers safety abort:
$ tpluci clients block 192.168.7.101 --confirm
Error: Refusing to block the current host device (HOST) to prevent router lockout.
(Exit code 5)

# Unblock a previously blacklisted device
$ tpluci clients unblock AA-BB-CC-DD-EE-99
Client 'AA-BB-CC-DD-EE-99' removed from access control blacklist.
```

---

### 2.3 `tpluci mesh` — EasyMesh Topology & Satellite Extender Management

`tpluci` provides comprehensive EasyMesh control. Operations are divided into:
1. **Router-Managed Mesh APIs:** Communicating directly with the main Archer router to inspect topology, node telemetry, firmware status, and link/unlink satellites.
2. **Direct Satellite Extender Protocols:** Communicating directly with range extenders (e.g. `RE705X` via HTTPS LuCI, `RE300` via TDDP) for satellite reboots, status LEDs, and reboot/power schedules.

```text
Usage: tpluci mesh [OPTIONS] COMMAND [ARGS]...

Commands:
  list             List all connected EasyMesh satellite nodes (alias: status)
  topology         Display full hierarchical mesh tree topology
  get              Inspect detailed metrics and backhaul speeds for a satellite
  set              Rename or update location of a mesh satellite node
  firmware         Inspect satellite firmware versions or trigger updates
  remove           Unlink and remove a mesh satellite from the network
  reboot           Reboot an individual mesh satellite extender (direct connection)
  led              Inspect or configure status LED / Night Mode on a satellite
  reboot-schedule  Inspect or configure reboot or power schedule on a satellite
```

#### 2.3.1 `tpluci mesh list` (alias: `tpluci mesh status`)

Queries `easymesh_network?form=mesh_sclient_list_all` and displays satellite health, model, location, backhaul type (wired vs wireless), signal strength in dBm (`-254` normalized to `"N/A"` for wired connections), and connected client counts:

```bash
$ tpluci mesh list
NAME              MODEL    IP            MAC                LOCATION  BACKHAUL  SIGNAL    CLIENTS  STATUS
----------------  -------  ------------  -----------------  --------  --------  --------  -------  ------
Satellite-Office  RE705X   192.168.7.2   AA-BB-CC-DD-EE-02  office    wireless  -58 dBm   2        online
Satellite-Hall    RE300    192.168.7.3   AA-BB-CC-DD-EE-03  hallway   wireless  -64 dBm   1        online

Total: 2 EasyMesh satellite(s)
```

#### 2.3.2 `tpluci mesh topology`

Queries `easymesh_network?form=mesh_topology` to construct the entire EasyMesh tree:

```bash
$ tpluci mesh topology
Root: Archer AX23 (Archer AX23) — IP: 192.168.7.250, MAC: AA-BB-CC-DD-EE-00
  Connected Clients:
    * NAS-Server (192.168.7.10, AA-BB-CC-DD-EE-10) [wire]
    * Test-Laptop (192.168.7.101, AA-BB-CC-DD-EE-01) [5G] Signal: -52 dBm TX/RX: 866/866 Mbps

Satellite: Satellite-Office (RE705X) — IP: 192.168.7.2, MAC: AA-BB-CC-DD-EE-02
  Location: office | Backhaul: wireless | Signal: -58 dBm
  Connected Clients:
    * Work-Phone (192.168.7.105, AA-BB-CC-DD-EE-05) [5G] Signal: -61 dBm TX/RX: 650/650 Mbps
    * Smart-Speaker (192.168.7.106, AA-BB-CC-DD-EE-06) [2.4G] Signal: -55 dBm TX/RX: 144/144 Mbps

Satellite: Satellite-Hall (RE300) — IP: 192.168.7.3, MAC: AA-BB-CC-DD-EE-03
  Location: hallway | Backhaul: wireless | Signal: -64 dBm
  Connected Clients:
    * Smart-Plug (192.168.7.103, AA-BB-CC-DD-EE-03) [2.4G] Signal: -67 dBm TX/RX: 72/72 Mbps
```

#### 2.3.3 `tpluci mesh get <NODE>`

Resolves `<NODE>` by name, IP, or MAC and queries `easymesh_network?form=mesh_sclient_detail`. Backhaul speeds are automatically normalized from Kbps to Mbps:

```bash
$ tpluci mesh get Satellite-Office
Node Name:            Satellite-Office
Model:                RE705X
IP Address:           192.168.7.2
MAC Address:          AA-BB-CC-DD-EE-02
Location:             office
Firmware Version:     1.0.8 Build 20230510 Rel. 61124
Parent Router MAC:    AA-BB-CC-DD-EE-00
Backhaul Connection:  wireless
Link Speed 2.4 GHz:   288 Mbps
Link Speed 5 GHz:     650 Mbps
Signal 2.4 GHz:       -54 dBm
Signal 5 GHz:         -58 dBm
Connected Clients:    2

Connected Clients:
CLIENT NAME    IP             MAC                MEDIUM  SIGNAL   TX/RX (Mbps)
-------------  -------------  -----------------  ------  -------  ------------
Work-Phone     192.168.7.105  AA-BB-CC-DD-EE-05  5G      -61 dBm  650/650     
Smart-Speaker  192.168.7.106  AA-BB-CC-DD-EE-06  2.4G    -55 dBm  144/144     
```

#### 2.3.4 `tpluci mesh set <NODE>` — Node Renaming & Location Update

Modifies a satellite's metadata using the verified minimal 3-parameter payload contract (`mac`, `name`, `location`):

```bash
$ tpluci mesh set Satellite-Office --name "Office-AP" --location "second_floor" --dry-run
[DRY-RUN] Simulated changes for mesh satellite AA-BB-CC-DD-EE-02:
  name: Satellite-Office -> Office-AP
  location: office -> second_floor

(Dry-run: No changes were applied to the router)
```

#### 2.3.5 `tpluci mesh firmware` & `tpluci mesh remove`

```bash
# Check satellite firmware versions and updates
$ tpluci mesh firmware

# Trigger satellite firmware upgrade (requires --confirm)
$ tpluci mesh firmware --upgrade Satellite-Office --confirm

# Unlink satellite from EasyMesh network (requires --confirm)
$ tpluci mesh remove Satellite-Hall --confirm
```

#### 2.3.6 Direct Satellite Control (`reboot`, `led`, `reboot-schedule`)

`tpluci` connects directly to satellite extenders using automatic protocol fingerprinting:
- **Architecture 2 (`RE705X`)**: Communicates over HTTPS Classic LuCI with PKCS#1 v1.5 RSA encryption and handles TP-Link Cloud ID login with session conflict resolution.
- **Architecture 3 (`RE300`)**: Communicates over HTTP using TDDP with mandatory `Referer` headers, XOR challenge authentication, and GDPR AES-128-CBC + SHA-256 payload signing.

##### Direct Satellite Reboot

```bash
# Simulate reboot without issuing hardware command
$ tpluci mesh reboot Satellite-Office --confirm --dry-run
[DRY-RUN] Simulated reboot for satellite Office-AP (192.168.7.2).

# Execute real satellite reboot
$ tpluci mesh reboot Satellite-Office --confirm
Reboot command sent to satellite 'Office-AP' (192.168.7.2).
```

##### Satellite Status LED & Night Mode

```bash
# Query current satellite LED status
$ tpluci mesh led Satellite-Office
Node:              Office-AP (192.168.7.2)
Status LED:        ON
Night Mode:        ON
Night Mode Start:  23:00
Night Mode End:    07:00

# Configure satellite LED Night Mode with --dry-run
$ tpluci mesh led Satellite-Office --night-mode on --start 22:30 --end 06:30 --dry-run
[DRY-RUN] Updated LED settings for satellite 'Office-AP' (192.168.7.2):
  time_start: 23:00 -> 22:30
  time_end: 07:00 -> 06:30
```

##### Satellite Reboot / Power Schedule

```bash
# Query satellite reboot schedule
$ tpluci mesh reboot-schedule Satellite-Hall
Node:             Satellite-Hall (192.168.7.3)
Schedule Type:    reboot_schedule
Enabled:          ON
Cycle:            week
Day:              Sun
Time:             03:30

# Configure automated weekly satellite reboot
$ tpluci mesh reboot-schedule Satellite-Hall --enable --cycle week --day Sun --time 03:30
```

---

### 2.4 `tpluci wifi` — Main, Guest & IoT Wireless Control

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

### 2.5 `tpluci wan` & `tpluci lan` — Network & DHCP Inspection

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

### 2.6 `tpluci system` — Hardware Info, Clock, Scheduled Reboot & LEDs

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

#### `tpluci system reboot-schedule` — Scheduled Automated Reboots

Inspects or configures the router's hardware reboot schedule via `reboot?form=set`:

```text
Usage: tpluci system reboot-schedule [OPTIONS]

Options:
  --enable / --disable    Enable or disable scheduled automatic reboot
  --cycle [day|week|month]
                          Reboot frequency cycle
  --day TEXT              Day of week (Mon..Sun) or day of month (1..28)
  --time TEXT             Scheduled reboot time in 24h format (HH:MM)
  --dry-run               Simulate schedule changes without writing to router
```

> **Weekday Normalization:** TP-Link firmware expects `"Mon"`, `"Tues"`, `"Wed"`, `"Thur"`, `"Fri"`, `"Sat"`, `"Sun"`. `tpluci` automatically normalizes common human variations (`"Tuesday"`, `"tue"`, `"thursday"`, `"thu"`).

```bash
# Query active reboot schedule
$ tpluci system reboot-schedule
Scheduled Reboot:  Enabled
Cycle:             week
Day:               Tues
Time:              04:00

# Configure weekly Tuesday reboot at 04:00 AM with --dry-run
$ tpluci system reboot-schedule --enable --cycle week --day tuesday --time 04:00 --dry-run
[DRY-RUN] Simulated reboot schedule updates:
  enable: off -> on
  cycle: day -> week
  day: Mon -> Tues
  time: 03:00 -> 04:00

(Dry-run: No changes were applied to the router)
```

#### `tpluci system led` — Status LEDs & Night Mode Schedule

Inspects or configures the router's physical status LEDs (`ledgeneral?form=setting`) and LED Night Mode schedule (`ledpm?form=setting`):

```text
Usage: tpluci system led [OPTIONS]

Options:
  --on / --off            Turn router status LEDs on or off
  --night-mode [on|off]   Enable or disable Night Mode schedule
  --start TEXT            Night mode start time in 24h format (HH:MM)
  --end TEXT              Night mode end time in 24h format (HH:MM)
  --dry-run               Simulate LED changes without writing to router
```

```bash
# Query status LEDs and Night Mode
$ tpluci system led
Status LED:        ON
Night Mode:        ON
Night Mode Start:  23:00
Night Mode End:    07:00

# Turn off LEDs immediately
$ tpluci system led --off
Updated LED settings. Status LEDs are now OFF.

# Configure Night Mode schedule (turn off LEDs from 23:00 to 07:00)
$ tpluci system led --night-mode on --start 23:00 --end 07:00
Updated LED settings:
  enable: on
  time_start: 23:00
  time_end: 07:00
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

### 2.7 `tpluci call` — Endpoint Registry & Raw LuCI Escape Hatch

Provides direct access to all 45 verified LuCI endpoints and arbitrary `<module>?form=<form>` testing.

#### List All 45 Verified Endpoints (`tpluci call --list`)

```bash
$ tpluci call --list
CATEGORY  MODULE            FORM                          DEFAULT OP      DESCRIPTION                                                    
--------  ----------------  ----------------------------  --------------  ---------------------------------------------------------------
System    status            all                           read            Master endpoint returning 199 telemetry & status keys          
System    status            internet                      read            Quick WAN internet connection status                           
System    status            menu_status                   read            Menu patrol status flag                                        
System    status            cloud_login_window_pop        read            Cloud binding status and popup counts                          
System    system            sysmode                       read            Router operation mode (Router / Bridge)                        
System    cloud_account     get_deviceInfo                read            Device model string (Archer AX23)                              
System    cloud_account     check_upgrade                 read            Cloud firmware upgrade notification                            
System    firmware          upgrade                       read            Firmware version, hardware revision, build date                
System    firmware          auto_upgrade                  read            Auto firmware update settings                                  
System    firmware          slave_cmd                     slave_get_info  Mesh satellite firmware versions and update check              
System    time              settings                      read            System clock, NTP servers, and timezone                        
System    reboot            set                           read            Router scheduled reboot configuration                          
System    ledgeneral        setting                       read            Master router LED status and switch                            
System    ledpm             setting                       read            Router LED Night Mode schedule settings                        
Network   network           wan_ipv4_status               read            WAN IPv4 connection status and protocol                        
Network   network           wan_ipv6_status               read            WAN IPv6 status                                                
Network   network           lan_ipv4                      read            LAN IP address, subnet mask, and MAC address                   
Network   network           lan_agg                       read            Link Aggregation (LACP) status and port assignments            
Network   dhcps             setting                       read            DHCP Server status, pool bounds, and lease time                
Network   iptv              setting                       read            IPTV / VLAN port mappings and IGMP snooping                    
Network   ddns              provider                      read            Dynamic DNS provider status                                    
Wireless  wireless          wireless_2g                   read            Main 2.4 GHz Wi-Fi radio configuration                         
Wireless  wireless          wireless_5g                   read            Main 5 GHz Wi-Fi radio configuration                           
Wireless  wireless          guest_2g                      read            Guest 2.4 GHz Wi-Fi radio configuration                        
Wireless  wireless          guest_5g                      read            Guest 5 GHz Wi-Fi radio configuration                          
Wireless  wireless          iot_2g                        read            IoT 2.4 GHz Wi-Fi radio configuration                          
Wireless  wireless          iot_5g                        read            IoT 5 GHz Wi-Fi radio configuration                            
Wireless  wireless          smart_connect                 read            Smart Connect band-steering setting                            
Wireless  easymesh_network  mesh_sclient_list_all         read            EasyMesh nodes and clients list                                
Wireless  easymesh_network  mesh_topology                 read            Full EasyMesh tree topology and per-node client lists          
Wireless  easymesh_network  mesh_sclient_detail           read            Single EasyMesh node detail, backhaul speeds, and clients      
Wireless  easymesh_network  available_mesh_device_manage  link            Link or unlink EasyMesh candidate satellites                   
Wireless  easymesh_network  available_mesh_device_list    read            List nearby unconfigured EasyMesh candidate devices            
Wireless  easymesh          easymesh_enable               read            Master EasyMesh toggle and configuration                       
Wireless  easymesh          search_slave                  write           Trigger background search for new EasyMesh slave devices       
Network   smart_network     game_accelerator              loadDevice      Rich client telemetry, real-time speeds, and traffic usage     
Network   traffic           dev_name                      write           Set custom display name (alias) for connected client           
Network   smart_network     client_speed_limit            read_max        Client download/upload bandwidth throttle limits               
Security  nat               dmz                           read            DMZ host status and IP                                         
Security  nat               alg                           read            Application Layer Gateway (ALG) passthrough toggles            
Security  access_control    enable                        read            Access Control engine toggle and host MAC                      
Security  access_control    mode                          read            Access Control mode (black / white list)                       
Security  access_control    black_devices                 load            Online devices list with host identification for access control
Security  access_control    black_list                    load            Access control blacklist rules table                           
Security  qos               settings                      read            Quality of Service bandwidth limits and prioritization         
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

### 2.8 `tpluci config` & `tpluci logout` — Credentials & Session Management

```bash
# Launch interactive profile wizard (TTY only)
$ tpluci config

# Add a named profile with secure OS keyring storage
$ tpluci config add --name home --url http://192.168.7.250 --password "MySecret"

# List configured profiles (passwords masked)
$ tpluci config list

# Test authentication with target router
$ tpluci config test --profile home

# Clear local /tmp session cache
$ tpluci logout
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

### 3.2 Exposed MCP Tools Reference (12 Tools)

All 12 MCP tools catch `TpluciError` exceptions and return structured JSON dictionaries (`{"ok": false, "error_code": "...", "message": "...", "hint": "..."}`) so LLM agents can self-correct without crashing the MCP server.

| Tool Name | Parameters & Defaults | Return Payload & Behavior |
| :--- | :--- | :--- |
| **`router_get_status`** | `full: bool = False`<br/>`field: str \| None = None` | By default returns the ~120-token curated status summary (`model`, `cpu_usage`, `mem_usage`, `uptime_seconds`, `internet_status`, `wan_ip`, `lan_ip`, `wifi`, `clients_count`). If `field` is provided, returns `{field: value}`. If `full=True`, returns all 199 raw keys from `status?form=all`. |
| **`router_list_clients`** | `query: str \| None = None`<br/>`medium: str = "all"`<br/>`node: str \| None = None`<br/>`detailed: bool = False` | Returns a list of connected client dictionaries (`hostname`, `ipaddr`, `macaddr`, `medium`, `band`, and if `detailed=True`: `node`, `signal_dbm`, `down_speed_kbps`, `up_speed_kbps`, `traffic_bytes`). Supports substring filtering by query or parent mesh node. |
| **`router_get_wifi`** | `radio: str = "all"` | When `radio="all"`, returns the 6-element summary list across `2g`, `5g`, `guest-2g`, `guest-5g`, `iot-2g`, and `iot-5g`. When a specific radio is passed, calls `wireless?form=<form>` (`operation=read`) and returns full radio parameters. |
| **`router_set_wifi`** | `radio: str`<br/>`enable: bool \| None = None`<br/>`ssid: str \| None = None`<br/>`password: str \| None = None`<br/>`hidden: bool \| None = None`<br/>`dry_run: bool = False` | Performs a safe Read-Modify-Write on the target radio (`2g`, `5g`, `guest-2g`, `guest-5g`, `iot-2g`, `iot-5g`). Validates WPA password length (8–63 chars), strips read-only nested metadata, and returns a mutation receipt (`dry_run`, `changed`, `diff`, `state`). |
| **`router_get_network_info`** | *(none)* | Queries `network?form=wan_ipv4_status`, `status?form=all`, `network?form=lan_ipv4`, and `dhcps?form=setting`, returning `{"wan": {...}, "lan": {...}}`. |
| **`router_manage_client`** | `target: str`<br/>`alias: str \| None = None`<br/>`download_limit_kbps: int \| None = None`<br/>`upload_limit_kbps: int \| None = None`<br/>`disable_limit: bool = False`<br/>`dry_run: bool = False` | Renames a client or configures download/upload speed limits (1–1,024,000 Kbps) using `traffic?form=dev_name` and `smart_network?form=client_speed_limit`. |
| **`router_get_mesh`** | `node: str \| None = None`<br/>`include_firmware: bool = False` | Returns complete EasyMesh topology tree, list of satellites, and connected clients. If `node` is provided, returns detailed node telemetry and backhaul link speeds. |
| **`router_set_mesh_node`** | `node: str`<br/>`name: str \| None = None`<br/>`location: str \| None = None`<br/>`dry_run: bool = False` | Renames an EasyMesh satellite or updates its location using `easymesh_network?form=mesh_sclient_detail` with a minimal 3-parameter payload. |
| **`router_reboot_mesh_node`** | `node: str`<br/>`confirm: bool = False`<br/>`dry_run: bool = False` | Reboots a specific satellite extender directly via device adapter (HTTPS LuCI or TDDP). **Safety Guard**: Strictly requires `confirm=True`. |
| **`router_system_settings`** | `reboot_schedule_enable: bool \| None = None`<br/>`reboot_cycle: str \| None = None`<br/>`reboot_day: str \| None = None`<br/>`reboot_time: str \| None = None`<br/>`led_enable: bool \| None = None`<br/>`night_mode_enable: bool \| None = None`<br/>`night_start: str \| None = None`<br/>`night_end: str \| None = None`<br/>`dry_run: bool = False` | Reads or updates router scheduled reboot and LED / Night Mode configuration. |
| **`router_reboot`** | `confirm: bool = False` | Reboots the physical router hardware. **Safety Guard**: Returns `error_code="SAFETY_ABORT"` unless `confirm=True` is explicitly passed by the caller. |
| **`router_raw_call`** | `module: str`<br/>`form: str`<br/>`operation: str = "read"`<br/>`params: dict \| None = None` | Executes any signed, AES-encrypted LuCI CGI request to `/cgi-bin/luci/;stok=<TOKEN>/admin/<module>?form=<form>` and returns the decrypted JSON dictionary. |
