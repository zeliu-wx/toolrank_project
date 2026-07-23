# Research: CEGO k=3 category-level majority voting

- Query: Inspect the current CEGO/OpenAI-compatible/RuleChecker pipeline and the effective manuscript text around low-temperature, k-sample majority voting; propose the smallest deterministic typed design for k=3, including unusable samples, citation merging, repair-loop interaction, API-call semantics, configuration ownership, and exact tests.
- Scope: mixed (local manuscript, task/spec artifacts, current source/tests, and the official OpenAI Chat Completions reference)
- Date: 2026-07-19

## Findings

### Conclusion

Implement majority voting as a **pre-certificate CEGO reducer**. In each checker
round, make exactly three independent single-choice completion calls, strictly
decode each response into one shared typed proposal model, take a strict `2 of
3` vote independently for each required category, merge only the winning
tool's citations, and pass the one aggregated proposal through the existing
`assemble_decision` and `check_decision` boundaries.

The aggregation should be deterministic given the three responses. It cannot
make a remote model deterministic across runs. A missing majority must retain
the primary for that category. A request failure or malformed sample must
abstain, not reduce the denominator from three and not silently count as a
primary-only model vote.

This is the smallest design because it leaves the public
`Step2DecisionCertificate`, RuleChecker, action IDs, budget logic, and fallback
contract unchanged. It adds one typed raw-response owner and a pure category
reducer before the existing deterministic assembly.

### Files found

- `/Users/liuze/Downloads/LAKES/main_revised.tex` -- effective manuscript; Stage 2 proposal, checking, repair, and voting prose is at lines 374--427.
- `.trellis/tasks/07-13-paper-code-alignment/prd.md` -- task requirements; weighted evidence must survive CEGO to RuleChecker at lines 314--344, and checked repair fallback is AC7 at line 354.
- `.trellis/tasks/07-13-paper-code-alignment/design.md` -- current typed evidence, additive ownership, checker, and fallback design at lines 267--374; test guidance is at lines 518--525.
- `.trellis/tasks/07-13-paper-code-alignment/implement.md` -- CEGO/checker checkpoint and existing repair-test intent at lines 119--152; weighted-lineage implementation record is at lines 428--447.
- `.trellis/tasks/07-13-paper-code-alignment/implement.jsonl` and `check.jsonl` -- active context manifests naming the scheduling and cross-layer specs.
- `.trellis/tasks/07-13-paper-code-alignment/research/paper-effective-contract.md` -- prior effective-paper extraction; the underspecified voting sentence is recorded at line 110 and repair ambiguities at lines 191--205.
- `.trellis/spec/backend/lakes-scheduling-contract.md` -- executable Stage 1--3 contract; canonical CEGO/checker signatures are at lines 14--45, evidence ownership at lines 51--74, repair behavior at lines 269--274, and required Stage 2 tests at lines 367--373.
- `.trellis/spec/guides/cross-layer-thinking-guide.md` -- requires one payload decoder/validator at the boundary rather than repeated untyped parsing at lines 74--101.
- `.trellis/spec/guides/code-reuse-thinking-guide.md` -- requires repeated constants and payload decoding to have a single owner at lines 55--82.
- `toolrank/cego.py` -- current prompt, response shape, lenient extraction, deterministic assembly, and one-call `run_cego` implementation.
- `toolrank/openai_compat.py` -- current OpenAI-compatible transport, stream parser, retry loop, JSON parsing, and hard-coded temperature.
- `toolrank/checker.py` -- deterministic certificate validation and matrix-owned citation/evidence checks.
- `toolrank/engine.py` -- Stage 2 eligibility branch, checker repair loop, checked primary-only fallback, and CEGO invocation.
- `toolrank/schemas_v2.py` -- current Pydantic ownership/certificate/checker models; the package requires Pydantic `>=2.7.0` (`pyproject.toml:12-17`).
- `toolrank/cli.py` -- current model option and checker ablation switch at lines 22--65.
- `tests/test_cego_assembly.py` -- existing additive assembly and invalid-candidate fallback coverage.
- `tests/test_repair_fallback.py` -- existing three-round rejection/fallback test.
- `tests/test_rule_checker_v2.py` and `tests/test_weighted_evidence_lineage.py` -- existing checker and citation-lineage coverage.
- `.env.example` -- current endpoint/model/key configuration surface; it has no CEGO sampling setting.

### Effective paper contract and what it does not define

The effective paper establishes the following observable order:

1. The LLM returns complementary owners and cited evidence IDs, while runtime
   remains RuleChecker-owned (`main_revised.tex:377`).
2. RuleChecker applies plan- and assignment-level checks
   (`main_revised.tex:381-403`).
3. Rejected output is revised with checker reasons, and the repair bound is
   `K_max=3` (`main_revised.tex:401`, `:417-423`).
4. The prose says: "We use low-temperature decoding, and majority voting over
   k samples, but the final plan must pass RuleChecker"
   (`main_revised.tex:401`).
5. Unresolved categories fall back to primary-only ownership
   (`main_revised.tex:424-427`).

The manuscript does **not** define:

- the value of `k`;
- the numerical temperature;
- whether a vote is over a whole plan, action ID, category owner, or citation
  set;
- whether the majority denominator is all configured samples or only valid
  samples;
- how request failures, non-JSON output, duplicate category proposals, or
  schema-invalid output vote;
- how citations from agreeing samples combine;
- whether RuleChecker checks each sample or only the voted result;
- whether samples or votes carry into a repair round.

The prior paper audit reaches the same conclusion
(`research/paper-effective-contract.md:110`) and also notes that the paper's
pseudocode revises after the final failed check and returns a later fallback
without checking either result (`research/paper-effective-contract.md:199`).
The current project already resolves that latter ambiguity correctly by
checking every model certificate and then checking the deterministic fallback
(`toolrank/engine.py:174-199`). The requested `k=3` and the exact voting rules
below are deterministic implementation resolutions, not claims about missing
manuscript detail.

### Current pipeline trace

```text
eligible complement exists + client available
  -> engine.run_model(previous CheckerVerdict)
  -> run_cego
  -> one create_json_chat_completion call at temperature=0
  -> permissive dict extraction
  -> assemble_decision
  -> one RuleChecker verdict
  -> accept OR repeat up to two repairs
  -> checked primary-only fallback after the third rejected round
```

Concrete patterns:

- CEGO currently asks for an envelope containing `complements[]`, with one
  `category`, `tool`, and non-empty `evidence_refs` list per item
  (`toolrank/cego.py:46-70`). The schema is appended to prompt text; it is not
  used for local model validation (`toolrank/openai_compat.py:214-227`).
- `run_cego` makes exactly one logical completion call and immediately
  assembles it (`toolrank/cego.py:303-333`). There is no sample loop or vote.
- The transport sets `temperature` to `0` itself
  (`toolrank/openai_compat.py:204-227`). This means a generic transport helper,
  rather than CEGO, currently owns the decoding policy.
- The stream parser reads only `chunk["choices"][0]` and never groups deltas by
  choice index (`toolrank/openai_compat.py:125-154`). Its request payload also
  omits `n` (`toolrank/openai_compat.py:220-227`).
- A logical call may make three HTTP attempts: the configured retry count is
  two (`toolrank/openai_compat.py:36-44`), and the loop is
  `range(retry_count + 1)` (`toolrank/openai_compat.py:229-275`). Those attempts
  are transport retries, not independent model votes.
- Parsed JSON is only required to be a dict. A top-level list is coerced to
  `{"items": ...}`, and extra or wrong fields are not validated against the
  supplied schema (`toolrank/openai_compat.py:65-89`).
- `_requested_complements` silently skips non-dicts, bad fields, and duplicate
  categories, and a missing/non-list `complements` field becomes an empty
  proposal (`toolrank/cego.py:176-191`). Consequently, a structurally malformed
  but parseable response can become a primary-only certificate and pass the
  checker instead of being identified as an unusable sample.
- Assembly is already the correct semantic boundary for legal candidates and
  global budget. It starts with the primary, accepts only matrix-listed
  candidates, tests the cumulative budget, and retains primary-only ownership
  otherwise (`toolrank/cego.py:214-291`). It must remain after voting rather
  than be duplicated in the voter.
- RuleChecker already owns citation authenticity/relevance
  (`toolrank/checker.py:150-163`), hard blocks (`:164-173`), weighted support
  (`:175-182`), action/owner consistency (`:184-211`), and final accept/reject
  (`:225-242`). The voter must not pre-approve citations or evidence balance.
- The repair loop calls CEGO and RuleChecker once per round, with
  `range(max_cego_retries + 1)`, then checks the primary-only fallback
  (`toolrank/engine.py:174-199`). The production default
  `max_cego_retries=2` therefore already means exactly three checked proposal
  rounds (`toolrank/engine.py:393-405`). It must not be changed to `3`, which
  would create four rounds.
- Every new repair prompt receives the previous checker's `rule_failures`
  (`toolrank/cego.py:163-173`; `toolrank/engine.py:543-566`).
- CEGO is not called when there are no required categories, no eligible
  complement, no client, or the primary runtime is terminal
  (`toolrank/engine.py:487-503`, `:519-541`).

### Smallest typed boundary

Use one strict response type as the single owner of both local decoding and the
JSON schema sent to the model. The names are illustrative but the ownership is
material:

```python
class CegoComplementProposal(BaseModel):
    model_config = ConfigDict(extra="forbid")
    category: str = Field(min_length=1)
    tool: str = Field(min_length=1)
    evidence_refs: Annotated[list[str], Field(min_length=1)]

class CegoProposalSample(BaseModel):
    model_config = ConfigDict(extra="forbid")
    complements: list[CegoComplementProposal]
    # after-validator: category values must be unique within the sample
```

Implementation ownership:

- Put the Pydantic response types in `toolrank/schemas_v2.py`, whose module
  already owns CEGO/checker pipeline models (`toolrank/schemas_v2.py:1`) and
  uses `extra="forbid"` throughout, including category assignments and the
  certificate (`toolrank/schemas_v2.py:821-969`).
- Replace the hand-maintained `_response_schema` body with
  `CegoProposalSample.model_json_schema()`. Do not maintain a Pydantic decoder
  and a separate hand-written JSON schema.
- In `run_cego`, validate every returned dict with
  `CegoProposalSample.model_validate`. A transport/non-JSON failure and a local
  validation failure are both unusable samples for voting. They may retain
  separate internal status labels for diagnostics, but they have identical vote
  semantics.
- Keep `Step2DecisionCertificate` unchanged. Sample outcomes are transient CEGO
  inputs, not accepted scheduling decisions; adding them to the public
  certificate would broaden the contract without helping RuleChecker.
- Keep `assemble_decision` as the sole legal-candidate/budget/category-owner
  assembler and `check_decision` as the sole final evidence validator.

An optional private immutable outcome record in `cego.py` is sufficient if
tests or warnings need to distinguish failure modes:

```python
@dataclass(frozen=True)
class _SampleOutcome:
    index: int
    status: Literal["VALID", "REQUEST_FAILED", "MALFORMED"]
    proposal: CegoProposalSample | None = None
```

It should not be added to `schemas_v2` or `PipelineResult` unless sample-level
observability becomes a separate requirement.

### Exact k=3 voting semantics

Let the vote value for category `c` be either `PRIMARY_ONLY` or one exact tool
ID. Use the stable de-duplicated order of `context.required_categories` only
when serializing the aggregate. The majority threshold is always
`floor(3/2)+1 = 2`.

| Sample condition for category `c` | Vote |
|---|---|
| Strictly valid sample contains one proposal for `c` | That proposal's exact `tool` ID |
| Strictly valid sample omits `c` | `PRIMARY_ONLY` |
| Request/stream/JSON call fails after transport retries | Abstain for every category |
| Parsed dict fails the typed response model | Abstain for every category |
| Sample repeats a category | Whole sample is malformed and abstains |
| Well-formed proposal names a non-required category | Ignore that row; it is never copied into the aggregate |
| Well-formed proposal names an ineligible tool or bad evidence ID | Count the syntactic tool vote; assembly/checker remains the semantic authority |

For each required category:

1. Count valid `PRIMARY_ONLY` and exact-tool votes. Abstentions do not enter the
   counter and do not lower the threshold.
2. A complement wins only when the same tool has at least two of the configured
   three votes.
3. If `PRIMARY_ONLY` has at least two votes, or no value reaches two, omit the
   category from the aggregated `complements` list. Both cases safely retain
   the primary; they need not create a new public status.
4. No lexical or score tie-break is needed. With three configured samples, at
   most one value can have two votes.
5. Call `assemble_decision` once with the aggregate. It re-applies legal
   candidate, cumulative slots, runtime, and additive-owner rules to the
   independently voted category winners.

Truth-table examples:

| Three outcomes for one category | Aggregate |
|---|---|
| `b, b, c` | complement `b` |
| `b, b, failed` | complement `b` |
| `b, primary-only, primary-only` | primary-only |
| `b, c, primary-only` | primary-only (no strict majority) |
| `b, failed, malformed` | primary-only (one vote is not a majority) |
| `failed, malformed, failed` | checked primary-only operational fallback |

When all three samples are unusable, raising one `CegoError` **after all three
logical calls have been attempted** is preferable to pretending that the model
voted primary-only. The existing engine catch then records a warning, builds a
primary-only certificate, and checks it (`toolrank/engine.py:568-571`). This is
an observability distinction; the executable result remains fail-closed.

### Citation merging

For a winning complement `(category, tool)`:

1. Take citations only from valid samples whose vote for that category is the
   winning tool.
2. Compute the set union of their `evidence_refs`.
3. Serialize the result in lexical order after de-duplication.
4. Do not include refs from a losing tool, a primary-only vote, an abstention,
   or another category.
5. Do not intersect refs. Two agreeing samples may cite different authentic
   rows; an intersection could erase all support despite agreement on the tool.
6. Do not discard an unknown or opposing ref before RuleChecker. The union must
   preserve model-supplied grounding exactly enough for the existing checker to
   reject `EVIDENCE_REF_NOT_FOUND`, irrelevance, hard ineligibility, or
   non-positive evidence balance (`toolrank/checker.py:150-182`).

Example:

```text
sample 1: reentrancy -> b, refs [z, a, a]
sample 2: reentrancy -> b, refs [b, a]
sample 3: reentrancy -> c, refs [loser]
aggregate: reentrancy -> b, refs [a, b, z]
```

Lexical ordering makes the aggregate independent of completion arrival order
and gives stable certificate/test serialization. RuleChecker still resolves
the IDs back to the matrix; the model never owns evidence weights
(`.trellis/spec/backend/lakes-scheduling-contract.md:65-74`).

### API-call semantics

Use three **sequential single-choice logical calls**, not one request with
`n=3`:

- Call `create_json_chat_completion` exactly three times per CEGO/checker round.
- Use the same system prompt, user payload, response schema, model, and previous
  checker failures for all three calls in a round.
- Always issue the third call even if the first two responses agree. Otherwise
  the implementation is early-stopped consensus, not `k=3`, and the third
  agreeing sample's citations can never join the union.
- Keep `n` absent. The official OpenAI reference says `n>1` can return multiple
  choices and that streamed choices carry an `index`; current code consumes
  only `choices[0]` and discards the index, so `n=3` would require a broader
  stream-parser and provider-compatibility rewrite.
- Do not parallelize the first implementation. Sequential calls preserve
  deterministic sample indices, avoid adding concurrency/rate-limit behavior,
  and are the smallest change. Aggregate output remains order-insensitive.
- A transport retry is part of one logical sample. Its eventual single parsed
  response gets at most one vote per category. Retry attempts never become
  additional votes.

Exact maximum counts with current defaults:

| Path | Logical model samples | Maximum HTTP POST attempts with transport retry count 2 | Checker calls |
|---|---:|---:|---:|
| No category/candidate/client or early runtime terminal | 0 | 0 | 0 or deterministic-plan check only |
| First aggregate accepted | 3 | 9 | 1 |
| First rejected, second accepted | 6 | 18 | 2 |
| All three proposal rounds rejected | 9 | 27 | 4 (three proposal checks plus checked fallback) |

The HTTP-attempt maxima assume every logical call reaches all three transport
attempts. They are not extra samples.

### Configuration ownership

| Setting | Single owner | Recommendation |
|---|---|---|
| CEGO sample count | `toolrank/cego.py` | `CEGO_SAMPLE_COUNT: Final = 3` |
| CEGO decoding temperature | `toolrank/cego.py` | `CEGO_TEMPERATURE: Final = 0.0` |
| Generic request temperature field | `toolrank/openai_compat.py` | Add an explicit `temperature: float` argument and serialize the caller value; do not own the CEGO default here |
| Checked proposal rounds | `toolrank/engine.py` | Keep `max_cego_retries=2`, which means initial round plus two repairs = manuscript `K_max=3` |
| Transport retry/backoff/timeouts | `toolrank/openai_compat.py` | Keep existing environment-owned transport settings; they do not affect vote cardinality |
| Model/base URL/key | existing CLI/environment/client boundary | No change |
| Candidate legality, evidence balance, runtime, slots | matrix/assembly/RuleChecker | No change; never make them sampling settings |

Temperature zero is the smallest faithful choice: the current code already
uses it (`toolrank/openai_compat.py:226`), it is a low-temperature setting, and
the paper gives no numeric value. Choosing `0.1` or `0.2` would invent a new
behavioral constant without evidence. Move ownership to CEGO by parameterizing
the generic transport, but preserve the value.

Do not add CLI flags or environment variables for `k` or temperature in this
change. The requested `k=3` is an algorithm contract, not a developer runtime
requirement. The existing `.env.example:1-4` and `toolrank/cli.py:22-65` should
remain focused on endpoint/model/key and user scheduling inputs. A configurable
sampling-policy model can be introduced later only if variability becomes a
real requirement.

### Repair-loop interaction

The checked sequence should be:

```text
round 1: 3 fresh samples -> category vote -> assemble once -> RuleChecker once
  ACCEPT -> return
  REJECT -> put this verdict's failure codes in all three round-2 prompts
round 2: 3 fresh samples -> category vote -> assemble once -> RuleChecker once
  ACCEPT -> return
  REJECT -> put this verdict's failure codes in all three round-3 prompts
round 3: 3 fresh samples -> category vote -> assemble once -> RuleChecker once
  ACCEPT -> return
  REJECT -> build primary-only -> RuleChecker once -> return or hard-fail
```

Rules:

- RuleChecker evaluates the aggregated certificate, not each raw sample. The
  paper says majority voting produces a plan that must then pass RuleChecker;
  checking three samples independently would change both the vote and repair
  semantics (`main_revised.tex:401-403`).
- Do not carry samples, votes, or citations between rounds. A repair round is a
  fresh `k=3` decision conditioned only on the current typed context and the
  previous checker failure codes.
- A category that has no strict majority becomes primary-only and is legal; it
  does not force another repair. This is consistent with the paper's category
  fallback (`main_revised.tex:401`, `:424-427`).
- A majority complement with merged invalid citations is rejected normally.
  The next round receives those checker failures. Do not sanitize the citations
  in the voter to avoid repair.
- If all three calls in a round are unusable, raise after collection and use the
  engine's existing checked primary-only error fallback. Do not consume three
  more checker-repair rounds without a checker verdict to repair.
- Keep the final fallback checker call at `toolrank/engine.py:195-198`; it fixes
  the manuscript pseudocode's unchecked-final-return ambiguity.

The default `--checker` path is the paper-faithful path. The current CLI still
offers `--no-checker` (`toolrank/cli.py:60-64`), and the engine accepts an
unchecked certificate in that ablation path (`toolrank/engine.py:572-578`).
Majority voting does not make that path satisfy the paper's “final plan must
pass RuleChecker” statement. Either retain it explicitly as an ablation or
remove it in a separately authorized contract change; do not conflate it with
this minimal voting implementation.

### Recommended implementation file scope

No production file was edited during this research. A minimal later
implementation should need only:

- `toolrank/schemas_v2.py` -- add the strict raw CEGO proposal types.
- `toolrank/cego.py` -- derive the response schema from the type, collect three
  outcomes, reduce per category, merge citations, then call existing assembly.
- `toolrank/openai_compat.py` -- accept caller-owned temperature; keep single
  choice and current transport retries.
- `tests/test_cego_majority.py` -- new pure reducer/collector tests.
- `tests/test_repair_fallback.py` -- extend call-count and fresh-round coverage.
- `tests/test_openai_compat.py` -- add the explicit-temperature/single-choice and
  logical-call-versus-transport-retry tests.

`toolrank/checker.py`, `toolrank/engine.py`, public certificate models, CLI,
action IDs, budget logic, and execution code should not require production
changes. If implementation pressure reaches those files, re-check whether the
vote is being placed after assembly/checking instead of before it.

### Exact tests

Use in-memory Stage 2 fixtures and mocked completion responses, consistent with
the task design's instruction to avoid network calls and exercise real
assembly/checker logic (`design.md:518-525`).

#### `tests/test_cego_majority.py`

1. `test_k3_majority_is_independent_per_category_and_merges_winner_refs`
   - Required categories: `reentrancy`, `access_control`.
   - Sample 1: `reentrancy -> b [z,a,a]`, `access_control -> c [c1]`.
   - Sample 2: `reentrancy -> b [b,a]`, omit `access_control`.
   - Sample 3: `reentrancy -> c [loser]`, `access_control -> c [c2]`.
   - Assert aggregate is `reentrancy -> b [a,b,z]` and
     `access_control -> c [c1,c2]`, in required-category order.
   - Assert `loser` is absent and the primary remains first after real
     `assemble_decision`.

2. `test_valid_omission_is_a_primary_only_vote`
   - Two valid samples omit `reentrancy`; one proposes `b`.
   - Assert no aggregate complement and a real assembled `run_primary`
     certificate.

3. `test_unusable_samples_abstain_without_lowering_the_two_vote_threshold`
   - Parameterize: `b,b,failed -> b`; `b,failed,malformed -> primary-only`;
     `b,c,failed -> primary-only`.
   - Assert the threshold stays two of configured three, not one of one valid or
     one of two valid.

4. `test_strict_sample_model_rejects_ambiguous_or_out_of_schema_payloads`
   - Parameterize duplicate category rows, empty `evidence_refs`, blank tool/ID,
     and an extra weight-like field.
   - Assert `CegoProposalSample.model_validate` fails. This proves the prompt
     schema is an actual local boundary rather than documentation only.

5. `test_run_cego_makes_exactly_three_sequential_calls_even_after_early_agreement`
   - Mock three valid responses; the first two agree.
   - Assert call count remains three, sample indices/order are stable, all calls
     receive the same prompt/schema/previous verdict, and every call uses the
     CEGO-owned temperature `0.0`.

6. `test_run_cego_all_unusable_samples_raises_after_three_calls`
   - Return one transport error, one non-JSON/unusable result, and one typed
     validation failure.
   - Assert all three logical calls occur before one `CegoError`; assert no raw
     partial proposal is assembled.

#### `tests/test_repair_fallback.py`

7. `test_checker_repair_checks_one_aggregate_per_round_and_uses_fresh_votes`
   - Round 1's three samples produce a majority `b` with `missing_ref`; the real
     checker rejects it.
   - Round 2's three fresh samples produce a grounded `b` majority; the real
     checker accepts it.
   - Assert six logical model calls, two checker calls, the second round's three
     prompts all contain the first verdict's exact failure code, and no round-1
     citation survives unless emitted again.

8. `test_three_rejected_k3_rounds_make_nine_samples_then_check_primary_fallback`
   - Supply nine majority-forming but checker-invalid responses.
   - Assert nine logical sample calls, three rejected aggregate checks, a fourth
     checker call for the deterministic primary-only fallback, final `ACCEPT`,
     and primary-only owners.
   - Keep the existing assertion that `max_cego_retries=2` means three proposal
     rounds (`tests/test_repair_fallback.py:40-51`).

#### `tests/test_openai_compat.py`

9. `test_explicit_temperature_is_serialized_without_multi_choice_n`
   - Capture the request body from one mocked SSE completion.
   - Assert `temperature == 0.0`, `stream is True`, and `n` is absent.
   - This guards CEGO-owned decoding while retaining one logical sample per
     request.

10. `test_transport_retries_still_return_one_logical_sample`
    - Make `_open_request` fail twice with a retryable transport error and
      succeed on the third attempt; patch backoff to avoid sleeping.
    - Assert three wire attempts but one returned proposal object. In the CEGO
      collector, that object must occupy one sample slot and contribute at most
      one vote per category.

Existing `tests/test_cego_assembly.py`, `tests/test_rule_checker_v2.py`, and the
weighted-evidence tests should remain unchanged and continue proving that the
aggregate cannot bypass candidate, citation, evidence-weight, action, or budget
rules.

### External references

- [OpenAI Chat Completions API reference](https://developers.openai.com/api/reference/resources/chat) (accessed 2026-07-19) -- documents that a completion can contain more than one `choices` element when `n > 1`, and that each streamed choice has an `index`. This supports the finding that the current `choices[0]` stream parser cannot safely implement `n=3` without a broader rewrite. LAKES targets OpenAI-compatible endpoints, so this reference describes OpenAI's contract only; it does not establish that every configured provider implements `n` identically.
- Local dependency version: `pydantic>=2.7.0` in `pyproject.toml:12-17`; no external Pydantic behavior beyond the already-used `BaseModel`, `ConfigDict`, validators, `model_validate`, and `model_json_schema` APIs is required.

### Related specs

- `.trellis/spec/backend/lakes-scheduling-contract.md` -- RuleChecker remains
  authoritative for matrix-owned evidence, citation validity, bounded repair,
  and checked primary-only fallback (`:51-74`, `:269-274`).
- `.trellis/spec/guides/cross-layer-thinking-guide.md` -- the raw LLM JSON must
  be decoded and validated once at its boundary, not parsed independently by
  aggregation and assembly (`:74-101`).
- `.trellis/spec/guides/code-reuse-thinking-guide.md` -- derive the prompt JSON
  schema from the same response type and keep sample/temperature constants in
  one CEGO owner (`:55-82`).
- `.trellis/tasks/07-13-paper-code-alignment/design.md` -- Stage 2 already
  requires typed evidence, deterministic assembly, and RuleChecker-owned
  arithmetic (`:267-374`).

## Caveats / Not Found

- Critical not-found: the effective manuscript fixes neither `k` nor a numeric
  temperature and never defines the majority unit, malformed-sample rule, or
  citation reducer (`main_revised.tex:401`). `k=3` is supplied by the research
  request; `temperature=0.0` is the minimal preservation of current behavior.
- “Deterministic” here means the reducer has one result for the same three typed
  outcomes. Low-temperature remote generation, provider routing, and backend
  changes can still vary the samples. Majority voting is not a reproducibility
  guarantee.
- Three sequential calls triple first-round model latency and token usage.
  With three checked rounds and current transport retries, the worst case is
  nine logical samples and 27 HTTP attempts. This cost follows directly from
  `k=3`; hiding it behind transport retries or early stopping would change the
  contract.
- Whole-sample strict validation deliberately makes an ambiguous/extra-field
  response abstain across categories. A more granular partial decoder could
  salvage unrelated categories, but it would add error-localization rules and
  is not the smallest design.
- A well-formed but semantically illegal tool/citation is not classified as
  malformed. It remains visible to deterministic assembly/RuleChecker so that
  no second semantic validator can drift from the matrix-owned rules.
- The current `--no-checker` switch is an explicit ablation and cannot satisfy
  the paper's final-check requirement. This research does not authorize its
  removal.
- No production code, spec, task plan, JSONL context, test, or user-owned
  knowledge-base file was modified. No tests were run because this artifact is
  design research, not implementation.
