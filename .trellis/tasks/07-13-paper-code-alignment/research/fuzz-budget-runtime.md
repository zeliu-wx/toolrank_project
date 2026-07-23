# Fuzz budget runtime boundary

## Decision

Treat fuzz duration as a developer-controlled campaign allocation, not a
historical completion-time estimate. Identify the policy by
`ToolCard.d8_mode == "fuzz"`; the currently packaged tools are ConFuzzius,
sFuzz, and Smartian.

Keep `ToolCostEntry.expected_runtime_minutes` and
`RuntimeEstimateProvenance` reserved for qualified historical completion
evidence. Add a separate typed `FuzzCampaignBudget` to the tool cost. Stage 1
continues to see fuzz completion runtime as unknown, so the budget cannot alter
`t^star`. Stage 2 and Stage 3 use one shared planning-runtime projection:

```text
fuzz     -> campaign.allocated_runtime_seconds / 60
non-fuzz -> expected_runtime_minutes
```

The default allocation is `ExecutionSchedule.tool_timeout_seconds`, which is
derived from the user's runtime budget. If the user supplies an explicit
per-tool timeout, that value becomes the fuzz campaign duration; it is not
compared with an absent historical completion estimate.

## Verified execution paths

- Generic tools are invoked through `prepare_smartbugs_invocation`, which
  forwards the resolved schedule as SmartBugs `--timeout`.
- ConFuzzius `tools/confuzzius/scripts/do_solidity.sh` receives `$TIMEOUT`,
  subtracts bounded per-contract overhead, and passes the remainder to
  `fuzzer/main.py --timeout`.
- sFuzz `tools/sfuzz/scripts/do_solidity.sh` receives `$TIMEOUT`, subtracts
  bounded overhead, and passes the derived value to `fuzzer -d`.
- Smartian receives the same outer `--timeout`; `run_smartian.py` uses
  `max(1, outer-3)` for the inner fuzz limit so report shutdown stays inside
  the scheduler-owned hard deadline.

The outer deadline remains authoritative. Very small allocations may end in a
typed timeout; wrappers must not silently extend the process deadline.

## Cross-layer consumers

- `toolrank/schemas_v2.py`: typed campaign allocation and validation.
- `toolrank/evidence_packet.py`: attach the allocation for every fuzz ToolCard;
  retain Performance-KB/literature evidence as descriptive only.
- `toolrank/plan_runtime.py`: own the shared planning-runtime projection and
  use it for constraints and `max * contract_count` accounting.
- `toolrank/checker.py`: use the shared projection instead of directly testing
  historical runtime presence.
- `toolrank/dace_rag.py` and `toolrank/cego.py`: expose historical completion
  runtime and campaign allocation as distinct fields.
- `toolrank/scene_scoring.py`: intentionally unchanged; Stage 1 must not turn
  user budget into historical runtime.
- `toolrank/execution.py`, `toolrank/runner.py`, and
  `docker/runners/run_smartian.py`: preserve the existing single timeout flow;
  add regressions unless a test exposes a real propagation defect.

## Accounting and edge cases

- Concurrent fuzz tools each receive the full per-input allocation. Do not
  divide the budget by tool count; plan time is the maximum.
- Directory inputs execute sequentially. Plan time remains
  `max(per-input runtime) * execution_input_count`. With the default full-budget
  campaign, more than one execution input is over the overall plan budget;
  the developer must provide a smaller explicit per-input timeout.
- A fuzz primary with no historical runtime is executable when its campaign
  plan fits the budget. A fuzz complement is judged by the same rule.
- Qualified-looking raw runtime rows, `campaign_cap`, literature means, and
  null summaries cannot override the campaign policy or populate expected
  completion time for a fuzz tool.
- A zero/unresolved budget cannot create a positive campaign allocation and
  remains unexecutable.
- An explicit timeout longer than the overall plan budget remains over-budget;
  it must not cause execution past the checked plan.
- Fresh measured elapsed time remains report metadata and is not written back
  into Performance-KB completion evidence.

## Required regressions

Cover all three packaged fuzz tools plus a renamed synthetic fuzz card;
default and explicit allocations; Stage 1 non-interference; primary and
complement executability; mixed static/fuzz and multiple-fuzz max accounting;
sequential input multiplication; DACE/CEGO serialization; Checker agreement;
SmartBugs timeout command construction for ConFuzzius/sFuzz; Smartian outer and
inner deadlines; and tiny-budget typed timeout behavior.
