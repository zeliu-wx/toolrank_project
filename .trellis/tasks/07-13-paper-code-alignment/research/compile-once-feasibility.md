# Research: Stage 3 compile-once feasibility

- Query: Inspect every Stage 3 execution path, runner adapter, Docker wrapper, compiler-selection/staging boundary, and the effective paper text for “compile once and share artifacts”; produce a per-tool/input feasibility matrix and the smallest truthful contract that consumes one real compilation result.
- Scope: internal / mixed (project code, adjacent pinned SmartBugs checkout, bundled third-party wrappers, and the local paper)
- Date: 2026-07-19

## Findings

### Executive conclusion

The current implementation does **not** compile once or share a compiled artifact bundle. `engine._run_execution_pipeline` builds a runner command and immediately executes it (`toolrank/engine.py:318-365`). The packaged runner then iterates logical inputs and invokes every selected tool independently (`toolrank/runner.py:1357-1384`); the native fallback does the same inside each tool worker (`toolrank/execution.py:307-449`). No ABI, AST, creation-bytecode, runtime-bytecode, compiler identity, or compilation manifest crosses the engine-to-runner boundary (`toolrank/execution.py:163-224`).

The smallest honest first implementation is a **conditional, run-scoped compilation bundle with declared consumers**, initially consumed by:

1. **Smartian**, whose wrapper already compiles source to ABI plus creation/runtime bytecode and passes ABI plus bytecode to the actual Smartian engine (`docker/runners/run_smartian.py:224-290`, `:398-426`).
2. **Vandal**, whose LAKES source adapter already compiles source to runtime bytecode before invoking Vandal's runtime-only SmartBugs mode (`toolrank/runner.py:639-721`; `../smartbugs/tools/vandal/config.yaml:6-9`).

These are genuine consumers because the shared outputs replace compilation that those two LAKES-owned wrappers perform today. Merely generating a bundle while still passing source to every adapter would be decorative and would not satisfy the paper sentence.

There is one mandatory policy decision before those two consumers can share a bit-identical result: Smartian currently compiles with `--optimize` (`docker/runners/run_smartian.py:233-242`), while Vandal's source bridge invokes `solc --combined-json bin-runtime` without optimization (`toolrank/runner.py:651-675`). One `solc --standard-json` invocation has one optimizer setting. Therefore:

- a **truthful canonical compile-once implementation** must pick and record one setting (the smallest deterministic default is optimizer disabled, matching Solidity's default and Vandal's current path), accepting and regression-testing the Smartian input change; or
- a **strict behavior-preserving implementation** cannot yet claim that Smartian and Vandal share one compilation. It must first prove another pair of consumers with identical compiler settings and equivalent tool mode, or obtain an explicit product decision to normalize settings.

The effective paper should be narrowed from an unconditional universal claim to the conditional contract proposed below. Source-native analyzers cannot consume a generic ABI/AST/bytecode bundle without tool-specific changes, and several need source text even after internal compilation.

### Files found

- `main_revised.tex` — effective Stage 3 paper sentence; line 434 is the only active compile-once contract.
- `toolrank/engine.py` — Stage 3 orchestration, execution-plan construction, report harvesting, and fusion.
- `toolrank/execution.py` — manual-runner and native-SmartBugs execution paths.
- `toolrank/runner.py` — typed input discovery, per-tool dispatch, compiler selection, special adapters, generic SmartBugs preparation, output staging, and batch execution.
- `toolrank/adapter_capabilities.py` — effective adapter/input support, narrower than several ToolCards.
- `toolrank/target_inputs.py` — `.sol`, creation-bytecode, and runtime-bytecode classification.
- `toolrank/contract_profile.py` and `toolrank/_complexity.py` — pre-Stage-1 AST profiling compilation; this output is not an execution artifact and is discarded.
- `toolrank/source_project.py` and `toolrank/smartbugs_project.py` — import closure, project staging, and generic SmartBugs compiler selection.
- `docker/runners/run_smartian.py` — source-to-ABI/bytecode compilation followed by the real Smartian invocation.
- `docker/runners/run_sailfish.py` — source-only Sailfish wrapper and its independent compiler download/selection.
- `docker/vendor/securify2/**` — source-to-AST Securify2 path; its internal CFG compiler can accept an AST dict, but its current CLI does not.
- `docker/vendor/gptscan/src/**` — GPTScan source/Falcon pipeline; source remains required for call-graph and LLM analysis.
- `../smartbugs/` — adjacent checkout at ref `89c16bb620c6bfb10e9c025f9372c9a80b1c5279`, the same ref pinned by `Dockerfile:4`; its package declares SmartBugs `2.1.1` (`../smartbugs/pyproject.toml:5-8`).
- `.trellis/spec/backend/lakes-scheduling-contract.md` — current execution, input, import, compiler, freshness, and failure invariants.
- `.trellis/tasks/07-13-paper-code-alignment/{prd.md,design.md,implement.md,progress.md}` — active task requirements and completed implementation history.
- `.trellis/tasks/07-13-paper-code-alignment/research/paper-effective-contract.md` — effective-paper extraction, including the Stage 3 sentence and its unspecified failure cases.

### What the effective paper actually requires

The active sentence says that Stage 3 “first compiles the target contract once with the specified solc version and shares the compiled artifacts across tools,” then executes tools in parallel (`main_revised.tex:434`). It does not define:

- an artifact schema or which of ABI, source AST, creation bytecode, deployed/runtime bytecode, source maps, metadata, storage layout, or IR is shared;
- how the “specified” exact `solc` patch is selected;
- optimizer, EVM version, remapping, library-linking, metadata, or via-IR settings;
- import/project behavior, multiple contracts in one source, or mixed source/bytecode targets;
- compilation failure, warning, timeout, or no-common-compiler behavior;
- whether source-only tools may compile internally, or whether compilation time consumes budget.

The paper's experimental set admits tools whose inputs are compatible with the evaluation pipeline (`main_revised.tex:494`), but that does not prove every tool accepts one universal compiled representation. The paper sentence is therefore directionally clear but operationally under-specified.

### Current execution and compilation paths

#### Normal runner

1. The engine serializes only target path, result root, selected tools, primary, timeout, jobs, and category filters (`toolrank/execution.py:163-224`).
2. The runner discovers source entrypoints plus every explicit bytecode/runtime file (`toolrank/runner.py:189-211`).
3. Inputs are sequential; selected tools for one input are parallel (`toolrank/runner.py:1357-1384`, `:1047-1164`).
4. Every invocation starts a private adapter worker and private result staging directory (`toolrank/runner.py:921-995`). The request contains a source/input path and kind, not a compilation bundle (`:944-958`).
5. Generic source-mode SmartBugs stages source plus imports and injects a compiler binary; the analyzer still invokes that compiler inside its own container (`toolrank/runner.py:738-795`; `toolrank/smartbugs_project.py:64-103`; `../smartbugs/sb/docker.py:60-100`).

#### Native fallback

The fallback rediscoveres inputs and, per tool and input, either calls the same LAKES special adapter or constructs a fresh SmartBugs invocation (`toolrank/execution.py:265-381`). It has no artifact-bundle parameter. Any compile-once implementation placed only in `toolrank.runner` would be bypassed or recomputed by this path.

#### Compiler selection is currently inconsistent

- `representative_solidity_version` selects the **lowest** version in the constraint intersection (`toolrank/solc_range.py:67-75`).
- special adapters using `_run_solc_select` select the **oldest installed** compatible version and mutate global `solc-select` state (`toolrank/runner.py:317-376`).
- the SmartBugs project bridge selects the **newest available** compatible version (`toolrank/smartbugs_project.py:21-40`).
- Securify2 derives a lower representative, then builds a version-specific Docker image (`toolrank/runner.py:512-562`).
- Sailfish receives a representative version but independently locates or downloads its compiler inside its wrapper (`docker/runners/run_sailfish.py:337-465`).
- Docker preinstalls only selected patches and leaves wrappers free to switch later (`Dockerfile:42-45`, `:111-124`).

Thus “specified solc version” has no single execution owner today.

#### The profiling AST is not reusable execution output

Target analysis does invoke a compiler before Stage 1 (`toolrank/contract_profile.py:120-129`), but that does not satisfy Stage 3:

- profiling rewrites pragmas in a private copy and may try several fixed canonical patch compilers (`toolrank/_complexity.py:290-367`);
- it requests only source ASTs (`toolrank/_complexity.py:342-355`);
- `profile_sources` returns metrics and compiler labels, discarding the ASTs (`toolrank/_complexity.py:370-380`);
- the task explicitly says this substitution is profiling-only and the original constraints remain authoritative for execution (`.trellis/tasks/07-13-paper-code-alignment/prd.md:271-279`; `.trellis/spec/backend/lakes-scheduling-contract.md:75-94`).

Reusing this AST would silently compile possibly rewritten source with a profiling compiler rather than the exact execution contract.

### Feasibility matrix for the 20 paper tools

Legend:

- `S`, `C`, `R` = effective LAKES adapter accepts Solidity source, creation bytecode, or runtime/deployed bytecode.
- “direct” = that artifact is accepted at the current adapter boundary.
- “post-compile” = a LAKES-owned wrapper currently derives and feeds it to the real engine; this is the strongest first-wave reuse candidate.
- “internal” = the tool/source wrapper builds or consumes an internal representation, but LAKES has no compatible artifact-input contract.
- “later only” = mechanically dispatchable, but switching the source workflow to artifact mode is not proven output-equivalent.

Effective modes come from `toolrank/adapter_capabilities.py:24-58`, not merely ToolCard declarations. Feasibility requires both ToolCard and adapter support for every present target kind (`toolrank/feasibility.py:33-43`).

| Tool | Effective kinds | ABI | AST | Creation bytecode | Runtime bytecode | Source behavior and truthful bundle verdict |
|---|---|---|---|---|---|---|
| ConFuzzius | S | — | internal/unknown | — | — | Source is passed to the fuzzer with injected `solc`; requires source-mode compilation (`../smartbugs/tools/confuzzius/config.yaml:6-10`, `scripts/do_solidity.sh:8-38`). Source-native; no v1 bundle consumer. |
| Conkas | S, R | — | — | — | direct | Source mode invokes `conkas.py -s`; runtime mode invokes `conkas.py` on bytecode (`../smartbugs/tools/conkas/config.yaml:7-11`, `scripts/do_solidity.sh:24-26`, `scripts/do_runtime.sh:6-9`). Runtime projection is mechanically possible later, but source/runtime output equivalence is unproven. |
| GPTScan | S | — | internal Falcon representation | — | — | Current path constructs `falcon.Falcon(source)` and separately reads source for call graph, prompts, and locations (`docker/vendor/gptscan/src/tasks.py:144-208`). An unused helper can load Falcon-compatible AST (`docker/vendor/gptscan/src/falcon_adapter.py:28-75`), but generic solc AST is not that contract and source is still required. Not a v1 bundle consumer. |
| HoneyBadger | S, R | — | — | — | direct | Source mode and runtime mode are distinct CLI paths (`../smartbugs/tools/honeybadger/config.yaml:7-11`, `scripts/do_solidity.sh:25-35`, `scripts/do_runtime.sh:7-17`). Runtime projection is later-only pending parity evidence. |
| Maian | S, C, R | — | — | direct | direct | SmartBugs exposes both bytecode modes (`../smartbugs/tools/maian/config.yaml:7-13`; `scripts/do_bytecode.sh:8-11`; `scripts/do_runtime.sh:8-11`). Later candidate, but source-to-bytecode mode parity is unproven; the pinned source script also constructs an `echo python3 ...` command rather than a clearly executed analyzer command (`scripts/do_solidity.sh:23-29`), so it is not a trustworthy parity baseline without a real smoke test. |
| MANDO-HGT | S | — | internal graph | — | — | Source wrapper inspects the injected compiler and runs `inference.sh` on source (`../smartbugs/tools/mando-hgt/scripts/do_solidity.sh:8-35`). Source-native. |
| Manticore | S | — | internal | — | — | Effective adapter is source-only; script runs Manticore on the source with injected `solc` (`../smartbugs/tools/manticore-0.3.7/config.yaml:7-10`, `scripts/do_solidity.sh:6-15`). ToolCard claims do not widen the registered adapter. |
| Mythril | S, C, R | — | internal | direct | direct | Bytecode and runtime commands are native Mythril modes (`../smartbugs/tools/mythril-0.24.8/config.yaml:7-13`, `scripts/do_bytecode.sh:15-17`, `scripts/do_runtime.sh:15-17`). Strong mechanical later candidate, but switching from source mode can lose source/contract context and must pass detector/location parity tests. |
| Osiris | S, R | — | — | — | direct | Runtime mode is explicit (`../smartbugs/tools/osiris/config.yaml:7-11`, `scripts/do_runtime.sh:15-17`). Later-only pending source/runtime parity. |
| Oyente | S, R | — | — | — | direct | Runtime mode is explicit (`../smartbugs/tools/oyente/config.yaml:7-11`, `scripts/do_runtime.sh:15-18`). Later-only pending source/runtime parity. |
| Sailfish | S | — | internal | — | — | Wrapper mounts source and invokes `contractlint.py ... -sc /usr/local/bin/solc`; it may download a compiler itself (`docker/runners/run_sailfish.py:382-465`, `:471-503`). Source-native and internally compiling. |
| Securify | S, R | — | internal dependency graph | — | direct | Source uses `-fs`; runtime uses `-fh` (`../smartbugs/tools/securify/config.yaml:8-12`, `scripts/do_solidity.sh:6-12`, `scripts/do_runtime.sh:6-10`). Runtime is a later candidate, not proven equivalent to source analysis. |
| Securify2 | S | — | post-compile internally; possible custom AST input | — | — | Current Docker CLI takes source and `compile_ast` calls solc standard JSON (`docker/vendor/securify2/securifyjson.py:137-186`; `securify/solidity/solidity_ast_compiler.py:13-39`). Its CFG compiler can accept an AST dict (`solidity_cfg_compiler.py:59-95`), so an AST adapter is feasible, but it needs Securify2's AST version/source annotations and a new CLI. Not a v1 consumer. |
| sFuzz | S | — | internal | — | — | Source-only adapter with injected `solc`; fuzzer receives copied `.sol` contracts (`../smartbugs/tools/sfuzz/config.yaml:6-10`, `scripts/do_solidity.sh:8-45`). Source-native. |
| Slither | S | — | internal Slither/CryticCompile AST/IR | — | — | Current adapter always sends source through SmartBugs; script invokes `slither $FILENAME` with injected `solc` (`../smartbugs/tools/slither-0.11.3/config.yaml:8-10`, `scripts/do_solidity.sh:7-14`). No compiled-bundle mode is registered. |
| SmartCheck | S | — | parser-internal | — | — | Script runs `smartcheck -p` on source (`../smartbugs/tools/smartcheck/config.yaml:5-8`, `scripts/do_solidity.sh:6-10`). It needs source text and gains nothing from ABI/bytecode. |
| Smartian | S | post-compile | — | post-compile | post-compile option, currently creation | Wrapper compiles `abi,bin,bin-runtime`, writes ABI plus the selected bytecode, then invokes `Smartian.dll fuzz -p ... -a ...` (`docker/runners/run_smartian.py:224-290`, `:398-426`). **Best first-wave bundle consumer**; current LAKES call uses the default creation-bytecode kind (`toolrank/runner.py:600-636`). |
| Solhint | S | — | source parser | — | — | Script invokes Solhint directly on source and does not use solc (`../smartbugs/tools/solhint-6.0.0/config.yaml:6-8`, `scripts/do_solidity.sh:6-10`). Source is irreducible input. |
| Vandal | S, R | — | — | — | direct; post-compile from S | Vandal itself is runtime-only (`../smartbugs/tools/vandal/config.yaml:4-9`). LAKES source mode compiles runtime bytecode first and then dispatches the runtime mode (`toolrank/runner.py:639-721`). **Best first-wave bundle consumer**. |
| VulHunter | S, C | — | internal CFG | direct | — | Bytecode mode is explicit (`../smartbugs/tools/vulhunter-0.2/config.yaml:8-12`, `scripts/do_bytecode.sh:7-11`); source mode passes source and a compiler version (`scripts/do_solidity.sh:8-25`). Creation projection is later-only pending parity. |

#### Component-level answer

- **ABI:** only Smartian's actual engine is presently fed ABI by LAKES, after its wrapper compiles source. No top-level target kind or generic SmartBugs mode represents ABI.
- **AST:** no production LAKES adapter currently accepts a shared solc AST. Securify2 can consume a specially annotated AST dict internally, and GPTScan contains Falcon-compatible-AST code, but neither is wired to the production runner and their formats are not interchangeable.
- **Creation bytecode:** Maian, Mythril, and VulHunter accept it directly; Smartian consumes it after its wrapper compiles source.
- **Runtime bytecode:** Conkas, HoneyBadger, Maian, Mythril, Osiris, Oyente, Securify, and Vandal accept it directly. Vandal's source path is already a source-to-runtime adapter.
- **Source and internal compilation/parsing:** every paper tool accepts source at the current LAKES boundary, but SmartCheck and Solhint are source parsers rather than beneficiaries of compiled artifacts. GPTScan also needs source after its Falcon compilation. The remaining source-mode analyzers either explicitly invoke solc or rely on a framework that does.

### Smallest truthful implementation contract

#### Proposed paper-facing wording

> For each Solidity project with a selected artifact-aware adapter, LAKES resolves one exact execution compiler and performs one run-scoped compilation over the unmodified in-project source closure. Every declared artifact consumer uses projections from that same validated compilation result; source-native analyzers continue to receive source and may compile internally. LAKES skips central compilation when no selected adapter consumes it and records compilation failures before launching analyzers.

This wording truthfully promises real reuse without claiming that source-only tools consume bytecode or that an unused bundle exists. If the paper retains “all tools share compiled artifacts,” the implementation scope is much larger and cannot be met by the present adapters.

#### Typed boundary

Add one owner before both normal and native dispatch, conceptually:

```text
Stage3CompilationBundle
  schema_version = "stage3_compile_v1"
  status = NOT_APPLICABLE | READY | FAILED
  bundle_id                         # digest of sources + exact solc + settings
  compiler_version
  compiler_binary_digest
  source_root
  entrypoints[]
  source_units[] {relative_path, sha256}
  settings {optimizer_enabled, optimizer_runs, evm_version, via_ir, remappings}
  requested_components[]           # union of real consumer requirements only
  contracts[fully_qualified_name]
    abi?                            # requested by Smartian
    creation_bytecode?              # requested by Smartian
    runtime_bytecode?               # requested by Vandal
    source_ast?                     # absent in v1 until a real AST consumer exists
  consumer_routes[] {tool, contract, components, bundle_id}
  warnings[]
  failure_reason?
  compile_runtime_seconds
```

`requested_components` is computed from selected declared consumers. A Smartian-only plan requests ABI plus creation bytecode; Vandal-only requests runtime bytecode; Smartian+Vandal requests all three in one standard-JSON invocation. AST must not be requested in v1 because no production adapter consumes the canonical AST. A source-only plan records `NOT_APPLICABLE` and does not invoke solc or write a bundle.

#### First-wave routing

- `smartian/sol` consumes `abi` plus `creation_bytecode` from the bundle. The wrapper keeps its existing `dotnet Smartian.dll fuzz -p ... -a ...` engine command and loses only its private `_compile_source` step.
- `vandal/sol` consumes `runtime_bytecode` from the same bundle and enters the existing generic SmartBugs runtime path. The private `_compile_runtime_hex_for_vandal` step is not called.
- every other `tool/sol` route remains source-native and is explicitly recorded as `source_native`; it must not be listed in `consumer_routes`.
- existing user-supplied creation/runtime files remain independent runner inputs and are never replaced by source-derived artifacts.

Later phases may add Mythril/Maian/VulHunter or runtime-capable tools only after proving that artifact-mode detector coverage, category mapping, contract selection, and locations are acceptable relative to the source mode. Capability declarations must name a precise format (`solc_standard_json_ast_vX`, not merely `ast`).

#### Compiler and settings contract

1. Select one exact installed execution compiler version satisfying all source-unit constraints and the exact support ranges of every selected tool. The existing pairwise overlap check is insufficient to prove a common version (`toolrank/feasibility.py:45-55`).
2. Use one immutable binary path; do not rely on concurrent `solc-select use` global state.
3. Compile original source, not profiling-rewritten source, with stable project-relative unit names.
4. Use a single standard-JSON request whose output selection is the union of components actually consumed.
5. Record optimizer/EVM/via-IR/remapping/library settings in the bundle digest. With no project build settings, the smallest deterministic policy is optimizer disabled, no via-IR, and compiler-default EVM version. This deliberately changes Smartian from its current optimized input and must be accepted/tested explicitly.
6. If selected consumers require incompatible settings and no canonical policy has been approved, fail with `NO_COMMON_COMPILATION_SETTINGS`; do not silently run two compilers while claiming “once.”
7. Source-native adapters must be passed the same selected exact version where their wrappers support compiler injection. They may still invoke it internally, so the truthful claim is shared artifacts for declared consumers, not zero redundant compiler processes globally.

#### Import and contract-selection contract

- Reuse `dependency_closure`/`source_entrypoints` as the source-set owner; include only regular in-root Solidity files, preserve relative paths, and exclude escaping symlinks and unrelated sources (`toolrank/source_project.py:183-260`).
- Compile the stable union of selected source-entrypoint closures once per accepted source project. The current target analyzer already rejects a globally unsatisfiable source constraint intersection (`toolrank/contract_profile.py:80-107`).
- Address outputs by fully qualified `relative/source.sol:ContractName`; never select a contract by unordered JSON iteration.
- Preserve the current explicit policy only if made deterministic: prefer a deployable contract whose name equals the entrypoint stem; otherwise require an unambiguous single deployable contract. Multiple unmatched deployable contracts are a typed `AMBIGUOUS_TARGET_CONTRACT` failure, not “first dict item.”
- Empty bytecode for interfaces/abstract contracts is not a successful artifact route.

#### Failure, timeout, freshness, and fusion contract

- Perform compilation before launching any analyzer worker. Compiler nonzero exit, timeout, standard-JSON `severity=error`, malformed JSON, missing requested output, ambiguous contract, or no exact compiler yields `Stage3CompilationBundle.status=FAILED`.
- On compilation failure, no analyzer starts; every selected tool remains `NOT_RUN` with a compilation reason, `ExecutionResult.status="failed"`, no stale report is harvested, and fusion reports categories unavailable. Do not classify a compile failure as a tool failure.
- Warnings are preserved in the compilation manifest but do not fail a complete requested output.
- The bundle is run-scoped, built in private staging, validated, and atomically promoted. It is cleared/quarantined with other selected-run artifacts; a previous run's bundle is never reused. This preserves the fresh-only rule (`.trellis/spec/backend/lakes-scheduling-contract.md:196-220`).
- Compilation duration is recorded separately. The paper does not say whether it consumes `B`; the smallest compatible rule is that tool deadlines begin after successful preflight compilation, while the compile itself has an explicit bounded timeout. The paper should say this if runtime comparisons include or exclude preprocessing.
- Both the normal runner and native fallback receive the same bundle object/path. Fallback may not call solc again.

#### Mixed-input behavior

The source-derived bundle is an internal projection, not a new user target kind. It must not alter `ContractFeatures.present_input_kinds` or feasibility.

- For `S + R`, a Vandal source route consumes the derived runtime once and its explicit runtime input is dispatched once; the source itself is not also sent to Vandal.
- For source-native tools, source is dispatched once; explicit accepted bytecode/runtime inputs remain separate work items.
- A selected tool must still support every **user-present** kind. For example, the current feasibility loop rejects a source+runtime target for Smartian because Smartian has no runtime adapter (`toolrank/feasibility.py:33-43`). Generated bundle projections do not change that result.
- Planning count remains source entrypoints plus explicit bytecode/runtime inputs (`toolrank/contract_profile.py:154-172`). Derived artifacts are alternate representations of a source work item and do not increment `execution_input_count`.
- Never dispatch both a source and its derived artifact to the same tool; route identity is `(logical_input_id, tool_id)` and must be unique.

### Exact regression tests required

Create focused tests with these names and assertions; all compiler/Docker/analyzer calls can be mocked except the existing parser-level unit tests.

1. `test_smartian_and_vandal_consume_one_shared_standard_json_compile`
   - source target; selected `smartian,vandal`;
   - mocked solc called exactly once;
   - request asks for ABI, creation bytecode, and runtime bytecode;
   - both routes carry the same non-empty `bundle_id`;
   - Smartian receives ABI+creation and Vandal receives runtime;
   - monkeypatched legacy `_compile_source` and `_compile_runtime_hex_for_vandal` raise if called.

2. `test_compile_bundle_requests_only_components_with_real_consumers`
   - Smartian-only requests ABI+creation, not AST/runtime;
   - Vandal-only requests runtime, not ABI/AST/creation;
   - no unconsumed field appears in the manifest.

3. `test_source_only_plan_skips_decorative_compilation`
   - selected `slither,solhint`;
   - solc mock is never called;
   - compilation status is `NOT_APPLICABLE` and `consumer_routes=[]`.

4. `test_source_native_tool_is_not_reported_as_artifact_consumer`
   - selected `smartian,slither`;
   - exactly one compile occurs for Smartian;
   - Slither receives the source path and exact selected compiler version;
   - only Smartian appears in `consumer_routes`.

5. `test_compile_failure_stops_every_adapter_before_launch`
   - compiler returns standard-JSON error/nonzero;
   - all adapter mocks raise if called;
   - execution is failed, tool statuses are `NOT_RUN`, no per-tool findings or promoted report exists, and the compiler diagnostic is typed.

6. `test_compile_timeout_stops_every_adapter_and_cannot_publish_late_bundle`
   - compiler exceeds its deadline;
   - no tool launches; staging is absent after return; a late writer cannot create a consumable bundle.

7. `test_execution_solc_is_one_exact_common_version`
   - target constraints plus selected tool ranges and installed versions choose the documented exact version deterministically;
   - source-native adapters and bundle manifest see that same version;
   - disjoint exact intersection returns `NO_COMMON_EXECUTION_SOLC` before compile.

8. `test_compile_bundle_uses_unmodified_safe_import_closure`
   - `Main.sol` imports `Lib.sol`; include both with stable relative keys;
   - exclude unrelated `.sol`, `.env`, and an escaping symlink;
   - captured compiler input retains original pragmas byte-for-byte.

9. `test_multi_contract_output_requires_deterministic_contract_identity`
   - stem-matching deployable contract is selected by fully qualified key;
   - two unmatched deployable contracts fail `AMBIGUOUS_TARGET_CONTRACT`;
   - interface/abstract empty bytecode is never routed.

10. `test_mixed_source_runtime_routes_each_logical_input_once`
    - source+explicit runtime target with `vandal,mythril`;
    - Vandal receives one derived runtime for the source and one explicit runtime, never the source too;
    - Mythril retains its declared source route plus explicit runtime;
    - execution input count excludes the derived runtime.

11. `test_user_supplied_bytecode_is_not_overwritten_by_source_bundle`
    - source plus `.bin`/`.runtime` fixtures retain their exact bytes and input IDs after source compilation.

12. `test_native_fallback_reuses_ready_bundle_without_recompile`
    - force manual-runner fallback after a ready bundle;
    - compile counter remains one;
    - native Smartian/Vandal requests reference the original bundle ID.

13. `test_stale_compile_bundle_is_cleared_and_never_reused_after_failure`
    - preseed a valid-looking prior bundle;
    - current compilation fails;
    - stale bundle is removed/quarantined, no analyzer/fusion output consumes it.

14. `test_optimizer_policy_is_explicit_and_digest_bound`
    - one canonical optimizer value appears in standard JSON, manifest, and bundle digest;
    - changing optimizer changes bundle ID;
    - Smartian and Vandal cannot receive different settings under one bundle.

15. `test_smartian_bundle_route_preserves_engine_command_shape`
    - after replacing only compilation, actual command remains `Smartian.dll fuzz -p <creation> -a <abi> ...` and uses bundle files.

16. `test_vandal_bundle_route_preserves_runtime_mode_shape`
    - Vandal receives normalized `.rt.hex` and SmartBugs command includes `--runtime`; no source compile helper runs.

17. `test_ast_is_not_advertised_without_a_production_consumer`
    - v1 capability registry does not request/serialize AST for GPTScan or Securify2;
    - adding an AST consumer requires a format-specific capability and fixture validation.

18. `test_compiler_warnings_are_recorded_but_errors_fail_closed`
    - warning plus complete outputs is `READY` with warnings;
    - any severity-error or missing requested component is `FAILED`.

19. `test_compile_once_capability_matrix_matches_registered_adapters`
    - parameterize all 20 tools and assert the exact S/C/R sets in `ADAPTER_INPUT_CAPABILITIES` plus first-wave consumers `{smartian: abi+creation, vandal: runtime}`.

20. `test_real_fixture_smartian_vandal_bundle_smoke` (environment-gated)
    - one small contract and fixed installed solc;
    - compile once, launch both real wrappers, validate structurally successful fresh reports and manifest consumer provenance;
    - skip clearly when Docker/.NET/compiler prerequisites are unavailable; the mocked boundary tests remain mandatory.

### External references and versions

No web search was needed. The execution substrate inspected is the adjacent SmartBugs checkout at ref `89c16bb620c6bfb10e9c025f9372c9a80b1c5279`, pinned by the project Dockerfile (`Dockerfile:4`, `:52-69`) and declaring version `2.1.1` (`../smartbugs/pyproject.toml:5-8`). Its own documentation describes three modes—source, deployment bytecode, and runtime bytecode—and automatic compiler injection (`../smartbugs/README.md:24-45`). Tool versions and modes were read from the exact local `tools/*/config.yaml` files used by that checkout, not inferred from current upstream releases.

### Related specs

- `.trellis/spec/backend/lakes-scheduling-contract.md:170-187` — target-kind feasibility, source entrypoints, execution input counts, and execution schedule.
- `.trellis/spec/backend/lakes-scheduling-contract.md:196-225` — fresh-only promotion, SmartBugs source staging, bytecode normalization, and exact compiler constraint behavior.
- `.trellis/spec/backend/lakes-scheduling-contract.md:262-265` — unsupported input and no-compatible-compiler fail-closed matrix.
- `.trellis/spec/guides/cross-layer-thinking-guide.md` — one typed owner and validation at each engine/runner/adapter boundary.
- `.trellis/spec/guides/code-reuse-thinking-guide.md` — supports one compiler-selection and compilation owner rather than per-wrapper copies.

## Caveats / Not Found

- Critical: no current code path shares a compilation result, and no current schema can describe one.
- Critical: Smartian and Vandal, the two lowest-change real consumers, currently disagree on optimizer settings. “Compile once” and “preserve both historical bytecodes exactly” cannot both be true without a policy change.
- Critical: an AST is not a portable scalar. Securify2's annotated solc AST and GPTScan/Falcon-compatible AST require different loaders; a generic `ast.json` contract would be misleading.
- Critical: direct bytecode/runtime support proves launchability, not semantic equivalence to source mode. Switching Mythril, Maian, VulHunter, Conkas, HoneyBadger, Osiris, Oyente, or Securify requires differential detector/category/location evidence.
- Critical: the paper does not state whether compile time is inside the developer budget. The proposed contract records and bounds it but does not silently add it to historical per-tool runtime.
- Not found: project build-setting ingestion for optimizer, EVM version, via-IR, remappings, linked libraries, or metadata hash. Without it, any source compilation reconstructs rather than reproduces a deployed build.
- Not found: a current production AST-input adapter, a shared bundle cleanup path, bundle provenance in `ExecutionResult`, or a common exact-solc selector across special and generic adapters.
- The adjacent SmartBugs checkout is a local execution dependency outside this repository. Line citations are to the exact pinned local state inspected on 2026-07-19.
- No production code, spec, task plan, ToolCard, or paper file was modified.
