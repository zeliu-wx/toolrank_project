# Research: SMARTIAN and MANDO-HGT runtime evidence

- Query: Find about five primary empirical/evaluation papers per tool, extract a defensible average runtime, and determine whether it can be used by ToolRank's scheduler.
- Scope: mixed (primary publications plus local runtime-evidence contracts)
- Date: 2026-07-21

## Findings

### Decision

| Tool | Candidate papers reviewed | Independent follow-up evaluations | Scheduler-usable runtime observations | Mean seconds per successful contract |
|---|---:|---:|---:|---:|
| SMARTIAN | 5 | 4 | 0 | `null` |
| MANDO-HGT | 4 | 3 | 0 | `null` |

No runtime average is written. The required mean would be
`sum(eligible end-to-end seconds) / successful completed analyses`; both tools have an eligible denominator of zero. Campaign limits, throughput, preprocessing-only timings, conditional time-to-bug values, and values estimated from unlabeled plots are not interchangeable with completed-analysis runtime.

The search target of about five independent papers was not met for MANDO-HGT. A fifth paper was not invented or padded with citation-only work. The original tool papers are shown for provenance but are not counted as independent follow-up evaluations.

### Eligibility contract used

An observation is scheduler-eligible only when it has all of the following:

1. A numeric duration convertible to seconds.
2. End-to-end analysis semantics or an explicitly supported runtime basis.
3. Attempted and successfully completed counts sufficient to normalize the value.
4. Tool identity and a compatible compiler/input profile.
5. Evidence precise enough to cite a table, cell, or exact text location.

The local implementation additionally rejects `campaign_cap`, unsupported component timings, missing compiler/LOC compatibility, and insufficient runtime support mass.

## SMARTIAN candidates

### S1. SMARTIAN: Enhancing Smart Contract Fuzzing with Static and Dynamic Data-Flow Analyses

- Authors/year/venue: Jaeseung Choi, Doyeon Kim, Soomin Kim, Gustavo Grieco, Alex Groce, Sang Kil Cha; 2021; ASE 2021.
- DOI/direct source: `10.1109/ASE51524.2021.9678888`; https://agroce.github.io/ase21.pdf
- Identity/version: Exact SMARTIAN tool; evaluated artifact/default configuration; no source commit reported in the paper.
- Dataset/canonical identity: B1 = 58, B2 = 72, B3 = 500 contracts. The comparative B1 experiment used a 32-contract subset. Dataset definitions are in physical PDF page 7, Table III.
- Compiler/environment: `solc 0.4.25`; Ubuntu 18.04; Docker 20.10.3; two Intel E5-2699 v4 CPUs; 512 GB RAM; each container received one core and 6 GB.
- Attempts/successes: One-hour fuzzing campaigns, generally repeated five times; the exact campaign count varies by research question. No successful-completion denominator is reported.
- Runtime evidence: A one-hour campaign limit (`3600 s`) is a cap. Static analysis averaged less than two seconds, with a five-second worst case, but this is preprocessing only. Dynamic feedback added 2.7% execution overhead, not an end-to-end duration.
- Evidence locator: `research/.runtime_papers_tmp/smartian_ase21.txt:458-467`, `:477-484`, `:523-530`, `:589-600`, `:610-630`; physical PDF pages 7-10.
- Formula/basis: `3600 s = 1 hour` with `runtime_basis=campaign_cap`; `<2 s` has `runtime_basis=component_only` and is not an exact value.
- Scheduler eligibility: **Rejected.** Campaign cap, component-only timing, inequality rather than exact mean, and no completed-analysis denominator.

### S2. Large-Scale Study of Vulnerability Scanners for Ethereum Smart Contracts

- Authors/year/venue: Christoph Sendner, Lukas Petzi, Jasper Stang, Alexandra Dmitrienko; 2024; IEEE Symposium on Security and Privacy.
- DOI/direct source: `10.1109/SP54263.2024.00230`; https://arxiv.org/pdf/2312.16533
- Identity/version: SMARTIAN run as distributed; tool versions were not extended to unsupported compiler versions.
- Dataset/canonical identity: 77,219 unique-source contracts and a 13,773-contract ground-truth set (RGT).
- Compiler/environment: Mixed real-world Solidity compiler requirements; bytecode fetched from chain where applicable. Runs used Docker on two Intel Xeon Gold 6134 CPUs with 384 GB RAM.
- Attempts/successes: RGT attempted = 13,773. SMARTIAN's reported completed confusion-matrix denominator is 2,460 (`2279+3+168+10`, also `1931+2+516+11` in the all-subtype table). Unfinished scans were excluded.
- Runtime evidence: The completion-rate figure contains no exact numeric duration or timeout threshold for SMARTIAN. No mean or total runtime is reported.
- Evidence locator: `research/.runtime_papers_tmp/scanner_sp24.txt:320-373`, `:392-402`, `:602-654`; Tables 3-4 and Figure 13.
- Formula/basis: No duration exists to normalize; `2460/13773` is a completion fraction, not runtime.
- Scheduler eligibility: **Rejected.** No numeric time value or timeout duration, despite a recoverable completion denominator.

### S3. Towards Smart Contract Fuzzing on GPUs

- Authors/year/venue: Weimin Chen, Xiapu Luo, Haipeng Cai, Haoyu Wang; 2024; IEEE Symposium on Security and Privacy.
- DOI/direct source: DOI not verified in the collected primary PDF; https://www4.comp.polyu.edu.hk/~csxluo/Mau.pdf
- Identity/version: SMARTIAN baseline in its default/artifact configuration.
- Dataset/canonical identity: Small benchmark = 130 contracts (58 CVE and 72 SmartBugs), average 136 LoC; large benchmark = 400 contracts, average 13,099 LoC.
- Compiler/environment: Ubuntu 20.04; two Intel Xeon Gold 6226R CPUs, 512 GB RAM, five RTX 3090 GPUs. A normalized per-contract compiler profile is not reported for SMARTIAN.
- Attempts/successes: The pure-execution microbenchmark averages across the small set, but an end-to-end successful-analysis count is not reported. SMARTIAN is `N/A` on the large set because static analysis failed under path explosion.
- Runtime evidence: Table 7 reports `37143.7 ms` for SMARTIAN on the small benchmark while executing `1024 x 32` random seeds. This measures only the pure program-execution step. Coverage and bug experiments use a one-hour cap. Table 6 reports `0.66K executions/s`, which is throughput rather than analysis duration.
- Evidence locator: `research/.runtime_papers_tmp/mau_sp24.txt:617-675`, `:684-686`, `:737-770`, `:775-814`; Table 7 visually checked in `research/.runtime_papers_tmp/mau_p13.png`.
- Formula/basis: `37143.7 ms / 1000 = 37.1437 s` per contract for the component experiment; `37.1437 / 32768 = 0.0011334136962890625 s/seed`. `runtime_basis=component_only`; campaign cap = `3600 s`.
- Scheduler eligibility: **Rejected.** Component-only microbenchmark, no end-to-end successful denominator, incompatible large-set failures, and campaign cap is not completion time.

### S4. Are We There Yet? Unraveling the State-of-the-Art Smart Contract Fuzzers

- Authors/year/venue: Shuohan Wu, Zihao Li, Luyi Yan, Weimin Chen, Muhui Jiang, Chenxu Wang, Xiapu Luo, Hao Zhou; 2024; ICSE 2024.
- DOI/direct source: `10.1145/3597503.3639152`; https://www4.comp.polyu.edu.hk/~csxluo/ESFuzzers.pdf
- Identity/version: SMARTIAN is one of the evaluated state-of-the-art fuzzers; exact commit not reported.
- Dataset/canonical identity: 2,000 contracts, average 224 LoC and 22 functions; each configuration repeated 20 times.
- Compiler/environment: Mixed Solidity versions. Ubuntu 16.04; AMD EPYC 7H12; 512 GB RAM; each Docker container received eight cores, 16 GB RAM, and 2 GB swap. The study notes failures from obsolete Solidity compilers.
- Attempts/successes: Nominal scheduled campaigns = `2000 x 20 = 40,000`; completed/successful SMARTIAN campaigns are not reported.
- Runtime evidence: Each contract had a 30-minute cap. Figure 3 reports 419 transactions/s for SMARTIAN. Figure 4 plots conditional time to detect a true positive on a log axis but gives no exact SMARTIAN numeric cell.
- Evidence locator: `research/.runtime_papers_tmp/esfuzzers_icse24.txt:577-618`, `:645-672`; physical PDF page 10 for the time-to-bug plot.
- Formula/basis: Cap = `30 x 60 = 1800 s`, `runtime_basis=campaign_cap`; 419 transactions/s cannot be converted to end-to-end seconds without completed workload size.
- Scheduler eligibility: **Rejected.** Cap-only duration, throughput-only exact value, plot-only conditional time-to-bug, missing success count, and mixed compiler failures.

### S5. ItyFuzz: Snapshot-Based Fuzzer for Smart Contract

- Authors/year/venue: Chaofan Shou, Shangyin Tan, Koushik Sen; 2023; ISSTA 2023.
- DOI/direct source: `10.1145/3597926.3598059`; https://scf.so/ityfuzz.pdf
- Identity/version: SMARTIAN comparison baseline; exact commit not reported.
- Dataset/canonical identity: B1 = 57, B2 = 72, B3 = 500, totaling 629 contracts.
- Compiler/environment: AMD EPYC host with 128 cores and 256 GB RAM; optimized builds used `-O3`. Per-contract Solidity compiler compatibility for SMARTIAN is not reported.
- Attempts/successes: Coverage curves include all 629 contracts; repetition and successful-completion counts for SMARTIAN are not reported.
- Runtime evidence: The paper reports coverage trajectories and timeout anecdotes, including B1 behavior at 10 seconds/one minute and two real-world cases where SMARTIAN did not finish within 24 hours. It reports no mean SMARTIAN completion runtime.
- Evidence locator: `research/.runtime_papers_tmp/ityfuzz.txt:423-450`, `:488-505`, `:535-545`.
- Formula/basis: No valid normalization. `60 s` and `86400 s` are observation windows/timeouts, not completed-analysis means.
- Scheduler eligibility: **Rejected.** Coverage-window and timeout evidence only; no exact completed duration, success denominator, or compiler profile.

## MANDO-HGT candidates

### M1. MANDO-HGT: Heterogeneous Graph Transformers for Smart Contract Vulnerability Detection

- Authors/year/venue: Hoang H. Nguyen, Nhat-Minh Nguyen, Chunyao Xie, Zahra Ahmadi, Daniel Kudendo, Thanh-Nam Doan, Lingxiao Jiang; 2023; MSR 2023.
- DOI/direct source: `10.1109/MSR59073.2023.00052`; https://hoanghnguyen.com/assets/pdf/nguyen2023msr.pdf
- Identity/version: Exact MANDO-HGT model/tool; original authors' evaluation.
- Dataset/canonical identity: More than 55,000 contracts collected; 423 processable vulnerable contracts and 2,742 clean contracts. Vulnerable data came from SmartBugs and SolidiFI, followed by balanced per-bug-type sampling.
- Compiler/environment: CrypticCompiler selects `solc` from declared pragmas; Slither supplies source CFG/CG and EtherSolve supplies bytecode CFG. Hardware is not reported.
- Attempts/successes: 70/30 splits and 20 runs per setting are reported, but per-contract inference attempts and successful completions are not.
- Runtime evidence: No training latency, inference duration, wall-clock total, timeout, or hardware timing appears in the evaluation.
- Evidence locator: `research/.runtime_papers_tmp/mando_hgt_msr23.txt:17-45`, `:103-118`, `:450-492`, `:536-566`, `:620-650`.
- Formula/basis: None; no duration reported.
- Scheduler eligibility: **Rejected.** No runtime value and no inference completion denominator.

### M2. Machine Learning for Vulnerability Detection in Smart Contracts: A Comparison of Approaches

- Author/year/type: Stephan Klein; 2025; TU Wien diploma thesis.
- DOI/direct source: `10.34726/hss.2025.123001`; https://repositum.tuwien.at/bitstream/20.500.12708/220334/1/Klein%20Stephan%20-%202025%20-%20Machine%20Learning%20for%20Vulnerability%20Detection%20in%20Smart...pdf
- Identity/version: MANDO-HGT command-line implementation; original snapshots in Experiments I-II and a modified fork for unknown edge types. Retrained HGT results are distinguishable from the original model.
- Dataset/canonical identity: SmartBugs 2.0. Experiment I covers 260 contracts; Experiment II S4 covers 987; Experiment III covers 120.
- Compiler/environment: Compiler version supplied per contract through an environment variable. Experiment I spans Solidity 0.4.26, 0.5.17, 0.6.12, 0.7.6, and 0.8.x.
- Attempts/successes: Experiment I original MANDO-HGT = `260 - 0 = 260`; Experiment II S4 = `987 - 131 = 856`; Experiment III original HGT = `120 - 12 = 108`. These are derived from reported errors/total counts.
- Runtime evidence: The output schema contains `graph runtime` and `node runtime` fields, but the thesis does not aggregate or publish numeric values for them. A comment that base MANDO was omitted for long setup/runtime does not quantify MANDO-HGT.
- Evidence locator: `research/.runtime_papers_tmp/klein_2025.txt:1164-1180`, `:1549-1631`, `:1698-1705`, `:1757-1791`, `:1828-1840`, `:1901-1917`, `:2154-2163`.
- Formula/basis: Success counts use `total - E/T errors`; no duration exists for `seconds / success`.
- Scheduler eligibility: **Rejected.** Strong completion denominators but no published numeric runtime.

### M3. Enhancing Smart Contract Vulnerability Detection via Dual-Source Feature Extraction and Fusion

- Authors/year/venue: Xiao Wang, Yanxiang Tong, Hai Dong, Ben Wang, Yan Xiao, Pengcheng Zhang; 2026; Blockchain: Research and Applications, article 100476.
- DOI/direct source: `10.1016/j.bcra.2026.100476`; https://www.sciencedirect.com/science/article/pii/S2096720926000382
- Identity/version: Baseline labeled `HGT`, interpreted by the paper as MANDO-HGT; exact repository version is not reported.
- Dataset/canonical identity: More than 40,000 contracts collected, with 2,472 vulnerable contracts retained; source and bytecode features; family-aware 80/20 split.
- Compiler/environment: Compiler versions and a scheduler-compatible per-contract compiler profile are not reported.
- Attempts/successes: Random-seed/repetition descriptions are internally inconsistent (narrative versus table), and successful HGT runs are not reported.
- Runtime evidence: Figure 7(b) visually suggests about `0.57 s` training plus `0.03 s` testing, about `0.60 s` total for HGT. These values are plot readings, not printed numeric cells; aggregation semantics are unclear.
- Evidence locator: primary article Figure 7(b); high-resolution local copy `research/.runtime_papers_tmp/dualsvd_fig7.jpg` if present in the collection. The article text gives approximate values for several neighboring methods but not an exact HGT cell.
- Formula/basis: Plot estimate `~0.57 + ~0.03 = ~0.60 s`; `runtime_basis=plot_approximation_unknown_aggregation`.
- Scheduler eligibility: **Rejected.** Plot-derived approximation, ambiguous train/test aggregation, no successful denominator, no compiler profile, and no exact baseline version.

### M4. ORACAL: A Robust and Explainable Multimodal Framework for Smart Contract Vulnerability Detection with Causal Graph Enrichment

- Authors/year/type: Tran Duong Minh Dai, Triet Huynh Minh Le, M. Ali Babar, Van-Hau Pham, Phan The Duy; 2026; arXiv preprint.
- DOI/direct source: `10.48550/arXiv.2603.28128`; https://arxiv.org/pdf/2603.28128
- Identity/version: MANDO-HGT effectiveness baseline; exact baseline commit not reported.
- Dataset/canonical identity: SoliAudit, CGTWeakness, and DAppScan benchmarks.
- Compiler/environment: Pipeline uses `solc` for AST extraction and EtherSolve/Slither for graph construction; exact compiler versions are not reported.
- Attempts/successes: Classification scores are reported, but attempted and successfully completed inference counts are not.
- Runtime evidence: No MANDO-HGT runtime, latency, timeout, or throughput is reported.
- Evidence locator: `research/.runtime_papers_tmp/oracal_2026.txt:235-251` and the MANDO-HGT row in Table 8.
- Formula/basis: None; no duration reported.
- Scheduler eligibility: **Rejected.** No numeric runtime, success denominator, compiler profile, or exact baseline version.

### Excluded MANDO-HGT-adjacent works

- `MANDO-LLM` was not counted as an independent follow-up because it shares the MANDO creator lineage; no scheduler-ready MANDO-HGT runtime was established from the collected material.
- Works that merely cite MANDO-HGT, or evaluate MANDO rather than MANDO-HGT, were not counted.
- Adding those papers would increase a bibliography count but would not create a valid time observation.

## Files found

- `research/.runtime_papers_tmp/smartian_ase21.pdf` / `.txt` — original SMARTIAN evaluation and extracted text.
- `research/.runtime_papers_tmp/scanner_sp24.pdf` / `.txt` — independent large-scale scanner study.
- `research/.runtime_papers_tmp/mau_sp24.pdf` / `.txt` — GPU-fuzzing comparison containing SMARTIAN's component microbenchmark.
- `research/.runtime_papers_tmp/esfuzzers_icse24.pdf` / `.txt` — 2,000-contract fuzzer study.
- `research/.runtime_papers_tmp/ityfuzz.pdf` / `.txt` — snapshot-fuzzer comparison with SMARTIAN coverage windows.
- `research/.runtime_papers_tmp/mando_hgt_msr23.pdf` / `.txt` — original MANDO-HGT evaluation.
- `research/.runtime_papers_tmp/klein_2025.pdf` / `.txt` — independent thesis with MANDO-HGT completion counts but no aggregated timing.
- `research/.runtime_papers_tmp/oracal_2026.pdf` / `.txt` — independent MANDO-HGT effectiveness comparison without timing.
- `toolrank/schemas.py` — runtime observation units, basis, and atomic evidence schema.
- `toolrank/evidence_packet.py` — scheduler eligibility, normalization, support-mass, and weighted-P90 logic.
- `toolrank/kb_update_service.py` — runtime ingestion validation and stable evidence IDs.
- `toolcards/performance_db.json` — current rows; SMARTIAN has a one-hour campaign cap, MANDO-HGT has no runtime.
- `tests/test_runtime_reliability.py` — executable checks rejecting campaign caps and incomplete compiler profiles.

## Code patterns

- Runtime field priority is `time_sec`, `execution_time_avg`, then `execution_time_avg_average_s` (`toolrank/schemas.py:41-69`).
- Runtime observations must use seconds, a positive value, and an explicit basis (`toolrank/schemas.py:214-288`).
- `per_contract` is retained, `per_kloc` is scaled, and `campaign_cap` is unschedulable (`toolrank/evidence_packet.py:262-267`).
- Compiler/LoC compatibility and at least 0.2 original support mass are required (`toolrank/evidence_packet.py:291-342`).
- Runtime is aggregated as a weighted P90 only after evidence becomes eligible (`toolrank/evidence_packet.py:371-413`).
- Runtime unit/basis is mandatory at ingestion (`toolrank/kb_update_service.py:703-731`).
- Tests explicitly cover rejection of caps and compiler-less rows (`tests/test_runtime_reliability.py:288-362`).

## External references

- SMARTIAN, ASE 2021: https://doi.org/10.1109/ASE51524.2021.9678888
- Large-scale scanner study, IEEE S&P 2024: https://doi.org/10.1109/SP54263.2024.00230
- Fuzzer study, ICSE 2024: https://doi.org/10.1145/3597503.3639152
- ItyFuzz, ISSTA 2023: https://doi.org/10.1145/3597926.3598059
- MANDO-HGT, MSR 2023: https://doi.org/10.1109/MSR59073.2023.00052
- Klein thesis, 2025: https://doi.org/10.34726/hss.2025.123001
- DualSVD, 2026: https://doi.org/10.1016/j.bcra.2026.100476
- ORACAL preprint, 2026: https://doi.org/10.48550/arXiv.2603.28128

## Related specs

- `.trellis/workflow.md` — project research and task persistence workflow.
- `.trellis/tasks/07-13-paper-code-alignment/prd.md` — active paper/code alignment objective, where present.
- `toolrank/schemas.py`, `toolrank/evidence_packet.py`, and `tests/test_runtime_reliability.py` act as the executable runtime-evidence contract for this decision.

## Caveats / Not Found

- No scheduler-usable runtime observation was found for either tool; therefore both means are explicitly `null`, not zero.
- The unified multi-index paper-search command encountered provider rate limits/timeouts. Primary PDFs and publisher pages already collected were used for exact verification. Coverage should not be represented as an exhaustive systematic review.
- Plot readings such as DualSVD's approximately 0.60 seconds are preserved only as non-ingestible leads. They must not be entered into `performance_db.json` as exact facts.
- SMARTIAN's 37.1437 seconds is an average for pure execution of 32,768 seeds, not full contract analysis. Its one-hour and 30-minute values are campaign caps.
- MAU's DOI was not verified from the collected primary PDF and is intentionally left blank rather than guessed.
- No API credential or secret was read, copied, or stored in these research artifacts.
