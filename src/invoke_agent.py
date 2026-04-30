"""
What: Submit one Somnia Agents request through the official platform contract.
Run:  python src/invoke_agent.py --config config.local.json --prompt "Hello"
Deps: Python 3.9+; install with `python -m pip install -r requirements.txt`.

TODO verified docs gap:
The official docs say off-chain clients can submit requests and later read
`getRequest`, but they do not define a callback-free callbackAddress /
callbackSelector convention. This script therefore refuses to spend unless both
values are explicitly configured.
"""

from __future__ import annotations

import argparse
import json
import logging
import time
from dataclasses import replace
from datetime import datetime
from decimal import Decimal
from typing import Any

import requests
from eth_abi import decode
from eth_abi import encode
from eth_account import Account
from eth_utils import function_signature_to_4byte_selector
from web3 import Web3
from web3.exceptions import ContractCustomError
from web3.exceptions import ContractLogicError
from web3.logs import DISCARD

from config_loader import AgentConfig
from config_loader import AppConfig
from config_loader import PayloadConfig
from config_loader import load_config
from config_loader import PRESET_FILES
from logging_utils import configure_logging as configure_somnia_logging
from somnia_constants import EXTRACT_STRING_SIGNATURE
from somnia_constants import FINAL_RESPONSE_STATUSES
from somnia_constants import NETWORKS
from somnia_constants import PLATFORM_ABI
from somnia_constants import RESPONSE_STATUS_LABELS


LOGGER = logging.getLogger("somnia-invoke")
TOKEN_WEI = Decimal(10) ** 18
INFER_STRING_SIGNATURE = "inferString(string,string,bool,string[])"
LLM_INFERENCE_PRESET = "llm-inference"
LLM_PARSE_WEBSITE_PRESET = "llm-parse-website"
CALLBACK_SUMMARY_ABI = [
    {
        "type": "function",
        "name": "latestRequestId",
        "stateMutability": "view",
        "inputs": [],
        "outputs": [{"type": "uint256"}],
    },
    {
        "type": "function",
        "name": "latestStatus",
        "stateMutability": "view",
        "inputs": [],
        "outputs": [{"type": "uint8"}],
    },
    {
        "type": "function",
        "name": "latestResponseCount",
        "stateMutability": "view",
        "inputs": [],
        "outputs": [{"type": "uint256"}],
    },
    {
        "type": "function",
        "name": "latestReceipt",
        "stateMutability": "view",
        "inputs": [],
        "outputs": [{"type": "uint256"}],
    },
    {
        "type": "function",
        "name": "latestResult",
        "stateMutability": "view",
        "inputs": [],
        "outputs": [{"type": "bytes"}],
    },
    {
        "type": "function",
        "name": "latestFailureResult",
        "stateMutability": "view",
        "inputs": [],
        "outputs": [{"type": "bytes"}],
    },
]
CALLBACK_EVENT_ABI = [
    {
        "type": "event",
        "name": "AgentResponseStored",
        "anonymous": False,
        "inputs": [
            {"indexed": True, "name": "requestId", "type": "uint256"},
            {"indexed": True, "name": "responseIndex", "type": "uint256"},
            {"indexed": False, "name": "status", "type": "uint8"},
            {"indexed": False, "name": "receipt", "type": "uint256"},
            {"indexed": False, "name": "validator", "type": "address"},
            {"indexed": False, "name": "executionCost", "type": "uint256"},
            {"indexed": False, "name": "result", "type": "bytes"},
        ],
    },
]


def preflight_static(config: AppConfig) -> None:
    """Fast local checks before any network call or transaction signing."""

    assert config.network in NETWORKS
    assert config.agent.agent_id >= 0
    assert config.agent.method_signature
    assert len(config.agent.input_types) == len(config.agent.args)
    assert config.agent.output_types
    assert len(PLATFORM_ABI) >= 5
    if not config.has_callback_config:
        raise SystemExit(
            "callback_address and callback_selector are required. "
            "TODO: Somnia docs do not define a callback-free convention for "
            "createRequest, so this script will not invent one."
        )


def main() -> None:
    args = parse_args()
    configure_logging()
    run_started_monotonic = time.monotonic()
    run_started_at = local_timestamp()
    tx_sent_monotonic: float | None = None
    LOGGER.info("run_started_at=%s", run_started_at)

    config = load_config(args.config, args.preset)
    config = apply_cli_overrides(config, args)
    preflight_static(config)

    network = NETWORKS[config.network]
    web3 = Web3(Web3.HTTPProvider(config.rpc_url, request_kwargs={"timeout": 20}))
    platform_address = Web3.to_checksum_address(network.platform_contract)
    platform = web3.eth.contract(address=platform_address, abi=PLATFORM_ABI)

    assert web3.is_connected(), f"Could not connect to RPC: {config.rpc_url}"
    assert web3.eth.chain_id == network.chain_id, "RPC chain ID does not match config"
    balance_wei = web3.eth.get_balance(config.wallet_address)
    LOGGER.info(
        "wallet_balance wallet_address=%s balance=%s %s",
        config.wallet_address,
        web3.from_wei(balance_wei, "ether"),
        network.native_symbol,
    )

    floor_wei = platform.functions.getRequestDeposit().call()
    reward_wei = tokens_to_wei(config.agent.per_agent_price_tokens) * (
        config.agent.subcommittee_size
    )
    deposit_wei = floor_wei + reward_wei
    payload = encode_agent_payload(config.agent)

    if args.dry_run:
        log_dry_run(
            web3=web3,
            config=config,
            platform=platform,
            payload=payload,
            value_wei=deposit_wei,
        )
        return

    account = Account.from_key(config.private_key)
    tx = build_create_request_tx(
        web3=web3,
        config=config,
        platform=platform,
        payload=payload,
        value_wei=deposit_wei,
    )
    assert_balance_covers_tx(web3, config.wallet_address, tx, network.native_symbol)

    LOGGER.info(
        "submitting createRequest agent_id=%s value=%s %s",
        config.agent.agent_id,
        web3.from_wei(deposit_wei, "ether"),
        network.native_symbol,
    )
    signed = account.sign_transaction(tx)
    raw_tx = getattr(signed, "raw_transaction", None) or getattr(signed, "rawTransaction")
    tx_send_started_monotonic = time.monotonic()
    LOGGER.info("tx_send_started_at=%s", local_timestamp())
    tx_hash = web3.eth.send_raw_transaction(raw_tx)
    tx_sent_monotonic = time.monotonic()
    tx_hash_hex = web3.to_hex(tx_hash)
    LOGGER.info(
        "tx_sent_at=%s tx_send_elapsed_seconds=%.2f",
        local_timestamp(),
        tx_sent_monotonic - tx_send_started_monotonic,
    )
    LOGGER.info("tx_hash=%s", tx_hash_hex)
    LOGGER.info("explorer_url=%s/tx/%s", network.explorer_url.rstrip("/"), tx_hash_hex)

    receipt = web3.eth.wait_for_transaction_receipt(tx_hash, timeout=180)
    assert receipt["status"] == 1, "createRequest transaction reverted"
    LOGGER.info(
        "tx_mined_at=%s tx_mined_elapsed_seconds=%.2f",
        local_timestamp(),
        time.monotonic() - tx_sent_monotonic,
    )

    request_id = decode_request_id(platform, receipt)
    LOGGER.info("request_id=%s", request_id)
    LOGGER.info(
        "receipt_ui_url=https://agents.somnia.network/receipts/%s",
        request_id,
    )
    LOGGER.info(
        "receipt_service_url=%s?requestId=%s",
        network.receipt_url.rstrip("/"),
        request_id,
    )

    request_details = wait_for_final_request(
        web3=web3,
        platform=platform,
        request_id=request_id,
        config=config,
        from_block=receipt["blockNumber"],
        poll_started_monotonic=time.monotonic(),
    )
    decode_and_log_result(request_details, config.agent)
    fetch_and_log_receipt(network.receipt_url, request_id)
    finished_monotonic = time.monotonic()
    LOGGER.info(
        "run_finished_at=%s end_to_end_elapsed_seconds=%.2f "
        "elapsed_since_tx_sent_seconds=%.2f",
        local_timestamp(),
        finished_monotonic - run_started_monotonic,
        finished_monotonic - tx_sent_monotonic,
    )


def build_create_request_tx(
    web3: Web3,
    config: AppConfig,
    platform: Any,
    payload: bytes,
    value_wei: int,
) -> dict[str, Any]:
    assert config.callback_address is not None
    assert config.callback_selector is not None

    tx_base: dict[str, Any] = {
        "from": config.wallet_address,
        "chainId": NETWORKS[config.network].chain_id,
        "nonce": web3.eth.get_transaction_count(config.wallet_address),
        "value": value_wei,
        "gas": config.gas_limit,
    }

    if (
        config.max_fee_per_gas_gwei is not None
        and config.max_priority_fee_per_gas_gwei is not None
    ):
        tx_base["maxFeePerGas"] = gwei_to_wei(config.max_fee_per_gas_gwei)
        tx_base["maxPriorityFeePerGas"] = gwei_to_wei(
            config.max_priority_fee_per_gas_gwei
        )
    else:
        tx_base["gasPrice"] = web3.eth.gas_price

    return platform.functions.createRequest(
        config.agent.agent_id,
        config.callback_address,
        config.callback_selector,
        payload,
    ).build_transaction(tx_base)


def encode_agent_payload(agent: AgentConfig) -> bytes:
    selector = function_signature_to_4byte_selector(agent.method_signature)
    encoded_args = encode(agent.input_types, agent.args)
    return selector + encoded_args


def encode_create_request_calldata(
    platform: Any,
    config: AppConfig,
    payload: bytes,
) -> str:
    assert config.callback_address is not None
    assert config.callback_selector is not None
    return platform.functions.createRequest(
        config.agent.agent_id,
        config.callback_address,
        config.callback_selector,
        payload,
    )._encode_transaction_data()


def log_dry_run(
    web3: Web3,
    config: AppConfig,
    platform: Any,
    payload: bytes,
    value_wei: int,
) -> None:
    network = NETWORKS[config.network]
    method_selector = function_signature_to_4byte_selector(
        config.agent.method_signature
    )
    calldata = encode_create_request_calldata(platform, config, payload)
    LOGGER.info("dry_run=true")
    LOGGER.info("preset=%s", config.preset_name)
    LOGGER.info("network=%s chain_id=%s", network.name, network.chain_id)
    LOGGER.info("wallet_address=%s", config.wallet_address)
    LOGGER.info("platform_contract=%s", network.platform_contract)
    LOGGER.info("agent_name=%s", config.agent.name)
    LOGGER.info("agent_id=%s", config.agent.agent_id)
    LOGGER.info("method_signature=%s", config.agent.method_signature)
    LOGGER.info("method_selector=%s", bytes_to_hex(method_selector))
    LOGGER.info("input_types=%s", json.dumps(config.agent.input_types))
    LOGGER.info("output_types=%s", json.dumps(config.agent.output_types))
    LOGGER.info("args=%s", json.dumps(config.agent.args, default=str))
    LOGGER.info("encoded_agent_payload_hex=%s", bytes_to_hex(payload))
    LOGGER.info("callback_address=%s", config.callback_address)
    LOGGER.info("callback_selector=%s", config.callback_selector)
    LOGGER.info(
        "deposit_value_wei=%s deposit_value=%s %s",
        value_wei,
        web3.from_wei(value_wei, "ether"),
        network.native_symbol,
    )
    LOGGER.info("createRequest_calldata_hex=%s", calldata)


def decode_request_id(platform: Any, receipt: Any) -> int:
    created_events = platform.events.RequestCreated().process_receipt(receipt)
    assert created_events, "RequestCreated event was not found in transaction receipt"
    return int(created_events[0]["args"]["requestId"])


def wait_for_final_request(
    web3: Web3,
    platform: Any,
    request_id: int,
    config: AppConfig,
    from_block: int,
    poll_started_monotonic: float,
) -> Any:
    deadline = time.monotonic() + config.max_wait_seconds
    while time.monotonic() < deadline:
        if not platform.functions.hasRequest(request_id).call():
            final_event = find_finalization_event(
                platform=platform,
                request_id=request_id,
                from_block=from_block,
                to_block=web3.eth.block_number,
            )
            if final_event is not None:
                status = int(final_event["args"]["status"])
                LOGGER.info(
                    "request_finalized_event status=%s (%s) block=%s tx_hash=%s",
                    status,
                    RESPONSE_STATUS_LABELS.get(status, "unknown"),
                    final_event["blockNumber"],
                    web3.to_hex(final_event["transactionHash"]),
                )
                return finalized_event_snapshot(
                    web3=web3,
                    config=config,
                    request_id=request_id,
                    status=status,
                    final_event=final_event,
                )
            raise RuntimeError(
                f"Platform no longer has request {request_id}, and no "
                "RequestFinalized event was found in the searched block range."
            )

        try:
            details = platform.functions.getRequest(request_id).call()
        except (ContractCustomError, ContractLogicError) as exc:
            final_event = find_finalization_event(
                platform=platform,
                request_id=request_id,
                from_block=from_block,
                to_block=web3.eth.block_number,
            )
            if final_event is not None:
                status = int(final_event["args"]["status"])
                LOGGER.info(
                    "getRequest_unavailable_after_finalization error=%s",
                    exc,
                )
                LOGGER.info(
                    "request_finalized_event status=%s (%s) block=%s tx_hash=%s",
                    status,
                    RESPONSE_STATUS_LABELS.get(status, "unknown"),
                    final_event["blockNumber"],
                    web3.to_hex(final_event["transactionHash"]),
                )
                return finalized_event_snapshot(
                    web3=web3,
                    config=config,
                    request_id=request_id,
                    status=status,
                    final_event=final_event,
                )
            raise

        status = int(get_field(details, "status", 11))
        LOGGER.info(
            "request_status=%s (%s) poll_elapsed_seconds=%.2f",
            status,
            RESPONSE_STATUS_LABELS.get(status, "unknown"),
            time.monotonic() - poll_started_monotonic,
        )
        if status in FINAL_RESPONSE_STATUSES:
            snapshot = normalize_request_details(details)
            final_event = find_finalization_event(
                platform=platform,
                request_id=request_id,
                from_block=from_block,
                to_block=web3.eth.block_number,
            )
            if final_event is not None:
                LOGGER.info(
                    "request_finalized_event status=%s (%s) block=%s tx_hash=%s",
                    int(final_event["args"]["status"]),
                    RESPONSE_STATUS_LABELS.get(
                        int(final_event["args"]["status"]), "unknown"
                    ),
                    final_event["blockNumber"],
                    web3.to_hex(final_event["transactionHash"]),
                )
                snapshot["callback_events"] = read_callback_events_from_finalization_tx(
                    web3=web3,
                    callback_address=config.callback_address,
                    request_id=request_id,
                    final_event=final_event,
                )
            else:
                snapshot["callback_events"] = []
            snapshot["callback_summary"] = read_callback_summary(
                web3=web3,
                callback_address=config.callback_address,
                request_id=request_id,
            )
            return snapshot
        time.sleep(config.poll_seconds)
    raise TimeoutError(f"Request {request_id} did not finalize in time")


def finalized_event_snapshot(
    web3: Web3,
    config: AppConfig,
    request_id: int,
    status: int,
    final_event: Any,
) -> dict[str, Any]:
    return {
        "status": status,
        "responses": [],
        "callback_events": read_callback_events_from_finalization_tx(
            web3=web3,
            callback_address=config.callback_address,
            request_id=request_id,
            final_event=final_event,
        ),
        "callback_summary": read_callback_summary(
            web3=web3,
            callback_address=config.callback_address,
            request_id=request_id,
        ),
    }


def find_finalization_event(
    platform: Any,
    request_id: int,
    from_block: int,
    to_block: int,
) -> Any | None:
    """Find RequestFinalized despite Somnia RPC's small log block-range limit."""

    matched_events: list[Any] = []
    for start_block in range(from_block, to_block + 1, 900):
        end_block = min(start_block + 899, to_block)
        matched_events.extend(
            platform.events.RequestFinalized().get_logs(
                from_block=start_block,
                to_block=end_block,
                argument_filters={"requestId": request_id},
            )
        )
    if not matched_events:
        return None
    return matched_events[-1]


def decode_and_log_result(details: dict[str, Any], agent: AgentConfig) -> None:
    status = int(details["status"])
    responses = details["responses"]
    callback_events = details.get("callback_events", [])
    callback_summary = details.get("callback_summary")
    LOGGER.info("final_status=%s", RESPONSE_STATUS_LABELS.get(status, status))
    LOGGER.info("response_count=%s", len(responses))
    LOGGER.info("callback_event_count=%s", len(callback_events))

    for event in callback_events:
        log_response_evidence("callback_response", event)
        if int(event["status"]) != 2:
            log_failure_decoders(
                "callback_response",
                event["index"],
                event["result_bytes"],
            )

    if not callback_events:
        for index, response in enumerate(responses):
            evidence = dict(response)
            evidence["index"] = index
            log_response_evidence("platform_response", evidence)
            if int(evidence["status"]) != 2:
                log_failure_decoders(
                    "platform_response",
                    index,
                    evidence["result_bytes"],
                )

    if callback_summary is not None:
        LOGGER.info(
            "callback_latest request_id=%s status=%s (%s) response_count=%s "
            "receipt=%s success_result_hex=%s failure_result_hex=%s",
            callback_summary["request_id"],
            callback_summary["status"],
            RESPONSE_STATUS_LABELS.get(callback_summary["status"], "unknown"),
            callback_summary["response_count"],
            callback_summary["receipt"],
            callback_summary["result_hex"],
            callback_summary["failure_result_hex"],
        )
        if callback_summary["failure_result_bytes"]:
            log_failure_decoders(
                "callback_latest_failure",
                -1,
                callback_summary["failure_result_bytes"],
            )

    for response in responses:
        if int(response["status"]) != 2:
            continue
        decoded = decode_agent_result(agent, response["result_bytes"])
        LOGGER.info("decoded_result=%s", format_decoded_value(decoded))
        return

    for event in callback_events:
        if int(event["status"]) != 2:
            continue
        decoded = decode_agent_result(agent, event["result_bytes"])
        LOGGER.info("decoded_callback_event_result=%s", format_decoded_value(decoded))
        return

    if callback_summary is not None and callback_summary["result_bytes"]:
        decoded = decode_agent_result(agent, callback_summary["result_bytes"])
        LOGGER.info("decoded_callback_result=%s", format_decoded_value(decoded))
        return

    LOGGER.warning("No successful response result was available to decode")


def normalize_request_details(details: Any) -> dict[str, Any]:
    responses = get_field(details, "responses", 5)
    return {
        "status": int(get_field(details, "status", 11)),
        "responses": [normalize_response(response) for response in responses],
    }


def normalize_response(response: Any) -> dict[str, Any]:
    result_bytes = bytes(get_field(response, "result", 1))
    return {
        "validator": get_field(response, "validator", 0),
        "result_bytes": result_bytes,
        "result_hex": bytes_to_hex(result_bytes),
        "status": int(get_field(response, "status", 2)),
        "receipt": int(get_field(response, "receipt", 3)),
        "timestamp": int(get_field(response, "timestamp", 4)),
        "execution_cost": int(get_field(response, "executionCost", 5)),
    }


def get_field(value: Any, name: str, index: int) -> Any:
    try:
        return value[name]
    except (KeyError, TypeError):
        return value[index]


def read_callback_events_from_finalization_tx(
    web3: Web3,
    callback_address: str | None,
    request_id: int,
    final_event: Any,
) -> list[dict[str, Any]]:
    if callback_address is None:
        return []
    callback = web3.eth.contract(
        address=Web3.to_checksum_address(callback_address),
        abi=CALLBACK_EVENT_ABI,
    )
    tx_receipt = web3.eth.get_transaction_receipt(final_event["transactionHash"])
    events = callback.events.AgentResponseStored().process_receipt(
        tx_receipt,
        errors=DISCARD,
    )
    parsed: list[dict[str, Any]] = []
    for event in events:
        event_args = event["args"]
        if int(event_args["requestId"]) != request_id:
            continue
        result_bytes = bytes(event_args["result"])
        parsed.append(
            {
                "index": int(event_args["responseIndex"]),
                "status": int(event_args["status"]),
                "receipt": int(event_args["receipt"]),
                "validator": event_args["validator"],
                "execution_cost": int(event_args["executionCost"]),
                "result_bytes": result_bytes,
                "result_hex": bytes_to_hex(result_bytes),
            }
        )
    return sorted(parsed, key=lambda item: item["index"])


def log_response_evidence(prefix: str, response: dict[str, Any]) -> None:
    status = int(response["status"])
    LOGGER.info(
        "%s index=%s status=%s (%s) receipt=%s validator=%s "
        "execution_cost=%s raw_result_hex=%s",
        prefix,
        response["index"],
        status,
        RESPONSE_STATUS_LABELS.get(status, "unknown"),
        response["receipt"],
        response["validator"],
        response["execution_cost"],
        response["result_hex"],
    )


def log_failure_decoders(prefix: str, index: int, result_bytes: bytes) -> None:
    if not result_bytes:
        return
    for kind, value in decode_failure_result(result_bytes):
        LOGGER.info(
            "%s_decoded index=%s kind=%s value=%s",
            prefix,
            index,
            kind,
            format_decoded_value(value),
        )


def decode_failure_result(result_bytes: bytes) -> list[tuple[str, Any]]:
    decoded: list[tuple[str, Any]] = []
    try:
        decoded.append(("abi_string", decode(["string"], result_bytes)[0]))
    except Exception:
        pass

    try:
        utf8_text = result_bytes.decode("utf-8")
    except UnicodeDecodeError:
        utf8_text = None
    if utf8_text is not None and is_readable_text(utf8_text):
        decoded.append(("utf8", utf8_text))
        try:
            decoded.append(("json", json.loads(utf8_text)))
        except json.JSONDecodeError:
            pass

    if result_bytes.startswith(bytes.fromhex("08c379a0")):
        try:
            decoded.append(("solidity_error", decode(["string"], result_bytes[4:])[0]))
        except Exception:
            pass
    return decoded


def is_readable_text(value: str) -> bool:
    return all(char in "\n\r\t" or ord(char) >= 32 for char in value)


def decode_agent_result(agent: AgentConfig, result_bytes: bytes) -> Any:
    decoded = decode(agent.output_types, result_bytes)
    if len(decoded) == 1:
        return decoded[0]
    return list(decoded)


def format_decoded_value(value: Any) -> str:
    if isinstance(value, (dict, list, tuple)):
        return json.dumps(value, default=str)
    return str(value)


def bytes_to_hex(value: bytes) -> str:
    return "0x" + bytes(value).hex()


def read_callback_summary(
    web3: Web3,
    callback_address: str | None,
    request_id: int,
) -> dict[str, Any] | None:
    if callback_address is None:
        return None
    callback = web3.eth.contract(
        address=Web3.to_checksum_address(callback_address),
        abi=CALLBACK_SUMMARY_ABI,
    )
    latest_request_id = int(callback.functions.latestRequestId().call())
    if latest_request_id != request_id:
        return {
            "request_id": latest_request_id,
            "status": int(callback.functions.latestStatus().call()),
            "response_count": int(callback.functions.latestResponseCount().call()),
            "receipt": int(callback.functions.latestReceipt().call()),
            "result_bytes": b"",
            "result_hex": "0x",
            "failure_result_bytes": b"",
            "failure_result_hex": "0x",
        }
    result_bytes = bytes(callback.functions.latestResult().call())
    try:
        failure_result_bytes = bytes(callback.functions.latestFailureResult().call())
    except (ContractCustomError, ContractLogicError, ValueError):
        failure_result_bytes = b""
    return {
        "request_id": latest_request_id,
        "status": int(callback.functions.latestStatus().call()),
        "response_count": int(callback.functions.latestResponseCount().call()),
        "receipt": int(callback.functions.latestReceipt().call()),
        "result_bytes": result_bytes,
        "result_hex": bytes_to_hex(result_bytes),
        "failure_result_bytes": failure_result_bytes,
        "failure_result_hex": bytes_to_hex(failure_result_bytes),
    }


def fetch_and_log_receipt(receipt_base_url: str, request_id: int) -> None:
    response = requests.get(
        receipt_base_url,
        params={"requestId": str(request_id)},
        timeout=20,
    )
    if response.status_code == 404:
        LOGGER.warning("execution receipt is not available yet")
        return
    response.raise_for_status()
    receipt_json = response.json()
    LOGGER.info("execution_receipt=%s", json.dumps(receipt_json, indent=2))


def assert_balance_covers_tx(
    web3: Web3,
    wallet_address: str,
    tx: dict[str, Any],
    native_symbol: str,
) -> None:
    gas_price = tx.get("gasPrice") or tx.get("maxFeePerGas")
    assert gas_price is not None, "Transaction has no gas price"
    needed = int(tx["value"]) + int(tx["gas"]) * int(gas_price)
    balance = web3.eth.get_balance(wallet_address)
    assert balance >= needed, (
        f"Insufficient balance: need about {web3.from_wei(needed, 'ether')} "
        f"{native_symbol}, have {web3.from_wei(balance, 'ether')} {native_symbol}"
    )


def tokens_to_wei(tokens: Decimal | None) -> int:
    assert tokens is not None, "per_agent_price_tokens is required"
    return int(tokens * TOKEN_WEI)


def gwei_to_wei(value: Decimal) -> int:
    return int(value * (Decimal(10) ** 9))


def local_timestamp() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def apply_cli_overrides(config: AppConfig, args: argparse.Namespace) -> AppConfig:
    if config.preset_name == LLM_INFERENCE_PRESET:
        assert (
            args.url is None
            and args.resolve_url is None
            and args.num_pages is None
            and args.confidence_threshold is None
        ), (
            "--url, --resolve-url, --no-resolve-url, --num-pages, and "
            "--confidence-threshold only apply to --preset llm-parse-website"
        )
        return build_llm_inference_config(config, args.prompt, args.system)
    if config.preset_name == LLM_PARSE_WEBSITE_PRESET:
        assert args.system is None, "--system only applies to --preset llm-inference"
        return build_llm_parse_website_config(
            config=config,
            prompt=args.prompt,
            url=args.url,
            resolve_url=args.resolve_url,
            num_pages=args.num_pages,
            confidence_threshold=args.confidence_threshold,
        )
    raise AssertionError(f"Unsupported preset for CLI overrides: {config.preset_name}")


def build_llm_inference_config(
    config: AppConfig,
    prompt: str | None,
    system: str | None,
) -> AppConfig:
    assert config.agent.method_signature == INFER_STRING_SIGNATURE, (
        "llm-inference preset must use inferString(string,string,bool,string[])"
    )
    agent_args = list(config.agent.args)
    assert len(agent_args) == 4, "llm-inference preset args must have length 4"
    if prompt is not None:
        agent_args[0] = prompt
    if system is not None:
        agent_args[1] = system
    return replace(config, agent=replace(config.agent, args=agent_args))


def build_llm_parse_website_config(
    config: AppConfig,
    prompt: str | None,
    url: str | None,
    resolve_url: bool | None,
    num_pages: int | None,
    confidence_threshold: int | None,
) -> AppConfig:
    assert config.agent.method_signature == EXTRACT_STRING_SIGNATURE, (
        "llm-parse-website preset must use ExtractString(...)"
    )

    payload = PayloadConfig(
        key=config.payload.key,
        description=config.payload.description,
        options=config.payload.options,
        prompt=prompt if prompt is not None else config.payload.prompt,
        url=url if url is not None else config.payload.url,
        resolve_url=(
            resolve_url if resolve_url is not None else config.payload.resolve_url
        ),
        num_pages=num_pages if num_pages is not None else config.payload.num_pages,
        confidence_threshold=(
            confidence_threshold
            if confidence_threshold is not None
            else config.payload.confidence_threshold
        ),
    )
    assert payload.num_pages <= 10, "--num-pages should stay small for a minimal invoke"
    agent_args = [
        payload.key,
        payload.description,
        payload.options,
        payload.prompt,
        payload.url,
        payload.resolve_url,
        payload.num_pages,
        payload.confidence_threshold,
    ]
    return replace(
        config,
        payload=payload,
        agent=replace(config.agent, args=agent_args),
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Submit one Somnia Agent request")
    parser.add_argument("--config", required=True, help="Path to ignored local config")
    parser.add_argument(
        "--preset",
        required=True,
        choices=sorted(PRESET_FILES),
        help="Agent preset to invoke",
    )
    parser.add_argument("--prompt", help="Override payload.prompt from config")
    parser.add_argument(
        "--system",
        help="Override the llm-inference system/context string",
    )
    parser.add_argument("--url", help="Override llm-parse-website URL")
    parser.add_argument(
        "--resolve-url",
        dest="resolve_url",
        action="store_true",
        default=None,
        help="Enable llm-parse-website URL resolution/search",
    )
    parser.add_argument(
        "--no-resolve-url",
        dest="resolve_url",
        action="store_false",
        help="Disable llm-parse-website URL resolution/search",
    )
    parser.add_argument(
        "--num-pages",
        type=int,
        help="Override llm-parse-website page count",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print encoded request details without signing or submitting",
    )
    parser.add_argument(
    "--confidence-threshold",
    type=int,
    dest="confidence_threshold",
    help="Override llm-parse-website confidence threshold (uint8)",
    )
    return parser.parse_args()


def configure_logging() -> None:
    configure_somnia_logging(logging.INFO)


if __name__ == "__main__":
    main()
