// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

/*
What: Minimal callback receiver for SomniaAgents.createRequest responses.
Run:  Deploy with Remix on Somnia Testnet, passing the testnet SomniaAgents
      platform address: 0x037Bb9C718F3f7fe5eCBDB0b600D607b52706776
Use:  Put the deployed contract address in config.local.json as
      callback_address and use callback_selector 0x387e0801.

This contract keeps enough raw callback evidence to debug failed executions.
*/

enum ConsensusType {
    Majority,
    Threshold
}

enum ResponseStatus {
    None,
    Pending,
    Success,
    Failed,
    TimedOut
}

struct Response {
    address validator;
    bytes result;
    ResponseStatus status;
    uint256 receipt;
    uint256 timestamp;
    uint256 executionCost;
}

struct Request {
    uint256 id;
    address requester;
    address callbackAddress;
    bytes4 callbackSelector;
    address[] subcommittee;
    Response[] responses;
    uint256 responseCount;
    uint256 failureCount;
    uint256 threshold;
    uint256 createdAt;
    uint256 deadline;
    ResponseStatus status;
    ConsensusType consensusType;
    uint256 remainingBudget;
    uint256 perAgentBudget;
}

contract SomniaAgentCallback {
    address public immutable owner;
    address public immutable platform;

    uint256 public latestRequestId;
    ResponseStatus public latestStatus;
    bytes public latestResult;
    bytes public latestFailureResult;
    uint256 public latestReceipt;
    uint256 public latestResponseCount;

    event AgentResponseStored(
        uint256 indexed requestId,
        uint256 indexed responseIndex,
        ResponseStatus status,
        uint256 receipt,
        address validator,
        uint256 executionCost,
        bytes result
    );

    event NativeReceived(address indexed sender, uint256 amount);

    constructor(address platform_) {
        require(platform_ != address(0), "platform required");
        owner = msg.sender;
        platform = platform_;
    }

    function handleResponse(
        uint256 requestId,
        Response[] memory responses,
        ResponseStatus status,
        Request memory details
    ) external {
        require(msg.sender == platform, "only platform");
        require(details.requester == owner, "only owner requests");

        latestRequestId = requestId;
        latestStatus = status;
        latestResponseCount = responses.length;
        latestResult = "";
        latestFailureResult = "";
        latestReceipt = 0;

        bool foundSuccess;
        bool foundFailure;

        for (uint256 i = 0; i < responses.length; i++) {
            if (
                responses[i].status == ResponseStatus.Success &&
                !foundSuccess
            ) {
                latestResult = responses[i].result;
                latestReceipt = responses[i].receipt;
                foundSuccess = true;
            }
            if (
                responses[i].status != ResponseStatus.Success &&
                responses[i].result.length != 0 &&
                !foundFailure
            ) {
                latestFailureResult = responses[i].result;
                foundFailure = true;
            }

            emit AgentResponseStored(
                requestId,
                i,
                responses[i].status,
                responses[i].receipt,
                responses[i].validator,
                responses[i].executionCost,
                responses[i].result
            );
        }
    }

    function handleResponseSelector() external view returns (bytes4) {
        return this.handleResponse.selector;
    }

    receive() external payable {
        emit NativeReceived(msg.sender, msg.value);
    }
}
