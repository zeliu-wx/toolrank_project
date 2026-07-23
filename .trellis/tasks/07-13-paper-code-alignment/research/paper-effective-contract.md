# Research: Effective contract of `main_revised.tex`

- Query: Extract the executable Stage 1--3 contract from the effective, uncommented LaTeX in `/Users/liuze/Downloads/LAKES/main_revised.tex`, including runtime/budget rules, tool and complement eligibility, execution/fusion behavior, every explicit threshold and output, and internal manuscript ambiguities or contradictions.
- Scope: internal (local manuscript, task artifacts, and Trellis specifications)
- Date: 2026-07-17

## Findings

### Files found

- `/Users/liuze/Downloads/LAKES/main_revised.tex` -- authoritative local manuscript inspected as effective LaTeX; the operative workflow is in lines 265--436.
- `.trellis/tasks/07-13-paper-code-alignment/prd.md` -- task requirements, including implementation-defined rules that go beyond the active manuscript.
- `.trellis/tasks/07-13-paper-code-alignment/design.md` -- current `screc_v2` design and deterministic resolutions for manuscript gaps.
- `.trellis/tasks/07-13-paper-code-alignment/implement.md` -- completed implementation checkpoints and verification plan.
- `.trellis/tasks/07-13-paper-code-alignment/implement.jsonl` and `check.jsonl` -- context manifests identifying the scheduling and cross-layer specifications.
- `.trellis/spec/backend/lakes-scheduling-contract.md` -- current executable implementation contract; it is substantially more specific than the paper.
- `.trellis/spec/guides/cross-layer-thinking-guide.md` -- one-owner boundary guidance relevant to the Stage 1 packet through fused-report flow.
- `.trellis/spec/guides/code-reuse-thinking-guide.md` -- one-owner/shared-helper guidance relevant to selection and runtime rules.
- `.trellis/workflow.md` -- Trellis research persistence and active-task workflow.

### Effective-LaTeX boundary

The manuscript has no `comment` environment or `\iffalse` block. Ordinary LaTeX `%` comments are therefore the material distinction between active and obsolete prose. The active framework overview is at `/Users/liuze/Downloads/LAKES/main_revised.tex:265`, Stage 1 at lines 267--331, Stage 2 at lines 333--429, and Stage 3 at lines 431--436.

The following tempting statements are **not** part of the effective paper:

- The older three-stage abstract at `/Users/liuze/Downloads/LAKES/main_revised.tex:152` is fully commented.
- The explicit old input/output summary at `/Users/liuze/Downloads/LAKES/main_revised.tex:188` is fully commented.
- Statistical certification, confidence-interval weakness partitioning, “one augmenting tool per category,” and “one tool responsible per category” appear together only in the fully commented line `/Users/liuze/Downloads/LAKES/main_revised.tex:190`. They cannot define current behavior.
- Older background descriptions at `/Users/liuze/Downloads/LAKES/main_revised.tex:205-217` and the duplicate overview at line 262 are commented.

The active abstract and introduction instead say that LAKES selects a primary, adds complementary tools, runs the selected tools in parallel, and produces one unified category-organized report (`/Users/liuze/Downloads/LAKES/main_revised.tex:155`, `:189`).

### Effective end-to-end contract

The active overview supplies these top-level inputs: target contract, precision/recall performance preference, developer-specified vulnerability categories, and time budget. It describes three stages and a dynamic knowledge base (`/Users/liuze/Downloads/LAKES/main_revised.tex:265`). The concrete data flow recoverable from the formulas and algorithms is:

```text
target C + preference + required categories C_req + runtime requirement B
  -> contract profile (solc, size, five complexity features)
  -> Gower-style contract distances
  -> normalized benchmark weights {w_D}
  -> per-benchmark precision/recall rank scores {s_t,D}
  -> support-qualified primary t* and scores {S_t}
  -> DACE-RAG evidence matrix M + KB runtime estimates {r_hat_t}
  -> LLM-proposed additive category owner sets and citations
  -> RuleChecker validation / bounded repair / primary-only fallback
  -> parallel execution of verified tools
  -> owner-filtered, provenance-preserving fused report
```

#### Stage 1: benchmark relevance

1. Profile the target and historical contracts using Solidity compiler version, code size, and five structural metrics: mean, maximum, and total cyclomatic complexity, maximum nesting depth, and cross-contract coupling count (`/Users/liuze/Downloads/LAKES/main_revised.tex:270-272`).
2. Compute a weighted Gower-style distance. Compiler mismatch contributes one half. The mean normalized numeric distance over code size plus the five complexity metrics contributes the other half (`/Users/liuze/Downloads/LAKES/main_revised.tex:275-280`). Numeric values are transformed with `log(1+x)` and normalized by the knowledge-base-wide transformed range (`:280`).
3. Convert contract distance to Gaussian similarity, average within each benchmark, and normalize across benchmarks:

   `p_hat_D = |D|^-1 sum_{x in D} K_h*(d(C,x))` and `w_D = p_hat_D / sum_D' p_hat_D'` (`/Users/liuze/Downloads/LAKES/main_revised.tex:282-290`).

4. Select bandwidth `h*` by leave-one-out likelihood over the supplied bandwidth grid (`/Users/liuze/Downloads/LAKES/main_revised.tex:316-328`).
5. The explicit output of the Gower-KDE algorithm is `{w_D}`, normalized so `sum_D w_D = 1` (`/Users/liuze/Downloads/LAKES/main_revised.tex:290`, `:317`, `:328-329`). There is no active scene-pruning threshold.

#### Stage 1: score, eligibility, selection, and output

1. The paper ranks only solc-compatible tools `T_C` (`/Users/liuze/Downloads/LAKES/main_revised.tex:270`, `:292`). The overview calls the selected tool “feasible,” but the formal Stage 1 text makes solc compatibility the only explicit eligibility property (`:265`, `:292`).
2. For benchmark `D`, recall and precision use ranks `r^R_t,D` and `r^P_t,D`, where rank 1 is best. Rank normalization is `phi(r,n)=(n-r+1)/n` (`/Users/liuze/Downloads/LAKES/main_revised.tex:292`).
3. The per-benchmark score is

   `s_t,D = lambda_R phi(r^R_t,D,n_D) + lambda_P phi(r^P_t,D,n_D)` (`/Users/liuze/Downloads/LAKES/main_revised.tex:294-298`).

4. Rank Order Centroid weights encode the developer preference: the preferred metric has weight `3/4`; the other has weight `1/4` (`/Users/liuze/Downloads/LAKES/main_revised.tex:300`).
5. For the benchmarks `D_t` having “comparable metrics” for tool `t`, compute

   `S_t = sum_{D in D_t}(w_D s_t,D) / sum_{D in D_t} w_D` (`/Users/liuze/Downloads/LAKES/main_revised.tex:303-306`).

6. Primary eligibility is exactly the conjunction visible in the argmax: `t` is solc-compatible and its comparable-metric support mass satisfies `sum_{D in D_t} w_D >= tau`. The paper fixes `tau=0.2` (`/Users/liuze/Downloads/LAKES/main_revised.tex:305`, `:309`). Runtime budget is not an eligibility predicate or score term.
7. Select the eligible tool with greatest `S_t`. Resolve an `S_t` tie first by “the raw value on the developer-preferred metric” and then by lower runtime (`/Users/liuze/Downloads/LAKES/main_revised.tex:309`). No final tie key is specified.
8. The explicit Stage 1-to-Stage 2 output is `(t*, {S_t}, {s_t,D}, {w_D})`. The paper assigns the meanings “default category owner,” global scores, benchmark-level comparison, and Stage 2 relevance weights, respectively (`/Users/liuze/Downloads/LAKES/main_revised.tex:309`).

No active prose gives Stage 1 certification, a primary candidate set, a robust-single action, category counts, a confidence interval, or a terminal result when the eligible argmax is empty.

#### Stage 2: inputs, evidence, proposal, and output

The formal inputs are primary `t*`, feasible candidates `T_cand`, required categories `C_req`, evidence matrix `M`, Stage 1 weights `{w_D}`, runtime estimates `{r_hat_t}`, runtime requirement `B`, and target solc version `v`. The explicit output is assignment `a` plus evidence citations `E` (`/Users/liuze/Downloads/LAKES/main_revised.tex:405-411`).

Assignment semantics are additive:

- `a : C_req -> 2^(T_cand union {t*})` (`/Users/liuze/Downloads/LAKES/main_revised.tex:336`).
- Every required category begins with `a(c)={t*}` (`:336`, `:412-415`).
- The LLM returns only complementary owners and cited evidence IDs; its delta is unioned with the existing primary owner set (`/Users/liuze/Downloads/LAKES/main_revised.tex:377`, `:413-415`).
- If no candidate qualifies or a category remains rejected after repair, the category stays/falls back to `{t*}` (`/Users/liuze/Downloads/LAKES/main_revised.tex:336`, `:401`, `:424-427`).

DACE-RAG behavior is:

1. Retrieve both primary and candidate evidence keyed by `(category, tool, decision action)`, linking passages to quantitative rows (`/Users/liuze/Downloads/LAKES/main_revised.tex:341`). Retrieval is described as BM25 plus dense retrieval, but no top-k, score blend, or retrieval threshold is specified (`:351`).
2. Runtime is not estimated by the LLM. The knowledge base supplies per-tool historical runtime statistics bucketed by solc compatibility and contract size/complexity. `r_hat_t` is a “conservative statistic” from a matching or nearest compatible bucket (`/Users/liuze/Downloads/LAKES/main_revised.tex:351`).
3. DACE-RAG is said to add `({S_t},{s_t,D},{w_D},{r_hat_t})` to the evidence (`/Users/liuze/Downloads/LAKES/main_revised.tex:351`).
4. Its formal matrix row is `M_c,t=(t, FOR_c,t, AGAINST_c,t, COMPARE_c,t, GAP_c,t, S_t, r_hat_t)` (`/Users/liuze/Downloads/LAKES/main_revised.tex:353-355`). Evidence entries carry source, claim, metric/passage, applicability tags, stance, and relevance weight (`:355`).
5. `FOR`, `AGAINST`, `COMPARE`, and `GAP` mean positive, negative, relative, and missing evidence (`/Users/liuze/Downloads/LAKES/main_revised.tex:357-371`). The complete knowledge-base stance mapping is active at lines 459--467; `owner_ineligible` maps to `AGAINST` and `owner_stronger` maps to `COMPARE` (`/Users/liuze/Downloads/LAKES/main_revised.tex:459-467`).
6. The explicit support predicate is: any applicable `owner_ineligible` entry hard-rejects the tool-category assignment; otherwise, relevance-weighted positive evidence (`FOR` plus `COMPARE/owner_stronger`) must **strictly exceed** relevance-weighted `AGAINST` evidence (`/Users/liuze/Downloads/LAKES/main_revised.tex:355`).

RuleChecker accepts a proposal only if all of the following hold:

- Every planned tool supports the target solc version (`/Users/liuze/Downloads/LAKES/main_revised.tex:389`, `:403`).
- Estimated parallel plan runtime satisfies `max_{t in T_plan} r_hat_t <= B`, where `T_plan = union_{c in C_req} a(c)` (`/Users/liuze/Downloads/LAKES/main_revised.tex:390`, `:403`).
- Every required category has a non-empty owner set (`/Users/liuze/Downloads/LAKES/main_revised.tex:391`, `:403`).
- No complementary tool owns a non-required category (`/Users/liuze/Downloads/LAKES/main_revised.tex:392`, `:403`).
- Every complementary owner cites authentic evidence in its `M_c,t` row and that cited evidence satisfies the support rule (`/Users/liuze/Downloads/LAKES/main_revised.tex:394-396`, `:403`).

The LLM receives rejection reasons and revises. The repair loop uses `K_max=3` (`/Users/liuze/Downloads/LAKES/main_revised.tex:401`, `:417-423`). The prose also says low-temperature decoding and majority voting over `k` samples, but gives neither the temperature nor `k` (`:401`).

#### Stage 3: execution and fusion

1. Execute the tools verified by Stage 2 (`/Users/liuze/Downloads/LAKES/main_revised.tex:434`). Given the Stage 2 definition of `T_plan`, this is the union of the verified category owner sets (`:403`).
2. Compile the target once using the specified solc version and share compiled artifacts across tools (`/Users/liuze/Downloads/LAKES/main_revised.tex:434`).
3. Run selected tools in parallel under the developer time budget (`/Users/liuze/Downloads/LAKES/main_revised.tex:434`).
4. On timeout, exclude that tool's results and record the timeout for categories assigned to it. Mark a category as having no valid output only when none of its owners returns usable findings (`/Users/liuze/Downloads/LAKES/main_revised.tex:434`).
5. Normalize raw reports to a common schema that includes source tool, vulnerability category, code location, and severity, and normalize tool-specific category names into the unified taxonomy (`/Users/liuze/Downloads/LAKES/main_revised.tex:436`).
6. Retain a category finding only if its source tool belongs to the verified owner set `a(c)` (`/Users/liuze/Downloads/LAKES/main_revised.tex:436`). This preserves primary findings when a complement is added; the active assignment is a set, not replacement ownership.
7. Merge retained findings with the same category and code location. If severity or description differs, preserve source-tool provenance and mark the inconsistent fields rather than selecting a forced value (`/Users/liuze/Downloads/LAKES/main_revised.tex:436`).
8. The final active-paper output is one unified report organized by vulnerability category (`/Users/liuze/Downloads/LAKES/main_revised.tex:189`, `:265`, `:434-436`). No serialized schema version, top-level status enum, action ID, or CLI shape is specified.

### Runtime and budget contract

The complete runtime rule stated by the active paper is narrow:

- `B` is the developer's maximum allowed runtime for the detection plan (`/Users/liuze/Downloads/LAKES/main_revised.tex:336`).
- The KB supplies a per-tool historical estimate `r_hat_t`, conservatively selected from a matching or nearest compatible solc/size/complexity bucket; the LLM does not invent runtime (`/Users/liuze/Downloads/LAKES/main_revised.tex:351`).
- A complement may be added only if the resulting estimated plan remains within `B` (`/Users/liuze/Downloads/LAKES/main_revised.tex:336`).
- Because execution is parallel, formal plan validation is `max r_hat_t <= B`, not a sum (`/Users/liuze/Downloads/LAKES/main_revised.tex:403`; parallel execution at `:434`).
- Stage 1 uses lower runtime only as its second stated tie-breaker, after the raw preferred metric (`/Users/liuze/Downloads/LAKES/main_revised.tex:309`). It does not state explicitly that this tie-break value is the same `r_hat_t` introduced later.
- The experiments use a 300-second-per-contract timeout by default, but the manuscript expressly says that this is an evaluation default, not a fixed LAKES limit; developers may provide a larger budget (`/Users/liuze/Downloads/LAKES/main_revised.tex:490`).

The paper does **not** state runtime units for `B` or `r_hat_t`, the exact conservative statistic, bucket-distance logic, missing-runtime behavior, whether compilation/queue overhead counts, worker limits, directory/multi-contract scaling, or how `B` maps to per-tool timeout. The experimental 300 seconds cannot be promoted to a universal framework threshold because line 490 explicitly disclaims that interpretation.

### Tool and complement eligibility

| Decision point | Active-paper requirement | Evidence |
|---|---|---|
| Stage 1 score domain | Tool is solc-compatible | `/Users/liuze/Downloads/LAKES/main_revised.tex:270`, `:292` |
| Stage 1 primary eligibility | Solc-compatible, comparable-metric support mass `>=0.2`, and maximal `S_t` | `/Users/liuze/Downloads/LAKES/main_revised.tex:303-309` |
| Stage 2 candidate domain | `T_cand` is called “feasible,” but feasibility is not fully defined | `/Users/liuze/Downloads/LAKES/main_revised.tex:336`, `:410` |
| Planned-tool compatibility | Every selected tool supports target solc version | `/Users/liuze/Downloads/LAKES/main_revised.tex:389`, `:403` |
| Complement category evidence | No applicable `owner_ineligible`; weighted positive evidence strictly exceeds weighted negative evidence; citations are authentic | `/Users/liuze/Downloads/LAKES/main_revised.tex:355`, `:395-396`, `:403` |
| Complement runtime | Adding it keeps `max r_hat_t <= B` | `/Users/liuze/Downloads/LAKES/main_revised.tex:336`, `:403` |
| Complement scope | It cannot own a category outside `C_req` | `/Users/liuze/Downloads/LAKES/main_revised.tex:392`, `:403` |
| Fallback | Failed/missing complement returns that category to primary-only ownership | `/Users/liuze/Downloads/LAKES/main_revised.tex:336`, `:401`, `:424-427` |
| Experimental candidate-set inclusion | Publicly obtainable, stable in the experiment, input-compatible with the evaluation pipeline, and output-normalizable to DASP-10 | `/Users/liuze/Downloads/LAKES/main_revised.tex:494` |

The last row describes construction of the 20-tool **evaluation set**, not a formal Stage 1/2 eligibility algorithm. The active workflow never defines “feasible” beyond solc compatibility and the checks above.

### Explicit thresholds, constants, and outputs

#### Workflow constants and strict comparisons

| Item | Explicit value/rule | Scope and source |
|---|---|---|
| Gower semantic block weights | compiler `1/2`, numeric profile `1/2` | Stage 1, `/Users/liuze/Downloads/LAKES/main_revised.tex:276`, `:280`, `:321` |
| Distance bands | matching compiler `[0,1/2]`; non-matching `[1/2,1]` | Stage 1, `/Users/liuze/Downloads/LAKES/main_revised.tex:280` |
| Benchmark weight normalization | `sum_D w_D=1` | Stage 1, `/Users/liuze/Downloads/LAKES/main_revised.tex:290`, `:317` |
| Best rank | rank `1` | Stage 1, `/Users/liuze/Downloads/LAKES/main_revised.tex:292` |
| Rank normalization | `phi(r,n)=(n-r+1)/n` | Stage 1, `/Users/liuze/Downloads/LAKES/main_revised.tex:292` |
| Preference weights | preferred metric `3/4`, other metric `1/4` | Stage 1, `/Users/liuze/Downloads/LAKES/main_revised.tex:300` |
| Primary support gate | `sum w_D >= tau`, with `tau=0.2` | Stage 1, `/Users/liuze/Downloads/LAKES/main_revised.tex:305`, `:309` |
| Evidence conflict gate | applicable `owner_ineligible` hard-rejects; otherwise weighted positive evidence must be strictly `>` weighted `AGAINST` evidence | Stage 2, `/Users/liuze/Downloads/LAKES/main_revised.tex:355` |
| Repair bound | `K_max=3` | Stage 2, `/Users/liuze/Downloads/LAKES/main_revised.tex:401`, `:417` |
| Runtime gate | `max_{t in T_plan} r_hat_t <= B` | Stage 2, `/Users/liuze/Downloads/LAKES/main_revised.tex:403` |
| KB admission | all three checks--DASP-10 category mapping, four-field schema validity, and concrete provenance--must pass; failure of any rejects/logs the entry | Dynamic KB, `/Users/liuze/Downloads/LAKES/main_revised.tex:472` |

There is no active numeric Stage 2 category-evidence threshold. In particular, the manuscript contains no `n_eff`, no `R_hat`, no `detected/total` category formula, and no eligibility threshold of `15`. The only certification/confidence wording is commented at line 190.

#### Explicit produced artifacts

| Producer | Output stated by active paper | Evidence |
|---|---|---|
| Gower-KDE algorithm | normalized benchmark weights `{w_D}` | `/Users/liuze/Downloads/LAKES/main_revised.tex:317`, `:329` |
| Stage 1 | `(t*, {S_t}, {s_t,D}, {w_D})` | `/Users/liuze/Downloads/LAKES/main_revised.tex:309` |
| DACE-RAG | provenance-preserving matrix rows `M_c,t` with four evidence slots, score, and runtime | `/Users/liuze/Downloads/LAKES/main_revised.tex:353-355` |
| LLM proposal | complementary owner deltas and cited evidence IDs | `/Users/liuze/Downloads/LAKES/main_revised.tex:377`, `:414-415` |
| Stage 2 algorithm | assignment `a` and evidence citations `E` | `/Users/liuze/Downloads/LAKES/main_revised.tex:410-411`, `:420`, `:427` |
| Stage 3 | unified category-organized report; timeout/category-validity annotations; merged findings with provenance and inconsistent-field markers | `/Users/liuze/Downloads/LAKES/main_revised.tex:189`, `:434-436` |
| Dynamic KB update | accepted capability entries in tool knowledge, accepted benchmark metrics in dataset knowledge, and links when paper/tool/category coincide | `/Users/liuze/Downloads/LAKES/main_revised.tex:474` |

#### Evaluation-only values, not scheduler thresholds

- Default experimental timeout: 300 seconds per contract, expressly not a fixed LAKES limit (`/Users/liuze/Downloads/LAKES/main_revised.tex:490`).
- Evaluation candidate set: 20 tools (`/Users/liuze/Downloads/LAKES/main_revised.tex:494`).
- Evaluation coverage table: nine concrete mappable DASP-10 categories, excluding `Unknown Unknowns` (`/Users/liuze/Downloads/LAKES/main_revised.tex:529`).
- Reported evaluation metrics are Precision, Recall, and F1 with explicit formulas (`/Users/liuze/Downloads/LAKES/main_revised.tex:492`). These are experiment outputs, not Stage 3 report fields.

### Internal ambiguities and contradictions in the active paper

1. **Primary-sufficiency gate is claimed but never defined or executed.** The overview says Stage 2 first checks whether the primary reliably covers each category and invokes DACE-RAG only for categories needing support (`/Users/liuze/Downloads/LAKES/main_revised.tex:265`). The formal algorithm instead queries the LLM unconditionally for every `c in C_req` (`:412-416`). There is no active statistic, threshold, or branch that defines “reliably cover” or “need additional support.”

2. **`n_eff >= 15` is not a paper rule.** No active or commented line contains `n_eff`, `R_hat`, or a category-count formula, and the only statistical-certification/confidence prose is commented (`/Users/liuze/Downloads/LAKES/main_revised.tex:190`). Any `15` gate is an implementation/specification refinement, not recoverable from this manuscript.

3. **Primary-only fallback can violate the mandatory runtime check.** Stage 1 can select a primary whose runtime exceeds `B`, because budget is absent from the primary argmax and runtime is only a tie-breaker (`/Users/liuze/Downloads/LAKES/main_revised.tex:303-309`). Stage 2 always retains `t*` in every owner set and falls back to `{t*}` (`:336`, `:413`, `:424-425`), while also requiring `max r_hat_t <= B` (`:403`). For an over-budget primary, the paper simultaneously requires primary ownership/fallback and rejection of the resulting plan, but defines no `NO_EXECUTABLE_PLAN`, alternate-primary, or stop outcome.

4. **The repair algorithm does not ensure the stated final validation.** The prose says “the final plan must pass RuleChecker” (`/Users/liuze/Downloads/LAKES/main_revised.tex:401`). In the pseudocode, each failed check is followed by a revision, including the last `i=K_max` iteration, but that last revision is not checked; the algorithm then mutates unresolved categories to primary-only and returns without another RuleChecker call (`:417-427`). “Unresolved rejection” after an unchecked final revision is also undefined.

5. **Complement cardinality is unspecified.** The prose speaks of adding “a complementary tool” (`/Users/liuze/Downloads/LAKES/main_revised.tex:336`), but the codomain is a power set, the LLM returns “complementary owners” plural, and `Delta a(c)` is unioned without a cardinality bound (`:336`, `:377`, `:414-415`). The commented “one augmenting tool per category” sentence at line 190 cannot resolve the active contract.

6. **The support table is weaker than the formal conflict rule.** The formal rule rejects unless weighted positive evidence strictly exceeds weighted negative evidence (`/Users/liuze/Downloads/LAKES/main_revised.tex:355`). Table 2 lists the Support rejection condition merely as “cited evidence gives no positive support” (`:394-396`). A tool with some positive evidence that is outweighed by negative evidence passes the table wording but fails the formal rule.

7. **The cited-entry check and aggregate support predicate use different granularity.** Line 403 requires each complement to cite “an entry” in `M_c,t` that passes the support predicate, but line 355 defines that predicate by aggregating entire positive and negative evidence lists. The paper does not say whether RuleChecker validates an individual citation, all cited entries, or the complete row.

8. **Stage 1 promises data that the formal Stage 2 matrix does not carry.** Stage 1 explicitly passes `{s_t,D}` and `{w_D}` (`/Users/liuze/Downloads/LAKES/main_revised.tex:309`), and DACE-RAG is said to add them (`:351`). Yet the formal matrix tuple contains only the four slots, `S_t`, and `r_hat_t` (`:353-355`); the algorithm passes `{w_D}` separately but never names `{s_t,D}` (`:410`, `:414`). The benchmark-score consumer and representation are therefore unspecified.

9. **The Stage 1 tie-break is not executable as written for multiple benchmarks.** “Raw value on the developer-preferred metric” does not say which benchmark value or aggregation to use, and lower runtime is not tied explicitly to `r_hat_t` (`/Users/liuze/Downloads/LAKES/main_revised.tex:309`, runtime estimate introduced at `:351`). Missing runtime and ties remaining after both stated tie-breaks have no rule.

10. **“Comparable metrics” and rank populations are undefined.** `D_t` contains benchmarks with comparable metrics for `t`, but the paper does not define whether both Recall and Precision must exist, which tools constitute `n_D`, how missing values are treated, or how metric ties receive ranks (`/Users/liuze/Downloads/LAKES/main_revised.tex:292-309`). It also defines no outcome for no comparable rows or no tool reaching support `0.2`.

11. **Gower/KDE edge cases are undefined.** A constant numeric feature makes `rho_j=0` in the stated division; missing features, an empty/singleton knowledge base, bandwidth-grid ties, and a zero normalization denominator have no behavior (`/Users/liuze/Downloads/LAKES/main_revised.tex:276-286`, `:316-328`).

12. **Runtime evidence is not replayable from the paper.** “Conservative statistic,” “matching,” and “nearest compatible” have no exact aggregation, quantile, distance, tie, source priority, unit, or missing-data rule (`/Users/liuze/Downloads/LAKES/main_revised.tex:351`). `B` is called maximum plan runtime (`:336`), while the only concrete unit/scope is the evaluation-only 300 seconds per contract (`:490`).

13. **Empty requirements are not handled.** If `C_req` is empty, the Stage 2 loop and union produce no owner sets and an empty `T_plan`; `max` over that set is undefined and the selected primary need not execute (`/Users/liuze/Downloads/LAKES/main_revised.tex:403`, `:412-427`). The paper never requires `C_req` to be non-empty.

14. **“Feasible candidate” is not a full operational predicate.** Stage 1 explicitly tests solc compatibility, and RuleChecker repeats solc compatibility (`/Users/liuze/Downloads/LAKES/main_revised.tex:292`, `:403`). Artifact/input support, installation availability, execution stability, and normalizable output appear only as evaluation-set criteria (`:494`), not as formal runtime checks. “Target constraints” are mentioned in prose, while the algorithm names only solc version `v` (`:377`, `:410`).

15. **Stage 3 failure and empty-result semantics are incomplete.** Only timeout is specified (`/Users/liuze/Downloads/LAKES/main_revised.tex:434`); nonzero exit, malformed report, compilation failure, partial output, and stale output are unaddressed. “Usable findings” makes it unclear whether a valid successful report with zero findings is valid category output or “no valid output.”

16. **Stage 3 merge/schema edge cases are undefined.** The common schema lists source, category, location, and severity, then conflict handling refers to descriptions (`/Users/liuze/Downloads/LAKES/main_revised.tex:436`). The handling of missing locations, location normalization, duplicate findings from one tool, raw variants, findings outside `C_req`, and exact conflict-marker/output fields is not stated.

17. **Parallel budget semantics stop at one formula.** `max r_hat_t` is consistent with stated parallel execution (`/Users/liuze/Downloads/LAKES/main_revised.tex:403`, `:434`), but the paper does not specify finite worker capacity, multiple contracts/files, per-tool versus whole-plan deadlines, compile time, or whether a timed-out owner's earlier partial results are discarded. These cannot be inferred from the 300-second experimental setting.

### Manuscript contract versus current task/spec refinements

The following current project rules are sensible deterministic resolutions, but they are **not explicit active-paper requirements**:

- `R_hat`, `n_eff`, the `15` boundary, peer-gap rules, and primary-sufficiency statuses are introduced by `.trellis/tasks/07-13-paper-code-alignment/design.md:205-246` and `.trellis/spec/backend/lakes-scheduling-contract.md:51`, `:87-95`.
- Runtime units/bases, original support mass `0.2`, weighted P90, compiler/LOC qualification, candidate-level provenance, and unknown-runtime behavior are introduced by `.trellis/tasks/07-13-paper-code-alignment/design.md:82-138` and `.trellis/spec/backend/lakes-scheduling-contract.md:54-84`. The paper says only “conservative statistic” from a matching/nearest compatible bucket (`/Users/liuze/Downloads/LAKES/main_revised.tex:351`).
- `screc_v2`, typed terminal statuses, `NO_EXECUTABLE_PLAN`, lexical fallback, and nullable later stages are project contract choices (`.trellis/tasks/07-13-paper-code-alignment/design.md:144-187`, `:278-284`, `:395-415`), not paper outputs.
- Execution jobs, input count, multi-contract multiplication, timeout propagation, fresh-only report lifecycle, category aliases, exact adapter behavior, and pragma-constraint semantics are project/spec hardening rules (`.trellis/spec/backend/lakes-scheduling-contract.md:96-166`), not specified in the manuscript.

These refinements may implement fail-closed behavior where the paper is silent, but they should not be attributed to exact manuscript text. The two clearly paper-mandated invariants they preserve are additive primary ownership and parallel max-runtime validation.

### Code patterns (line-cited algorithm forms)

- Relevance owner: `w_D = p_hat_D / sum p_hat_D'` (`/Users/liuze/Downloads/LAKES/main_revised.tex:285-290`).
- Score owner: `S_t` is the support-normalized weighted average of `s_t,D` (`/Users/liuze/Downloads/LAKES/main_revised.tex:303-306`).
- Primary owner: the support-constrained `argmax` at `/Users/liuze/Downloads/LAKES/main_revised.tex:305`.
- Category owner initialization: `a(c) <- {t*}` before unioning `Delta a(c)` (`/Users/liuze/Downloads/LAKES/main_revised.tex:412-415`).
- Runtime owner: RuleChecker evaluates `max_{t in T_plan} r_hat_t <= B` (`/Users/liuze/Downloads/LAKES/main_revised.tex:403`).
- Fusion owner: Stage 2 owner sets filter findings before same-category/same-location merge (`/Users/liuze/Downloads/LAKES/main_revised.tex:436`).

No production source file was modified.

### External references

No external source or web documentation was consulted. The manuscript's citations were treated as citations, not independently verified evidence. No library/runtime version outside the manuscript was needed for this extraction.

### Related specs

- `.trellis/spec/backend/lakes-scheduling-contract.md` -- executable `screc_v2` rules and fail-closed resolutions for paper gaps.
- `.trellis/spec/backend/index.md` -- identifies the LAKES scheduling contract as the active backend guideline.
- `.trellis/spec/guides/cross-layer-thinking-guide.md` -- requires one exact owner and validated format at each packet/matrix/certificate/execution/report boundary.
- `.trellis/spec/guides/code-reuse-thinking-guide.md` -- supports single shared owners for selection, runtime, and normalization rules.

## Caveats / Not Found

- Critical not-found: no `n_eff`, `R_hat`, `detected/total` Stage 2 formula, `15` threshold, certification state, robust-single action, `screc_v2`, terminal status, action ID, or serialized result schema exists in active manuscript text.
- The raster contents of `overview.png`, `dace_rag.png`, `kb_extraction.png`, and `example.jpg` were not treated as independent normative contracts because the requested evidence had to be recoverable from `main_revised.tex` with exact line citations. Their captions and surrounding active prose were included.
- Evaluation results and numeric tables after line 478 were separated from workflow semantics. Only the explicitly qualified 300-second experimental timeout and evaluation-set cardinalities are recorded above.
- Line citations refer to the local manuscript state inspected on 2026-07-17 and will shift if the paper is edited.
