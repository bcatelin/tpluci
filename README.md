# tpluci

**Pure-Python CLI, library, and Model Context Protocol (MCP) server for TP-Link Archer routers running encrypted OpenWrt/LuCI firmware.**

[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](https://opensource.org/licenses/MIT)
[![Startup: <50ms](https://img.shields.io/badge/startup-%3C50ms-brightgreen.svg)](#why-tpluci)

`tpluci` provides instantaneous (<50ms startup), browser-free inspection and remote control for TP-Link Archer routers that replace stock OpenWrt `ubus` with TP-Link's proprietary RSA + AES-128-CBC encrypted LuCI CGI dispatcher. It is engineered from the ground up for **dual ergonomics**: crisp, grep-friendly tables for human operators and deterministic JSON, self-healing error envelopes, and native MCP tools for AI agents.

---

## Why `tpluci`?

- **Pure Python, Zero Browser Overhead**: Implements TP-Link's custom 53-byte UTF-8 RSA PKCS#1 v1.5 chunking and ephemeral AES-128-CBC handshake natively in Python. No Playwright, Selenium, or 200 MB headless Chromium downloads.
- **Sub-50ms Startup & ~30ms Cached Calls**: Built on pure `click` and `httpx` with ephemeral `0600` session caching (`/tmp/tpluci-session-<uid>-<profile>.json`), avoiding redundant RSA handshakes and single-session lockouts on the router's embedded `uhttpd` server.
- **Safe Read-Modify-Write Mutations**: Changing Wi-Fi settings (`tpluci wifi set`) automatically reads the existing LuCI form state first, strips read-only nested metadata (`extinfo`), merges your changes, supports `--dry-run` simulation, and outputs a before/after diff receipt.
- **Agent-First Ergonomics**:
  - Position-agnostic global flags (`tpluci --json status` and `tpluci status --json` both work).
  - Token-efficient curated telemetry (`tpluci status` compresses 199 raw LuCI keys into ~120 tokens, while `--full` and `--field <KEY>` remain one flag away).
  - Structured error envelopes (`ok`, `error_code`, `message`, `hint`) with semantic exit codes (`0`–`5`) and non-interactive TTY safety guards.
- **Native FastMCP Server (`tpluci-mcp`)**: Exposes 7 structured tools over stdio JSON-RPC for Claude Desktop, Antigravity (`agy`), Cursor, and other MCP hosts.

---

## Supported Hardware Baseline

| Model | Hardware Revision | Firmware Architecture | Status |
| :--- | :--- | :--- | :--- |
| **TP-Link Archer AX23 (AX1800)** | V1 / V1.20 (EU / DE / US) | Encrypted OpenWrt / LuCI CGI (`/cgi-bin/luci/;stok=`) | **Verified Baseline** (30 endpoints tested) |
| **TP-Link Archer AX-Series / C-Series** | AX10, AX1500, AX20, AX21, AX50, AX55, C6U | Encrypted LuCI CGI (`tpEncrypt.js` RSA 53-byte + AES-128-CBC) | **Compatible Protocol** (endpoint subset may vary by model) |

> **Note:** Newer TP-Link routers that use the **TMP / TDDP binary protocol** or **HomeShield web-encrypted APIs** (without `/cgi-bin/luci/;stok=/login?form=keys`) are out of scope for `tpluci`. You can verify compatibility in one command with `tpluci config test`.

---

## Installation

### Recommended: Isolated CLI + MCP Tool (`uv`)

```bash
uv tool install .
```

This installs both `tpluci` and `tpluci-mcp` onto your `PATH` inside an isolated virtual environment.

### Editable Development Install (`uv`)

```bash
uv pip install -e .
```

### Alternative: `pipx`

```bash
pipx install .
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

---

## Documentation Guides

Comprehensive documentation is organized by role in [`docs/`](docs/):

1. **[User & AI Agent Guide (`docs/USER_GUIDE.md`)](docs/USER_GUIDE.md)**
   - Complete CLI command reference (`status`, `clients`, `wifi`, `wan`, `lan`, `system`, `call`, `config`, `logout`) with human and `--json` examples.
   - Position-agnostic global flags and single-field extraction (`--field`).
   - Wiring `tpluci-mcp` into Claude Desktop, Antigravity (`agy`), and Cursor, plus schemas for all 7 MCP tools.
2. **[Administrator Guide (`docs/ADMIN_GUIDE.md`)](docs/ADMIN_GUIDE.md)**
   - 4-Tier Credential Architecture (Environment variables, `.env`, OS Keyring, and `0600` headless config fallback).
   - Multi-router profile management (`--profile`, `TPLUCI_PROFILE`).
   - Ephemeral session caching, TP-Link `uhttpd` single-session concurrency, and 50ms rate limiting.
   - Unattended automation, TTY safety guards, exit codes (`0`–`5`), and troubleshooting runbook.
3. **[Developer & Contributor Guide (`docs/DEVELOPER_GUIDE.md`)](docs/DEVELOPER_GUIDE.md)**
   - Architecture & module map (`src/tpluci/`) and how the <50ms startup budget is maintained.
   - Deep-dive into TP-Link's cryptographic LuCI protocol (`/login?form=keys`, `/login?form=auth`, 53-byte UTF-8 RSA PKCS#1 v1.5 chunking, AES-128-CBC, and `seq + len(data)` signing).
   - Using `tpluci` as a Python library (`RouterClient`, `call()`, `read_modify_write()`).
   - Extending endpoints, running offline/live `pytest` suites, and pre-release sanitization checks.

---

## License

Released under the [MIT License](LICENSE).
