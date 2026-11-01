# tpluci

**Pure-Python CLI, library, and Model Context Protocol (MCP) server for TP-Link Archer routers running encrypted OpenWrt/LuCI firmware.**

[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](https://opensource.org/licenses/MIT)
[![Startup: <50ms](https://img.shields.io/badge/startup-%3C50ms-brightgreen.svg)](#why-tpluci)

`tpluci` provides instantaneous (<50ms startup), browser-free inspection and remote control for TP-Link Archer routers that replace stock OpenWrt `ubus` with TP-Link's proprietary RSA + AES-128-CBC encrypted LuCI CGI dispatcher. It is engineered from the ground up for **dual ergonomics**: crisp, grep-friendly tables for human operators and deterministic JSON, self-healing error envelopes, and native MCP tools for AI agents.

---

## Why `tpluci`?

- **Pure Python, Zero Browser Overhead**: Implements TP-Link's custom 53-byte UTF-8 RSA PKCS#1 v1.5 chunking and ephemeral AES-128-CBC handshake natively in Python. Supports direct multi-architecture satellite extender control (HTTPS Classic LuCI on RE705X, TDDP/GDPR on RE300). No Playwright, Selenium, or 200 MB headless Chromium downloads.
- **Sub-50ms Startup & ~30ms Cached Calls**: Built on pure `click` and `httpx` with ephemeral `0600` session caching (`/tmp/tpluci-session-<uid>-<profile>.json`), avoiding redundant RSA handshakes and single-session lockouts on the router's embedded `uhttpd` server.
- **EasyMesh Topology & Satellite Management (`tpluci mesh`)**: First-class monitoring and control of mesh networks—inspect mesh topology, query and rename satellite nodes, inspect backhaul link speeds and signal strength, trigger satellite firmware updates, and reboot or schedule extenders directly.
- **Tether-Grade Device Management (`tpluci clients`)**: Rich per-device client telemetry (real-time upload/download speeds, cumulative traffic, signal dBm, parent mesh node association), client renaming (`tpluci clients rename`), upload/download bandwidth throttling (`tpluci clients limit`), and safety-guarded client blocking/unblocking (`tpluci clients block` with current host self-lockout prevention).
- **Scheduled Maintenance & LED Night Mode (`tpluci system`)**: Configure automated weekly/monthly router reboot schedules (`tpluci system reboot-schedule`) and control router status LEDs and Night Mode time windows (`tpluci system led`).
- **Safe Read-Modify-Write Mutations**: Changing Wi-Fi or system settings automatically reads the existing LuCI form state first, strips read-only nested metadata (`extinfo`), merges your changes, supports `--dry-run` simulation, and outputs a before/after diff receipt.
- **Agent-First Ergonomics**:
  - Position-agnostic global flags (`tpluci --json status` and `tpluci status --json` both work).
  - Token-efficient curated telemetry (`tpluci status` compresses 199 raw LuCI keys into ~120 tokens, while `--full` and `--field <KEY>` remain one flag away).
  - Structured error envelopes (`ok`, `error_code`, `message`, `hint`) with semantic exit codes (`0`–`5`) and non-interactive TTY safety guards.
- **Native FastMCP Server (`tpluci-mcp`)**: Exposes 12 structured tools over stdio JSON-RPC for Claude Desktop, Antigravity (`agy`), Cursor, and other MCP hosts.

---

## Supported Hardware Baseline

| Model | Hardware Revision | Firmware Architecture | Status |
| :--- | :--- | :--- | :--- |
| **TP-Link Archer AX23 (AX1800)** | V1 / V1.20 (EU / DE / US) | Architecture 1: Encrypted OpenWrt / LuCI CGI (`/cgi-bin/luci/;stok=`) | **Verified Baseline** (45 verified operations) |
| **TP-Link RE705X (AX3000 Extender)** | V1 (EU / US) | Architecture 2: HTTPS Classic LuCI (PKCS#1 v1.5 RSA) | **Verified Satellite** (reboot, LEDs, power schedule) |
| **TP-Link RE300 (AC1200 Extender)** | V1 / V1.10 | Architecture 3: VxWorks / Mercury TDDP + GDPR AES/RSA | **Verified Satellite** (reboot, LEDs, reboot schedule) |
| **TP-Link Archer AX-Series / C-Series** | AX10, AX1500, AX20, AX21, AX50, AX55, C6U | Encrypted LuCI CGI (`tpEncrypt.js` RSA 53-byte + AES-128-CBC) | **Compatible Protocol** (endpoint subset may vary by model) |

> **Note:** Newer TP-Link routers that use the **TMP binary protocol** or **HomeShield web-encrypted APIs** (without `/cgi-bin/luci/;stok=/login?form=keys`) are out of scope for `tpluci`. To discover and verify endpoints on your hardware, consult the [Endpoint Discovery Guide](docs/ENDPOINT_DISCOVERY_GUIDE.md) or run `tpluci config test`.

---

## Installation & Updating

### Recommended: Isolated CLI + MCP Tool (`uv`)

Install `tpluci` and `tpluci-mcp` onto your global `PATH` inside an isolated virtual environment:

```bash
# From a local repository checkout:
uv tool install .

# Or directly from GitHub:
uv tool install git+https://github.com/bcatelin/tpluci.git
```

#### Updating with `uv`:

```bash
# If installed from a local checkout, re-install the latest code:
uv tool install --force .

# If installed directly from GitHub:
uv tool upgrade tpluci
```

### Editable Development Install (`uv`)

For local development where edits to `src/tpluci/` take effect immediately without reinstalling:

```bash
uv pip install -e .
```

To update dependencies when `pyproject.toml` changes:

```bash
uv sync
```

### Alternative: `pipx`

```bash
# Install:
pipx install .

# Update:
pipx install --force .

# Or if installed from GitHub:
pipx upgrade tpluci
```

---

## 60-Second Quickstart

### 1. Configure Credentials

Launch the interactive configuration wizard (stores your password in macOS Keychain, Linux SecretService, or Windows Credential Locker), or pass `ROUTER_PASSWORD` via `.env`:

```bash
tpluci config
```

Or configure non-interactively:

```bash
tpluci config add --name default --url http://192.168.7.250 --password "YourRouterPassword"
tpluci config test
```

### 2. Inspect Router Health (`tpluci status`)

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

### 3. Search Connected Clients (`tpluci clients`)

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

### 4. Inspect All 6 Wi-Fi Networks (`tpluci wifi list`)

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

### 5. Safely Toggle Guest Wi-Fi with `--dry-run`

```bash
$ tpluci wifi set guest-2g --enable --dry-run
[DRY-RUN] Simulated changes for Guest 2.4 GHz (guest-2g):
  enable: off -> on

(Dry-run: No changes were applied to the router)
```

Remove `--dry-run` to apply the change to the router, or append `--json` at any position for machine-readable output.

### 6. Inspect EasyMesh Topology & Extenders (`tpluci mesh`)

```bash
$ tpluci mesh list
NAME              MODEL    IP            MAC                BACKHAUL  SIGNAL    CLIENTS  STATUS
----------------  -------  ------------  -----------------  --------  --------  -------  ------
Satellite-Office  RE705X   192.168.7.2   AA-BB-CC-DD-EE-02  wireless  -58 dBm   2        online
Satellite-Hall    RE300    192.168.7.3   AA-BB-CC-DD-EE-03  wireless  -64 dBm   1        online
```

Print hierarchical topology mapping every client to its parent mesh node:

```bash
$ tpluci mesh topology
* Archer AX23 (192.168.7.250 / AA-BB-CC-DD-EE-00) [root]
  - NAS-Server (192.168.7.10) [wired]
  - Test-Laptop (192.168.7.101) [5G, -52 dBm]
  |-- Satellite-Office (192.168.7.2 / AA-BB-CC-DD-EE-02) [RE705X, 5G backhaul: 650 Mbps]
      - Work-Phone (192.168.7.105) [5G, -61 dBm]
      - Smart-Speaker (192.168.7.106) [2.4G, -55 dBm]
  |-- Satellite-Hall (192.168.7.3 / AA-BB-CC-DD-EE-03) [RE300, 5G backhaul: 300 Mbps]
      - Smart-Plug (192.168.7.103) [2.4G, -67 dBm]
```

### 7. Tether-Grade Device Telemetry & Bandwidth Limiting (`tpluci clients`)

Query enriched per-device metrics (real-time speeds, signal dBm, and mesh node):

```bash
$ tpluci clients --detailed
HOSTNAME     IP             MAC                NODE              SIGNAL   DOWN SPEED  UP SPEED  TRAFFIC
-----------  -------------  -----------------  ----------------  -------  ----------  --------  -------
NAS-Server   192.168.7.10   AA-BB-CC-DD-EE-10  Archer AX23       wired    0 Kbps      0 Kbps    4.2 GB
Smart-Plug   192.168.7.103  AA-BB-CC-DD-EE-03  Satellite-Hall    -67 dBm  12 Kbps     4 Kbps    120 MB
Test-Laptop  192.168.7.101  AA-BB-CC-DD-EE-01  Archer AX23       -52 dBm  450 Kbps    85 Kbps   1.8 GB
```

Rename a client or throttle bandwidth:

```bash
# Rename device alias
tpluci clients rename 192.168.7.101 "Workstation-Pro"

# Throttle download to 5 Mbps (5000 Kbps)
tpluci clients limit 192.168.7.103 --down 5000
```

### 8. Scheduled Reboot & LED Night Mode (`tpluci system`)

```bash
# Schedule weekly Tuesday reboot at 04:00 AM
tpluci system reboot-schedule --enable --cycle week --day Tues --time 04:00

# Enable LED Night Mode (turn off LEDs between 23:00 and 07:00)
tpluci system led --night-mode on --start 23:00 --end 07:00
```

---

## Documentation Guides

Comprehensive documentation is organized by role in [`docs/`](docs/):

1. **[User & AI Agent Guide (`docs/USER_GUIDE.md`)](docs/USER_GUIDE.md)**
   - Complete CLI command reference (`status`, `clients`, `mesh`, `wifi`, `wan`, `lan`, `system`, `call`, `config`, `logout`) with human and `--json` examples.
   - Position-agnostic global flags and single-field extraction (`--field`).
   - Wiring `tpluci-mcp` into Claude Desktop, Antigravity (`agy`), and Cursor, plus schemas for all 12 MCP tools.
2. **[Administrator Guide (`docs/ADMIN_GUIDE.md`)](docs/ADMIN_GUIDE.md)**
   - 4-Tier Credential Architecture (Environment variables, `.env`, OS Keyring, and `0600` headless config fallback).
   - Multi-router profile management (`--profile`, `TPLUCI_PROFILE`).
   - Satellite credential resolution (`--satellite-user`/`--satellite-password`, `TPLUCI_SATELLITE_*`, named satellite profiles, TP-Link Cloud ID binding notes).
   - `HOST` self-lockout protection on client blocking.
   - Ephemeral session caching, TP-Link `uhttpd` single-session concurrency, and 50ms rate limiting.
   - Unattended automation, TTY safety guards, exit codes (`0`–`5`), and troubleshooting runbook.
3. **[Developer & Contributor Guide (`docs/DEVELOPER_GUIDE.md`)](docs/DEVELOPER_GUIDE.md)**
   - Architecture & module map (`src/tpluci/`, including `satellites.py` adapters) and how the <50ms startup budget is maintained.
   - Deep-dive into TP-Link's cryptographic LuCI protocol (`/login?form=keys`, `/login?form=auth`, 53-byte UTF-8 RSA PKCS#1 v1.5 chunking, AES-128-CBC, and `seq + len(data)` signing).
   - Direct satellite protocols (Architecture 2 HTTPS Classic LuCI vs Architecture 3 TDDP GDPR).
   - Using `tpluci` as a Python library (`RouterClient`, `call()`, `read_modify_write()`, `connect_satellite()`).
   - Catalog of 45 verified endpoints/operations, running offline/live `pytest` suites, and pre-release sanitization checks.
4. **[Endpoint Discovery & Reverse-Engineering Guide (`docs/ENDPOINT_DISCOVERY_GUIDE.md`)](docs/ENDPOINT_DISCOVERY_GUIDE.md)**
   - Static frontend JS reverse-engineering methodology without brute-forcing or browser automation.
   - Deep inspection across all three firmware architectures (Encrypted LuCI SPA, HTTPS Classic LuCI, VxWorks/Mercury TDDP).
   - Custom `operation` verbs, route manifests (`models.json`/`modules.json`), and payload encryption schemas.

---

## License

Released under the [MIT License](LICENSE).
