"""
What: Official Somnia network and agent constants used by the local scripts.
Run:  Imported by `python src/preflight.py` and `python src/invoke_agent.py`.
Docs: Values here are copied only from the official Somnia docs linked in README.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class NetworkConfig:
    """Small immutable network record; secrets never belong here."""

    name: str
    chain_id: int
    rpc_url: str
    native_symbol: str
    explorer_url: str
    receipt_url: str
    platform_contract: str


NETWORKS: dict[str, NetworkConfig] = {
    "mainnet": NetworkConfig(
        name="mainnet",
        chain_id=5031,
        rpc_url="https://api.infra.mainnet.somnia.network",
        native_symbol="SOMI",
        explorer_url="https://explorer.somnia.network",
        receipt_url="https://receipts.mainnet.agents.somnia.host",
        platform_contract="0x5E5205CF39E766118C01636bED000A54D93163E6",
    ),
    "testnet": NetworkConfig(
        name="testnet",
        chain_id=50312,
        rpc_url="https://api.infra.testnet.somnia.network",
        native_symbol="STT",
        explorer_url="https://shannon-explorer.somnia.network",
        receipt_url="https://receipts.testnet.agents.somnia.host",
        platform_contract="0x037Bb9C718F3f7fe5eCBDB0b600D607b52706776",
    ),
}


VERIFIED_AGENT_TYPE = "llm-parse-website"
VERIFIED_AGENT_METHOD = "ExtractString"
VERIFIED_AGENT_ID = 12875401142070969085
DEFAULT_SUBCOMMITTEE_SIZE = 3
LLM_PARSE_WEBSITE_PRICE_TOKENS = "0.10"

EXTRACT_STRING_SIGNATURE = (
    "ExtractString(string,string,string[],string,string,bool,uint8,uint8)"
)
EXTRACT_STRING_INPUT_TYPES = [
    "string",
    "string",
    "string[]",
    "string",
    "string",
    "bool",
    "uint8",
    "uint8",
]
EXTRACT_STRING_OUTPUT_TYPES = ["string"]

RESPONSE_STATUS_LABELS = {
    0: "None",
    1: "Pending",
    2: "Success",
    3: "Failed",
    4: "TimedOut",
}

FINAL_RESPONSE_STATUSES = {2, 3, 4}

ZERO_HEX_BYTES4 = "0x00000000"

RESPONSE_COMPONENTS = [
    {"name": "validator", "type": "address"},
    {"name": "result", "type": "bytes"},
    {"name": "status", "type": "uint8"},
    {"name": "receipt", "type": "uint256"},
    {"name": "timestamp", "type": "uint256"},
    {"name": "executionCost", "type": "uint256"},
]

REQUEST_COMPONENTS = [
    {"name": "id", "type": "uint256"},
    {"name": "requester", "type": "address"},
    {"name": "callbackAddress", "type": "address"},
    {"name": "callbackSelector", "type": "bytes4"},
    {"name": "subcommittee", "type": "address[]"},
    {"name": "responses", "type": "tuple[]", "components": RESPONSE_COMPONENTS},
    {"name": "responseCount", "type": "uint256"},
    {"name": "failureCount", "type": "uint256"},
    {"name": "threshold", "type": "uint256"},
    {"name": "createdAt", "type": "uint256"},
    {"name": "deadline", "type": "uint256"},
    {"name": "status", "type": "uint8"},
    {"name": "consensusType", "type": "uint8"},
    {"name": "remainingBudget", "type": "uint256"},
    {"name": "perAgentBudget", "type": "uint256"},
]

PLATFORM_ABI = [
    {
        "type": "function",
        "name": "createRequest",
        "stateMutability": "payable",
        "inputs": [
            {"name": "agentId", "type": "uint256"},
            {"name": "callbackAddress", "type": "address"},
            {"name": "callbackSelector", "type": "bytes4"},
            {"name": "payload", "type": "bytes"},
        ],
        "outputs": [{"name": "requestId", "type": "uint256"}],
    },
    {
        "type": "function",
        "name": "getRequestDeposit",
        "stateMutability": "view",
        "inputs": [],
        "outputs": [{"name": "", "type": "uint256"}],
    },
    {
        "type": "function",
        "name": "getRequest",
        "stateMutability": "view",
        "inputs": [{"name": "requestId", "type": "uint256"}],
        "outputs": [{"name": "", "type": "tuple", "components": REQUEST_COMPONENTS}],
    },
    {
        "type": "function",
        "name": "hasRequest",
        "stateMutability": "view",
        "inputs": [{"name": "requestId", "type": "uint256"}],
        "outputs": [{"name": "", "type": "bool"}],
    },
    {
        "type": "event",
        "name": "RequestCreated",
        "anonymous": False,
        "inputs": [
            {"indexed": True, "name": "requestId", "type": "uint256"},
            {"indexed": True, "name": "agentId", "type": "uint256"},
            {"indexed": False, "name": "perAgentBudget", "type": "uint256"},
            {"indexed": False, "name": "payload", "type": "bytes"},
            {"indexed": False, "name": "subcommittee", "type": "address[]"},
        ],
    },
    {
        "type": "event",
        "name": "RequestFinalized",
        "anonymous": False,
        "inputs": [
            {"indexed": True, "name": "requestId", "type": "uint256"},
            {"indexed": False, "name": "status", "type": "uint8"},
        ],
    },
]
