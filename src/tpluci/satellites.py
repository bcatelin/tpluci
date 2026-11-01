"""Direct Mesh Satellite Protocol Adapters for TP-Link range extenders.

Supports:
- Architecture 2: HTTPS Classic LuCI with PKCS#1 v1.5 RSA encryption (e.g. RE705X)
- Architecture 3: MERProxy / TDDP with GDPR AES-128-CBC + RSA-signed sessions (e.g. RE300)
"""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import quote

import httpx

from tpluci.crypto import (
    DEFAULT_DICT,
    DEFAULT_KEY,
    aes_decrypt,
    aes_encrypt,
    generate_aes_key_iv,
    rsa_encrypt_pkcs1_v15,
    sha256_hash,
    tp_xor_encrypt,
)
from tpluci.exceptions import AuthError, LuciApiError
from tpluci.models import normalize_weekday

# Exact TDDP DATA_ID constants
DEVICE_DATA_ID = 0
SYSTEM_DATA_ID = 1
SNTPC_CONFIG_DATA_ID = 28
SNTPC_TIME_DATA_ID = 29
CLOUD_CURRENT_USER_CFG_DATA_ID = 68
LED_DATA_ID = 112
NIGHT_MODE_DATA_ID = 113
SCHEDULE_REBOOT_DATA_ID = 114
POWER_SCHEDULE_DATA_ID = 115

# TDDP Opcodes
TDDP_INSTRUCT = 0
TDDP_WRITE = 1
TDDP_READ = 2
TDDP_RESET = 5
TDDP_REBOOT = 6
TDDP_AUTH = 7
TDDP_LOGOUT = 11
HTTP_OP_CLOUD_LOGIN = 15
HTTP_OP_GDPRCFG = 16
CLOUD_TMP = 17


def _clean_ip(ip: str) -> str:
    """Extract clean IP or host string from URL or host string."""
    clean = ip.strip()
    if clean.startswith("https://"):
        clean = clean[len("https://") :]
    elif clean.startswith("http://"):
        clean = clean[len("http://") :]
    return clean.split("/")[0].split(":")[0]


class HttpsLuciSatelliteClient:
    """Protocol adapter for Architecture 2 satellite extenders (e.g. RE705X).

    Communicates over HTTPS (self-signed cert) using Classic LuCI form endpoints
    and PKCS#1 v1.5 RSA password encryption.
    """

    def __init__(
        self,
        ip: str,
        password: str,
        username: str = "",
        timeout: float = 5.0,
        verify: bool = False,
    ) -> None:
        self.ip = _clean_ip(ip)
        self.password = password
        self.username = username.strip()
        self.timeout = timeout
        self.verify = verify
        self.stok: str | None = None
        self.cloud_ever_login: bool = False
        self._client = httpx.Client(
            base_url=f"https://{self.ip}",
            verify=self.verify,
            timeout=self.timeout,
            headers={
                "Referer": f"https://{self.ip}/webpages/login.html",
                "User-Agent": "tpluci",
            },
        )

    def __enter__(self) -> HttpsLuciSatelliteClient:
        if not self.stok:
            self.login()
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        self.logout()

    def login(self) -> None:
        """Execute pre-flight check, RSA key fetch, PKCS#1 v1.5 encryption, and login."""
        # 1. Pre-flight check: inspect cloud_ever_login
        try:
            r_pf = self._client.post(
                "/cgi-bin/luci/;stok=/login?form=check_factory_default",
                data={"operation": "read"},
            )
            if r_pf.status_code == 200:
                data = r_pf.json().get("data", {})
                self.cloud_ever_login = bool(data.get("cloud_ever_login", False))
        except Exception:
            self.cloud_ever_login = False

        # 2. Fetch RSA public key
        r_keys = self._client.post(
            "/cgi-bin/luci/;stok=/login?form=login",
            data={"operation": "read"},
        )
        if r_keys.status_code != 200:
            raise LuciApiError(
                message=f"Failed to fetch RSA key from satellite at {self.ip} (HTTP {r_keys.status_code}).",
                error_code="SATELLITE_KEY_FETCH_FAILED",
            )
        try:
            key_data = r_keys.json().get("data", {})
            nn_hex, ee_hex = key_data["password"][0], key_data["password"][1]
        except Exception as e:
            raise LuciApiError(
                message=f"Malformed RSA key response from satellite at {self.ip}: {e}",
                error_code="SATELLITE_KEY_FETCH_FAILED",
            )

        # 3. Encrypt password using PKCS#1 v1.5 random padding
        enc_password = rsa_encrypt_pkcs1_v15(self.password, nn_hex, ee_hex, chunk_size=53)

        # 4. Submit login request
        login_success = False
        if self.username or (self.cloud_ever_login and self.username):
            payload = {
                "operation": "login",
                "username": self.username,
                "password": enc_password,
            }
            r_login = self._client.post(
                "/cgi-bin/luci/;stok=/login?form=cloud_login",
                data=payload,
            )
            resp_data = r_login.json() if r_login.status_code == 200 else {}
            if resp_data.get("errorcode") == "user conflict" or "user conflict" in str(resp_data):
                payload["confirm"] = "true"
                r_login = self._client.post(
                    "/cgi-bin/luci/;stok=/login?form=cloud_login",
                    data=payload,
                )
                resp_data = r_login.json() if r_login.status_code == 200 else {}
            if resp_data.get("success") and resp_data.get("data", {}).get("stok"):
                self.stok = resp_data["data"]["stok"]
                login_success = True
        else:
            payload = {
                "operation": "login",
                "password": enc_password,
            }
            r_login = self._client.post(
                "/cgi-bin/luci/;stok=/login?form=login",
                data=payload,
            )
            resp_data = r_login.json() if r_login.status_code == 200 else {}
            if resp_data.get("success") and resp_data.get("data", {}).get("stok"):
                self.stok = resp_data["data"]["stok"]
                login_success = True

        if not login_success:
            if self.cloud_ever_login:
                raise AuthError(
                    message=f"Failed to authenticate with satellite at {self.ip} (extender is bound to TP-Link Cloud ID).",
                    error_code="SATELLITE_AUTH_FAILED",
                    hint=(
                        "Extender has cloud_ever_login: true. Pass --satellite-user <email> "
                        "--satellite-password <pwd> or configure a profile: "
                        f"tpluci config add --name re705x --username <email> --url https://{self.ip}"
                    ),
                )
            else:
                raise AuthError(
                    message=f"Failed to authenticate with satellite at {self.ip}.",
                    error_code="SATELLITE_AUTH_FAILED",
                    hint="Check extender password or supply --satellite-password.",
                )

    def call(
        self,
        module: str,
        form: str,
        operation: str = "read",
        params: dict[str, Any] | None = None,
    ) -> Any:
        """Call an authenticated LuCI endpoint on the satellite."""
        if not self.stok:
            self.login()

        url = f"/cgi-bin/luci/;stok={self.stok}/admin/{module}?form={form}"
        data = {"operation": operation}
        if params:
            data.update(params)

        resp = self._client.post(url, data=data)
        if resp.status_code == 403:
            # Re-login once on expired session
            self.login()
            url = f"/cgi-bin/luci/;stok={self.stok}/admin/{module}?form={form}"
            resp = self._client.post(url, data=data)

        try:
            res_json = resp.json()
        except Exception:
            raise LuciApiError(
                message=f"Satellite response is not valid JSON (HTTP {resp.status_code}): {resp.text[:200]}",
                error_code="SATELLITE_API_ERROR",
            )

        if not res_json.get("success"):
            err_code = res_json.get("errorcode", "UNKNOWN")
            raise LuciApiError(
                message=f"Satellite API error [{err_code}] calling {module}?form={form}",
                error_code="SATELLITE_API_ERROR",
            )

        return res_json.get("data")

    def reboot(self) -> dict[str, Any]:
        """Trigger immediate reboot on the satellite extender."""
        self.call("system", "reboot", operation="reboot")
        return {
            "ok": True,
            "reboot": True,
            "ip": self.ip,
            "message": f"Reboot command sent to satellite {self.ip}.",
        }

    def get_led(self) -> dict[str, Any]:
        """Read LED status, Night Mode schedule, and mesh sync indicator."""
        gen = self.call("ledgeneral", "setting", operation="read") or {}
        pm = self.call("ledpm", "setting", operation="read") or {}
        sync_enable = False
        try:
            mesh_info = self.call("easy_mesh", "mesh_info", operation="read") or {}
            sync_enable = (mesh_info.get("led_sync_enable") == "on")
        except Exception:
            pass

        return {
            "led_enable": gen.get("enable") == "on",
            "night_mode": pm.get("enable") == "on",
            "time_start": pm.get("time_start", ""),
            "time_end": pm.get("time_end", ""),
            "led_sync_enable": sync_enable,
        }

    def set_led(
        self,
        enable: bool | None = None,
        night_mode: bool | None = None,
        start: str | None = None,
        end: str | None = None,
        dry_run: bool = False,
    ) -> dict[str, Any]:
        """Configure LED state or Night Mode schedule."""
        current = self.get_led()
        diff: dict[str, Any] = {}
        changed = False

        if enable is not None:
            diff["led_enable"] = {"before": current["led_enable"], "after": enable}
            if current["led_enable"] != enable:
                changed = True

        if night_mode is not None:
            diff["night_mode"] = {"before": current["night_mode"], "after": night_mode}
            if current["night_mode"] != night_mode:
                changed = True

        if start is not None:
            diff["time_start"] = {"before": current["time_start"], "after": start}
            if current["time_start"] != start:
                changed = True

        if end is not None:
            diff["time_end"] = {"before": current["time_end"], "after": end}
            if current["time_end"] != end:
                changed = True

        warning = None
        if current.get("led_sync_enable"):
            warning = "Mesh LED sync is enabled (led_sync_enable: on). Changes may be overwritten by the mesh controller."

        if dry_run:
            res: dict[str, Any] = {"ok": True, "dry_run": True, "changed": changed, "diff": diff}
            if warning:
                res["warning"] = warning
            return res

        if enable is not None:
            self.call("ledgeneral", "setting", operation="write", params={"enable": "on" if enable else "off"})

        pm_params: dict[str, str] = {}
        if night_mode is not None:
            pm_params["enable"] = "on" if night_mode else "off"
        if start is not None:
            pm_params["time_start"] = start
        if end is not None:
            pm_params["time_end"] = end

        if pm_params:
            if "enable" not in pm_params:
                pm_params["enable"] = "on" if current["night_mode"] else "off"
            if "time_start" not in pm_params and current["time_start"]:
                pm_params["time_start"] = current["time_start"]
            if "time_end" not in pm_params and current["time_end"]:
                pm_params["time_end"] = current["time_end"]
            self.call("ledpm", "setting", operation="write", params=pm_params)

        res = {"ok": True, "dry_run": False, "changed": changed, "diff": diff}
        if warning:
            res["warning"] = warning
        return res

    def get_schedule(self) -> dict[str, Any]:
        """Read Power Schedule settings."""
        settings = self.call("power", "settings", operation="read") or {}
        schedule = self.call("power", "power_schedule", operation="read") or {}
        return {
            "type": "power_schedule",
            "enabled": settings.get("enable_power_schedule") == "on",
            "settings": settings,
            "schedule": schedule,
        }

    def set_schedule(
        self,
        enable: bool | None = None,
        schedule_params: dict[str, Any] | None = None,
        dry_run: bool = False,
    ) -> dict[str, Any]:
        """Configure Power Schedule settings."""
        current = self.get_schedule()
        diff: dict[str, Any] = {}
        changed = False

        if enable is not None:
            diff["enabled"] = {"before": current["enabled"], "after": enable}
            if current["enabled"] != enable:
                changed = True

        if schedule_params:
            diff["schedule"] = {"before": current["schedule"], "after": schedule_params}
            changed = True

        if dry_run:
            return {"ok": True, "dry_run": True, "changed": changed, "diff": diff}

        if enable is not None:
            self.call(
                "power",
                "settings",
                operation="write",
                params={"enable_power_schedule": "on" if enable else "off"},
            )

        if schedule_params:
            self.call("power", "power_schedule", operation="write", params=schedule_params)

        return {"ok": True, "dry_run": False, "changed": changed, "diff": diff}

    def logout(self) -> None:
        """Clean session logout and client termination."""
        if self.stok:
            try:
                self.call("system", "logout", operation="write")
            except Exception:
                pass
            self.stok = None
        try:
            self._client.close()
        except Exception:
            pass


class TddpSatelliteClient:
    """Protocol adapter for Architecture 3 satellite extenders (e.g. RE300).

    Communicates over HTTP using TDDP / MERProxy plaintext protocols with
    GDPR AES-128-CBC + SHA-256 RSA request signing.
    """

    def __init__(
        self,
        ip: str,
        password: str,
        username: str = "",
        timeout: float = 5.0,
    ) -> None:
        self.ip = _clean_ip(ip)
        self.password = password
        self.username = username.strip()
        self.timeout = timeout
        self.token: str | None = None
        self.gdpr: bool = False
        self.ee_hex: str = "010001"
        self.nn_hex: str = ""
        self.seq: int = 1000
        self.aes_key: str = ""
        self.aes_iv: str = ""
        self.pw_hash: str = ""
        self._client = httpx.Client(
            base_url=f"http://{self.ip}",
            timeout=self.timeout,
            headers={
                "Referer": f"http://{self.ip}/",
                "Content-Type": "text/plain;charset=UTF-8",
                "User-Agent": "tpluci",
            },
        )

    def __enter__(self) -> TddpSatelliteClient:
        if not self.token:
            self.login()
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        self.logout()

    def login(self) -> None:
        """Execute GDPR handshake, local/cloud challenge authentication, and AES registration."""
        # 1. Enable GDPR session encryption check
        try:
            r_gdpr = self._client.post("/?code=16&asyn=0", content="enable")
            if r_gdpr.status_code == 200 and "00000" in r_gdpr.text:
                self.gdpr = True
        except Exception:
            self.gdpr = False

        # 2. Fetch GDPR RSA key and sequence number
        r_key = self._client.post("/?code=16&asyn=0", content="get")
        lines = [l.strip() for l in r_key.text.splitlines() if l.strip()]
        if len(lines) >= 4 and lines[0] == "00000":
            self.ee_hex = lines[1]
            self.nn_hex = lines[2]
            try:
                self.seq = int(lines[3])
            except ValueError:
                self.seq = 1000
        else:
            raise LuciApiError(
                message=f"Failed to fetch TDDP GDPR key from satellite at {self.ip}: {r_key.text}",
                error_code="SATELLITE_KEY_FETCH_FAILED",
            )

        self.aes_key, self.aes_iv = generate_aes_key_iv()
        user_for_hash = self.username if self.username else "admin"
        self.pw_hash = sha256_hash(user_for_hash + self.password)

        # 3. Authenticate: Cloud login vs Local login
        if self.username:
            cred_block = f"u{len(self.username):03d}{self.username}p{len(self.password):03d}{self.password}"
            enc_cred = rsa_encrypt_pkcs1_v15(cred_block, self.nn_hex, self.ee_hex, chunk_size=53)
            self._client.post("/?code=16&asyn=0", content=f"cloud {enc_cred}")
            self._client.post("/?code=15&asyn=0", content="main cloud -account_login needBind:0")
            r_chal = self._client.post("/?code=17&asyn=0")
            chal_lines = [l.strip() for l in r_chal.text.splitlines() if l.strip()]
            auth_key = chal_lines[3] if len(chal_lines) > 3 else (chal_lines[1] if len(chal_lines) > 1 else "")
            auth_dict = chal_lines[4] if len(chal_lines) > 4 else (chal_lines[2] if len(chal_lines) > 2 else DEFAULT_DICT)
            token = tp_xor_encrypt(auth_key, self.username + self.password, auth_dict)
            r_auth = self._client.post(f"/?code=17&asyn=0&id={quote(token, safe='')}")
            if r_auth.status_code != 200 or not r_auth.text.startswith("00000"):
                raise AuthError(
                    message=f"Cloud authentication failed on TDDP satellite at {self.ip}.",
                    error_code="SATELLITE_AUTH_FAILED",
                    hint="Check cloud username and password.",
                )
            self.token = token
        else:
            # Local XOR login challenge
            r_chal = self._client.post("/?code=7&asyn=1")
            chal_lines = [l.strip() for l in r_chal.text.splitlines() if l.strip()]
            auth_key = chal_lines[3] if len(chal_lines) > 3 else (chal_lines[1] if len(chal_lines) > 1 else "")
            auth_dict = chal_lines[4] if len(chal_lines) > 4 else (chal_lines[2] if len(chal_lines) > 2 else DEFAULT_DICT)
            pwd_enc = tp_xor_encrypt(self.password, DEFAULT_KEY, DEFAULT_DICT)
            token = tp_xor_encrypt(auth_key, pwd_enc, auth_dict)
            r_auth = self._client.post(f"/?code=7&asyn=0&id={quote(token, safe='')}")
            if r_auth.status_code != 200 or not r_auth.text.startswith("00000"):
                # Probe block 68 to check if bound to cloud ID
                is_binded = False
                try:
                    r_b68 = self._client.post("/?code=2&asyn=0", content="68|1,0,0\r\n")
                    is_binded = (
                        "isBinded 1" in r_b68.text
                        or "isBinded: 1" in r_b68.text
                        or "isBinded\t1" in r_b68.text
                    )
                except Exception:
                    pass
                if is_binded:
                    raise AuthError(
                        message=f"Failed to authenticate with satellite at {self.ip} (extender is bound to TP-Link Cloud ID).",
                        error_code="SATELLITE_AUTH_FAILED",
                        hint=(
                            "Extender has isBinded: 1. Pass --satellite-user <email> "
                            "--satellite-password <pwd> or configure a profile: "
                            f"tpluci config add --name re300 --username <email> --url http://{self.ip}"
                        ),
                    )
                else:
                    raise AuthError(
                        message=f"Failed to authenticate with satellite at {self.ip}.",
                        error_code="SATELLITE_AUTH_FAILED",
                        hint="Check extender password or supply --satellite-password.",
                    )
            self.token = token

        # 4. Register Session AES key via code=16
        aes_block = f"k={self.aes_key}&i={self.aes_iv}"
        enc_aes = rsa_encrypt_pkcs1_v15(aes_block, self.nn_hex, self.ee_hex, chunk_size=53)
        self._client.post(f"/?code=16&asyn=0&id={quote(self.token, safe='')}", content=f"set {enc_aes}")

    def tddp_call(self, opcode: int, payload_text: str) -> str:
        """Encrypt payload with AES-128-CBC, sign with RSA, post, and decrypt response."""
        if not self.token:
            self.login()

        data_b64 = aes_encrypt(payload_text, self.aes_key, self.aes_iv)
        seq_val = self.seq + len(data_b64)
        self.seq = seq_val
        sign = rsa_encrypt_pkcs1_v15(f"h={self.pw_hash}&s={seq_val}", self.nn_hex, self.ee_hex, chunk_size=53)
        body = f"sign={sign}\r\ndata={data_b64}\r\n"
        url = f"/?code={opcode}&asyn=0&id={quote(self.token, safe='')}"

        resp = self._client.post(url, content=body)
        lines = [l.strip() for l in resp.text.splitlines() if l.strip()]
        if not lines or not lines[0].startswith("00000"):
            raise LuciApiError(
                message=f"TDDP call failed (opcode {opcode}): {resp.text[:200]}",
                error_code="TDDP_ERROR",
            )
        if len(lines) > 1:
            return aes_decrypt(lines[1], self.aes_key, self.aes_iv)
        return ""

    @staticmethod
    def parse_block(decrypted_text: str) -> dict[str, str]:
        """Parse key-value pairs from decrypted TDDP block text."""
        res: dict[str, str] = {}
        for line in decrypted_text.splitlines():
            line = line.strip()
            if not line or line.startswith("id ") or "|" in line:
                continue
            parts = line.split(None, 1)
            if len(parts) == 2:
                res[parts[0]] = parts[1]
            elif len(parts) == 1:
                res[parts[0]] = ""
        return res

    def reboot(self) -> dict[str, Any]:
        """Trigger immediate reboot on the TDDP satellite extender."""
        if not self.token:
            self.login()
        url = f"/?code={TDDP_REBOOT}&asyn=1&id={quote(self.token, safe='')}"
        self._client.post(url)
        return {
            "ok": True,
            "reboot": True,
            "ip": self.ip,
            "message": f"Reboot command sent to satellite {self.ip}.",
        }

    def get_led(self) -> dict[str, Any]:
        """Read LED status and Night Mode schedule via blocks 112 and 113."""
        text_112 = self.tddp_call(TDDP_READ, f"{LED_DATA_ID}|1,0,0\r\n")
        b_112 = self.parse_block(text_112)
        text_113 = self.tddp_call(TDDP_READ, f"{NIGHT_MODE_DATA_ID}|1,0,0\r\n")
        b_113 = self.parse_block(text_113)

        return {
            "led_enable": b_112.get("enable") == "1",
            "night_mode": b_113.get("enable") == "1",
            "time_start": b_113.get("timeStart", ""),
            "time_end": b_113.get("timeEnd", ""),
        }

    def set_led(
        self,
        enable: bool | None = None,
        night_mode: bool | None = None,
        start: str | None = None,
        end: str | None = None,
        dry_run: bool = False,
    ) -> dict[str, Any]:
        """Configure LED state or Night Mode schedule via blocks 112 and 113."""
        current = self.get_led()
        diff: dict[str, Any] = {}
        changed = False

        if enable is not None:
            diff["led_enable"] = {"before": current["led_enable"], "after": enable}
            if current["led_enable"] != enable:
                changed = True

        if night_mode is not None:
            diff["night_mode"] = {"before": current["night_mode"], "after": night_mode}
            if current["night_mode"] != night_mode:
                changed = True

        if start is not None:
            diff["time_start"] = {"before": current["time_start"], "after": start}
            if current["time_start"] != start:
                changed = True

        if end is not None:
            diff["time_end"] = {"before": current["time_end"], "after": end}
            if current["time_end"] != end:
                changed = True

        if dry_run:
            return {"ok": True, "dry_run": True, "changed": changed, "diff": diff}

        if enable is not None:
            val = "1" if enable else "0"
            self.tddp_call(TDDP_WRITE, f"id {LED_DATA_ID}|1,0,0\r\nenable {val}\r\n")

        if night_mode is not None or start is not None or end is not None:
            nm_val = ("1" if night_mode else "0") if night_mode is not None else ("1" if current["night_mode"] else "0")
            s_val = start if start is not None else current["time_start"]
            e_val = end if end is not None else current["time_end"]
            self.tddp_call(
                TDDP_WRITE,
                f"id {NIGHT_MODE_DATA_ID}|1,0,0\r\nenable {nm_val}\r\ntimeStart {s_val}\r\ntimeEnd {e_val}\r\n",
            )

        return {"ok": True, "dry_run": False, "changed": changed, "diff": diff}

    def get_schedule(self) -> dict[str, Any]:
        """Read scheduled reboot settings from block 114."""
        text_114 = self.tddp_call(TDDP_READ, f"{SCHEDULE_REBOOT_DATA_ID}|1,0,0\r\n")
        b_114 = self.parse_block(text_114)
        cycle_map = {"1": "day", "2": "week", "3": "month"}
        cycle_str = cycle_map.get(b_114.get("cycle", "2"), "week")

        return {
            "type": "reboot_schedule",
            "enabled": b_114.get("enable") == "1",
            "cycle": cycle_str,
            "day": b_114.get("day", ""),
            "time": b_114.get("time", ""),
        }

    def set_schedule(
        self,
        enable: bool | None = None,
        cycle: str | None = None,
        day: str | None = None,
        time: str | None = None,
        dry_run: bool = False,
    ) -> dict[str, Any]:
        """Configure scheduled reboot settings on block 114."""
        current = self.get_schedule()
        diff: dict[str, Any] = {}
        changed = False

        if enable is not None:
            diff["enabled"] = {"before": current["enabled"], "after": enable}
            if current["enabled"] != enable:
                changed = True

        if cycle is not None:
            diff["cycle"] = {"before": current["cycle"], "after": cycle.lower()}
            if current["cycle"] != cycle.lower():
                changed = True

        if day is not None:
            norm_day = normalize_weekday(day)
            diff["day"] = {"before": current["day"], "after": norm_day}
            if current["day"] != norm_day:
                changed = True

        if time is not None:
            diff["time"] = {"before": current["time"], "after": time}
            if current["time"] != time:
                changed = True

        if dry_run:
            return {"ok": True, "dry_run": True, "changed": changed, "diff": diff}

        cycle_map_rev = {"day": "1", "week": "2", "month": "3"}
        en_val = ("1" if enable else "0") if enable is not None else ("1" if current["enabled"] else "0")
        c_val = cycle_map_rev.get(cycle.lower(), "2") if cycle else cycle_map_rev.get(current["cycle"], "2")
        t_val = time if time is not None else current["time"]
        d_val = normalize_weekday(day) if day is not None else current["day"]

        payload = (
            f"id {SCHEDULE_REBOOT_DATA_ID}|1,0,0\r\n"
            f"enable {en_val}\r\n"
            f"cycle {c_val}\r\n"
            f"time {t_val}\r\n"
            f"day {d_val}\r\n"
        )
        self.tddp_call(TDDP_WRITE, payload)

        return {"ok": True, "dry_run": False, "changed": changed, "diff": diff}

    def logout(self) -> None:
        """Clean session logout and client termination."""
        if self.token:
            try:
                self._client.post(f"/?code={TDDP_LOGOUT}&asyn=0&id={quote(self.token, safe='')}")
            except Exception:
                pass
            self.token = None
        try:
            self._client.close()
        except Exception:
            pass


def connect_satellite(
    ip: str,
    password: str,
    username: str = "",
    timeout: float = 5.0,
) -> HttpsLuciSatelliteClient | TddpSatelliteClient:
    """Probe satellite extender protocol and return an authenticated client.

    1. First probes https://{ip}/cgi-bin/luci/;stok=/login?form=login (operation=read, verify=False).
       If HTTP 200 with "success": true, instantiates HttpsLuciSatelliteClient.
    2. Otherwise probes http://{ip}/?code=2&asyn=0 with content "0|1,0,0".
       If HTTP 200 or 401 with TDDP response, instantiates TddpSatelliteClient.
    """
    clean_ip = _clean_ip(ip)

    # Probe 1: HTTPS LuCI
    is_https = False
    try:
        with httpx.Client(base_url=f"https://{clean_ip}", verify=False, timeout=timeout) as test_client:
            r = test_client.post(
                "/cgi-bin/luci/;stok=/login?form=login",
                data={"operation": "read"},
                headers={"Referer": f"https://{clean_ip}/webpages/login.html"},
            )
            if r.status_code == 200 and r.json().get("success"):
                is_https = True
    except Exception:
        is_https = False

    if is_https:
        client = HttpsLuciSatelliteClient(
            ip=clean_ip,
            password=password,
            username=username,
            timeout=timeout,
        )
        client.login()
        return client

    # Probe 2: TDDP / MERProxy HTTP
    is_tddp = False
    try:
        with httpx.Client(base_url=f"http://{clean_ip}", timeout=timeout) as test_client:
            r = test_client.post(
                "/?code=2&asyn=0",
                content="0|1,0,0\r\n",
                headers={
                    "Referer": f"http://{clean_ip}/",
                    "Content-Type": "text/plain;charset=UTF-8",
                },
            )
            if r.status_code in (200, 401):
                is_tddp = True
    except Exception:
        is_tddp = False

    if is_tddp:
        tddp_client = TddpSatelliteClient(
            ip=clean_ip,
            password=password,
            username=username,
            timeout=timeout,
        )
        tddp_client.login()
        return tddp_client

    raise LuciApiError(
        message=f"Unable to detect satellite protocol for {clean_ip}.",
        error_code="SATELLITE_NOT_REACHABLE",
        hint="Ensure the node IP is correct, reachable, and has its web interface enabled.",
    )
