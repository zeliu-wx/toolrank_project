# Research: GPTScan and SAILFISH runtime papers

- Query: Find approximately five independent empirical/evaluation papers per tool, verify exact runtime evidence in primary full text, compute averages only across comparable units, and determine whether each observation is schedulable.
- Scope: mixed
- Date: 2026-07-21

## Findings

### Decision summary

| Tool | Candidate papers | Papers with verified runtime | Comparable average | Result |
|---|---:|---:|---|---|
| GPTScan | 5 | 3 | Per-KLoC, 2 papers | **21.845 s/KLoC** (`(14.39 + 29.3) / 2`) |
| GPTScan | 5 | 3 | Per-project, 2 papers | **24.2543 s/project**, conditional descriptive value only |
| GPTScan | 5 | 3 | Per-contract | **Not found**; project, case, and KLoC must not be relabeled as contracts |
| SAILFISH | 5 | 5 | Per-contract, 3 papers | **23.6767 s/contract** (`(30.79 + 10.9 + 29.34) / 3`) |

These are unweighted descriptive cross-paper means. They are not scheduler values. The scheduling contract keeps independent paper rows, requires compiler/LOC-compatible scene support of at least `0.2`, and applies weighted P90 within the qualified set. None of the verified sources supplies a sufficient compiler scene profile, so every row remains scheduler-ineligible today.

### GPTScan evidence

#### 1. GPTScan primary paper — accepted

- Paper: Yuqiang Sun, Daoyuan Wu, Yue Xue, Han Liu, Haijun Wang, Zhengzi Xu, Xiaofei Xie, and Yang Liu. “GPTScan: Detecting Logic Vulnerabilities in Smart Contracts by Combining GPT with Program Analysis.” ICSE 2024. DOI: `10.1145/3597503.3639117`.
- Primary full text: https://daoyuan14.github.io/papers/ICSE24_GPTScan.pdf
- Tool identity: exact paper implementation; GPT-3.5-turbo, 4K context, temperature 0. No dated model snapshot or commit is printed.
- Dataset: Top200, Web3Bugs, and DefiHacks; 388 projects, 3,157 Solidity files, 472,024 LoC. Seventeen Top200 projects cannot compile for static confirmation. No Solidity-version distribution is given.
- Runtime: 6,793.35 seconds total; 14.39 seconds/KLoC mean; median not reported; timeout policy and hardware not reported.
- Exact evidence: PDF p.6 Table 2; pp.8–9 RQ4 and Table 5. Table 5 gives Top200 `1,437.37 s / 134.32 KLoC = 10.70`, Web3Bugs `4,980.57 / 319.88 = 15.57`, DefiHacks `375.41 / 17.82 = 21.06`, and overall `6,793.35 / 472.02 = 14.39 s/KLoC`.
- Normalization: use 14.39 s/KLoC directly. A conditional project value is `6,793.35 / 388 = 17.508634 s/project`; project is not contract. The paper does not tabulate a successful-run denominator separately.
- Runtime basis: `per_kloc`; supported in principle.
- Scheduler eligibility: **false** because the source has no compatible compiler bucket/profile.

#### 2. IntentChecker independent rerun — accepted as per-case only

- Paper: Inseong Jeon, Sundeuk Kim, Hyunwoo Kim, and Hoh Peter In. “IntentChecker: An Intent-Model-Based Debugging Assistant for Mitigating Numeric Logic Errors in Solidity.” Research Square, 2026. DOI: `10.21203/rs.3.rs-9541907/v1`.
- Primary full text: https://assets-eu.researchsquare.com/files/rs-9541907/v1_covered_e81afd1e-c85f-4093-a47e-86c4a1cec2d3.pdf
- Tool identity: GPTScan code rerun in April 2026. The authors warn that its OpenAI model aliases had been redirected since 2023; this is not the original ICSE model snapshot.
- Dataset: 20 contract/function cases, three runs each, 60 measured observations. All 60 appear in Figure 9. The broader benchmark includes Solidity `>=0.6` cases and one `0.4.x` pragma, but the 20-case compiler distribution is absent.
- Runtime: mean **265.9 s/case**, median **149.0 s/case**; no GPTScan timeout stated. The paper's 1,800-second timeout applies to NumScout, not GPTScan.
- Exact evidence: PDF p.21 Section 4.1 gives Intel i7-11390H, 16 GB RAM, Windows 10; pp.31–32 Section 4.4/Figure 9 give `n=60`, mean 265.9, median 149.0; p.33 documents alias drift and common hardware/OS/network.
- Normalization: no conversion. `20 cases × 3 runs = 60`; a case cannot be assumed to be one deployable contract. The mean-implied total `265.9 × 60 = 15,954 s` is approximate because the mean is rounded.
- Runtime basis: `per_case`; descriptive only.
- Scheduler eligibility: **false** because `per_case` is unsupported and model/compiler identity is incomplete.

#### 3. Heimdallr independent evaluation — accepted

- Paper: Xiaohui Hu, Wun Yu Chan, Yuejie Shi, Qumeng Sun, Wei-Cheng Wang, Chiachih Wu, Haoyu Wang, and Ningyu He. “An Effective and Cost-Efficient Agentic Framework for Ethereum Smart Contract Auditing.” arXiv:2601.17833, 2026.
- Primary full text: https://arxiv.org/pdf/2601.17833
- Tool identity: authors say GPTScan was successfully deployed as an open-source baseline. Exact commit and model snapshot are absent; proprietary model requests use OpenRouter for standardized latency/rate limits.
- Dataset: D1 has 20 recent exploit projects, D2 has 30 Anthropic benchmark projects, and D3 has 30 Sherlock contest projects. Successful-run and timeout counts are not reported. Solidity versions are not reported.
- Runtime: Table 1 reports **31 s/project** for D1+D2. Table 2 reports **293 s/10 KLoC** for D3, normalized as `293 / 10 = 29.3 s/KLoC`. Median and totals are not reported.
- Exact evidence: PDF p.7 Section 6.1.2; p.8 Tables 1–2 and Section 6.1.4. Hardware is Mac Studio, M3 Ultra, 32-core CPU/32-core GPU, 512 GB unified memory.
- Runtime bases: `per_project` and normalized `per_kloc`.
- Scheduler eligibility: **false** because successful counts and a compatible compiler/LOC scene profile are missing.

#### 4. AiRacleX comparison — rejected

- Paper: Bo Gao, Yuan Wang, Qingsong Wei, Yong Liu, Rick Siow Mong Goh, and David Lo. “AiRacleX: Automated Detection of Price Oracle Manipulations via LLM-Driven Knowledge Mining and Prompt Generation.” arXiv:2502.06348, 2025.
- Primary full text: https://arxiv.org/pdf/2502.06348
- Dataset: explicit GPTScan comparisons cover 11 DeFiHacks and 14 Code4rena projects.
- Rejection: no GPTScan runtime is reported. The authors also replace GPT-3.5 with GPT-4o-mini and modify GPTScan for structured JSON output, so exact-tool identity is not preserved.
- Exact locator: PDF p.11 Section 4.2 for modifications; p.13 Table 4 and p.17 Table 7 for accuracy-only comparisons.

#### 5. E-Guard comparison — rejected

- Paper: Feng Du, Junwei Ma, Liang Gu, Honglin Xue, Xiaowei Hao, Xin Gong, and Rongsheng Li. “E-Guard: a vulnerability detection tool for smart contracts in electric power systems.” *Blockchain: Research and Applications* 6(4), 100309, 2025. DOI: `10.1016/j.bcra.2025.100309`.
- Publisher full text: https://www.sciencedirect.com/science/article/pii/S2096720925000363
- Dataset: 27 electric-power-system smart contracts; Intel i5-12400F, 64 GB RAM.
- Rejection: GPTScan detection metrics are reported, but GPTScan runtime is not. RQ3 measures E-Guard EIR overhead rather than GPTScan completion time.

#### GPTScan averages and write recommendation

- Comparable per-KLoC papers: primary GPTScan 14.39 and Heimdallr 29.3. Unweighted mean: **21.845 s/KLoC**.
- Comparable per-project values: primary-paper conditional derivation 17.508634 and Heimdallr 31. Unweighted mean: **24.254317 s/project**. This is descriptive and depends on treating the reported 388-project campaign as complete.
- Per-case reference: IntentChecker 265.9 mean, 149.0 median; only one paper and not a supported scheduling basis.
- Per-contract average: **not available**. No defensible conversion exists from project, case, or KLoC to individual contract.
- Safe write shape: retain independent `per_kloc` rows with unique source IDs. Do not replace the original paper row with 21.845, do not add 24.254 as `per_contract`, and leave rows unschedulable until compiler/LOC profiles exist.

### SAILFISH evidence

#### 1. SAILFISH primary paper — accepted

- Paper: Priyanka Bose, Dipanjan Das, Yanju Chen, Yu Feng, Christopher Kruegel, and Giovanni Vigna. “SAILFISH: Vetting Smart Contract State-Inconsistency Bugs in Seconds.” IEEE S&P 2022. DOI: `10.1109/SP46214.2022.9833721`.
- Primary full text: https://arxiv.org/pdf/2104.08638
- Tool identity: exact paper implementation; no commit printed.
- Dataset: 89,853 deduplicated Solidity contracts from Etherscan. Contracts requiring Solidity `<0.3.x` and Vyper contracts were excluded. No retained-version histogram is given.
- Outcomes: 83,171 safe, 2,076 unsafe, 1,211 timeout, 3,395 error; derived completed count `83,171 + 2,076 = 85,247`.
- Runtime: **30.79 s/contract** mean; median and total not reported; 20-minute per-contract budget.
- Exact evidence: PDF p.10 Section VIII-A/Table II; p.12 Table IV and Section VIII-C. Hardware is six Ubuntu 18.04.3 servers, each with Xeon E5-2690 v2 3.00 GHz, 40 cores, and 256 GB RAM.
- Normalization: use 30.79 directly. Table IV does not explicitly say whether its mean excludes timeout/error cases, so no total is reconstructed from 85,247.
- Runtime basis: `per_contract`.
- Scheduler eligibility: **false** because the source has no compiler-bucket profile.

#### 2. Smart Learning to Find Dumb Contracts — accepted

- Paper: Tamer Abdelaziz and Aquinas Hobor. “Smart Learning to Find Dumb Contracts.” 32nd USENIX Security Symposium, 2023.
- Primary full text: https://www.usenix.org/system/files/usenixsecurity23-abdelaziz.pdf
- Extended full text: https://arxiv.org/pdf/2304.10726
- Tool identity: Table 3 identifies SAILFISH by release year 2022; no version/commit.
- Dataset: three disjoint reentrancy tests—Elysium source subset 59, Reentrancy benchmark 472, SolidiFI 444; 975 attempted contracts.
- Outcomes: exceptions are 6, 125, and 0. Derived completed count: `(59-6) + (472-125) + (444-0) = 844`.
- Runtime: Figure 1 reports **10.9 s/contract**; median, total, and a main-benchmark timeout policy are not reported.
- Exact evidence: PDF p.2 Figure 1; p.8 Section 4.1; extended PDF pp.17–18 Tables 5–6. Hardware is i7-8700, 12 cores, 3.2 GHz, 16 GB RAM.
- Caveat: the 87.8% completion marker is the unweighted mean of the three test completion rates. Figure 1 does not state whether 10.9 is pooled or a mean of benchmark means, so `10.9 × 844` is not a valid reconstructed total.
- Runtime basis: `per_contract`.
- Scheduler eligibility: **false** because compiler distribution, runtime weighting, and exact tool version are missing.

#### 3. DivertScan comparison — accepted

- Paper: Yinxi Liu, Wei Meng, and Yinqian Zhang. “Detecting Smart Contract State-Inconsistency Bugs via Flow Divergence and Multiplex Symbolic Execution.” PACMSE/FSE 2025. DOI: `10.1145/3715712`.
- Primary full text: https://yinqian.org/papers/fse25.pdf
- Dataset: 4,502 contracts from 174 active projects across 11 Etherscan networks.
- Outcomes: SAILFISH analyzes 1,484, times out on 18, and leaves 3,000 other cases unanalyzed, mainly because of unsupported Solidity versions.
- Runtime: **29.34 s per analyzed contract**; median and reported total absent; 20-minute per-contract timeout.
- Exact evidence: PDF pp.13–14 Section 5.1; p.15 Table 1; p.16 Scalability paragraph. Hardware is four 24-core 2.10 GHz Xeon Platinum 8160 CPUs running Debian 9.
- Normalization: use 29.34 directly. A non-authoritative implied successful total is `29.34 × 1,484 = 43,540.56 s`.
- Runtime basis: `per_contract`.
- Scheduler eligibility: **false** because compiler distribution is absent and extensive compiler incompatibility is documented.

#### 4. Nyx comparison — rejected from per-contract average

- Paper: Wuqi Zhang, Zhuo Zhang, Qingkai Shi, Lu Liu, Lili Wei, Yepang Liu, Xiangyu Zhang, and Shing-Chi Cheung. “Nyx: Detecting Exploitable Front-Running Vulnerabilities in Smart Contracts.” IEEE S&P 2024. DOI: `10.1109/SP54263.2024.00146`.
- Primary full text: https://qingkaishi.github.io/public_pdfs/SP2024.pdf
- Dataset: 513 real-world vulnerable contract groups, each containing one or more contracts. Baselines analyze member contracts separately, then results are aggregated by group.
- Outcomes: SAILFISH has 1 timeout, 428 errors, and 84 successfully analyzed groups. Newer unsupported Solidity versions cause the errors.
- Runtime: **32.83 s/successfully analyzed group**, average 1,260.87 LoC; three-hour group-analysis cap. Hardware is AMD Ryzen 3975X, 512 GB RAM, single thread.
- Exact evidence: PDF pp.9–10 experiment setup and Table 1.
- Rejection: `per_contract_group` is not `per_contract`. Group cardinalities are not available for normalization. `32.83 × 84 = 2,757.72 s` is only a mean-implied group total.
- Scheduler eligibility: **false**.

#### 5. SmarTrim comparison — rejected

- Paper: Hyegeun Song, Jiseong Han, and Sunbeom So. “SmarTrim: Symbolic Execution for Smart Contracts Powered by Redundant Transaction-Sequence Pruning.” PACMSE/FSE 2026. DOI: `10.1145/3797074`.
- Primary full text: https://ku-formal.github.io/assets/pdf/fse26-smartrim.pdf
- Tool identity: SAILFISH commit `bbab10cde68cc12a2f50e85a40dae213f5453259` via the cited Docker artifact.
- Dataset: RE Dataset with 49 contracts, average 226 LoC. Only 21 contracts are commonly successful across all 12 tools; this is not a SAILFISH-specific success count.
- Runtime: **1 minute 40 seconds total** for SAILFISH on RE; 30-minute internal and 35-minute external per-contract timeouts. Hardware is Ubuntu, Ryzen Threadripper 3970X 3.7 GHz, 62 GB RAM, up to 24 threads per analyzer.
- Exact evidence: PDF pp.13–14 setup/Table 1; p.15 Analysis Time; p.20 reference [14].
- Rejection: cumulative campaign time lacks a SAILFISH-specific successful denominator. `100 / 49 = 2.0408 s/attempt` is not a completion-time mean, and `100 / 21` wrongly substitutes a cross-tool denominator.
- Scheduler eligibility: **false**.

#### SAILFISH average and write recommendation

- Accepted comparable means: 30.79, 10.9, and 29.34 seconds/contract.
- Unweighted descriptive mean: **23.6766667 s/contract**, rounded **23.68 s/contract**.
- Excluded: Nyx 32.83 because it is per contract group; SmarTrim 100 seconds because it is a cumulative campaign value without a successful denominator.
- Safe write shape: preserve the three accepted observations as independent paper rows. Do not replace them with 23.68. Do not write Nyx or SmarTrim as per-contract evidence. All rows remain unschedulable until compatible compiler/LOC profiles are added.

### Files found

- `toolcards/performance_db.json:2863` — existing GPTScan source row; 14.39 seconds with `runtime_basis: per_kloc`, but `solc` is empty.
- `toolcards/performance_db.json:2912` — existing SAILFISH source row; 30.79 seconds with `runtime_basis: per_contract`, but `solc` is empty.
- `.trellis/spec/backend/lakes-scheduling-contract.md:155` — runtime values must originate in the Performance KB.
- `.trellis/spec/backend/lakes-scheduling-contract.md:158` — seconds and default per-contract basis contract.
- `.trellis/spec/backend/lakes-scheduling-contract.md:163` — only `per_contract`, `per_kloc`, and descriptive `campaign_cap`; per-KLoC converts once using target LoC.
- `.trellis/spec/backend/lakes-scheduling-contract.md:166` — compiler/LoC compatibility, support threshold, and weighted-P90 rule.
- `.trellis/spec/backend/lakes-scheduling-contract.md:172` — provenance must retain sample, success, timeout, compilation-failure, and failure counts.
- `.trellis/spec/backend/lakes-scheduling-contract.md:410` — cumulative, non-finite, non-positive, and timeout values are rejected as per-run evidence.

### Code patterns

- Current GPTScan data already uses the correct paper basis: `toolcards/performance_db.json:2876`–`2882` stores 14.39 seconds as `per_kloc`.
- Current SAILFISH data stores the primary paper mean: `toolcards/performance_db.json:2926`–`2932` stores 30.79 seconds as `per_contract`.
- Both rows have empty compiler profiles at `toolcards/performance_db.json:2867` and `toolcards/performance_db.json:2916`; under `.trellis/spec/backend/lakes-scheduling-contract.md:167`–`178`, they cannot become executable estimates.
- A cross-paper arithmetic mean is a research summary, not the selection statistic. `.trellis/spec/backend/lakes-scheduling-contract.md:169` requires weighted P90 after compatible support reaches `0.2`.

### External references

- GPTScan primary paper and DOI: https://doi.org/10.1145/3597503.3639117
- IntentChecker preprint DOI: https://doi.org/10.21203/rs.3.rs-9541907/v1
- Heimdallr arXiv record: https://arxiv.org/abs/2601.17833
- AiRacleX arXiv record: https://arxiv.org/abs/2502.06348
- E-Guard DOI: https://doi.org/10.1016/j.bcra.2025.100309
- SAILFISH primary DOI: https://doi.org/10.1109/SP46214.2022.9833721
- Smart Learning official proceedings PDF: https://www.usenix.org/system/files/usenixsecurity23-abdelaziz.pdf
- DivertScan DOI: https://doi.org/10.1145/3715712
- Nyx DOI: https://doi.org/10.1109/SP54263.2024.00146
- SmarTrim DOI: https://doi.org/10.1145/3797074

### Related specs

- `.trellis/spec/backend/lakes-scheduling-contract.md` — authoritative runtime basis, provenance, compatibility, support, and weighted-P90 rules.
- `.trellis/spec/guides/code-reuse-thinking-guide.md` — favors extending the existing Performance KB evidence path instead of a parallel runtime mechanism.
- `.trellis/spec/guides/cross-layer-thinking-guide.md` — requires new evidence fields to remain aligned across ingestion, schemas, selection, and UI/reporting.

## Caveats / Not Found

- A defensible five-paper runtime average does not exist for either tool. GPTScan has two comparable per-KLoC papers and no per-contract papers. SAILFISH has three comparable per-contract papers.
- GPTScan per-project and per-case values are useful descriptive evidence but cannot be converted to per-contract without contract-count denominators.
- SAILFISH primary-paper Table IV does not state whether the 30.79-second mean excludes timeout/error cases. Smart Learning does not state the weighting behind its 10.9-second figure. Both are retained only as paper-reported means.
- No accepted paper supplies a compiler-version distribution adequate for the scheduler's compatibility contract. Runtime remains unknown at execution planning time until compatible scene evidence is added.
- Semantic Scholar citation lookup repeatedly returned HTTP 429. A generic OpenAlex search returned HTTP 504, although exact-DOI OpenAlex lookups worked for original papers. One DBLP API search returned HTTP 500. Publisher/author PDFs, exact DOI metadata, arXiv, and official proceedings were used as fallbacks.
- No API key or secret was read, copied, or written during this research. Credential use for later GPTScan execution is outside this literature-only task.
