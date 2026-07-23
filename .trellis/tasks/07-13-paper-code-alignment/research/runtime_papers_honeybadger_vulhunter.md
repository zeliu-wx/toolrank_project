# Research: HoneyBadger and VulHunter runtime papers

- Query: Verify independent empirical runtime evidence for HoneyBadger and VulHunter, targeting about five papers per tool without padding; capture exact full-text locators, denominators, timeout policy, normalization, provenance, and current LAKES scheduling eligibility.
- Scope: mixed (repository runtime contract plus external primary/evaluation papers, 2015-2026)
- Date: 2026-07-21

## Findings

### Executive result

The evidence target cannot honestly be filled to five usable papers for both tools.

| Tool | Independent usable descriptive runtime observations | Currently schedulable in LAKES | Result |
|---|---:|---:|---|
| HoneyBadger | 4 | 0 | Four independent evaluations report per-contract means of `142`, `98`, `72`, and `2.28` seconds. Their unweighted descriptive mean is `78.57 s/contract`, but it is not a scheduling statistic. |
| VulHunter | 1 | 0 | The original paper reports `4.4 s/contract`; no second independent exact completion-time measurement survived verification. |

“Usable descriptive” means that an independent empirical source explicitly reports a per-contract mean. It does **not** mean “eligible for the production scheduler.” Every accepted observation still fails the current compiler/profile/scene-support contract in `.trellis/spec/backend/lakes-scheduling-contract.md:146-178`: none is linked to a shipped canonical scene with compatible compiler metadata and at least `0.2` original scene mass.

The requested cross-paper mean is therefore retained only as an auditable summary. It must not be written into `time_sec`, `execution_time_avg`, or `execution_time_avg_average_s`, because the current resolver would misrepresent a derived arithmetic mean as one observed, scene-weighted-P90 candidate (`toolrank/evidence_packet.py:92-134,291-414`).

### HoneyBadger: accepted independent observations

#### HB-1 — Torres, Steichen, and State, USENIX Security 2019

- **Paper:** Christof Ferreira Torres, Mathis Steichen, and Radu State, “The Art of The Scam: Demystifying Honeypots in Ethereum Smart Contracts,” 28th USENIX Security Symposium, 2019, pp. 1591-1607.
- **Direct URLs:** [USENIX record](https://www.usenix.org/conference/usenixsecurity19/presentation/ferreira); [official PDF](https://www.usenix.org/system/files/sec19-torres.pdf); [arXiv record](https://arxiv.org/abs/1902.06976).
- **Tool/version:** HoneyBadger research implementation; no release/commit is named in the paper. The environment is explicit: Geth EVM `1.8.16`, Solidity `0.4.25`, and Z3 `4.7.1`.
- **Dataset/profile:** bytecode from 2,019,434 deployed contracts, de-duplicated to 151,935 unique bytecodes; dates span 2015-08-07 to 2018-10-12. Hardware was a 10-node cluster, each node with two 12-core Intel Xeon L5640 CPUs and 960 GB aggregate memory.
- **Attempted denominator:** 151,935 unique bytecodes.
- **Successful denominator:** 149,603 completed within the 30-minute global limit (`98%`); 2,332 did not finish within that limit.
- **Exact statistic:** mean `142 s/contract`; median `31 s`; mode `<1 s`.
- **Timeout policy:** 1 second per Z3 request; 30 minutes global symbolic-execution timeout per contract; loop/depth/gas bounds of 10/50/4,000,000.
- **Locator:** Section 5 “Evaluation,” Section 5.1 “Results,” PDF page 9 (proceedings page 1599), paragraph beginning “We run HONEYBADGER…”. The mean, median, mode, completed count, and timeout are in the same paragraph.
- **Normalization:** direct paper-reported per-contract mean, `142 seconds`. It is not recomputed as `total/successes` because no aggregate CPU-time numerator is reported and the mean may include timeout-censored attempts.
- **runtime_basis:** `per_contract` (descriptive, timeout-censored experiment).
- **Scheduling eligibility:** **no**. The deployed-bytecode corpus is absent from the canonical AST scene artifact and has no compatible `dataset_profile.solc`; current scene support is zero.

#### HB-2 — Durieux et al., ICSE 2020

- **Paper:** Thomas Durieux, João F. Ferreira, Rui Abreu, and Pedro Cruz, “Empirical Review of Automated Analysis Tools on 47,587 Ethereum Smart Contracts,” ICSE 2020, pp. 530-541.
- **DOI/URLs:** [DOI 10.1145/3377811.3380364](https://doi.org/10.1145/3377811.3380364); [arXiv record](https://arxiv.org/abs/1910.10601); [full PDF](https://www.inesc-id.pt/wp-content/uploads/2024/04/ICSE2020_Ferreira-1.pdf).
- **Tool/version:** SmartBugs-integrated HoneyBadger; the paper does not give a HoneyBadger commit/version in the runtime table.
- **Dataset/profile:** `sbwild`, 47,518 unique Solidity contracts (9,693,457 LOC) collected from Etherscan. The execution used three Scaleway servers (32 vCPU, 128 GB RAM) and three Google Cloud servers (32 vCPU, 30 GB RAM).
- **Attempted denominator:** 47,518 contracts for RQ3.
- **Successful denominator:** not itemized per tool. The paper states that Manticore was the only tool that encountered timeouts, so HoneyBadger's timeout count is reported implicitly as zero; compilation/other failures are not separately tabulated.
- **Exact statistic:** Table 8 reports `00:01:38`, i.e. `98 s/contract`, and a total of `23 days, 13:40:00`.
- **Timeout policy:** 30 minutes per tool-contract analysis; partial results were collected when the budget expired.
- **Locator:** Section 3.3 “Execution Time of the Analysis Tools (RQ3),” Table 8, PDF page 8 (proceedings page 537). The text immediately left of the table says the average is per contract and includes container startup/binding, cleanup, analysis/compilation, and result parsing.
- **Normalization:** direct table mean, `1*60 + 38 = 98 seconds/contract`. Do not derive it from the displayed total: `23 d 13:40:00 / 47,518` does not equal 98 seconds, consistent with the paper's parallel execution/wall-time discussion.
- **runtime_basis:** `per_contract` (end-to-end SmartBugs analysis attempt).
- **Scheduling eligibility:** **no**. `sbwild` is not a declared shipped canonical scene identity with compiler/LOC profile support under the current artifact; the exact paper observation therefore has zero scheduler scene mass.

#### HB-3 — Vaishnavi, M.Tech. thesis, 2023

- **Work:** Vaishnavi, “A Static Analysis Approach for Ethereum Smart Contracts,” M.Tech. thesis, Dhirubhai Ambani Institute of Information and Communication Technology, June 2023.
- **Direct URL:** [institutional full-text PDF](https://ir.daiict.ac.in/server/api/core/bitstreams/f6210523-fc16-4a08-b3ce-3da8c18a8be5/content).
- **Tool/version:** SmartBugs-integrated HoneyBadger cited to Torres et al.; no commit/version is reported.
- **Dataset/profile:** 69 SB-curated contracts plus a random sample of 3,031 contracts from SB-wild; the evaluation considered five vulnerability types and ran on one machine.
- **Attempted denominator:** 3,100 contract inputs across the two datasets.
- **Successful denominator:** not reported per tool.
- **Exact statistic:** Table 5.5 reports HoneyBadger `Avg ETC 00:01:12`, `ET(SB curated) 02:49:03`, and `ET(SB wild) 3 days, 20:13:46`.
- **Timeout policy:** SB-curated was run in both a 30-minute-budget regime (partial results collected) and an execution-until-halt regime; SB-wild is described as having no time budget. The table does not identify which regime owns the displayed mean.
- **Locator:** Chapter 5, Section 5.4.2 “Performance of Tools,” Table 5.5, PDF page 76 / thesis page 65.
- **Normalization:** direct reported mean, `1*60 + 12 = 72 seconds/contract`. The two displayed totals and stated denominators do not replay to 72 seconds, so they must not be used as a numerator for a derived per-success value.
- **runtime_basis:** `per_contract`, but the row mixes datasets and has an ambiguous timeout regime.
- **Scheduling eligibility:** **no**. No stable paper/dataset/compiler scene row links this observation to a canonical profile; its mixed regime and non-replayable totals are additional limitations.

#### HB-4 — Akbar and Vighio, IJIST 2025

- **Paper:** Nashaib Akbar and Muhammad Saleem Vighio, “A Comparative Evaluating Auditing Tools for Unverified Smart Contracts on Ethereum Blockchain,” *International Journal of Innovations in Science & Technology*, vol. 7, special issue CSET 2025, pp. 85-96, published 14 May 2025.
- **Direct PDF:** [journal PDF](https://journal.50sea.com/index.php/IJIST/article/download/1364/1869/15093).
- **Tool/version:** SmartBugs-integrated HoneyBadger over runtime bytecode; no commit/version is reported.
- **Dataset/profile:** 353 unverified ERC-20 runtime bytecodes collected from Ethereum plus 310 blacklisted unverified ERC-20 tokens from DappRadar, for 663 inputs.
- **Attempted denominator:** 663 contracts.
- **Successful denominator:** 663; the paper explicitly says HoneyBadger successfully audited all contracts.
- **Exact statistic:** RQ2 prose reports `2.28 s/contract`; Table 6 rounds the mean to `00:00:02` and reports total `00:24:40`.
- **Timeout policy:** not reported.
- **Locator:** RQ2 and Table 6 “Average execution time for each tool,” PDF page 8 / journal page 92.
- **Normalization:** use the more precise prose value, `2.28 seconds/contract`. The rounded table total gives `1,480/663 = 2.232277… s/contract`, so the paper's precision mismatch is retained as a limitation rather than silently corrected.
- **runtime_basis:** `per_contract` over runtime-bytecode inputs.
- **Scheduling eligibility:** **no**. The two bytecode collections have no canonical scene/compiler profile or source ID in the shipped artifact; timeout policy and tool version are also absent.

### HoneyBadger derived arithmetic mean

The user-requested mean is replayable from the four independent paper-level means:

```text
mean_seconds = (142 + 98 + 72 + 2.28) / 4
             = 78.57 seconds/contract
```

- **summary basis:** paper-level unweighted arithmetic mean of reported `per_contract` means;
- **n:** 4 independent empirical works;
- **included:** `HB-1`, `HB-2`, `HB-3`, `HB-4`;
- **excluded:** copied baselines, figure-only values, framework papers without a numeric cell, and papers that excluded HoneyBadger;
- **runtime_basis:** `per_contract` only at the coarse label level;
- **eligibility:** **non-schedulable derived summary**.

This number is heterogeneous: bytecode/source input, hardware, versions, wrapper overhead, datasets, and timeout regimes differ. It is neither weighted by contracts nor a pooled per-success mean. It is suitable only as the requested descriptive summary and must not replace LAKES's compatible-scene weighted P90.

### HoneyBadger: rejected or not-yet-admissible candidates

| Candidate | Exact evidence screened | Verdict / reason |
|---|---|---|
| Sfyrakis et al., “LightCross,” *Computers* 2025, DOI `10.3390/computers14090369` | Figure 3 contains a HoneyBadger series over SB-curated categories; prose gives exact averages for several other detectors but not HoneyBadger. | **Rejected.** No exact HoneyBadger scalar/table cell is stated; reading a value from the plotted line would invent precision. |
| Durgut et al., “Hybrid Quantum-Classical Deep Neural Networks Based Smart Contract Vulnerability Detection,” *Applied Sciences* 2025, DOI `10.3390/app15074037` | Table 1 gives `00:00:46` and `00:53:11`, while surrounding prose describes 47,518 SmartBugs-Wild contracts. | **Rejected as independent evidence.** `3,191/46 ≈ 69.37`, not 47,518; the paper does not document a HoneyBadger rerun or reconcile the denominator. The value cannot be attributed to a new independent experiment. |
| “Ensemble multi-label machine learning solidity smart contract vulnerability detection model,” *Cluster Computing* 2025, DOI `10.1007/s10586-025-05725-y` | Table 12 gives HoneyBadger `98,000 ms`. | **Rejected as duplicate.** It is exactly Durieux et al.'s `98 s` baseline converted to milliseconds and is not a new HoneyBadger timing experiment. |
| Di Angelo et al., “SmartBugs 2.0,” ASE 2023 | Framework/compatibility evaluation. | **Rejected.** No verified per-contract HoneyBadger completion-time statistic is reported. |
| Lashkari and Musilek, “Evaluation of Smart Contract Vulnerability Analysis Tools: A Domain-Specific Perspective,” *Information* 2023, DOI `10.3390/info14100533` | Table 1 contains individual HoneyBadger durations for a 20-contract curated subset; other figures report domain timeouts. | **Not admitted in this pass.** A complete 20-cell extraction plus exact timeout/success denominator was not finished before the research stop; no partial mean is invented. |
| “An empirical analysis of vulnerability detection tools for Solidity smart contracts,” *Empirical Software Engineering* 2026 | Full text explicitly says HoneyBadger was excluded because it targets honeypots. | **Rejected.** The tool was not evaluated. |

### VulHunter: accepted independent observation

#### VH-1 — Li et al., IEEE TSE 2023

- **Paper:** Zhaoxuan Li, Siqi Lu, Rui Zhang, Ziming Zhao, Rujin Liang, Rui Xue, Wenhao Li, Fan Zhang, and Sheng Gao, “VulHunter: Hunting Vulnerable Smart Contracts at EVM Bytecode-Level via Multiple Instance Learning,” *IEEE Transactions on Software Engineering*, vol. 49, 2023, pp. 3793-3810.
- **DOI/URLs:** [DOI 10.1109/TSE.2023.3317209](https://doi.org/10.1109/TSE.2023.3317209); [full-text record](https://www.researchgate.net/publication/374128313_VulHunter_Hunting_Vulnerable_Smart_Contracts_at_EVM_bytecode-level_via_Multiple_Instance_Learning).
- **Tool/version:** VulHunter research implementation; the paper does not state a release/commit in the verified runtime claim.
- **Dataset/profile:** RQ3 overhead sample described as approximately 100 Ethereum contracts in the paper/packaged source note; the source note also mentions a roughly 121 KB size profile, whose exact per-contract versus cohort meaning was not recoverable in this pass.
- **Attempted denominator:** approximately 100 RQ3 contracts; the paper-level exact denominator needs table-level re-verification before ingestion.
- **Successful denominator:** the abstract reports a `0% analysis failed rate`, implying all attempted RQ3 items completed, but the exact integer is not restated in the abstract.
- **Exact statistic:** `4.4 s/contract`.
- **Timeout policy:** not reported in the verified abstract claim.
- **Locator:** abstract, PDF page 1, sentence reporting accuracy, F1, efficiency (`4.4 seconds per contract`), and `0%` analysis-failure rate. The packaged source attributes it to RQ3; an exact RQ3 table number was not verified.
- **Normalization:** direct paper-reported mean, `4.4 seconds/contract`; no aggregate-time division is performed.
- **runtime_basis:** `per_contract`.
- **Scheduling eligibility:** **no**. The RQ3 source is absent from the canonical profile artifact, `dataset_profile.solc` is unavailable, and its scene support is zero.

### VulHunter derived summary

Only one independent paper-level observation survived verification:

```text
mean_seconds = 4.4 / 1 = 4.4 seconds/contract
```

This is an identity summary (`n=1`), not a cross-paper average and not a robust estimate. It remains descriptive and non-schedulable.

### VulHunter: rejected or unavailable candidates

| Candidate | Evidence screened | Verdict / reason |
|---|---|---|
| Stephan Klein, “Machine learning for vulnerability detection in smart contracts: a comparison of approaches,” TU Wien thesis, 2025 | The repository abstract confirms an implementation-grounded comparison of retrained VulHunter and MANDO-HGT on a 120-contract holdout. | **Rejected for runtime insertion.** No exact per-contract completion-time table/cell was verified; accuracy/F1 and implementation comparison do not substitute for runtime. [Repository record](https://repositum.tuwien.at/handle/20.500.12708/220334?mode=full). |
| SmartBugs / SmartBugs 2.0 evaluation papers | Framework papers cover many analyzers, but no verified exact VulHunter completion-time cell was found in the screened material. | **Rejected / not found.** Do not transfer another ML tool's timing or infer one from framework overhead. |

No additional independent primary empirical paper with an exact VulHunter completion-time statistic survived the bounded search. The scarcity is itself the correct result; padding the table with reviews or papers that merely cite Li et al.'s `4.4 s` would duplicate the same observation.

### Insertion and scheduling consequence

For both tools, the paper measurements should first be stored as atomic observations with stable paper IDs, exact locators, original value/unit, explicit basis, and limitations. The cross-paper HoneyBadger mean should be a separate derived summary with constituent IDs. The current legacy scheduling fields cannot safely hold it.

The following remain hard blockers for execution scheduling:

1. the evaluated dataset must be a genuine canonical scene identity, not renamed to `smartbugsdb` or another high-weight source merely to gain support;
2. compiler compatibility metadata must be present and match the target;
3. original unrenormalized compatible scene mass must reach `0.2`;
4. only atomic `per_contract` or target-converted `per_kloc` rows may enter the existing weighted P90;
5. a derived arithmetic mean needs a new typed summary/provenance contract before it can ever control scheduling.

### Files found

| Path | Role / one-line finding |
|---|---|
| `toolcards/performance_db.json:2887-2908` | Existing HoneyBadger descriptive row (`142 s/contract`) lacks compiler/scene linkage. |
| `toolcards/performance_db.json:2937-2957` | Existing VulHunter descriptive row (`4.4 s/contract`) lacks compiler/scene linkage. |
| `toolrank/evidence_packet.py:45-134` | Canonical alias matching, recognized runtime fields, and same-source maximum collapse. |
| `toolrank/evidence_packet.py:217-414` | Candidate limitations, compiler/LOC compatibility, original support `0.2`, and observed weighted P90. |
| `toolrank/schemas_v2.py:215-386` | Typed candidate/provenance/runtime-minute coupling. |
| `.trellis/tasks/07-13-paper-code-alignment/research/runtime_gap_inventory.md` | Complete internal gap inventory and safe two-layer atomic-observation/derived-summary design. |

### Code patterns

- Runtime values are accepted only from `time_sec`, `execution_time_avg`, or `execution_time_avg_average_s`; cumulative totals are not per-run evidence (`toolrank/evidence_packet.py:49-53,92-100`).
- Duplicate `(source_id, tool)` rows collapse to the maximum observed seconds value; five papers cannot be hidden under one source ID without losing their identities (`toolrank/evidence_packet.py:103-134`).
- `per_contract` and `per_kloc` are schedulable only after compiler/LOC/scene qualification; a `campaign_cap` is not completion time (`toolrank/evidence_packet.py:186-205,262-307`).
- The selected weighted P90 is one observed candidate, not an arithmetic mean (`toolrank/evidence_packet.py:371-414`).

### External references

- Torres et al. (2019), USENIX Security, official record/PDF and arXiv `1902.06976`.
- Durieux et al. (2020), ICSE, DOI `10.1145/3377811.3380364`, arXiv `1910.10601`.
- Vaishnavi (2023), DA-IICT M.Tech. thesis, institutional repository full text.
- Akbar and Vighio (2025), IJIST special issue, journal PDF.
- Li et al. (2023), IEEE TSE, DOI `10.1109/TSE.2023.3317209`.

### Related specs

- `.trellis/spec/backend/lakes-scheduling-contract.md:146-178` — Performance-KB-only runtime ownership, supported bases, compatible support, weighted P90, and paper-source independence.
- `.trellis/spec/backend/lakes-scheduling-contract.md:399-421` — fail-closed outcomes for unknown, incompatible, weak-support, cumulative, or unprofiled runtime evidence.
- `.trellis/tasks/07-13-paper-code-alignment/prd.md:102-143` — R8/R9 runtime evidence and provenance requirements.
- `.trellis/tasks/07-13-paper-code-alignment/research/runtime_gap_inventory.md` — exact schema path, current last-write projection gap, and derived-summary requirements.

## Caveats / Not Found

- The HoneyBadger `78.57 s` value is an unweighted mean of paper-level means, not a pooled observation. The experiments differ in hardware, wrapper overhead, dataset, input representation, version, and timeout policy.
- Three accepted HoneyBadger studies do not report a clean per-tool success denominator; their explicit per-contract means are retained, but a “seconds per successful completion” statistic cannot be reconstructed honestly.
- The 2023 thesis's `72 s` mean and the IJIST paper's `2.28 s` mean do not exactly replay from their displayed totals. The report preserves those inconsistencies instead of silently choosing a new statistic.
- VulHunter has only one verified exact timing source. Its RQ3 table locator, exact sample integer, and timeout policy remain unresolved; the abstract is sufficient for the `4.4 s/contract` descriptive claim but not for a richer atomic ingestion record.
- No accepted row currently supplies compatible canonical scene/compiler evidence. Writing any of these numbers into a recognized legacy runtime field would still leave the tool unknown for scheduling, unless provenance is falsified—which is forbidden.
- Semantic Scholar search was rate-limited (`HTTP 429`); OpenAlex returned `504` and DBLP returned `500` during candidate discovery. Crossref and primary full-text repositories were used where available. These search failures are recorded rather than retried into hidden results.
