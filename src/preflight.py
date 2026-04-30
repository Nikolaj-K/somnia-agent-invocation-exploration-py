"""
What: No-spend Somnia Agent environment check.
Run:  python src/preflight.py --config config.local.json
Deps: Python 3.9+; install with `python -m pip install -r requirements.txt`.
"""

from __future__ import annotations

import argparse
import logging
from decimal import Decimal

from web3 import Web3

from config_loader import AppConfig
from config_loader import load_config
from config_loader import PRESET_FILES
from logging_utils import configure_logging as configure_somnia_logging
from somnia_constants import NETWORKS
from somnia_constants import PLATFORM_ABI


LOGGER = logging.getLogger("somnia-preflight")
TOKEN_WEI = Decimal(10) ** 18


def preflight_static(config: AppConfig) -> None:
    """Fast local assertions before touching RPC."""

    assert config.network in NETWORKS
    assert config.agent.agent_id >= 0
    assert config.agent.method_signature
    assert len(config.agent.input_types) == len(config.agent.args)
    assert len(PLATFORM_ABI) >= 5


def main() -> None:
    args = parse_args()
    configure_logging()

    config = load_config(args.config, args.preset)
    preflight_static(config)

    network = NETWORKS[config.network]
    web3 = Web3(Web3.HTTPProvider(config.rpc_url, request_kwargs={"timeout": 20}))
    platform_address = Web3.to_checksum_address(network.platform_contract)
    platform = web3.eth.contract(address=platform_address, abi=PLATFORM_ABI)

    assert web3.is_connected(), f"Could not connect to RPC: {config.rpc_url}"
    observed_chain_id = web3.eth.chain_id
    assert observed_chain_id == network.chain_id, (
        f"RPC chain ID {observed_chain_id} != expected {network.chain_id}"
    )

    balance_wei = web3.eth.get_balance(config.wallet_address)
    code = web3.eth.get_code(platform_address)
    floor_wei = platform.functions.getRequestDeposit().call()
    reward_wei = tokens_to_wei(config.agent.per_agent_price_tokens) * (
        config.agent.subcommittee_size
    )
    practical_deposit_wei = floor_wei + reward_wei

    LOGGER.info("preset=%s agent_name=%s", config.preset_name, config.agent.name)
    LOGGER.info("network=%s chain_id=%s", network.name, observed_chain_id)
    LOGGER.info("rpc_url=%s", config.rpc_url)
    LOGGER.info("wallet_address=%s", config.wallet_address)
    LOGGER.info(
        "balance=%s %s",
        web3.from_wei(balance_wei, "ether"),
        network.native_symbol,
    )
    LOGGER.info("platform_contract=%s", platform_address)
    LOGGER.info("platform_code_present=%s", len(code) > 0)
    LOGGER.info("platform_abi_entries=%s", len(PLATFORM_ABI))
    LOGGER.info(
        "getRequestDeposit_floor=%s %s",
        web3.from_wei(floor_wei, "ether"),
        network.native_symbol,
    )
    LOGGER.info(
        "practical_deposit=%s %s",
        web3.from_wei(practical_deposit_wei, "ether"),
        network.native_symbol,
    )
    LOGGER.info(
        "agent_id=%s method_signature=%s",
        config.agent.agent_id,
        config.agent.method_signature,
    )
    LOGGER.info("callback_config_ready=%s", config.has_callback_config)

    if not config.has_callback_config:
        LOGGER.warning(
            "invoke_agent.py will refuse to spend until callback_address and "
            "callback_selector are set; official docs do not define a "
            "callback-free convention."
        )


def tokens_to_wei(tokens: Decimal | None) -> int:
    assert tokens is not None, "per_agent_price_tokens is required"
    return int(tokens * TOKEN_WEI)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="No-spend Somnia Agent preflight")
    parser.add_argument("--config", required=True, help="Path to ignored local config")
    parser.add_argument(
        "--preset",
        required=True,
        choices=sorted(PRESET_FILES),
        help="Agent preset to check",
    )
    return parser.parse_args()


def configure_logging() -> None:
    configure_somnia_logging(logging.INFO)


if __name__ == "__main__":
    main()
