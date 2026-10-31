"""Ephemeral session cache for tpluci.

Caches authenticated session tokens, AES ephemeral keys, and LuCI sequence
counters in a user-isolated 0600 temp file with automatic TTL invalidation.
"""

from __future__ import annotations

import json
import os
import tempfile
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


@dataclass
class SessionData:
    """Stored session state for an active router session."""

    stok: str
    aes_key: str
    aes_iv: str
    seq: int
    password_hash: str
    nn_auth: str
    ee_auth: str
    cookies: dict[str, str]
    updated_at: float
    url: str = ""

    def is_valid(self, ttl: float = 180.0) -> bool:
        """Check if session is still within TTL window."""
        return (time.time() - self.updated_at) < ttl

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SessionData:
        return cls(
            stok=data["stok"],
            aes_key=data["aes_key"],
            aes_iv=data["aes_iv"],
            seq=int(data["seq"]),
            password_hash=data["password_hash"],
            nn_auth=data["nn_auth"],
            ee_auth=data["ee_auth"],
            cookies=data.get("cookies", {}),
            updated_at=float(data["updated_at"]),
            url=data.get("url", ""),
        )


class SessionCache:
    """Manages reading and writing ephemeral session state to disk."""

    @staticmethod
    def get_cache_path(profile: str) -> Path:
        """Return the user-isolated cache file path."""
        try:
            uid = os.getuid()
        except AttributeError:
            uid = 1000
        safe_profile = "".join(c for c in profile if c.isalnum() or c in ("-", "_")) or "default"
        filename = f"tpluci-session-{uid}-{safe_profile}.json"
        return Path(tempfile.gettempdir()) / filename

    @classmethod
    def load(cls, profile: str, ttl: float = 180.0) -> SessionData | None:
        """Load session data from cache file if exists and within TTL."""
        path = cls.get_cache_path(profile)
        if not path.is_file():
            return None

        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            session = SessionData.from_dict(data)
            if not session.is_valid(ttl):
                cls.clear(profile)
                return None
            return session
        except Exception:
            cls.clear(profile)
            return None

    @classmethod
    def save(cls, profile: str, data: SessionData) -> None:
        """Persist session data to disk with strict atomic 0600 permissions."""
        path = cls.get_cache_path(profile)
        payload = json.dumps(data.to_dict(), indent=2)
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

    @classmethod
    def clear(cls, profile: str) -> bool:
        """Delete cache file if it exists."""
        path = cls.get_cache_path(profile)
        if path.is_file():
            try:
                path.unlink()
                return True
            except OSError:
                return False
        return False
