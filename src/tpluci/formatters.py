"""Output formatters and stream emitters for CLI human and agent modes."""

from __future__ import annotations

import json
import os
import sys
from typing import Any

from tpluci.exceptions import TpluciError


def should_use_color(plain_flag: bool = False) -> bool:
    """Return whether ANSI colors and styling should be applied."""
    if plain_flag:
        return False
    if os.environ.get("NO_COLOR") is not None:
        return False
    if os.environ.get("TPLUCI_COLOR") == "0":
        return False
    return sys.stdout.isatty()


def format_table(headers: list[str], rows: list[list[Any]], plain: bool = False) -> str:
    """Format aligned, space-padded plain-text table with header separator."""
    if not headers and not rows:
        return ""

    str_headers = [str(h) for h in headers]
    str_rows = [[str(cell) if cell is not None else "" for cell in row] for row in rows]

    num_cols = len(str_headers)
    widths = [len(h) for h in str_headers]
    for row in str_rows:
        for i, cell in enumerate(row):
            if i < num_cols:
                widths[i] = max(widths[i], len(cell))
            else:
                widths.append(len(cell))
                num_cols += 1

    lines = []
    # Header line
    header_line = "  ".join(h.ljust(widths[i]) for i, h in enumerate(str_headers))
    lines.append(header_line)
    # Separator
    sep_line = "  ".join("-" * widths[i] for i in range(len(str_headers)))
    lines.append(sep_line)
    # Rows
    for row in str_rows:
        row_padded = [row[i].ljust(widths[i]) if i < len(row) else "".ljust(widths[i]) for i in range(len(str_headers))]
        lines.append("  ".join(row_padded))

    return "\n".join(lines)


def format_key_value(pairs: list[tuple[str, Any]], plain: bool = False) -> str:
    """Format aligned key-value pairs (e.g. Model:       Archer AX23)."""
    if not pairs:
        return ""
    str_pairs = [(str(k), str(v) if v is not None else "") for k, v in pairs]
    max_key_len = max(len(k) for k, _ in str_pairs) + 1

    lines = []
    for k, v in str_pairs:
        key_part = f"{k}:".ljust(max_key_len + 1)
        lines.append(f"{key_part} {v}")
    return "\n".join(lines)


def emit_output(data: Any, human_text: str, json_mode: bool = False) -> None:
    """Emit command output to stdout in JSON or formatted human text."""
    if json_mode or os.environ.get("TPLUCI_OUTPUT") == "json":
        sys.stdout.write(json.dumps(data, indent=2) + "\n")
    else:
        if human_text:
            sys.stdout.write(human_text.rstrip("\n") + "\n")


def emit_error(err: TpluciError, json_mode: bool = False) -> None:
    """Emit standardized error message and envelope to stderr and exit with exit_code."""
    if json_mode or os.environ.get("TPLUCI_OUTPUT") == "json":
        sys.stderr.write(json.dumps(err.to_dict(), indent=2) + "\n")
    else:
        msg = f"Error [{err.error_code}]: {err.message}\n"
        if err.hint:
            msg += f"Hint: {err.hint}\n"
        sys.stderr.write(msg)
    sys.exit(err.exit_code)
