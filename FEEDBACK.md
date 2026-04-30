Note(Nikolaj-K): The notes below are basically all ChatGPT generates, I prompted it to keep adding and refactorign this file as we went along and solved problems. 99% of the code in the repo is vibeslopped. At the least it gives you a good idea of what the agent could make use of and where this coding still has blockers with the docs, or where stuff is open/ambiguous for it.

# Feedback: Faster First Somnia Agent Invocation

This feedback comes from building and testing a minimal local project whose only
goal was to fund a wallet, connect to Somnia, and obtain one successful agent
result end to end on testnet.

## Executive Summary

Somnia Agents look real and usable, and the core platform path is good enough to
build against. We were able to:

- connect to testnet
- verify wallet balance and platform contract presence
- compute request deposit
- deploy a callback contract
- submit `createRequest(...)`
- observe `RequestCreated`
- observe callback execution
- observe `RequestFinalized`

So the main onboarding problem is no longer basic chain access. The problem is
getting from a successful request-creation transaction to a first successful
agent result without having to reverse-engineer agent-specific expectations.
We eventually got a successful LLM Inference result, but only after switching
away from LLM Parse Website, upgrading callback diagnostics, and deriving the
live LLM Inference testnet agent ID from platform events because it was not
published in the docs.

The fastest improvement would be a single, authoritative, known-good testnet
example that shows the full path:

- exact agent ID
- exact method signature
- exact payload values
- exact deposit/value
- exact callback convention
- expected polling behavior
- expected successful decoded result

## What Now Seems Clear

These parts appear to be working and reasonably discoverable once the right docs
pages are found:

- Somnia Agents are publicly invokable on testnet.
- The invocation path is contract-driven, not a simple hosted REST LLM API.
- The platform contract accepts requests and emits the expected lifecycle
  events.
- Callback-based asynchronous delivery is a real part of the flow.
- A client can successfully reach the point where agent execution is attempted.

## What Still Blocks a New Developer

### 1. The first successful result is not easy to reach without the right agent

The biggest remaining gap is not request creation. It is obtaining a first
successful decoded agent result.

From our initial LLM Parse Website testing:

- request creation succeeded multiple times
- callback execution succeeded
- finalization happened
- runner responses existed
- but the requests still finalized as `Failed`

That means a new developer can do many things correctly and still have no clear
path to the first working result. We did later get a successful result using
LLM Inference, which suggests the first quickstart should lead with the simpler
LLM path rather than a browser/page-parsing agent.

### 2. Agent-specific invocation expectations are still too implicit

The current docs were enough to build the platform interaction, but not enough
to make the agent-specific part feel decision-complete.

The remaining ambiguity appears to be around one or more of:

- exact payload conventions for a live agent
- exact field semantics for website parsing inputs
- callback assumptions
- runner behavior on testnet
- whether Explorer-generated snippets are the canonical source of truth for
  live agent invocation details

### 3. Callback semantics need to be explicit

The docs show `callbackAddress` and `callbackSelector`, but a new developer
still has to ask:

- Is a callback contract mandatory?
- Is there a supported callback-free convention for off-chain callers?
- If a callback contract is required, what is the minimal recommended one?
- Which callback state or events should a client rely on after finalization?

For first-run success, this needs a direct answer very early in the docs.

## Additional Onboarding Friction We Hit In Practice

Beyond the agent-specific ABI issues, a new developer can lose substantial time
on workflow questions that are easy to answer once you already understand the
system, but are not obvious at the start.

### 1. Environment and setup path were more confusing than necessary

We had to decide for ourselves whether to:

- use a project-local virtual environment
- reuse an existing conda environment
- keep secrets in JSON config
- move secrets into environment variables
- keep one config or multiple configs when switching between agent modes

The best local outcome was eventually:

- project-local environment
- `.env.local` for the private key
- one shared local config for network/callback/runtime state
- separate non-secret presets for `llm-inference` and `llm-parse-website`

This is mostly local tooling, but it was driven by the fact that the public
Somnia invocation flow is callback- and agent-shape-dependent. A short official
"recommended local project layout" would reduce unnecessary iteration.

### 2. The first successful path depended on refactoring for easier mode switching

Once `LLM Inference` started working, we wanted the same client to support both:

- `llm-inference`
- `llm-parse-website`

That pushed us toward explicit presets and mode selection. The resulting local
CLI is much clearer, but this was figured out by trial and error. It would help
if the official docs framed base agents as separate invocation modes from the
start, rather than leaving developers to infer the best configuration split.

### 3. Color/logging and diagnostics mattered more than expected

This is a smaller point, but it affected debugging speed. We needed richer
callback logs, dry-run calldata printing, and terminal color handling before the
agent failures became understandable. Better official examples for:

- dry-run / calldata inspection
- callback event inspection
- failed-response decoding
- how many places a client should read state from after finalization

would materially shorten the time to first successful integration.

## Highest-Impact Docs Improvements

### 1. Add one canonical "first successful invocation" guide

Please add a page whose only goal is to get a developer to one successful
result on testnet.

It should include:

- funded wallet on testnet
- exact chain ID and RPC URL
- platform contract address
- one known-good agent ID
- one known-good method signature
- exact example payload values
- exact deposit/value formula with worked numbers
- callback setup requirements
- request submission example
- event parsing example
- polling example
- successful result decoding example
- receipt lookup example

This would remove most of the current guesswork.

### 2. Make the Agent Explorer's role explicit

Please state clearly whether the Agent Explorer is authoritative for:

- live agent IDs
- method signatures
- snippet generation
- current recommended invocation patterns

If the Explorer is the source of truth for live invocations, say so directly in
the quickstart and link to it immediately.

### 3. Put base-agent metadata in one table

Please provide one table for all official base agents with:

- agent name
- short purpose
- testnet ID
- mainnet ID
- method names / signatures
- example payload link
- price per runner
- default subcommittee size
- Explorer link

This would make it much easier to pivot from one agent to another without
reconstructing the whole flow.

### 4. Start with the mental model

Please explain early and plainly that this is:

- not a normal hosted LLM REST endpoint
- an asynchronous on-chain request flow
- off-chain execution by Somnia runners / validators
- on-chain finalization plus callback / state / event / receipt inspection

That distinction changes the entire shape of a starter project.

## Important Lifecycle Clarifications To Document

### 1. Explain what explorer "Success" means

A successful `createRequest` transaction can still lead to a failed async agent
execution later.

That distinction is easy to miss. The docs should say explicitly:

- transaction success means the request was created
- it does **not** mean the agent execution succeeded
- final agent outcome is determined later by request finalization status

### 2. Explain post-finalization request readability

In our testing, a request could exist during polling and then become unreadable
through `getRequest(requestId)` after finalization.

Observed behavior included:

- `hasRequest(requestId)` changing unexpectedly around finalization
- `getRequest(requestId)` reverting after finalization
- clients needing to fall back to `RequestFinalized` and callback state

If this is expected, it should be documented. If not, it would help to document
the intended lifecycle guarantees.

### 3. Clarify receipt behavior for failed requests

At the time of testing, the receipt URL returned 404 for failed requests.

Please document whether:

- receipts are delayed after finalization
- failed requests do not produce receipts
- different lookup rules apply to failed executions
- some receipt data is only available on success

### 4. Clarify failure payload expectations

A failed request still contains valuable diagnostic information. Please explain:

- whether failed runner responses contain structured error bytes
- whether callback contracts should expect useful failure payloads
- how a client should decode or inspect failure results
- whether there is a standard ABI or schema for failed responses

### 5. Clarify how the number of responding agents is determined

While testing, we repeatedly saw exactly two validator responses in the callback
for both failed and successful requests. That raised a natural developer
question: where did that number come from?

We locally configured a `subcommittee_size` and used it to compute the deposit,
but that value was not directly passed as an explicit argument to
`createRequest(...)` in the simple client flow. So from the client side it was
not obvious whether:

- the number of runners is fixed by the selected agent
- it is chosen by Somnia on the backend
- it is inferred from price/deposit
- it is configurable by the requester through a different mechanism
- only a threshold of responses is surfaced even if a larger committee exists

Please document, for each base agent if relevant:

- default committee / subcommittee size
- threshold required for finalization
- whether the requester can influence either one
- whether callback/event logs should normally show all runner responses or only
  the ones needed for consensus

This would make the observed `response_count = 2` much easier to interpret.

### 5. Publish LLM Inference agent IDs

The LLM Inference docs are good for method shapes, but the page does not publish
the live testnet agent ID. The GitBook `ask` endpoint also answered that it
could not find the official LLM Inference testnet agent ID in the docs.

We found a working testnet ID only by scanning recent `RequestCreated` logs on
the official platform contract for payloads whose first four bytes matched the
documented `inferString(string,string,bool,string[])` selector.

Observed working testnet LLM Inference details:

- agent ID: `12847293847561029384`
- method: `inferString(string,string,bool,string[])`
- selector: `0xfe7ca098`
- output type: `string`
- per-agent price: `0.07 STT`
- default subcommittee size used: `3`
- practical deposit observed from docs formula: `0.24 STT`

This should be in the official base-agent metadata table instead of requiring
log mining.

Note(Nikolaj-K): I think ChatGPT had problems parsing the info from https://agents.somnia.network/ and so we played around without some IDs that actually were there.

## Suggested Product Strategy For New Developers

### 1. Lead with the easiest agent, not just the most illustrative one

If `LLM Parse Website` is more brittle because of URL/content constraints, it
may not be the best first success path.

For a beginner quickstart, it may be better to lead with whichever of the base
agents has the highest probability of succeeding consistently on testnet, even
if it is less visually impressive.

If `LLM Inference` is the simpler path to a first success, it may deserve to be
the primary quickstart example.

### 2. Publish one or two exact known-good payloads

A minimal starter should not have to infer payload semantics.

Please publish exact payloads that are expected to work today, for example:

- one `LLM Inference` request
- one `LLM Parse Website` request

The docs should include both the human-readable arguments and the final ABI
encoding shape.

## Attempted Implementation History

This is the practical path we tried while building the minimal starter.

### Initial setup and chain wiring

- Built a Python/web3.py preflight command.
  - Result: worked.
  - It connected to Somnia testnet, verified chain ID `50312`, derived the
    wallet address, read live STT balance, checked platform bytecode, called
    `getRequestDeposit()`, and calculated the practical LLM Parse Website
    deposit as `0.33 STT`.
- Tried to keep the first version purely off-chain.
  - Result: blocked by unclear callback semantics.
  - The documented `createRequest` API requires `callbackAddress` and
    `callbackSelector`; the docs did not define a callback-free convention.
- Deployed a minimal callback contract.
  - Result: worked.
  - The callback contract deployed on testnet, `createRequest` accepted it, and
    later failed requests did call it.

### Paid invocation attempts

- Submitted an LLM Parse Website request using `resolveUrl=true` and
  `docs.somnia.network` as the target.
  - Result: request creation transaction succeeded, but the async agent request
    finalized as `Failed`.
- Submitted a simpler direct-URL request using the `.md` docs page with
  `resolveUrl=false`.
  - Result: request creation and callback both worked, but the async request
    again finalized as `Failed`.
- Submitted another direct-URL request using the HTML Agents page with
  `resolveUrl=false`.
  - Result: request creation and callback both worked, but the async request
    again finalized as `Failed`.

### What we tried specifically for Parse Website, and what we think now

We tried several progressively simpler Parse Website requests:

- `docs.somnia.network` with `resolveUrl=true`
- direct Markdown docs URL with `resolveUrl=false`
- direct HTML docs page with `resolveUrl=false`
- later, a very simple target page: `https://example.com`
  with prompt `Return exactly the HTML title text.`

The first three attempts finalized as failed without enough diagnostics to say
why. After upgrading callback logging, the `example.com` test finally produced a
clear failure payload from two validators.

The failure was not a generic scraping error. Both validators reported that the
submitted selector `0xbb2cde46` could not be decoded against the live agent ABI:

- configured method signature:
  `ExtractString(string,string,string[],string,string,bool,uint8)`
- configured selector: `0xbb2cde46`
- validator error: selector not found on ABI

So Parse Website still does not work for us as of this feedback. Our current
best hypotheses are:

- the live Parse Website agent ID is wrong for the current network/version
- the documented or assumed method signature is stale or incomplete
- the Agent Explorer snippet is the real source of truth, and our local preset
  needs to be regenerated from it

Our next-step ideas were:

- stop paying for repeated retries with the current Parse Website preset
- compare local dry-run calldata against the current Agent Explorer output
- treat `LLM Inference` as the canonical first-success path
- only return to Parse Website once the live ID/signature/payload shape are
  confirmed from authoritative Somnia sources

### What these attempts established

Across the failed runs, we observed:

- successful `createRequest(...)` transactions
- successful request ID extraction
- successful callback invocation
- successful finalization detection
- callback state showing `latestResponseCount = 2`
- no successful decoded result
- finalization status `Failed`

This strongly suggests that:

- wallet setup was fine
- funding was fine
- platform contract wiring was fine
- callback deployment and callback routing were fine
- the remaining issue was agent-specific invocation semantics or runner-side
  behavior

### Lifecycle and client-behavior issues discovered during testing

- After finalization, `getRequest(requestId)` could become unreadable.
- A request could appear to exist and then revert during a later poll.
- The client therefore had to be patched to fall back to `RequestFinalized`
  event lookup and callback state rather than assuming `getRequest` would remain
  readable.
- The explorer showing the request-creation transaction as `Success` was
  correct, but easy to misread as meaning the agent execution succeeded.
- The receipt endpoint returned 404 for failed requests at the time of testing.

### Diagnostic upgrades after Parse Website failures

The original callback only stored the first successful response result. That
meant failed responses could finalize, call the callback, and still leave the
client with no raw failure bytes to inspect.

We upgraded the callback without changing the Somnia platform callback
signature:

```solidity
handleResponse(
    uint256 requestId,
    Response[] memory responses,
    ResponseStatus status,
    Request memory details
)
```

The selector stayed `0x387e0801`. The upgraded callback now:

- emits one `AgentResponseStored` event per response
- includes request ID, response index, response status, receipt ID, validator,
  execution cost, and raw result bytes
- stores latest request ID, latest overall status, latest response count, first
  successful result, and first non-empty failure result

We also added client-side decoding for:

- ABI `string`
- readable UTF-8
- JSON if the UTF-8 parses as JSON
- Solidity `Error(string)` payloads with selector `0x08c379a0`

This improved the situation materially: after the successful LLM Inference run,
the callback event stream showed both validator responses and the ABI-encoded
result bytes.

### No-spend calldata parity mode

We added `--dry-run` to the invoker before spending again. It does not sign or
submit a transaction. It prints:

- network and chain ID
- wallet address
- platform contract
- agent name and agent ID
- method signature and selector
- input types and arguments
- encoded agent payload hex
- callback address and selector
- deposit/value
- final `createRequest` calldata

This let us verify that the local call had switched from Parse Website to LLM
Inference before submitting another paid request.

### LLM Inference source-of-truth path

What we found in official sources:

- `LLM Inference` docs publish the method shapes, including
  `inferString(string prompt, string system, bool chainOfThought, string[] allowedValues) returns (string response)`.
- Gas Fees docs publish the current per-agent price:
  `LLM Inference (llm-inference) = 0.07 SOMI/STT`.
- The docs do not publish the LLM Inference testnet agent ID.
- The GitBook `ask` endpoint confirmed it could not find that official testnet
  agent ID in the docs.

How we resolved the missing ID:

- Computed the documented method selector:
  `inferString(string,string,bool,string[]) -> 0xfe7ca098`.
- Scanned recent `RequestCreated` events from the official testnet platform
  contract `0x037Bb9C718F3f7fe5eCBDB0b600D607b52706776`.
- Looked for payloads beginning with `0xfe7ca098`.
- Found recent LLM Inference traffic using agent ID
  `12847293847561029384`.
- Used that ID in local config and confirmed dry-run showed
  `agent_name=llm-inference`, `method_selector=0xfe7ca098`, and deposit
  `0.24 STT`.

This worked, but it is not an onboarding-quality path. A developer should not
have to mine platform logs to discover a base-agent ID.

### Successful LLM Inference run

After switching config to LLM Inference and redeploying the upgraded callback,
we ran:

```text
prompt = "What is two plus three? Reply with exactly one lowercase four-letter English word."
```

The paid invocation succeeded:

- createRequest tx:
  `0x718ede88446b8d21ed29724f60ef547d798aebd4b7d172cf1753246aebf1cab6`
- request ID: `64299`
- finalization tx:
  `0xd54530d3a4b3787ffbd08fb31e4638a34649a49c27ca651d5e2e69ac08799f96`
- final status: `Success`
- callback response count: `2`
- decoded result: `five`

The callback captured two successful validator responses:

- validator `0x05f1fE2DDF9B65576D3165E37C6A60e6c5Ba93De`
  - status `Success`
  - execution cost `70000000000000000`
  - raw ABI string result encoded as `"five"`
- validator `0x3E05e29029C60E000C8F01EB5AC9cEE6b242D7e0`
  - status `Success`
  - execution cost `70000000000000000`
  - raw ABI string result encoded as `"five"`

This establishes that:

- the Python/web3 invoker can submit an LLM Inference request
- the callback contract shape is compatible with the platform
- the inferred LLM Inference testnet agent ID is currently valid
- `0.24 STT` is sufficient for a default-subcommittee `inferString` request
- result decoding via callback events works even when `getRequest` is no longer
  readable after finalization

### Receipt lookup issue after success

The docs say the programmatic testnet receipt service can be queried as:

```text
https://receipts.testnet.agents.somnia.host?requestId=<request-id>
```

For successful request `64299`, the client initially warned:

```text
execution receipt is not available yet
```

Opening the raw service URL in a browser returned:

```text
Cannot GET /
```

Direct curl to the same root-query URL returned HTTP 404 with `Cannot GET /`.
The browser-friendly UI route loaded, but reported no receipt record:

```text
https://agents.somnia.network/receipts/64299
Receipts -- Request 64299
No receipts found for this request ID
```

This suggests the docs need to distinguish clearly between:

- browser-friendly UI receipt route
- raw service API route
- expected behavior when a receipt is delayed or absent
- whether a successful finalized request can legitimately have no public
  receipt record
- whether the raw receipt service currently supports root `?requestId=...`
  requests as documented

We updated the local script to print both:

```text
receipt_ui_url=https://agents.somnia.network/receipts/<request_id>
receipt_service_url=https://receipts.testnet.agents.somnia.host?requestId=<request_id>
```

## What Worked Well

- The platform addresses for mainnet and testnet are documented.
- The platform interface is usable once found:
  - `createRequest`
  - `getRequestDeposit`
  - `getRequest`
  - `hasRequest`
  - `RequestCreated`
  - `RequestFinalized`
- The gas-fee page is helpful because it distinguishes:
  - the enforced operations-reserve floor
  - the practical amount runners need before they will execute the request
- Receipt service URLs and receipt structure are documented, though the
  observed successful request did not produce a retrievable receipt in either
  the raw service URL or the public receipts UI.
- The LLM Parse Website page contains enough ABI information to encode a real
  method payload.
- The LLM Inference page contains clear method signatures once found.
- The Gas Fees page made it possible to compute the correct LLM Inference
  practical deposit (`0.03 STT` floor plus `0.07 STT × 3 = 0.24 STT`).
- Once configured with the live LLM Inference ID, the platform returned a
  clean, fast, consensus-backed result.

## What a New Developer Still Has To Figure Out Today

- Whether the intended first integration path is:
  - Explorer snippet
  - Solidity integration
  - TypeScript client
  - Python/web3.py client
- Which source is authoritative for each required value:
  - docs
  - Agent Explorer
  - generated code snippets
  - deployed contract ABI
- Whether callback contracts are mandatory for off-chain callers.
- How failure states should be inspected and decoded.
- Which base agent is the best first-success path.
- The live LLM Inference agent ID, unless they know to use Agent Explorer or
  inspect platform events.
- Which receipt URL is meant for browser UI versus raw JSON fetches, and
  whether missing receipts after successful finalization are expected.

## Suggested Smoke-Test Checklist

Before any spendful transaction, provide a no-spend checklist:

- RPC reachable
- chain ID matches selected network
- wallet address derived from key
- native token balance shown
- platform contract bytecode present
- ABI contains required methods/events
- `getRequestDeposit()` callable
- practical deposit calculated for selected agent type
- callback mode confirmed before submit
- exact agent ID and method signature confirmed from an authoritative source

## Suggested "First Invocation" Page Shape

```text
Goal: Invoke one known-good base agent on testnet and print a decoded result.

Prerequisites:
- funded testnet wallet
- private key in local env var
- RPC URL
- platform contract address
- callback convention or minimal callback contract
- exact live agent ID and method signature

Steps:
1. Run no-spend preflight.
2. Quote deposit.
3. Encode one known-good payload.
4. Submit createRequest.
5. Parse RequestCreated for requestId.
6. Poll until finalization.
7. On success, decode the result.
8. On failure, inspect callback / response / receipt diagnostics.
9. Fetch receipt by requestId if available.
```

## Small Docs Clarifications

- State whether current per-agent prices are the recommended defaults for both
  mainnet and testnet.
- Say whether agent IDs are stable across networks.
- Say whether the Agent Explorer is authoritative for IDs and snippets.
- If TypeScript/viem is the primary supported off-chain route, say so directly.
- If Python/web3.py is unofficial but acceptable, say that too.
- Keep one compact network facts table near the Agents quickstart:
  - chain ID
  - RPC URL
  - native token
  - explorer URL
  - platform contract
  - receipt service base URL

## Main Takeaway

A developer can get the on-chain request path working from the docs today, and
LLM Inference can produce a successful decoded result on testnet. The successful
path, however, required stitching together:

- LLM Inference method shape from the base-agent docs
- LLM Inference price from the Gas Fees docs
- a live agent ID inferred from recent platform events
- a custom callback contract
- client-side finalization-event fallback logic
- callback-event decoding

The protocol surface looks real. The main remaining onboarding gap is making
the known-good path explicit enough that a new developer can go from "funded
wallet" to "successful result decoded" without reverse-engineering IDs,
callbacks, and receipt behavior.

## Additional Debugging Lessons

- The current failure is likely agent-specific, not wallet/RPC/platform wiring.
  We proved request creation, callback routing, and finalization.
- Starter clients should preserve failed response evidence. A minimal callback
  should emit or store every response's status, receipt ID, and raw result bytes,
  not only the first successful response.
- A no-spend parity mode would help a lot: print method selector, encoded
  payload hex, `createRequest` calldata, and deposit so developers can compare
  byte-for-byte against an Agent Explorer generated snippet before spending.
- If the goal is simply "invoke an LLM," `LLM Inference` is a better first
  success target than `LLM Parse Website`. It succeeded with a small arithmetic
  prompt once the live agent ID was known.

## Current state (evening of April 30'th) - LLM inference success and Parse Website attempts

We successfully reached a working end-to-end Somnia LLM invocation on testnet by switching to the `LLM Inference` agent (`agent_id = 12847293847561029384`) and using the prompt:

`What is two plus three? Reply with exactly one lowercase four-letter English word.`

The request finalized successfully, two validator responses were observed, both returned the same ABI-encoded result, and the decoded output was `five`. This gave us confidence that wallet setup, funding, callback deployment, request creation, finalization tracking, and result decoding were all functioning correctly.

The exact terminal flow we used for the successful LLM inference path was:

```bash
cd /Users/nikolajk/Dev/scrips_crypto/Somnia/agents
source .venv/bin/activate
set -a
source .env.local
set +a

python src/preflight.py --config config.local.json --preset llm-inference
python src/invoke_agent.py --config config.local.json --preset llm-inference --dry-run --prompt "What is two plus three? Reply with exactly one lowercase four-letter English word."
python src/invoke_agent.py --config config.local.json --preset llm-inference --prompt "What is two plus three? Reply with exactly one lowercase four-letter English word."
```

We then tried to get `LLM Parse Website` working, using `https://example.com` as the simplest possible target and prompts such as:

`Return exactly the HTML title text.`

Initially this failed because the configured method signature was stale: we were using a 7-argument `ExtractString(...)` shape whose selector was not found on the live agent ABI. After checking the Agent Explorer, we updated the parse call to the live 8-argument signature:

`ExtractString(string,string,string[],string,string,bool,uint8,uint8)`

and retried.

At that point the ABI mismatch appeared resolved, but the parse requests still finalized as failed: two validators executed the request, spent execution cost, returned no result bytes, and no public receipt was published for the request. So far, the best candidate command for the Parse Website path is:

```bash
cd /Users/nikolajk/Dev/scrips_crypto/Somnia/agents
source .venv/bin/activate
set -a
source .env.local
set +a

python src/preflight.py --config config.local.json --preset llm-parse-website
python src/invoke_agent.py --config config.local.json --preset llm-parse-website --dry-run --url "https://example.com" --prompt "Return exactly the HTML title text." --num-pages 1 --confidence-threshold 1
python src/invoke_agent.py --config config.local.json --preset llm-parse-website --url "https://example.com" --prompt "Return exactly the HTML title text." --num-pages 1 --confidence-threshold 1
```

Our current conjecture is that the remaining Parse Website issue is not local wiring but either a Somnia-side runtime problem or an undocumented semantic requirement of the Parse Website agent, such as stricter expectations around fields like `description`, `confidenceThreshold`, URL handling, or other method-specific behavior that is not obvious from the exposed signature alone.