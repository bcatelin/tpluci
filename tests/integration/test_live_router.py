"""Live integration tests running non-destructive queries against physical router.

Automatically skipped if .env file is absent or router is unreachable.
"""

import json
from pathlib import Path
from click.testing import CliRunner
import pytest

from tpluci.cli import cli

ENV_PATH = Path(".env")
HAVE_LIVE_ENV = ENV_PATH.is_file()


@pytest.mark.skipif(not HAVE_LIVE_ENV, reason="No .env file found; skipping live router tests")
def test_live_router_status():
    runner = CliRunner()
    result = runner.invoke(cli, ["status", "--json"])
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert "model" in data
    assert "wan_ip" in data
    assert "clients_count" in data


@pytest.mark.skipif(not HAVE_LIVE_ENV, reason="No .env file found; skipping live router tests")
def test_live_router_wifi_list():
    runner = CliRunner()
    result = runner.invoke(cli, ["wifi", "list", "--json"])
    assert result.exit_code == 0
    radios = json.loads(result.output)
    assert len(radios) == 6
    radio_codes = {r["radio"] for r in radios}
    assert "2g" in radio_codes
    assert "guest-2g" in radio_codes


@pytest.mark.skipif(not HAVE_LIVE_ENV, reason="No .env file found; skipping live router tests")
def test_live_router_clients():
    runner = CliRunner()
    result = runner.invoke(cli, ["clients", "--json"])
    assert result.exit_code == 0
    clients = json.loads(result.output)
    assert isinstance(clients, list)


@pytest.mark.skipif(not HAVE_LIVE_ENV, reason="No .env file found; skipping live router tests")
def test_live_router_wifi_dry_run():
    runner = CliRunner()
    result = runner.invoke(cli, ["wifi", "set", "guest-2g", "--enable", "--dry-run", "--json"])
    assert result.exit_code == 0
    receipt = json.loads(result.output)
    assert receipt["dry_run"] is True
    assert "diff" in receipt


@pytest.mark.skipif(not HAVE_LIVE_ENV, reason="No .env file found; skipping live router tests")
def test_live_router_wan():
    runner = CliRunner()
    result = runner.invoke(cli, ["wan", "--json"])
    assert result.exit_code == 0
    wan = json.loads(result.output)
    assert wan["ipaddr"] != ""
    assert wan["gateway"] != ""
    assert wan["dns"] != ""
    assert wan["conntype"] != ""
