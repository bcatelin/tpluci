"""Pure-Python client for TP-Link LuCI routers (Archer AX23 / AX1800).

Handles RSA+AES authentication handshake, ephemeral session caching, rate-limiting,
automatic transparent re-login on session expiry, and safe read-modify-write mutations.
"""

from __future__ import annotations

import json
import time
import urllib.parse
from typing import Any

import httpx

from tpluci.config import ResolvedCredentials, resolve_credentials
from tpluci.crypto import (
    aes_decrypt,
    aes_encrypt,
    build_signature,
    generate_aes_key_iv,
    md5_hash,
    rsa_encrypt,
)
from tpluci.exceptions import (
    AuthError,
    LuciApiError,
    NetworkError,
)
from tpluci.session import SessionCache, SessionData


class RouterClient:
    """Client for monitoring and configuring TP-Link LuCI routers."""

    def __init__(
        self,
        creds: ResolvedCredentials | None = None,
        use_cache: bool = True,
        cache_ttl: float = 180.0,
        rate_limit_delay: float = 0.05,
    ):
        self.creds = creds or resolve_credentials()
        self.use_cache = use_cache
        self.cache_ttl = cache_ttl
        self.rate_limit_delay = rate_limit_delay
        self._last_call_time = 0.0

        self.base_url = self.creds.url.rstrip("/")
        self.http_client = httpx.Client(
            base_url=self.base_url,
            timeout=self.creds.timeout,
            verify=False,
            follow_redirects=True,
        )

    def close(self) -> None:
        """Close the underlying HTTP client."""
        try:
            self.http_client.close()
        except Exception:
            pass

    def __enter__(self) -> RouterClient:
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        self.close()

    def _apply_rate_limit(self) -> None:
        """Enforce minimal rate-limiting delay (50ms) to prevent server overload."""
        elapsed = time.time() - self._last_call_time
        if elapsed < self.rate_limit_delay:
            time.sleep(self.rate_limit_delay - elapsed)
        self._last_call_time = time.time()

    def _post(self, endpoint: str, data: dict[str, Any], context_label: str = "") -> httpx.Response:
        """Execute an HTTP POST with standardized NetworkError mapping."""
        try:
            return self.http_client.post(endpoint, data=data)
        except httpx.TimeoutException as exc:
            target = f" ({context_label})" if context_label else ""
            raise NetworkError(
                message=f"Connection timed out reaching router at {self.base_url}{target}.",
                error_code="NETWORK_TIMEOUT",
                hint="Verify router power, network connection, or increase --timeout.",
            ) from exc
        except httpx.ConnectError as exc:
            raise NetworkError(
                message=f"Failed to connect to router at {self.base_url}.",
                error_code="NETWORK_UNREACHABLE",
                hint="Check Wi-Fi/Ethernet connection and router IP address.",
            ) from exc
        except httpx.HTTPError as exc:
            raise NetworkError(
                message=f"HTTP transport error communicating with {self.base_url}: {exc}",
                error_code="NETWORK_ERROR",
            ) from exc

    def login(self, force: bool = False) -> SessionData:
        """Execute full TP-Link LuCI authentication handshake."""
        expected_pwd_hash = md5_hash(self.creds.username or "admin", self.creds.password)

        # 1. Check ephemeral session cache
        if not force and self.use_cache:
            cached = SessionCache.load(self.creds.profile, ttl=self.cache_ttl)
            if cached:
                url_matches = (not cached.url) or (cached.url == self.base_url)
                pwd_matches = (not cached.url) or (cached.password_hash == expected_pwd_hash)
                if url_matches and pwd_matches:
                    return cached

        self._apply_rate_limit()

        # 2. Fetch RSA public key for password encryption
        keys_resp = self._post(
            "/cgi-bin/luci/;stok=/login?form=keys",
            data={"operation": "read"},
            context_label="login keys",
        )

        if keys_resp.status_code != 200:
            raise NetworkError(
                message=f"Router returned HTTP {keys_resp.status_code} fetching encryption keys.",
                error_code="NETWORK_HTTP_ERROR",
            )

        try:
            keys_json = keys_resp.json()
            nn_keys, ee_keys = keys_json["data"]["password"]
        except Exception as exc:
            raise LuciApiError(
                message="Failed to parse RSA password encryption key from router.",
                error_code="LUCI_KEY_PARSE_ERROR",
            ) from exc

        # 3. Fetch RSA public key & sequence counter for auth signature
        self._apply_rate_limit()
        auth_resp = self._post(
            "/cgi-bin/luci/;stok=/login?form=auth",
            data={"operation": "read"},
            context_label="login auth",
        )
        if auth_resp.status_code != 200:
            raise NetworkError(
                message=f"Router returned HTTP {auth_resp.status_code} fetching auth sequence.",
                error_code="NETWORK_HTTP_ERROR",
            )
        try:
            auth_json = auth_resp.json()
            nn_auth, ee_auth = auth_json["data"]["key"]
            seq = int(auth_json["data"]["seq"])
        except Exception as exc:
            raise LuciApiError(
                message="Failed to parse auth keys and sequence counter from router.",
                error_code="LUCI_AUTH_PARSE_ERROR",
            ) from exc

        # 4. Generate ephemeral AES key/IV and encrypt password
        enc_pwd = rsa_encrypt(self.creds.password, nn_keys, ee_keys)
        key, iv = generate_aes_key_iv()
        pwd_hash = expected_pwd_hash

        # 5. Encrypt URL-encoded login payload
        encoded_pwd = urllib.parse.quote(enc_pwd, safe="")
        data_plain = f"operation=login&password={encoded_pwd}"
        data_enc = aes_encrypt(data_plain, key, iv)

        # 6. Build login signature
        sign = build_signature(
            password_hash=pwd_hash,
            seq_with_data_len=seq + len(data_enc),
            nn_hex=nn_auth,
            ee_hex=ee_auth,
            aes_key=key,
            aes_iv=iv,
            is_login=True,
        )

        # 7. POST login credentials
        self._apply_rate_limit()
        login_resp = self._post(
            "/cgi-bin/luci/;stok=/login?form=login",
            data={"sign": sign, "data": data_enc},
            context_label="login",
        )

        if login_resp.status_code != 200:
            raise AuthError(
                message=f"Router returned HTTP {login_resp.status_code} on login attempt.",
                error_code="AUTH_HTTP_ERROR",
            )

        try:
            resp_body = login_resp.json()
        except Exception as exc:
            raise AuthError(
                message="Router returned invalid JSON on login attempt.",
                error_code="AUTH_INVALID_JSON",
            ) from exc

        ct_data = resp_body.get("data")
        if not ct_data:
            err_code = resp_body.get("errorcode", "Unknown")
            raise AuthError(
                message=f"Router rejected login: {err_code}",
                error_code="AUTH_FAILED",
            )

        try:
            decrypted_str = aes_decrypt(ct_data, key, iv)
            decrypted = json.loads(decrypted_str)
        except Exception as exc:
            raise AuthError(
                message=f"Failed to decrypt router login response: {exc}",
                error_code="AUTH_DECRYPT_ERROR",
            ) from exc

        if not decrypted.get("success", False):
            err_code = decrypted.get("errorcode", "login failed")
            raise AuthError(
                message=f"Router authentication failed: {err_code}",
                error_code="AUTH_FAILED",
                hint="Verify router password in .env or run: tpluci config add --name default",
            )

        stok = decrypted.get("data", {}).get("stok")
        if not stok:
            raise AuthError(
                message="No session token ('stok') returned in login response.",
                error_code="AUTH_NO_TOKEN",
            )

        cookies = {k: v for k, v in login_resp.cookies.items()}
        session_data = SessionData(
            stok=stok,
            aes_key=key,
            aes_iv=iv,
            seq=seq,
            password_hash=pwd_hash,
            nn_auth=nn_auth,
            ee_auth=ee_auth,
            cookies=cookies,
            updated_at=time.time(),
            url=self.base_url,
        )

        if self.use_cache:
            SessionCache.save(self.creds.profile, session_data)

        return session_data

    def call(
        self,
        module: str,
        form: str,
        operation: str = "read",
        params: dict[str, Any] | None = None,
        retrying_after_relogin: bool = False,
    ) -> Any:
        """Execute signed, AES-encrypted request to a LuCI form endpoint."""
        session = self.login(force=False)
        self._apply_rate_limit()

        # 1. Format payload
        payload_dict: dict[str, Any] = {"operation": operation}
        if params:
            payload_dict.update(params)
        payload_plain = urllib.parse.urlencode(payload_dict)

        # 2. Encrypt and sign
        data_enc = aes_encrypt(payload_plain, session.aes_key, session.aes_iv)
        sign = build_signature(
            password_hash=session.password_hash,
            seq_with_data_len=session.seq + len(data_enc),
            nn_hex=session.nn_auth,
            ee_hex=session.ee_auth,
            is_login=False,
        )

        endpoint_url = f"/cgi-bin/luci/;stok={session.stok}/admin/{module}?form={form}"
        if session.cookies:
            self.http_client.cookies.update(session.cookies)

        resp = self._post(
            endpoint_url,
            data={"sign": sign, "data": data_enc},
            context_label=f"{module}?form={form}",
        )

        # 3. Handle session expiry (HTTP 401/403 or unauthenticated response)
        if resp.status_code in (401, 403):
            if not retrying_after_relogin:
                SessionCache.clear(self.creds.profile)
                self.login(force=True)
                return self.call(module, form, operation, params, retrying_after_relogin=True)
            raise AuthError(
                message=f"Access denied (HTTP {resp.status_code}) for endpoint {module}?form={form}.",
                error_code="AUTH_EXPIRED",
                hint="Session token expired or credentials changed.",
            )

        if resp.status_code != 200:
            raise LuciApiError(
                message=f"Router returned HTTP {resp.status_code} for {module}?form={form}.",
                error_code="LUCI_HTTP_ERROR",
            )

        # 4. Decrypt response
        try:
            resp_json = resp.json()
        except Exception as exc:
            raise LuciApiError(
                message=f"Invalid JSON returned from {module}?form={form}.",
                error_code="LUCI_INVALID_JSON",
            ) from exc

        raw_ct = resp_json.get("data")
        if not raw_ct:
            if resp_json.get("errorcode") == "no such callback":
                raise LuciApiError(
                    message=f"Endpoint '{module}?form={form}' is not supported by this router.",
                    error_code="LUCI_NO_CALLBACK",
                    hint="Run 'tpluci call --list' to check verified endpoints.",
                    luci_error_code="no such callback",
                )
            if not retrying_after_relogin and not resp_json.get("success", False):
                SessionCache.clear(self.creds.profile)
                self.login(force=True)
                return self.call(module, form, operation, params, retrying_after_relogin=True)
            raise LuciApiError(
                message=f"LuCI API returned failure: {resp_json.get('errorcode')}",
                error_code="LUCI_ERROR",
                luci_error_code=str(resp_json.get("errorcode")),
            )

        try:
            decrypted_str = aes_decrypt(raw_ct, session.aes_key, session.aes_iv)
            result = json.loads(decrypted_str)
        except Exception as exc:
            raise LuciApiError(
                message=f"Failed to decrypt payload from {module}?form={form}: {exc}",
                error_code="LUCI_DECRYPT_ERROR",
            ) from exc

        # Check inner LuCI response
        if not result.get("success", False):
            err = result.get("errorcode")
            if not retrying_after_relogin and str(err) in ("-1", "session timeout", "unauthenticated"):
                SessionCache.clear(self.creds.profile)
                self.login(force=True)
                return self.call(module, form, operation, params, retrying_after_relogin=True)
            raise LuciApiError(
                message=f"LuCI API returned error: {err}",
                error_code="LUCI_ERROR",
                hint="Check parameter names and values.",
                luci_error_code=str(err),
            )

        # Update cache timestamp
        session.updated_at = time.time()
        if self.use_cache:
            SessionCache.save(self.creds.profile, session)

        return result.get("data", {})

    def read_modify_write(
        self,
        module: str,
        form: str,
        updates: dict[str, Any],
        dry_run: bool = False,
    ) -> dict[str, Any]:
        """Perform a safe Read-Modify-Write update with diff receipt and dry-run support."""
        current = self.call(module, form, operation="read")
        diff: dict[str, dict[str, Any]] = {}
        merged = dict(current)

        for key, new_val in updates.items():
            old_val = current.get(key)
            if str(old_val) != str(new_val):
                diff[key] = {"before": old_val, "after": new_val}
                merged[key] = new_val

        changed = bool(diff)

        if changed and not dry_run:
            write_params = {
                k: v for k, v in merged.items() if not isinstance(v, (dict, list))
            }
            self.call(module, form, operation="write", params=write_params)

        return {
            "dry_run": dry_run,
            "changed": changed,
            "diff": diff,
            "state": merged,
        }

    def logout(self) -> bool:
        """Clear session cache and terminate local router session."""
        cleared = SessionCache.clear(self.creds.profile)
        try:
            self.http_client.close()
        except Exception:
            pass
        return cleared
