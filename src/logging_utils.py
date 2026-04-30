"""Shared terminal logging for Somnia helper scripts."""

from __future__ import annotations

import logging
import os
import re
import sys
from typing import Any

try:
    from rich.console import Console
    from rich.text import Text
except ImportError:  # pragma: no cover - keeps scripts usable before pip install.
    Console = None
    Text = None


KEY_VALUE_RE = re.compile(r"\b([A-Za-z_][A-Za-z0-9_]*)=([^\s]+)")
ISO_TIMESTAMP_RE = re.compile(
    r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:Z|[+-]\d{2}:\d{2})"
)
URL_RE = re.compile(r"https?://[^\s]+")
ADDRESS_RE = re.compile(r"\b0x[a-fA-F0-9]{40}\b")
SELECTOR_RE = re.compile(r"\b0x[a-fA-F0-9]{8}\b")
LONG_HEX_RE = re.compile(r"\b0x[a-fA-F0-9]{64,}\b")

LEVEL_STYLES = {
    logging.DEBUG: "bright_black",
    logging.INFO: "bold cyan",
    logging.WARNING: "bold yellow",
    logging.ERROR: "bold red",
    logging.CRITICAL: "bold white on red",
}
STATUS_STYLES = {
    "Success": "bold green",
    "Pending": "bold yellow",
    "Failed": "bold red",
    "TimedOut": "bold red",
    "Timeout": "bold red",
    "Rejected": "bold red",
    "true": "green",
    "false": "yellow",
    "True": "green",
    "False": "yellow",
}
EXTERNAL_PREFIXES = (
    "request_",
    "callback_",
    "platform_",
    "execution_",
    "receipt_",
    "tx_hash=",
    "tx_mined_at=",
    "explorer_url=",
)
LOCAL_TIME_KEYS = {
    "run_started_at",
    "run_finished_at",
    "tx_send_started_at",
    "tx_sent_at",
    "tx_mined_at",
}
LINK_KEYS = {"explorer_url", "receipt_ui_url", "receipt_service_url", "rpc_url"}
HEX_KEYS = {
    "raw_result_hex",
    "result_hex",
    "success_result_hex",
    "failure_result_hex",
    "encoded_agent_payload_hex",
    "createRequest_calldata_hex",
}
ADDRESS_KEYS = {
    "wallet_address",
    "platform_contract",
    "callback_address",
    "validator",
}


class SomniaRichLogHandler(logging.Handler):
    """Color key-value logs without requiring call sites to use Rich markup."""

    def __init__(self) -> None:
        super().__init__()
        assert Console is not None
        no_color = os.environ.get("NO_COLOR") is not None
        force_color = os.environ.get("FORCE_COLOR") is not None and not no_color
        interactive_tty = sys.stderr.isatty() or sys.stdout.isatty()
        should_force_terminal = force_color or (interactive_tty and not no_color)
        # Rich can misdetect app terminals on stderr; force styling for real TTYs
        # while leaving redirected/piped output plain unless FORCE_COLOR is set.
        self.console = Console(
            stderr=True,
            highlight=False,
            no_color=no_color,
            force_terminal=should_force_terminal,
            color_system="truecolor" if should_force_terminal else None,
        )

    def emit(self, record: logging.LogRecord) -> None:
        try:
            message = record.getMessage()
            line = Text()
            line.append(record.levelname, style=LEVEL_STYLES.get(record.levelno, ""))
            line.append(" ")
            body = Text(message)
            stylize_log_body(body, message, record.levelno)
            line.append_text(body)
            self.console.print(line, soft_wrap=True)
            if record.exc_info:
                self.console.print_exception(show_locals=False)
        except Exception:
            self.handleError(record)


def configure_logging(level: int = logging.INFO) -> None:
    """Configure consistent colored logs, with a plain fallback if Rich is absent."""

    root_logger = logging.getLogger()
    root_logger.handlers.clear()
    root_logger.setLevel(level)

    if Console is None or Text is None:
        logging.basicConfig(level=level, format="%(levelname)s %(message)s")
        return

    handler = SomniaRichLogHandler()
    handler.setLevel(level)
    root_logger.addHandler(handler)


def stylize_log_body(body: Any, message: str, level: int) -> None:
    if level >= logging.ERROR:
        body.stylize("red")
    elif level >= logging.WARNING:
        body.stylize("yellow")
    elif message.startswith(EXTERNAL_PREFIXES):
        body.stylize("bright_green")

    apply_regex_style(body, message, ISO_TIMESTAMP_RE, "grey70")
    apply_regex_style(body, message, URL_RE, "bold underline bright_blue")
    apply_regex_style(body, message, LONG_HEX_RE, "grey70")
    apply_regex_style(body, message, ADDRESS_RE, "bright_cyan")
    apply_regex_style(body, message, SELECTOR_RE, "bright_cyan")

    for word, style in STATUS_STYLES.items():
        apply_regex_style(body, message, re.compile(rf"\b{re.escape(word)}\b"), style)

    for match in KEY_VALUE_RE.finditer(message):
        key = match.group(1)
        value = match.group(2)
        body.stylize("grey70", match.start(1), match.end(1) + 1)
        body.stylize(style_for_key_value(key, value), match.start(2), match.end(2))


def style_for_key_value(key: str, value: str) -> str:
    if key in LOCAL_TIME_KEYS or "elapsed_seconds" in key:
        return "grey70"
    if key in LINK_KEYS or value.startswith(("http://", "https://")):
        return "bold underline bright_blue"
    if key in HEX_KEYS or key.endswith("_hex"):
        return "grey70"
    if key in ADDRESS_KEYS or key.endswith("_address") or key.endswith("_contract"):
        return "bright_cyan"
    if key in {"tx_hash", "deployment_tx"}:
        return "bright_cyan"
    if key in {"final_status", "status"}:
        return STATUS_STYLES.get(value.strip("()"), "white")
    if key.startswith("decoded") or key.endswith("_decoded"):
        return "bold green"
    if key in {"request_id", "agent_id", "chain_id", "block", "receipt"}:
        return "bright_magenta"
    if key in {"dry_run", "callback_config_ready", "platform_code_present"}:
        return STATUS_STYLES.get(value, "white")
    if key in {"value", "deposit_value", "balance", "practical_deposit"}:
        return "bold white"
    if key == "raw_result_hex":
        return "grey70"
    return "bright_white"


def apply_regex_style(body: Any, message: str, pattern: re.Pattern[str], style: str) -> None:
    for match in pattern.finditer(message):
        body.stylize(style, match.start(), match.end())
