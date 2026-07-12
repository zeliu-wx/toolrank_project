# Release Blockers Batch 1 Design

## Goal

Fix the first three release-blocking correctness and security defects without changing benchmark data, ranking formulas, category selection, or executor packaging:

1. a valid primary-only decision must reference the action matrix's real action ID;
2. missing parsed findings must never be replaced with ToolCard capability claims;
3. GPTScan credentials must not appear in serialized execution state, displayed commands, or child-process argument lists created by LAKES.

## Scope

This batch changes only the CEGO assembly contract, fused-report behavior for zero parsed findings, credential transport, and focused regression tests. It does not change `performance_db.json`, `n_eff`, Top-5 selection, taxonomy normalization, Solidity pragma parsing, packaging, Docker images, timeout semantics, or stale-report reuse.

## Decision 1: Matrix-Owned Action IDs

`ActionByEvidenceMatrix` remains the source of truth for executable action IDs. When CEGO selects no complement, `_parse_and_assemble` must locate the legal `RUN_PRIMARY` action whose tool is the current primary and copy that action's `action_id` into the certificate. It must not construct or hard-code `run_primary`.

If the matrix has no matching legal primary action, assembly fails closed with `CegoError`; it must not emit a certificate that the checker will inevitably reject.

Acceptance behavior:

- a matrix containing `run_primary_slither` produces a certificate with `selected_action_id == "run_primary_slither"`;
- the checker accepts the action when the remaining evidence and feasibility requirements are valid;
- composition decisions continue to use the existing matrix action `plan_tool_composition`.

## Decision 2: Honest Empty Reports

The ToolCard synthesis fallback in `engine._build_fused_report` is removed. Tool capability is recommendation evidence, not an executed vulnerability finding.

When execution reports parsed findings, fusion continues unchanged and uses `findings_source="execution"`. When execution returns success but parsing yields no findings, the engine writes an empty fused report with `findings_source="no_parsed_findings"`. This label deliberately does not claim that the contract is clean; it only states what the pipeline observed.

The compact `fused_report.json` payload includes `findings_source` alongside `findings`. A zero-result payload therefore has this shape:

```json
{
  "findings_source": "no_parsed_findings",
  "findings": []
}
```

Failed or unrequested execution still produces no fused report. No code path may create a `Finding` from a ToolCard category assignment.

## Decision 3: Environment-Only Child Credential Transport

The existing top-level CLI options remain accepted for compatibility, but the engine no longer appends their values to `runner_command`. `ExecutionResult` carries runner environment overrides in a field excluded from Pydantic serialization and object representation. `execute_plan` merges those overrides into a copy of the parent environment before starting the runner.

The runner passes the GPTScan key and compatible API base through environment variables. Its GPTScan child command no longer contains `-k <secret>`. The vendored GPTScan CLI accepts an omitted `-k` and reads `OPENAI_API_KEY` from its environment. Direct users should prefer `OPENAI_API_KEY` and `OPENAI_API_BASE`; retaining the old top-level options in this batch avoids an unrelated breaking CLI change.

Security acceptance behavior:

- the secret is absent from `runner_command`;
- the secret is absent from `ExecutionResult.model_dump()` and `model_dump_json()`;
- the secret is absent from execution detail output and persisted `execution.json`;
- the secret is present in the environment delivered to the runner;
- the GPTScan child command contains no secret-bearing argument.

## Tests

Tracked pytest regression tests cover each root cause independently:

1. primary-only CEGO assembly copies the matrix-owned action ID and passes checker action lookup;
2. successful execution with no parsed findings yields an empty, provenance-labelled report and never emits `coverage-level` findings;
3. real execution findings still use `findings_source="execution"`;
4. execution-plan serialization and diagnostic output contain no test secret;
5. the runner receives the test secret through its environment;
6. the GPTScan child command omits the secret and `-k` credential argument.

The repository's blanket `tests/` ignore rule is removed so the new regression source is tracked; existing cache patterns continue to ignore `tests/__pycache__` and pytest artifacts.

## Isolation and Change Discipline

Implementation runs in a separate Git worktree based on the committed design. The user's modified `toolcards/performance_db.json` remains untouched and unstaged in the original checkout. Each production change is limited to lines required by these three fixes, plus the focused tests and the minimum `.gitignore` adjustment needed to track them.

## Completion Criteria

This batch is complete only when:

- each new regression test is observed failing before its production fix and passing afterward;
- the focused tests pass together;
- the full available tracked test suite passes;
- a secret scan of generated execution structures and diagnostic text finds no injected test secret;
- `git diff` contains no benchmark-data changes and no unrelated refactoring.
