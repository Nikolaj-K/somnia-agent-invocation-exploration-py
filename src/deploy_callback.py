"""
What: Compile and deploy the minimal Somnia Agent callback contract.
Run:  python src/deploy_callback.py --config config.local.json
Deps: Python 3.9+; install with `python -m pip install -r requirements.txt`.

This is a small deployment helper for `contracts/SomniaAgentCallback.sol`.
It spends gas but does not invoke an agent.
"""

from __future__ import annotations

import argparse
import logging
from pathlib import Path
from typing import Any

from solcx import compile_source
from solcx import install_solc
from web3 import Web3

from config_loader import load_config
from logging_utils import configure_logging as configure_somnia_logging
from somnia_constants import NETWORKS


LOGGER = logging.getLogger("somnia-deploy-callback")
CONTRACT_PATH = Path("contracts/SomniaAgentCallback.sol")
SOLC_VERSION = "0.8.20"
SOLCX_DIR = Path(".solcx")
SOLC_BINARY = SOLCX_DIR / f"solc-v{SOLC_VERSION}"


def main() -> None:
    args = parse_args()
    configure_logging()

    config = load_config(args.config)
    network = NETWORKS[config.network]
    web3 = Web3(Web3.HTTPProvider(config.rpc_url, request_kwargs={"timeout": 20}))

    assert web3.is_connected(), f"Could not connect to RPC: {config.rpc_url}"
    assert web3.eth.chain_id == network.chain_id, "RPC chain ID does not match config"

    contract_interface = compile_callback_contract()
    contract_factory = web3.eth.contract(
        abi=contract_interface["abi"],
        bytecode=contract_interface["bin"],
    )
    platform_address = Web3.to_checksum_address(network.platform_contract)

    tx = build_deploy_tx(
        web3=web3,
        config=config,
        contract_factory=contract_factory,
        platform_address=platform_address,
    )
    assert_balance_covers_tx(web3, config.wallet_address, tx, network.native_symbol)

    signed = web3.eth.account.sign_transaction(tx, private_key=config.private_key)
    raw_tx = getattr(signed, "raw_transaction", None) or getattr(signed, "rawTransaction")
    tx_hash = web3.eth.send_raw_transaction(raw_tx)
    tx_hash_hex = web3.to_hex(tx_hash)
    LOGGER.info("deployment_tx=%s", tx_hash_hex)
    LOGGER.info("explorer_url=%s/tx/%s", network.explorer_url.rstrip("/"), tx_hash_hex)

    receipt = web3.eth.wait_for_transaction_receipt(tx_hash, timeout=180)
    assert receipt["status"] == 1, "Callback deployment reverted"
    contract_address = Web3.to_checksum_address(receipt["contractAddress"])
    code = web3.eth.get_code(contract_address)
    assert len(code) > 0, "No callback contract code found after deployment"

    deployed = web3.eth.contract(
        address=contract_address,
        abi=contract_interface["abi"],
    )
    selector = deployed.functions.handleResponseSelector().call().hex()
    if not selector.startswith("0x"):
        selector = "0x" + selector

    LOGGER.info("callback_address=%s", contract_address)
    LOGGER.info("callback_selector=%s", selector)
    LOGGER.info("Paste these into config.local.json:")
    LOGGER.info('"callback_address": "%s",', contract_address)
    LOGGER.info('"callback_selector": "%s"', selector)


def compile_callback_contract() -> dict[str, Any]:
    assert CONTRACT_PATH.exists(), f"Missing contract: {CONTRACT_PATH}"
    SOLCX_DIR.mkdir(exist_ok=True)
    if not SOLC_BINARY.exists():
        try:
            install_solc(SOLC_VERSION, solcx_binary_path=SOLCX_DIR)
        except Exception:
            if not SOLC_BINARY.exists():
                raise
    source = CONTRACT_PATH.read_text(encoding="utf-8")
    compiled = compile_source(
        source,
        output_values=["abi", "bin"],
        solc_binary=SOLC_BINARY,
    )
    _, contract_interface = compiled.popitem()
    return contract_interface


def build_deploy_tx(
    web3: Web3,
    config: Any,
    contract_factory: Any,
    platform_address: str,
) -> dict[str, Any]:
    base_tx: dict[str, Any] = {
        "chainId": NETWORKS[config.network].chain_id,
        "from": config.wallet_address,
        "nonce": web3.eth.get_transaction_count(config.wallet_address),
        "gasPrice": web3.eth.gas_price,
    }

    constructor = contract_factory.constructor(platform_address)
    try:
        estimated_gas = constructor.estimate_gas({"from": config.wallet_address})
        base_tx["gas"] = int(estimated_gas * 1.25)
    except Exception as exc:
        LOGGER.warning("gas estimation failed; using fallback gas. error=%s", exc)
        base_tx["gas"] = 2_000_000

    return constructor.build_transaction(base_tx)


def assert_balance_covers_tx(
    web3: Web3,
    wallet_address: str,
    tx: dict[str, Any],
    native_symbol: str,
) -> None:
    needed = int(tx["gas"]) * int(tx["gasPrice"])
    balance = web3.eth.get_balance(wallet_address)
    assert balance >= needed, (
        f"Insufficient balance for deployment: need about "
        f"{web3.from_wei(needed, 'ether')} {native_symbol}, have "
        f"{web3.from_wei(balance, 'ether')} {native_symbol}"
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Deploy Somnia callback contract")
    parser.add_argument("--config", required=True, help="Path to ignored local config")
    return parser.parse_args()


def configure_logging() -> None:
    configure_somnia_logging(logging.INFO)


if __name__ == "__main__":
    main()
