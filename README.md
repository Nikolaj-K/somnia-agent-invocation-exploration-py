# Minimal Somnia Agents Python Invoker

This is a local Python project for calling the Somnia Agents platform contract.
Almost entirely vibe-slopped today. But tiny enough.

<img width="832" height="511" alt="Screenshot 2026-05-01 at 01 35 27" src="https://github.com/user-attachments/assets/b0585af2-9331-452a-a62e-f8a64f0f924c" />

Python is practical here because Somnia Agents use standard EVM ABI encoding; the official docs also show TypeScript/viem snippets and Explorer-generated code.
It loads ignored local runtime config plus `SOMNIA_PRIVATE_KEY` from `.env.local`, combines that with an explicit non-secret agent preset, checks RPC/chain/balance, quotes the documented deposit, and submits one agent request when callback config is supplied.
The recommended first-success preset is LLM Inference. LLM Parse Website is also supported in principle, but in a TODO state - I didn't quite get it yet. Probably more fragile because it adds website fetching/parsing behavior to the basic request path.

## How This Works

This project does not run an LLM locally. Your machine signs transactions,
encodes payloads, and reads results. Somnia's agent runner/validator
infrastructure runs the agent and submits responses back on-chain.

Flow:

1. `src/preflight.py` checks RPC, chain ID, wallet address, balance, platform
   bytecode, and the current request-deposit floor. It does not spend funds.
2. `src/deploy_callback.py` deploys `contracts/SomniaAgentCallback.sol`. This
   spends gas once and gives the Somnia platform a callback target.
3. `src/invoke_agent.py --preset ...` ABI-encodes the selected preset payload
   and sends `createRequest{value: deposit}` to the official `SomniaAgents`
   platform contract.
4. Somnia runners execute the agent off-chain, including the LLM/web extraction
   work, then submit responses to the platform contract.
5. The platform contract finalizes consensus, calls your callback contract, and
   stores request details.
6. `src/invoke_agent.py` polls `getRequest(requestId)`, parses callback events
   from the finalization transaction, decodes the first successful
   `responses[].result`, and fetches the execution receipt from Somnia's
   receipt service.

Contracts:

- `SomniaAgents` platform contract: official Somnia contract that accepts
  requests, holds deposits, coordinates responses, finalizes consensus, and
  exposes `getRequest`.
- `SomniaAgentCallback`: local callback receiver. It verifies calls come from
  the official platform, stores latest status/count, preserves the first
  successful result and first non-empty failed result, emits one event per
  response, and accepts native-token rebates.

Interface used by this project:

- `createRequest(agentId, callbackAddress, callbackSelector, payload)`
- `getRequestDeposit()`
- `hasRequest(requestId)`
- `getRequest(requestId)`
- `RequestCreated(requestId, agentId, perAgentBudget, payload, subcommittee)`
- `RequestFinalized(requestId, status)`

## Setup From Scratch

Use either a dedicated conda env or a project-local venv. Do not reuse an
unrelated project environment.

Conda:

```bash
cd /Users/nikolajk/Dev/scrips_crypto/Somnia/agents
source "$HOME/miniforge3/etc/profile.d/conda.sh"
conda create -n somnia-agents python=3.11
conda activate somnia-agents
python -m pip install -r requirements.txt
```

Venv:

```bash
cd /Users/nikolajk/Dev/scrips_crypto/Somnia/agents
python -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

Create shared local config and secret env file:

```bash
cp config.example.json config.local.json
umask 077
printf 'SOMNIA_PRIVATE_KEY=0xYOUR_PRIVATE_KEY_DO_NOT_COMMIT\n' > .env.local
```

Edit `.env.local` and replace the placeholder with the full private key,
including the `0x` prefix. Keep `config.local.json` for non-secret settings
only; `wallet_address` is optional and, when set, must match the key-derived
address.

`config.local.json` is for shared local/runtime settings only:

- `network`
- optional `rpc_url`
- `wallet_address`
- `callback_address`
- `callback_selector`
- polling, wait, gas, and fee settings

Agent-specific ABI and pricing settings live in non-secret presets under
`configs/`:


## Parse Website Update

The live Agent Explorer confirms that `LLM Parse Website` uses the same agent ID already in this repo, but the working `ExtractString` signature includes **eight** inputs, not seven:

`ExtractString(string key, string description, string[] options, string prompt, string url, bool resolveUrl, uint8 numPages, uint8 confidenceThreshold) returns (string output)`

Earlier parse failures were caused by sending the older 7-argument selector. The preset and code now include `confidence_threshold`, and the CLI can override it with `--confidence-threshold`.

Recommended Parse Website smoke test:

```bash
python src/preflight.py --config config.local.json --preset llm-parse-website
python src/invoke_agent.py --config config.local.json --preset llm-parse-website --dry-run --url "https://example.com" --prompt "Return exactly the HTML title text." --num-pages 1 --confidence-threshold 1
python src/invoke_agent.py --config config.local.json --preset llm-parse-website --url "https://example.com" --prompt "Return exactly the HTML title text." --num-pages 1 --confidence-threshold 1
```

- `configs/llm_inference.json`
- `configs/llm_parse_website.json`

When `--preset` is supplied, the selected preset is the source of agent
metadata. This keeps mode switching explicit and avoids duplicating callback or
network settings across local files.

Fund the wallet derived from `SOMNIA_PRIVATE_KEY`: testnet STT from <https://testnet.somnia.network>, or mainnet SOMI through the official channels.

## Load Secrets

Run this in every new shell before `preflight`, `deploy_callback`, or `invoke`.

```bash
set -a
source .env.local
set +a
```

## No-Spend Preflight

```bash
python src/preflight.py --config config.local.json --preset llm-inference
```

`preflight.py` is the safe first command to run. It reads `.env.local` and
`config.local.json`, then makes live read-only RPC calls to Somnia. It does not
sign transactions and does not spend funds.

It checks:

- selected network and live chain ID
- wallet address derived from `SOMNIA_PRIVATE_KEY`
- live native-token balance
- configured RPC URL
- official platform contract address
- whether platform contract bytecode is present
- whether the local ABI fragment has the expected entries
- live `getRequestDeposit()` floor from the platform contract
- practical deposit for the configured agent type
- active preset and agent name
- whether callback config is ready

Expected before callback deployment:

```text
callback_config_ready=False
```

Expected after callback deployment and config update:

```text
callback_config_ready=True
```

## Colored Output

The command logs use Rich for readable terminal colors while keeping the same
`KEY=value` structure:

- timestamps and elapsed-time fields are muted gray
- external chain/platform/callback evidence is bright green
- URLs are blue and underlined
- addresses and selectors are cyan
- long raw hex/calldata fields are dim gray
- success/pending/failure states are green/yellow/red
- decoded agent results are bold green

Colors are enabled automatically in interactive terminals. Set `NO_COLOR=1` if
you need plain output for copying, parsing, or a terminal that does not handle
ANSI colors well. Set `FORCE_COLOR=1` if a capable terminal is misdetected.

## Deploy Callback Contract

Somnia's documented `createRequest` path requires `callbackAddress` and
`callbackSelector`. Deploy the tiny callback contract using the same wallet that
will run `invoke_agent.py`.

```bash
python src/deploy_callback.py --config config.local.json
```

The deploy script prints a `callback_address` and `callback_selector`.

Paste those values into `config.local.json`:

```json
"callback_address": "0xYOUR_DEPLOYED_CALLBACK_CONTRACT",
"callback_selector": "0x387e0801"
```

`0x387e0801` is the selector for the provided contract's `handleResponse`
callback. The upgraded callback keeps the same signature and selector, but emits
per-response evidence so failed agent executions do not lose raw result bytes.
The contract also exposes `handleResponseSelector()` so you can verify the
selector after deployment.

The deploy script spends testnet STT/mainnet SOMI for gas, but does not invoke
an agent. It uses the platform address for the configured network. If you still
have an older callback deployed, redeploy before another paid diagnostic run so
the finalization transaction includes the new `AgentResponseStored` events.

## No-Spend Dry Run

Use dry-run mode before spending on another invocation:

```bash
python src/invoke_agent.py --config config.local.json --preset llm-inference --dry-run --prompt "What is two plus three? Reply with exactly one lowercase four-letter English word."
```

Dry-run makes read-only RPC calls only. It does not sign, submit, or spend. It
prints the selected preset, network, wallet address, platform contract, agent
ID, method signature and selector, input/output types, arguments, encoded agent
payload, callback address/selector, deposit value, and final `createRequest`
calldata hex.

Compare this output against the official Agent Explorer-generated snippet before
another paid request. In particular, check agent ID, method signature, selector,
argument order/types, payload hex, callback selector, and value/deposit.

## Invoke LLM Inference

```bash
python src/preflight.py --config config.local.json --preset llm-inference
python src/invoke_agent.py --config config.local.json --preset llm-inference --prompt "What is two plus three? Reply with exactly one lowercase four-letter English word."
```

`invoke_agent.py` will refuse to spend until `callback_address` and `callback_selector` are configured.

`--preset llm-inference` is the recommended first-success path. It uses
`inferString(string,string,bool,string[])`; `--prompt` overrides the first
argument, and `--system` overrides the existing system/context string argument.

## Invoke LLM Parse Website

```bash
python src/preflight.py --config config.local.json --preset llm-parse-website
python src/invoke_agent.py --config config.local.json --preset llm-parse-website --url "https://example.com" --prompt "Return exactly the HTML title text."
```

`--preset llm-parse-website` uses the docs-verified
`ExtractString(string,string,string[],string,string,bool,uint8)` path. It
supports:

- `--prompt`
- `--url`
- `--resolve-url` / `--no-resolve-url`
- `--num-pages`

This mode is useful, but more fragile than LLM Inference because it depends on
the target page and the website parsing/browser-style agent behavior.

## Troubleshooting Invocation

- `request_status=1 (Pending)` means the platform has accepted the request and
  is waiting for runner responses/finalization.
- `request_finalized_event status=3 (Failed)` means the platform finalized the
  request as failed. The callback contract was called, but there was no
  successful response to decode.
- Somnia testnet may stop returning a finalized request from `getRequest` after
  finalization. The script therefore also checks `RequestFinalized` events and
  reports the finalization block and transaction hash.
- `status=4 (TimedOut)` means the request did not reach consensus before the
  platform timeout.
- For the first LLM Parse Website invocation, prefer the direct HTML URL
  `https://docs.somnia.network/agents` with `"resolve_url": false` in
  `config.local.json`. This avoids adding search/discovery as another possible
  failure point while testing the basic invocation path.
- Avoid the `.md` docs endpoints for the first LLM Parse Website smoke test;
  those are machine-readable Markdown, while this agent is documented as a
  website scraping/browser-style agent.
- If the receipt service returns 404 immediately after finalization, rerun later
  with the printed `receipt_ui_url`; receipts may lag finalization or may be
  absent for failed requests. The raw `receipts.*.agents.somnia.host` service is
  for programmatic JSON fetches and may return `Cannot GET /` in a browser.
- Safe next diagnostic flow: run `preflight`, run `invoke_agent.py --dry-run`,
  compare calldata with Agent Explorer, redeploy the upgraded callback if needed,
  then do at most one paid retry once the calldata and callback evidence path
  match official Explorer details.
- Do not do another paid invocation while dry-run output diverges from Explorer
  or while the configured callback is still the older version that only stores a
  successful result.

## Updating Dependencies

Only rerun this when `requirements.txt` changes or a package is missing:

```bash
python -m pip install -r requirements.txt
```

## Share Safe Files

To create a zip that excludes local secrets, local config, virtualenvs, and
compiler caches:

```bash
ZIP_NAME="somnia-agents-safe-$(date +%Y%m%d-%H%M%S).zip"

zip -r "$ZIP_NAME" \
  README.md \
  TODO.md \
  FEEDBACK.md \
  requirements.txt \
  .gitignore \
  config.example.json \
  configs \
  src \
  contracts \
  -x '*/__pycache__/*' \
     '*.pyc' \
     '.env.local' \
     'config.local.json' \
     '.venv/*' \
     '.solcx/*' \
     'somnia-agents-safe-*.zip'
```

Do not upload `.env.local`, `config.local.json`, `.venv/`, `.solcx/`, or
terminal history containing a private key.

## What Is Verified vs TODO

Verified from docs: chain IDs, RPCs, native symbols, SomniaAgents platform addresses, platform ABI subset, `getRequestDeposit()`, deposit model, receipt service URLs, LLM Parse Website `agentId=12875401142070969085`, and `ExtractString(string,string,string[],string,string,bool,uint8)`.

TODO: official docs confirm off-chain clients can submit platform transactions and later read `getRequest`, but they do not define a callback-free `callbackAddress`/`callbackSelector` convention. This project therefore requires explicit callback config instead of inventing a zero-address or empty-selector path.

JSON API Request and LLM Inference method ABIs are documented, but their official agent IDs are not in the docs. The `configs/llm_inference.json` preset uses an LLM Inference agent ID observed from recent official platform `RequestCreated` events; verify it against Agent Explorer before a paid call.

Official sources:
- <https://docs.somnia.network/agents/invoking-agents/quickstart.md>
- <https://docs.somnia.network/agents/invoking-agents/from-solidity.md>
- <https://docs.somnia.network/agents/invoking-agents/gas-fees.md>
- <https://docs.somnia.network/agents/invoking-agents/receipts.md>
- <https://docs.somnia.network/agents/base-agents/llm-parse-website.md>
- <https://testnet.somnia.network/>
- <https://shannon-explorer.somnia.network/>
