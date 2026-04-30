"""
What: Load ignored local Somnia Agent config plus private key from environment.
Run:  Imported by `python src/preflight.py --config config.local.json`.
Deps: Python 3.9+ and web3.py from `requirements.txt`.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any

from eth_account import Account
from web3 import Web3

from somnia_constants import DEFAULT_SUBCOMMITTEE_SIZE
from somnia_constants import EXTRACT_STRING_OUTPUT_TYPES
from somnia_constants import EXTRACT_STRING_SIGNATURE
from somnia_constants import LLM_PARSE_WEBSITE_PRICE_TOKENS
from somnia_constants import NETWORKS
from somnia_constants import VERIFIED_AGENT_ID
from somnia_constants import VERIFIED_AGENT_METHOD
from somnia_constants import VERIFIED_AGENT_TYPE


@dataclass(frozen=True)
class AgentConfig:
    """ABI and pricing metadata for one Somnia Agent Explorer method."""

    name: str
    agent_id: int
    method_signature: str
    input_types: list[str]
    output_types: list[str]
    args: list[Any]
    per_agent_price_tokens: Decimal
    subcommittee_size: int

    @property
    def method(self) -> str:
        return self.method_signature.split("(", 1)[0]

    @property
    def agent_type(self) -> str:
        return self.name


@dataclass(frozen=True)
class PayloadConfig:
    """Payload for the verified LLM Parse Website `ExtractString` method."""

    key: str
    description: str
    options: list[str]
    prompt: str
    url: str
    resolve_url: bool
    num_pages: int
    confidence_threshold: int


@dataclass(frozen=True)
class AppConfig:
    """Complete runtime config with private key deliberately excluded from repr."""

    config_path: Path
    preset_name: str
    preset_path: Path | None
    private_key: str
    wallet_address: str
    network: str
    rpc_url: str
    agent: AgentConfig
    callback_address: str | None
    callback_selector: str | None
    payload: PayloadConfig
    poll_seconds: int
    max_wait_seconds: int
    gas_limit: int
    max_fee_per_gas_gwei: Decimal | None
    max_priority_fee_per_gas_gwei: Decimal | None

    def __repr__(self) -> str:
        return (
            "AppConfig("
            f"config_path={self.config_path!s}, "
            f"preset_name={self.preset_name}, "
            f"wallet_address={self.wallet_address}, "
            f"network={self.network}, "
            f"rpc_url={self.rpc_url}, "
            f"agent={self.agent}, "
            "private_key=<redacted>)"
        )

    @property
    def has_callback_config(self) -> bool:
        return self.callback_address is not None and self.callback_selector is not None


PRESET_DIR = Path(__file__).resolve().parent.parent / "configs"
PRESET_FILES = {
    "llm-inference": "llm_inference.json",
    "llm-parse-website": "llm_parse_website.json",
}


def load_config(path: str | Path, preset_name: str | None = None) -> AppConfig:
    """Load non-secret JSON config, derive wallet address, and fail before RPC."""

    config_path = Path(path)
    assert config_path.exists(), f"Config file does not exist: {config_path}"
    raw = json.loads(config_path.read_text(encoding="utf-8"))
    assert isinstance(raw, dict), "Config root must be a JSON object"
    preset_path = _resolve_preset_path(preset_name)
    preset_raw = _load_preset_raw(preset_path) if preset_path is not None else {}

    assert "private_key" not in raw, (
        "Do not store private_key in JSON. Put SOMNIA_PRIVATE_KEY in .env.local "
        "and load it before running the scripts."
    )

    private_key = _require_private_key_from_env()
    derived_address = Account.from_key(private_key).address
    wallet_address = _resolve_wallet_address(raw.get("wallet_address"), derived_address)

    network = _require_str(raw, "network", default="testnet").lower()
    assert network in NETWORKS, f"network must be one of: {', '.join(NETWORKS)}"

    rpc_url = raw.get("rpc_url") or NETWORKS[network].rpc_url
    assert isinstance(rpc_url, str) and rpc_url.startswith("http"), (
        "rpc_url must be null or an HTTP(S) URL"
    )

    callback_address = _optional_address(raw.get("callback_address"), "callback_address")
    callback_selector = _optional_bytes4(raw.get("callback_selector"))

    payload_raw = _merged_section(preset_raw, raw, "payload")
    assert isinstance(payload_raw, dict), "payload must be an object"
    payload = _load_payload_config(payload_raw)

    agent_raw = (
        preset_raw.get("agent") if preset_path is not None else raw.get("agent", {})
    )
    assert isinstance(agent_raw, dict), "agent must be an object"
    agent = _load_agent_config(agent_raw, payload)

    return AppConfig(
        config_path=config_path,
        preset_name=preset_name or agent.name,
        preset_path=preset_path,
        private_key=private_key,
        wallet_address=wallet_address,
        network=network,
        rpc_url=rpc_url,
        agent=agent,
        callback_address=callback_address,
        callback_selector=callback_selector,
        payload=payload,
        poll_seconds=_require_int(raw, "poll_seconds", default=15, minimum=1),
        max_wait_seconds=_require_int(raw, "max_wait_seconds", default=1200, minimum=1),
        gas_limit=_require_int(raw, "gas_limit", default=500000, minimum=21000),
        max_fee_per_gas_gwei=_optional_decimal(raw.get("max_fee_per_gas_gwei")),
        max_priority_fee_per_gas_gwei=_optional_decimal(
            raw.get("max_priority_fee_per_gas_gwei")
        ),
    )


def _resolve_preset_path(preset_name: str | None) -> Path | None:
    if preset_name in (None, ""):
        return None
    assert preset_name in PRESET_FILES, (
        "Unknown preset "
        f"{preset_name!r}. Expected one of: {', '.join(sorted(PRESET_FILES))}"
    )
    preset_path = PRESET_DIR / PRESET_FILES[preset_name]
    assert preset_path.exists(), f"Preset file does not exist: {preset_path}"
    return preset_path


def _load_preset_raw(preset_path: Path) -> dict[str, Any]:
    raw = json.loads(preset_path.read_text(encoding="utf-8"))
    assert isinstance(raw, dict), "Preset root must be a JSON object"
    forbidden = {
        "private_key",
        "wallet_address",
        "network",
        "rpc_url",
        "callback_address",
        "callback_selector",
    }
    present = sorted(key for key in forbidden if key in raw)
    assert not present, (
        "Preset files must not contain local/private settings: "
        + ", ".join(present)
    )
    assert isinstance(raw.get("agent"), dict), "Preset must contain agent object"
    return raw


def _merged_section(
    preset_raw: dict[str, Any],
    local_raw: dict[str, Any],
    key: str,
) -> dict[str, Any]:
    preset_section = preset_raw.get(key, {})
    local_section = local_raw.get(key, {})
    assert isinstance(preset_section, dict), f"preset {key} must be an object"
    assert isinstance(local_section, dict), f"{key} must be an object"
    return {**preset_section, **local_section}


def _load_agent_config(raw: dict[str, Any], payload: PayloadConfig) -> AgentConfig:
    name_default = raw.get("agent_type", VERIFIED_AGENT_TYPE)
    name = _require_str(raw, "name", default=name_default)
    agent_id = _require_uint256(raw, "agent_id", default=VERIFIED_AGENT_ID)
    method_signature = _resolve_method_signature(raw)
    method_name, signature_input_types = _parse_method_signature(method_signature)
    legacy_method = raw.get("method")
    if legacy_method not in (None, ""):
        assert isinstance(legacy_method, str), "agent.method must be a string"
        assert legacy_method.strip() == method_name, (
            "agent.method must match agent.method_signature"
        )

    is_default_parse_website = (
        name == VERIFIED_AGENT_TYPE
        and agent_id == VERIFIED_AGENT_ID
        and method_signature == EXTRACT_STRING_SIGNATURE
    )
    input_types = _load_string_list(
        raw.get("input_types"),
        "agent.input_types",
        default=signature_input_types,
    )
    assert input_types == signature_input_types, (
        "agent.input_types must match agent.method_signature"
    )

    output_types_default = (
        EXTRACT_STRING_OUTPUT_TYPES if is_default_parse_website else None
    )
    output_types = _load_string_list(
        raw.get("output_types"),
        "agent.output_types",
        default=output_types_default,
    )

    args_value = raw.get("args")
    if args_value is None:
        assert is_default_parse_website, (
            "agent.args is required for non-default agent configs"
        )
        args = _payload_to_extract_string_args(payload)
    else:
        assert isinstance(args_value, list), "agent.args must be a list"
        args = args_value
    assert len(args) == len(input_types), (
        "agent.args length must match agent.input_types length"
    )

    price = _optional_decimal(raw.get("per_agent_price_tokens"))
    if price is None:
        assert is_default_parse_website, (
            "agent.per_agent_price_tokens is required for non-default agents"
        )
        price = Decimal(LLM_PARSE_WEBSITE_PRICE_TOKENS)

    if "subcommittee_size" in raw:
        subcommittee_size = _require_int(
            raw,
            "subcommittee_size",
            default=DEFAULT_SUBCOMMITTEE_SIZE,
            minimum=1,
        )
    else:
        assert is_default_parse_website, (
            "agent.subcommittee_size is required for non-default agents"
        )
        subcommittee_size = DEFAULT_SUBCOMMITTEE_SIZE

    return AgentConfig(
        name=name,
        agent_id=agent_id,
        method_signature=method_signature,
        input_types=input_types,
        output_types=output_types,
        args=args,
        per_agent_price_tokens=price,
        subcommittee_size=subcommittee_size,
    )


def _resolve_method_signature(raw: dict[str, Any]) -> str:
    value = raw.get("method_signature")
    if value not in (None, ""):
        assert isinstance(value, str), "agent.method_signature must be a string"
        return value.strip()

    method = raw.get("method", VERIFIED_AGENT_METHOD)
    assert isinstance(method, str), "agent.method must be a string"
    assert method.strip() == VERIFIED_AGENT_METHOD, (
        "agent.method_signature is required for custom agent methods"
    )
    return EXTRACT_STRING_SIGNATURE


def _payload_to_extract_string_args(payload: PayloadConfig) -> list[Any]:
    return [
        payload.key,
        payload.description,
        payload.options,
        payload.prompt,
        payload.url,
        payload.resolve_url,
        payload.num_pages,
        payload.confidence_threshold,
    ]


def _load_payload_config(raw: dict[str, Any]) -> PayloadConfig:
    options = raw.get("options", [])
    assert isinstance(options, list) and all(isinstance(item, str) for item in options), (
        "payload.options must be a list of strings"
    )

    num_pages = _require_int(raw, "num_pages", default=3, minimum=1)
    assert num_pages <= 10, "payload.num_pages should stay small for a minimal invoke"
    confidence_threshold = _require_int(
        raw, "confidence_threshold", default=1, minimum=0, maximum=255
    )

    return PayloadConfig(
        key=_require_str(raw, "key", default="answer"),
        description=_require_str(raw, "description", default="A short answer."),
        options=options,
        prompt=_require_str(raw, "prompt", default="What is Somnia?"),
        url=_require_str(raw, "url", default="docs.somnia.network"),
        resolve_url=_require_bool(raw, "resolve_url", default=True),
        num_pages=num_pages,
        confidence_threshold=confidence_threshold,
    )


def _require_private_key_from_env() -> str:
    value = os.environ.get("SOMNIA_PRIVATE_KEY", "").strip()
    assert value, (
        "SOMNIA_PRIVATE_KEY is not set. Run: set -a; source .env.local; set +a"
    )
    assert value.startswith("0x"), "SOMNIA_PRIVATE_KEY must start with 0x"
    assert len(value) == 66, "SOMNIA_PRIVATE_KEY must be 32 bytes hex encoded"
    int(value[2:], 16)
    return value


def _resolve_wallet_address(configured: Any, derived: str) -> str:
    if configured in (None, ""):
        return Web3.to_checksum_address(derived)
    wallet_address = _optional_address(configured, "wallet_address")
    assert wallet_address is not None
    assert wallet_address == Web3.to_checksum_address(derived), (
        "wallet_address does not match private_key-derived address"
    )
    return wallet_address


def _optional_address(value: Any, field_name: str) -> str | None:
    if value in (None, ""):
        return None
    assert isinstance(value, str), f"{field_name} must be a string or null"
    assert Web3.is_address(value), f"{field_name} is not a valid EVM address"
    return Web3.to_checksum_address(value)


def _optional_bytes4(value: Any) -> str | None:
    if value in (None, ""):
        return None
    assert isinstance(value, str), "callback_selector must be a hex string or null"
    assert value.startswith("0x") and len(value) == 10, (
        "callback_selector must be exactly 4 bytes, e.g. 0x12345678"
    )
    int(value[2:], 16)
    return value.lower()


def _require_uint256(raw: dict[str, Any], key: str, default: int) -> int:
    value = raw.get(key, default)
    if isinstance(value, str):
        assert value.isdecimal(), f"{key} must be a decimal string or integer"
        parsed = int(value)
    else:
        assert isinstance(value, int), f"{key} must be a decimal string or integer"
        parsed = value
    assert 0 <= parsed < 2**256, f"{key} must fit uint256"
    return parsed


def _load_string_list(
    value: Any,
    field_name: str,
    default: list[str] | None,
) -> list[str]:
    if value is None:
        assert default is not None, f"{field_name} is required"
        return list(default)
    assert isinstance(value, list) and all(isinstance(item, str) for item in value), (
        f"{field_name} must be a list of strings"
    )
    assert all(item.strip() == item and item for item in value), (
        f"{field_name} entries must be non-empty canonical ABI type strings"
    )
    return list(value)


def _parse_method_signature(signature: str) -> tuple[str, list[str]]:
    assert signature.strip() == signature and signature, (
        "agent.method_signature must be a canonical ABI signature"
    )
    assert "(" in signature and signature.endswith(")"), (
        "agent.method_signature must look like Method(type,type)"
    )
    method_name, raw_types = signature.split("(", 1)
    assert method_name, "agent.method_signature method name is empty"
    assert " " not in method_name, "agent.method_signature must not contain spaces"
    types_text = raw_types[:-1]
    if types_text == "":
        return method_name, []
    input_types = _split_top_level_types(types_text)
    assert all(item for item in input_types), (
        "agent.method_signature contains an empty input type"
    )
    return method_name, input_types


def _split_top_level_types(types_text: str) -> list[str]:
    types: list[str] = []
    current: list[str] = []
    depth = 0
    for char in types_text:
        if char == "," and depth == 0:
            types.append("".join(current))
            current = []
            continue
        if char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
            assert depth >= 0, "agent.method_signature has unbalanced parentheses"
        current.append(char)
    assert depth == 0, "agent.method_signature has unbalanced parentheses"
    types.append("".join(current))
    return types


def _require_str(raw: dict[str, Any], key: str, default: str | None = None) -> str:
    value = raw.get(key, default)
    assert isinstance(value, str) and value.strip(), f"{key} must be a non-empty string"
    return value.strip()


def _require_bool(raw: dict[str, Any], key: str, default: bool) -> bool:
    value = raw.get(key, default)
    assert isinstance(value, bool), f"{key} must be a boolean"
    return value


def _require_int(
    raw: dict[str, Any],
    key: str,
    default: int,
    minimum: int,
    maximum: int | None = None,
) -> int:
    value = raw.get(key, default)
    assert isinstance(value, int), f"{key} must be an integer"
    assert value >= minimum, f"{key} must be >= {minimum}"
    if maximum is not None:
        assert value <= maximum, f"{key} must be <= {maximum}"
    return value


def _optional_decimal(value: Any, default: Decimal | None = None) -> Decimal | None:
    if value in (None, ""):
        return default
    assert isinstance(value, (str, int)), (
        "decimal config values must be strings or ints"
    )
    parsed = Decimal(str(value))
    assert parsed >= 0, "decimal config values must be non-negative"
    return parsed
