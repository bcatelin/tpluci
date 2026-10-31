"""Unit tests for tpluci exit codes, exception hierarchy, and error envelopes."""

import pytest

from tpluci.exceptions import (
    EXIT_AUTH_ERROR,
    EXIT_LUCI_ERROR,
    EXIT_NETWORK_ERROR,
    EXIT_OK,
    EXIT_SAFETY_ABORT,
    EXIT_USAGE_ERROR,
    AuthError,
    LuciApiError,
    NetworkError,
    SafetyAbortError,
    TpluciError,
)


def test_exit_code_constants():
    assert EXIT_OK == 0
    assert EXIT_USAGE_ERROR == 1
    assert EXIT_AUTH_ERROR == 2
    assert EXIT_NETWORK_ERROR == 3
    assert EXIT_LUCI_ERROR == 4
    assert EXIT_SAFETY_ABORT == 5


def test_tpluci_error_envelope():
    err = TpluciError(
        message="Something went wrong",
        error_code="CUSTOM_ERR",
        hint="Try again later",
        exit_code=1,
    )
    assert err.exit_code == 1
    envelope = err.to_dict()
    assert envelope == {
        "ok": False,
        "error_code": "CUSTOM_ERR",
        "message": "Something went wrong",
        "hint": "Try again later",
    }


def test_auth_error_envelope():
    err = AuthError("Invalid router password", error_code="AUTH_FAILED")
    assert err.exit_code == EXIT_AUTH_ERROR
    envelope = err.to_dict()
    assert envelope["ok"] is False
    assert envelope["error_code"] == "AUTH_FAILED"
    assert "Check ROUTER_PASSWORD" in envelope["hint"]


def test_network_error_envelope():
    err = NetworkError("Connection timed out", error_code="NETWORK_TIMEOUT")
    assert err.exit_code == EXIT_NETWORK_ERROR
    envelope = err.to_dict()
    assert envelope["ok"] is False
    assert envelope["error_code"] == "NETWORK_TIMEOUT"
    assert "192.168.7.250" in envelope["hint"]


def test_luci_api_error_envelope():
    err = LuciApiError("no such callback", error_code="LUCI_NO_CALLBACK", luci_error_code="-1")
    assert err.exit_code == EXIT_LUCI_ERROR
    envelope = err.to_dict()
    assert envelope["ok"] is False
    assert envelope["error_code"] == "LUCI_NO_CALLBACK"
    assert envelope["luci_error_code"] == "-1"
    assert "call --list" in envelope["hint"]


def test_safety_abort_error_envelope():
    err = SafetyAbortError("Reboot aborted", error_code="SAFETY_ABORT")
    assert err.exit_code == EXIT_SAFETY_ABORT
    envelope = err.to_dict()
    assert envelope["ok"] is False
    assert envelope["error_code"] == "SAFETY_ABORT"
    assert "--confirm" in envelope["hint"]
