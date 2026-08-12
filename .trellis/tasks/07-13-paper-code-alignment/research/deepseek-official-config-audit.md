# Research: DeepSeek official API configuration and call-path audit

- Query: Identify every local configuration point and call path that sets or assumes a SiliconFlow or OpenAI-compatible base URL, API-key environment variable, DeepSeek model identifier, retry/fallback behavior, and related tests or documentation.
- Scope: mixed
- Date: 2026-08-06

## Findings

### Executive conclusion

The shared CEGO, report-explanation, knowledge-base extraction, and GPTScan chat paths now default to the official DeepSeek endpoint (`https://api.deepseek.com`) and `deepseek-v4-flash`. Provider-specific API-key lookup is hostname-aware and does not send a DeepSeek or SiliconFlow credential to an unrelated custom host. SiliconFlow remains intentionally in use only for dense embeddings.

### Files found

- `toolrank/openai_compat.py` — shared OpenAI-compatible chat transport, default endpoint/model, credential selection, streaming parser, and bounded retry policy.
- `toolrank/cego.py` — single structured CEGO request and typed request/response failures.
- `toolrank/report_explanation.py` — optional report explanation request with labeled deterministic fallback.
- `toolrank/kb_update.py` — CLI default for knowledge-base extraction model.
- `toolrank/kb_update_service.py` — dynamic knowledge-base extraction and embedding call paths.
- `toolrank/engine.py` — client loading, CEGO fallback, checker repair, and report-explanation orchestration.
- `toolrank/cli.py` — public CLI model option; no base-URL or API-key flags.
- `toolrank/runner.py` — separate GPTScan endpoint, model, and credential environment mapping.
- `toolrank/execution.py` — native GPTScan environment forwarding.
- `toolrank/gptscan_safe_entry.py` — moves the GPTScan key from the process environment into the vendored CLI invocation in memory.
- `docker/vendor/gptscan/src/chatgpt_api.py` — vendored legacy OpenAI SDK client and its unbounded internal retry loop.
- `docker/vendor/gptscan/requirements-docker.txt` — pins the GPTScan client to `openai==0.27.8`.
- `toolrank/vector_store.py` — SiliconFlow/OpenAI-compatible embedding provider resolution and transport.
- `toolrank/passage_store.py` — dense retrieval and visible BM25 fallback diagnostics.
- `toolrank/toolcard_snapshot.py` — public/private vector-index metadata consistency checks.
- `toolcards/vector_index/index.json` — checked-in embedding provider, base URL, model, and dimension metadata.
- `README.md` and `.env.example` — current operator-facing chat and embedding configuration.
- `tests/test_openai_compat.py` — shared-client defaults, credential isolation, payload, and retry coverage.
- `tests/test_cego_single_request.py`, `tests/test_repair_fallback.py` — one-call contract, typed failures, repair, and primary-only fallback.
- `tests/test_final_report.py` — explanation success/default selection and deterministic fallback.
- `tests/test_dace_retrieval.py`, `tests/test_private_toolcards.py` — embedding configuration, mismatch handling, and BM25 fallback.
- `tests/test_execution_secret_handling.py`, `tests/test_runner_outer_timeout.py` — GPTScan credential isolation, redaction, and outer timeout behavior.
- `.trellis/spec/backend/lakes-scheduling-contract.md` — normative request, fallback, retrieval, ingestion, and secret-delivery contracts.

### Shared chat configuration and call path

`toolrank/openai_compat.py:14-26` defines the official defaults and resolves configuration in this order:

1. Base URL: `LAKES_OPENAI_BASE_URL`, then legacy `TOOLRANK_OPENAI_BASE_URL`, then `https://api.deepseek.com`.
2. Model: `LAKES_OPENAI_MODEL`, then legacy `TOOLRANK_OPENAI_MODEL`, then `deepseek-v4-flash`.

The timeout and retry defaults are also resolved at import time (`toolrank/openai_compat.py:28-46`): connect timeout `0.25` seconds, request timeout `360` seconds, two retries, and `1.0`-second backoff. A process must set these environment variables before importing the module; changing them later does not update the module constants.

The transport appends `/chat/completions` to the configured base (`toolrank/openai_compat.py:159-166`). It uses streaming requests, sends one request per high-level call, retries network failures and HTTP 429/500/502/503/504, and permits three total attempts under the default retry count. It consumes `content` and only uses `reasoning_content` when normal content is absent.

Credential selection is hostname-aware (`toolrank/openai_compat.py:187-208`):

- DeepSeek host: `DEEPSEEK_API_KEY`, then generic `OPENAI_API_KEY`.
- SiliconFlow host: `SILICONFLOW_API_KEY`, then generic `OPENAI_API_KEY`.
- Other hosts: generic `OPENAI_API_KEY` only.

This prevents `SILICONFLOW_API_KEY` from being sent to DeepSeek, prevents `DEEPSEEK_API_KEY` from being sent to SiliconFlow or an arbitrary custom host, and removes the unrelated `WHATAI_API_KEY` fallback.

`load_openai_client()` resolves the API key at call time, probes only localhost endpoints, and constructs a remote client without a live health check (`toolrank/openai_compat.py:211-218`). An accepted key or reachable endpoint therefore does not establish model availability until the first request.

Shared-client consumers and their failure behavior are:

- CEGO: `toolrank/cego.py:323-333` uses the explicit model or shared default, performs one structured request, and converts transport failures or malformed output into `CegoError`.
- Scheduling: `toolrank/engine.py:623-666` degrades a missing client or CEGO failure to the checked primary-only decision; checker repair is bounded before the same fallback.
- Report explanation: `toolrank/report_explanation.py:289-333` uses the shared default for a blank model and turns missing configuration, request failures, schema failures, or semantic failures into a labeled deterministic fallback with no model recorded. Scheduling output is preserved.
- Knowledge-base extraction: `toolrank/kb_update.py:110-113` uses the shared default; `toolrank/kb_update_service.py:293-357` requires a configured client and fails ingestion on missing configuration, request errors, malformed structure, or digest mismatch. It does not publish a deterministic substitute.
- Public CLI: `toolrank/cli.py:91-115` exposes `--model` but no API-key or base-URL flag. Operators configure those through the environment; programmatic callers may pass them through the engine API (`toolrank/engine.py:438-466`).

### GPTScan bridge uses the same official DeepSeek default

GPTScan has an independent configuration path:

- `toolrank/runner.py` defaults its base and model to the shared official DeepSeek constants, while retaining explicit GPTScan overrides.
- Base resolution is explicit value, `OPENAI_API_BASE`, `OPENAI_BASE_URL`, GPTScan-specific defaults, shared LAKES/TOOLRANK defaults, then official DeepSeek.
- Model resolution is GPTScan model variables, GPTScan-specific defaults, shared LAKES/TOOLRANK model variables, then `deepseek-v4-flash`.
- Key resolution is explicit value, then endpoint-aware provider lookup. Official DeepSeek hosts prefer `DEEPSEEK_API_KEY` over generic `OPENAI_API_KEY`; unrelated custom hosts may use only `OPENAI_API_KEY`.
- The native execution path resolves the GPTScan base, model, and host-bound key from its effective isolated environment before passing only those resolved values to the adapter (`toolrank/execution.py`).
- The engine maps programmatic key/base parameters into those OpenAI variables (`toolrank/engine.py:385-391`), but the public CLI does not expose these parameters.
- `toolrank/gptscan_safe_entry.py:11-19` limits subprocess environment exposure by transferring the key to the required vendored `-k` argument only in memory.
- The vendored client uses legacy SDK globals and model variables (`docker/vendor/gptscan/src/chatgpt_api.py`). Official DeepSeek requests disable thinking, and callers that parse JSON also enable the provider's JSON response mode. Its `while True` loop retries rate limits, connection errors, timeouts, and API errors without an internal cap. The outer analyzer/runner timeout is the effective bound.

Consequently, one `DEEPSEEK_API_KEY` configures the default official DeepSeek chat path for CEGO, report explanation, KB extraction, and GPTScan. Generic adapter workers still receive a sanitized environment, and GPTScan remains the only analyzer that receives a chat credential.

### SiliconFlow embedding path

SiliconFlow remains an intentional, separate provider for dense embeddings:

- `toolrank/vector_store.py:17-18` defaults to `https://api.siliconflow.cn/v1` and `Qwen/Qwen3-Embedding-8B`.
- `toolrank/vector_store.py:41-48` accepts an explicit embedding key, then `SILICONFLOW_API_KEY`, then `QWEN_API_KEY`.
- `toolrank/vector_store.py:51-96` infers SiliconFlow when no custom OpenAI-compatible embedding configuration is supplied. It supports `SILICONFLOW_BASE_URL` and `SILICONFLOW_EMBEDDING_MODEL`; custom providers use `OPENAI_API_KEY` and LAKES/TOOLRANK embedding-model variables.
- `toolrank/vector_store.py:134-207` calls `/embeddings`. The low-level call fails when a key is absent. Its direct helper can optionally fall back to `curl`, but dynamic KB building disables that path to avoid placing a secret in process arguments (`toolrank/kb_update_service.py:360-368`).
- `toolcards/vector_index/index.json:4-6` records the SiliconFlow provider, endpoint, and embedding model used to build the checked-in index.
- `toolrank/passage_store.py:318-420` visibly degrades missing index, missing credentials, or dense-query failures to BM25 and reports the mode/reason.

The runtime query configuration is independently inferred rather than derived from the saved index provider/model metadata. Static snapshot checks compare public/private metadata (`toolrank/toolcard_snapshot.py:218-228`), but they do not guarantee that a runtime embedding query uses the model that generated the index. Binding query configuration to index metadata, or rejecting a mismatch before requesting embeddings, would make retrieval behavior reproducible.

### DeepSeek API compatibility details

Official DeepSeek documentation identifies `https://api.deepseek.com` as the API base and currently lists `deepseek-v4-flash` and `deepseek-v4-pro`. The task owner also live-verified `/models` and `/chat/completions` against the official endpoint with `deepseek-v4-flash`; no credential value was recorded here.

DeepSeek V4 thinking mode is enabled by default, and the official guide states that `temperature` is ignored in thinking mode. Shared structured requests and GPTScan requests to recognized DeepSeek hosts therefore send the provider-specific `thinking: {"type": "disabled"}` switch so the documented temperature-zero behavior remains effective. Custom OpenAI-compatible endpoints receive no DeepSeek-specific fields.

Shared structured requests and GPTScan callers that parse JSON send `response_format: {"type": "json_object"}` to recognized DeepSeek hosts while retaining explicit JSON instructions and local validation. Compatibility tests verify the exact request body and ensure custom hosts receive neither provider-specific field.

External references:

- DeepSeek models, API base, and pricing: https://api-docs.deepseek.com/quick_start/pricing
- DeepSeek thinking mode: https://api-docs.deepseek.com/guides/thinking_mode
- DeepSeek JSON output: https://api-docs.deepseek.com/guides/json_mode/
- SiliconFlow embeddings API: https://docs.siliconflow.cn/cn/api-reference/embeddings/create-embeddings

### Documentation and test coverage

Current documentation states the official DeepSeek chat defaults and makes only `DEEPSEEK_API_KEY` necessary for the default chat stack (`README.md`, `.env.example`). Knowledge-base extraction and GPTScan use the same chat defaults, while dense embeddings remain a separate SiliconFlow/Qwen path.

Existing focused coverage includes:

- Shared defaults and key isolation: `tests/test_openai_compat.py:24-98`.
- Payload and bounded transport retries: `tests/test_openai_compat.py:101-152`.
- Blank-model official default: `tests/test_cego_single_request.py:116-133` and `tests/test_final_report.py:110-145`.
- CEGO repair and primary-only fallback: `tests/test_repair_fallback.py:17-173`.
- Explanation fallback: `tests/test_final_report.py:50-277`.
- Dense failure to BM25: `tests/test_dace_retrieval.py:46-154`.
- Credential redaction and GPTScan-only delivery: `tests/test_execution_secret_handling.py:24-220` and `tests/test_runner_outer_timeout.py:64-140`.
- DeepSeek request semantics and GPTScan structured-call wiring: `tests/test_openai_compat.py` and `tests/test_gptscan_deepseek.py`.
- Vector provider/model/dimension mismatch: `tests/test_private_toolcards.py:453-502`.

Missing focused coverage:

1. The import-time environment-variable behavior of module defaults.
2. Runtime embedding configuration versus saved index metadata.

### Related specifications

`.trellis/spec/backend/lakes-scheduling-contract.md` contains the relevant contracts:

- Lines 115-121: exactly one application-level temperature-zero request, no sampling/voting, typed CEGO failures, and bounded repair before primary-only fallback.
- Lines 122-129: visible dense-retrieval failure to BM25.
- Lines 380-393: optional explanation fallback semantics.
- Lines 506-529: knowledge-base ingestion and environment-only credentials.
- Lines 530-535: secret delivery only to GPTScan, with no secrets in argv, reports, logs, or general workers.
- Lines 589-593, 618-621, and 633-634: failure-mode table entries for CEGO, retrieval, ingestion, and explanation.

The official DeepSeek request path now aligns its literal temperature-zero contract with the provider's thinking- and JSON-mode semantics.

### Local and generated artifacts

Ignored historical handoff and experiment files contain plaintext credential assignments. Values were neither opened into this report nor reproduced. Even though `.gitignore` and `.dockerignore` exclude the relevant handoff/experiment paths, those credentials should be treated as exposed: revoke or rotate them, then sanitize the local files. Affected families include `HANDOFF_2026-06-*.md` and `experiments_2026-06-23/` scripts/documentation.

`toolrank.egg-info/PKG-INFO` and `build/lib/toolrank/` contain stale generated copies of older configuration/documentation. Egg-info and distribution artifacts are ignored/excluded, but `build/` is not excluded by the Docker context. Regenerate or remove stale build output before packaging, or add `build/` to `.dockerignore`, so audits and image contents cannot be confused by obsolete defaults.

## Caveats / Not Found

- The shared-client source, README, environment example, and tests were being updated concurrently during this audit. Line references describe the final inspected snapshot and may move with later edits.
- No real `.env` file was found; only `.env.example` was present.
- No API keys are included in this report. Live official-endpoint success was relayed by the task owner and was not independently repeated with a credential in this research pass.
- Tests were inspected but not executed because this research task was read-only outside its research directory.
- Provider model availability can depend on account and rollout state. `deepseek-v4-flash` was live-verified for the configured account on 2026-08-06, but availability should still be handled as a request-time failure.
