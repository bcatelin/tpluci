"""Configuration and credential manager for tpluci.

Implements the 4-tier credential resolution hierarchy:
  Tier 1: Environment variables (ROUTER_PASSWORD / TPLUCI_PASSWORD)
  Tier 2: .env files (./.env then ~/.config/tpluci/.env)
  Tier 3: OS Keyring (macOS Keychain / Linux SecretService)
  Tier 4: Plaintext 0600 config file fallback (~/.config/tpluci/config.json)
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from tpluci.exceptions import AuthError

DEFAULT_ROUTER_URL = "http://192.168.7.250"
DEFAULT_TIMEOUT = 5.0
DEFAULT_PROFILE = "default"


@dataclass
class ResolvedCredentials:
    """Resolved credentials and connection metadata for a router session."""

    profile: str
    url: str
    username: str
    password: str
    timeout: float
    source: str  # "env", "dotenv", "keyring", "config_file"
    warning: str | None = None


def get_config_dir() -> Path:
    """Return base directory for tpluci configuration files."""
    env_dir = os.environ.get("TPLUCI_CONFIG_DIR")
    if env_dir:
        return Path(env_dir).expanduser()
    return Path("~/.config/tpluci").expanduser()


def get_config_path() -> Path:
    """Return path to config.json."""
    return get_config_dir() / "config.json"


def load_config() -> dict[str, Any]:
    """Load config.json if it exists, otherwise return default structure."""
    path = get_config_path()
    if not path.is_file():
        return {
            "default_profile": DEFAULT_PROFILE,
            "profiles": {},
        }
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
            if not isinstance(data, dict):
                return {"default_profile": DEFAULT_PROFILE, "profiles": {}}
            return data
    except Exception:
        return {"default_profile": DEFAULT_PROFILE, "profiles": {}}


def save_config(config_dict: dict[str, Any]) -> None:
    """Save config.json with strict atomic 0600 permissions."""
    path = get_config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(config_dict, indent=2)
    flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    fd = os.open(path, flags, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(payload)
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


def list_profiles() -> dict[str, Any]:
    """Return list of profiles with passwords scrubbed."""
    cfg = load_config()
    profiles = cfg.get("profiles", {})
    sanitized: dict[str, Any] = {}
    for name, data in profiles.items():
        copy = dict(data)
        if "password" in copy:
            copy["password"] = "******"
        sanitized[name] = copy
    return {
        "default_profile": cfg.get("default_profile", DEFAULT_PROFILE),
        "profiles": sanitized,
    }


def save_profile(
    name: str,
    url: str,
    password: str,
    username: str = "",
    timeout: float = DEFAULT_TIMEOUT,
    use_keyring: bool = True,
) -> str:
    """Save or update a profile.

    Stores password in OS keyring if use_keyring is True and keyring is operational,
    otherwise falls back to storing password in config.json with 0600 permissions.
    Returns the storage backend used ('keyring' or 'config_file').
    """
    storage = "config_file"
    if use_keyring:
        try:
            import keyring
            keyring.set_password("tpluci", name, password)
            storage = "keyring"
        except Exception:
            storage = "config_file"

    cfg = load_config()
    profile_data: dict[str, Any] = {
        "url": url,
        "username": username,
        "timeout": timeout,
        "use_keyring": (storage == "keyring"),
    }
    if storage == "config_file":
        profile_data["password"] = password

    cfg.setdefault("profiles", {})[name] = profile_data
    if "default_profile" not in cfg or not cfg["default_profile"]:
        cfg["default_profile"] = name

    save_config(cfg)
    return storage


def delete_profile(name: str) -> None:
    """Delete a profile from config.json and keyring."""
    cfg = load_config()
    if name in cfg.get("profiles", {}):
        del cfg["profiles"][name]
        save_config(cfg)

    try:
        import keyring
        keyring.delete_password("tpluci", name)
    except Exception:
        pass


def set_default_profile(name: str) -> None:
    """Set the default profile name."""
    cfg = load_config()
    cfg["default_profile"] = name
    save_config(cfg)


def resolve_profile_name(profile: str | None = None, cfg: dict[str, Any] | None = None) -> str:
    """Resolve the active profile name from CLI argument, environment, or config.json."""
    if profile:
        return profile
    env_prof = os.environ.get("TPLUCI_PROFILE") or os.environ.get("ROUTER_PROFILE")
    if env_prof:
        return env_prof
    loaded_cfg = cfg if cfg is not None else load_config()
    return loaded_cfg.get("default_profile", DEFAULT_PROFILE) or DEFAULT_PROFILE


def resolve_credentials(
    profile: str | None = None,
    url_override: str | None = None,
    timeout_override: float | None = None,
) -> ResolvedCredentials:
    """Resolve credentials across the 4-tier hierarchy.

    Tier 1: Environment variables
    Tier 2: .env files (current working dir or ~/.config/tpluci/.env)
    Tier 3: OS Keyring for the selected profile
    Tier 4: ~/.config/tpluci/config.json fallback
    """
    cfg = load_config()
    target_profile = resolve_profile_name(profile, cfg=cfg)

    # -------------------------------------------------------------
    # Tier 1: Environment Variables
    # -------------------------------------------------------------
    env_pwd = os.environ.get("ROUTER_PASSWORD") or os.environ.get("TPLUCI_PASSWORD")
    if env_pwd:
        url = url_override or os.environ.get("ROUTER_URL") or os.environ.get("TPLUCI_URL") or DEFAULT_ROUTER_URL
        user = os.environ.get("ROUTER_USERNAME") or os.environ.get("TPLUCI_USERNAME") or ""
        timeout_val = (
            timeout_override
            if timeout_override is not None
            else float(os.environ.get("ROUTER_TIMEOUT") or os.environ.get("TPLUCI_TIMEOUT") or DEFAULT_TIMEOUT)
        )
        return ResolvedCredentials(
            profile=target_profile,
            url=url,
            username=user,
            password=env_pwd,
            timeout=timeout_val,
            source="env",
        )

    # -------------------------------------------------------------
    # Tier 2: .env Files (./.env then ~/.config/tpluci/.env)
    # -------------------------------------------------------------
    dotenv_paths = [Path("./.env"), get_config_dir() / ".env"]
    for dotenv_path in dotenv_paths:
        if dotenv_path.is_file():
            from dotenv import dotenv_values
            values = {k.upper(): v for k, v in dotenv_values(dotenv_path).items() if k and v}
            pwd = values.get("ROUTER_PASSWORD") or values.get("PASSWORD") or values.get("TPLUCI_PASSWORD") or values.get("PASS")
            if pwd:
                url = url_override or values.get("ROUTER_URL") or values.get("URL") or values.get("TPLUCI_URL") or DEFAULT_ROUTER_URL
                user = values.get("ROUTER_USERNAME") or values.get("TPLUCI_USERNAME") or values.get("USERNAME") or ""
                timeout_str = values.get("ROUTER_TIMEOUT") or values.get("TPLUCI_TIMEOUT") or values.get("TIMEOUT")
                timeout_val = (
                    timeout_override
                    if timeout_override is not None
                    else (float(timeout_str) if timeout_str else DEFAULT_TIMEOUT)
                )
                return ResolvedCredentials(
                    profile=target_profile,
                    url=url,
                    username=user,
                    password=pwd,
                    timeout=timeout_val,
                    source="dotenv",
                )

    # -------------------------------------------------------------
    # Tier 3: OS Keyring
    # -------------------------------------------------------------
    profile_data = cfg.get("profiles", {}).get(target_profile, {})
    url = url_override or profile_data.get("url") or DEFAULT_ROUTER_URL
    user = profile_data.get("username", "")
    timeout_val = timeout_override if timeout_override is not None else float(profile_data.get("timeout", DEFAULT_TIMEOUT))

    if profile_data.get("use_keyring", True):
        try:
            import keyring
            keyring_pwd = keyring.get_password("tpluci", target_profile)
            if keyring_pwd:
                return ResolvedCredentials(
                    profile=target_profile,
                    url=url,
                    username=user,
                    password=keyring_pwd,
                    timeout=timeout_val,
                    source="keyring",
                )
        except Exception:
            pass  # Fall through to Tier 4

    # -------------------------------------------------------------
    # Tier 4: Config file fallback
    # -------------------------------------------------------------
    config_pwd = profile_data.get("password")
    if config_pwd:
        warning = (
            f"Warning: Using plaintext password storage in {get_config_path()}. "
            "OS keyring not available or disabled."
        )
        return ResolvedCredentials(
            profile=target_profile,
            url=url,
            username=user,
            password=config_pwd,
            timeout=timeout_val,
            source="config_file",
            warning=warning,
        )

    # -------------------------------------------------------------
    # If no credentials found across all 4 tiers
    # -------------------------------------------------------------
    raise AuthError(
        message=f"No router credentials found for profile '{target_profile}'.",
        error_code="AUTH_MISSING",
        hint=(
            f"Set ROUTER_PASSWORD in .env or run: "
            f"tpluci config add --name {target_profile} --url {DEFAULT_ROUTER_URL}"
        ),
    )
