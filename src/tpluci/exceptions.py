"""Structured, actionable exception contracts and standard exit codes for tpluci."""

from typing import Any

EXIT_OK = 0
EXIT_USAGE_ERROR = 1
EXIT_AUTH_ERROR = 2
EXIT_NETWORK_ERROR = 3
EXIT_LUCI_ERROR = 4
EXIT_SAFETY_ABORT = 5


class TpluciError(Exception):
    """Base exception for all tpluci operational errors."""

    def __init__(
        self,
        message: str,
        error_code: str = "GENERIC_ERROR",
        hint: str = "",
        exit_code: int = EXIT_USAGE_ERROR,
    ):
        super().__init__(message)
        self.message = message
        self.error_code = error_code
        self.hint = hint
        self.exit_code = exit_code

    def to_dict(self) -> dict[str, Any]:
        """Return standardized JSON envelope for agent and API consumers."""
        return {
            "ok": False,
            "error_code": self.error_code,
            "message": self.message,
            "hint": self.hint,
        }


class AuthError(TpluciError):
    """Raised when authentication credentials are missing, invalid, or expired."""

    def __init__(
        self,
        message: str,
        error_code: str = "AUTH_FAILED",
        hint: str = "Check ROUTER_PASSWORD in .env or run: tpluci config add --name default",
        exit_code: int = EXIT_AUTH_ERROR,
    ):
        super().__init__(message=message, error_code=error_code, hint=hint, exit_code=exit_code)


class NetworkError(TpluciError):
    """Raised when router is unreachable, times out, or connection is refused."""

    def __init__(
        self,
        message: str,
        error_code: str = "NETWORK_ERROR",
        hint: str = "Verify router IP (default: http://192.168.7.250) and network connection.",
        exit_code: int = EXIT_NETWORK_ERROR,
    ):
        super().__init__(message=message, error_code=error_code, hint=hint, exit_code=exit_code)


class LuciApiError(TpluciError):
    """Raised when the LuCI backend returns an error or unsupported endpoint."""

    def __init__(
        self,
        message: str,
        error_code: str = "LUCI_ERROR",
        hint: str = "Run 'tpluci call --list' to check verified endpoint names.",
        exit_code: int = EXIT_LUCI_ERROR,
        luci_error_code: str | None = None,
    ):
        super().__init__(message=message, error_code=error_code, hint=hint, exit_code=exit_code)
        self.luci_error_code = luci_error_code

    def to_dict(self) -> dict[str, Any]:
        envelope = super().to_dict()
        if self.luci_error_code is not None:
            envelope["luci_error_code"] = self.luci_error_code
        return envelope


class SafetyAbortError(TpluciError):
    """Raised when a destructive operation is aborted due to missing confirmation."""

    def __init__(
        self,
        message: str,
        error_code: str = "SAFETY_ABORT",
        hint: str = "Pass --confirm to authorize this operation in non-interactive environments.",
        exit_code: int = EXIT_SAFETY_ABORT,
    ):
        super().__init__(message=message, error_code=error_code, hint=hint, exit_code=exit_code)
