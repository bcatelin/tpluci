"""Unit tests for CLI base, option positioning, and formatters."""

import json
from click.testing import CliRunner
import click
import pytest

from tpluci import __version__
from tpluci.cli import cli
from tpluci.exceptions import AuthError
from tpluci.formatters import emit_error, format_key_value, format_table, should_use_color


@pytest.fixture(autouse=True)
def register_dummy_cmd():
    @cli.command("dummy")
    @click.pass_context
    def dummy_cmd(ctx):
        """Test subcommand to verify argument extraction."""
        click.echo(json.dumps(ctx.obj))

    yield
    cli.commands.pop("dummy", None)


def test_cli_help():
    runner = CliRunner()
    result = runner.invoke(cli, ["--help"])
    assert result.exit_code == 0
    assert "Fast, lightweight CLI to monitor and control" in result.output
    assert "--json" in result.output
    assert "--plain" in result.output
    assert "--no-cache" in result.output


def test_cli_version():
    runner = CliRunner()
    result = runner.invoke(cli, ["--version"])
    assert result.exit_code == 0
    assert __version__ in result.output


def test_flag_placement_before_and_after():
    runner = CliRunner()

    # Before subcommand
    res_before = runner.invoke(cli, ["--json", "--no-cache", "dummy"])
    assert res_before.exit_code == 0
    obj_before = json.loads(res_before.output)
    assert obj_before.get("json") is True
    assert obj_before.get("no_cache") is True

    # After subcommand
    res_after = runner.invoke(cli, ["dummy", "--json", "--plain"])
    assert res_after.exit_code == 0
    obj_after = json.loads(res_after.output)
    assert obj_after.get("json") is True
    assert obj_after.get("plain") is True


def test_option_with_values_placement():
    runner = CliRunner()

    # --url and --timeout before
    res1 = runner.invoke(cli, ["--url", "http://10.0.0.1", "--timeout", "8.5", "dummy"])
    assert res1.exit_code == 0
    obj1 = json.loads(res1.output)
    assert obj1.get("url") == "http://10.0.0.1"
    assert obj1.get("timeout") == 8.5

    # --url=... after
    res2 = runner.invoke(cli, ["dummy", "--url=http://172.16.0.1", "--profile=iot"])
    assert res2.exit_code == 0
    obj2 = json.loads(res2.output)
    assert obj2.get("url") == "http://172.16.0.1"
    assert obj2.get("profile") == "iot"


def test_invalid_timeout_and_missing_flag_args():
    runner = CliRunner()
    res_bad_timeout = runner.invoke(cli, ["dummy", "--timeout", "not_a_float"])
    assert res_bad_timeout.exit_code != 0
    assert "not a valid float" in res_bad_timeout.output

    res_missing_arg = runner.invoke(cli, ["dummy", "--profile"])
    assert res_missing_arg.exit_code != 0
    assert "requires an argument" in res_missing_arg.output


def test_format_table():
    headers = ["NAME", "IP", "MAC"]
    rows = [
        ["Desktop", "192.168.7.50", "AA:BB:CC:DD:EE:FF"],
        ["Phone", "192.168.7.51", "11:22:33:44:55:66"],
    ]
    table = format_table(headers, rows)
    lines = table.split("\n")
    assert len(lines) == 4  # Header, separator, 2 rows
    assert "NAME" in lines[0]
    assert "---" in lines[1]
    assert "Desktop" in lines[2]


def test_format_key_value():
    pairs = [("Model", "Archer AX23"), ("CPU", "15%"), ("RAM", "40%")]
    out = format_key_value(pairs)
    assert "Model: " in out
    assert "Archer AX23" in out


def test_emit_error_json(capsys):
    err = AuthError("Bad credentials", error_code="AUTH_FAILED")
    with pytest.raises(SystemExit) as exc:
        emit_error(err, json_mode=True)
    assert exc.value.code == 2
    captured = capsys.readouterr()
    envelope = json.loads(captured.err)
    assert envelope["ok"] is False
    assert envelope["error_code"] == "AUTH_FAILED"
