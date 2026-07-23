from __future__ import annotations

import pytest
from semantic_version import Version

from toolrank import _complexity, runner
from toolrank.contract_profile import SolidityConstraintError, analyze_target
from toolrank.feasibility import check_feasibility
from toolrank.schemas import ContractFeatures, ToolCard
from toolrank.schemas_v2 import BudgetProfile
from toolrank.solc_range import version_satisfies_solidity_constraint


def _disable_ast(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("toolrank.contract_profile._complexity.profile_sources", lambda _sources: {})


@pytest.mark.parametrize(
    ("constraint", "representative"),
    [
        ("^0.5.3", "0.5.3"),
        ("~0.5.3", "0.5.3"),
        (">=0.5.0 <0.8.0", "0.5.0"),
        (">=0.5.0 <=0.8.0", "0.5.0"),
        ("^0.4.24 || ^0.8.20", "0.4.24"),
    ],
)
def test_profile_representative_satisfies_pragma_constraint(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
    constraint: str,
    representative: str,
) -> None:
    _disable_ast(monkeypatch)
    target = tmp_path / "Target.sol"
    target.write_text(
        f"pragma solidity {constraint};\ncontract Target {{}}\n",
        encoding="utf-8",
    )

    features = analyze_target(str(target))

    assert features.primary_solidity_version == representative
    assert features.solidity_version_constraints == [constraint]
    assert version_satisfies_solidity_constraint(representative, constraint)


def test_excluded_upper_bound_is_never_selected() -> None:
    assert not version_satisfies_solidity_constraint("0.8.0", ">=0.5.0 <0.8.0")
    assert version_satisfies_solidity_constraint("0.8.0", ">=0.5.0 <=0.8.0")


def test_multiple_files_intersect_their_pragma_constraints(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _disable_ast(monkeypatch)
    (tmp_path / "A.sol").write_text(
        "pragma solidity >=0.5.0 <0.8.0; contract A {}",
        encoding="utf-8",
    )
    (tmp_path / "B.sol").write_text(
        "pragma solidity ^0.7.0; contract B {}",
        encoding="utf-8",
    )

    features = analyze_target(str(tmp_path))

    assert features.primary_solidity_version == "0.7.0"
    assert version_satisfies_solidity_constraint(
        features.primary_solidity_version,
        features.solidity_version_constraints[0],
    )
    assert version_satisfies_solidity_constraint(
        features.primary_solidity_version,
        features.solidity_version_constraints[1],
    )


def test_disjoint_multifile_constraints_fail_closed(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _disable_ast(monkeypatch)
    (tmp_path / "A.sol").write_text(
        "pragma solidity ^0.5.0; contract A {}",
        encoding="utf-8",
    )
    (tmp_path / "B.sol").write_text(
        "pragma solidity ^0.8.0; contract B {}",
        encoding="utf-8",
    )

    with pytest.raises(SolidityConstraintError, match="No supported Solidity version"):
        analyze_target(str(tmp_path))


def test_noncode_pragmas_do_not_participate_in_constraint_intersection(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _disable_ast(monkeypatch)
    target = tmp_path / "Target.sol"
    target.write_text(
        """
        // pragma solidity ^0.5.0;
        /* pragma solidity ^0.6.0; */
        pragma solidity ^0.8.20;
        contract Target {
            string constant DOUBLE = "pragma solidity ^0.4.0;";
            string constant ESCAPED = "keep \\\" pragma solidity ^0.7.0;";
            string constant SINGLE = 'pragma solidity ^0.5.0;';
        }
        """,
        encoding="utf-8",
    )

    features = analyze_target(str(target))

    assert features.solidity_version_constraints == ["^0.8.20"]
    assert features.primary_solidity_version == "0.8.20"


@pytest.mark.parametrize(
    ("exact_version", "profiling_version"),
    [("0.5.3", "0.5.17"), ("0.8.20", "0.8.30")],
)
def test_ast_compiler_selection_uses_fixed_patch_for_profiling_only(
    monkeypatch: pytest.MonkeyPatch,
    exact_version: str,
    profiling_version: str,
) -> None:
    installed = [Version("0.5.3"), Version("0.5.17"), Version("0.8.20"), Version("0.8.30")]
    monkeypatch.setattr(
        _complexity,
        "solcx",
        type("FakeSolcx", (), {"get_installed_solc_versions": staticmethod(lambda: installed)}),
    )

    selected = _complexity._ast_compiler_versions(
        {
            "Target.sol": (
                "/* pragma solidity ^0.4.0; */\n"
                f"pragma solidity {exact_version}; "
                'contract Target { string constant X = "pragma solidity ^0.6.0;"; }'
            )
        }
    )

    assert [str(version) for version in selected] == [profiling_version]


def test_broad_range_tries_each_allowed_canonical_bucket_in_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    installed = [Version("0.4.26"), Version("0.5.17"), Version("0.8.30")]
    monkeypatch.setattr(
        _complexity,
        "solcx",
        type(
            "FakeSolcx",
            (),
            {"get_installed_solc_versions": staticmethod(lambda: installed)},
        ),
    )

    selected = _complexity._ast_compiler_versions(
        {
            "Target.sol": (
                "pragma solidity >=0.4.22 <0.6.0; "
                "contract Target {}"
            )
        }
    )

    assert [str(version) for version in selected] == ["0.4.26", "0.5.17"]


def test_broad_range_profile_labels_the_compiler_that_emitted_the_ast(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []

    class FakeSolcx:
        @staticmethod
        def get_installed_solc_versions():
            return [Version("0.4.26"), Version("0.5.17")]

        @staticmethod
        def compile_standard(input_data, *, solc_version):
            calls.append(str(solc_version))
            if str(solc_version) == "0.4.26":
                raise RuntimeError("fixture: source uses 0.5 syntax")
            return {
                "sources": {
                    "Target.sol": {"ast": {"nodeType": "SourceUnit", "nodes": []}}
                }
            }

    monkeypatch.setattr(_complexity, "solcx", FakeSolcx)
    sources = {
        "Target.sol": (
            "pragma solidity >=0.4.22 <0.6.0; "
            "contract Target {}"
        )
    }

    profile = _complexity.profile_sources(sources)

    assert calls == ["0.4.26", "0.5.17"]
    assert profile["solc"] == "0.5.x"
    assert profile["profiling_compiler"] == "0.5.17"
    assert sources["Target.sol"].startswith("pragma solidity >=0.4.22")


def test_broad_range_fallback_does_not_change_target_execution_constraints(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = tmp_path / "Target.sol"
    original = "pragma solidity >=0.4.22 <0.6.0; contract Target {}\n"
    target.write_text(original, encoding="utf-8")

    class FakeSolcx:
        @staticmethod
        def get_installed_solc_versions():
            return [Version("0.4.26"), Version("0.5.17")]

        @staticmethod
        def compile_standard(input_data, *, solc_version):
            if str(solc_version) == "0.4.26":
                raise RuntimeError("fixture: source uses 0.5 syntax")
            return {
                "sources": {
                    "Target.sol": {"ast": {"nodeType": "SourceUnit", "nodes": []}}
                }
            }

    monkeypatch.setattr(_complexity, "solcx", FakeSolcx)

    features = analyze_target(str(target))

    assert features.solidity_version_constraints == [">=0.4.22 <0.6.0"]
    assert features.primary_solidity_version == "0.4.22"
    assert features.gower_solc_bucket == "0.5.x"
    assert features.gower_ast_available
    assert target.read_text(encoding="utf-8") == original


def test_or_constraint_limits_candidate_buckets(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    installed = [
        Version("0.4.26"),
        Version("0.5.17"),
        Version("0.6.12"),
        Version("0.7.6"),
        Version("0.8.30"),
    ]
    monkeypatch.setattr(
        _complexity,
        "solcx",
        type(
            "FakeSolcx",
            (),
            {"get_installed_solc_versions": staticmethod(lambda: installed)},
        ),
    )

    selected = _complexity._ast_compiler_versions(
        {"Target.sol": "pragma solidity ^0.4.24 || ^0.8.20; contract Target {}"}
    )

    assert [str(version) for version in selected] == ["0.4.26", "0.8.30"]


def test_profiling_substitution_does_not_change_exact_execution_constraint(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = tmp_path / "Target.sol"
    original = "pragma solidity 0.5.3; contract Target {}\n"
    target.write_text(original, encoding="utf-8")
    captured: list[str] = []

    class FakeSolcx:
        @staticmethod
        def get_installed_solc_versions():
            return [Version("0.5.17")]

        @staticmethod
        def compile_standard(input_data, *, solc_version):
            captured.append(input_data["sources"]["Target.sol"]["content"])
            return {
                "sources": {
                    "Target.sol": {"ast": {"nodeType": "SourceUnit", "nodes": []}}
                }
            }

    monkeypatch.setattr(_complexity, "solcx", FakeSolcx)

    features = analyze_target(str(target))

    assert features.primary_solidity_version == "0.5.3"
    assert features.solidity_version_constraints == ["0.5.3"]
    assert features.gower_solc_bucket == "0.5.x"
    assert features.gower_ast_available
    assert "pragma solidity 0.5.17;" in captured[0]
    assert target.read_text(encoding="utf-8") == original


def test_no_pragma_profile_uses_deterministic_default_compiler(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        _complexity,
        "solcx",
        type(
            "FakeSolcx",
            (),
            {
                "get_installed_solc_versions": staticmethod(
                    lambda: [
                        Version("0.4.26"),
                        Version("0.5.17"),
                        Version("0.6.12"),
                        Version("0.7.6"),
                        Version("0.8.30"),
                    ]
                )
            },
        ),
    )

    selected = _complexity._ast_compiler_versions(
        {"Target.sol": "contract Target {}"}
    )

    assert [str(version) for version in selected] == [
        "0.8.30",
        "0.7.6",
        "0.6.12",
        "0.5.17",
        "0.4.26",
    ]


def test_no_pragma_profile_falls_back_and_labels_successful_bucket(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []

    class FakeSolcx:
        @staticmethod
        def get_installed_solc_versions():
            return [
                Version("0.4.26"),
                Version("0.5.17"),
                Version("0.6.12"),
                Version("0.7.6"),
                Version("0.8.30"),
            ]

        @staticmethod
        def compile_standard(input_data, *, solc_version):
            calls.append(str(solc_version))
            if str(solc_version) != "0.4.26":
                raise RuntimeError("fixture: legacy no-pragma syntax")
            return {
                "sources": {
                    "Target.sol": {"ast": {"nodeType": "SourceUnit", "nodes": []}}
                }
            }

    monkeypatch.setattr(_complexity, "solcx", FakeSolcx)

    profile = _complexity.profile_sources({"Target.sol": "contract Target {}"})

    assert calls == ["0.8.30", "0.7.6", "0.6.12", "0.5.17", "0.4.26"]
    assert profile["solc"] == "0.4.x"
    assert profile["profiling_compiler"] == "0.4.26"


def test_runner_pragma_collection_ignores_comments_and_quoted_strings(tmp_path) -> None:
    target = tmp_path / "Target.sol"
    target.write_text(
        """
        // pragma solidity ^0.5.0;
        pragma solidity >=0.8.20 <0.9.0;
        contract Target {
            string constant A = "pragma solidity ^0.4.0;";
            string constant B = 'escaped \\' pragma solidity ^0.6.0;';
        }
        """,
        encoding="utf-8",
    )

    assert runner._collect_pragma_specs(target) == [">=0.8.20 <0.9.0"]


def test_runner_selects_an_installed_compiler_that_satisfies_full_constraint(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = tmp_path / "Target.sol"
    target.write_text(
        "pragma solidity ^0.8.20; contract Target {}",
        encoding="utf-8",
    )
    selected: list[list[str]] = []
    monkeypatch.setattr(
        runner,
        "_installed_solc_select_versions",
        lambda: ["0.8.19", "0.8.30"],
    )
    monkeypatch.setattr(
        runner,
        "_stream_process",
        lambda command, **_kwargs: selected.append(command) or 0,
    )

    assert runner._run_solc_select(target, "gptscan")
    assert selected == [["solc-select", "use", "0.8.30"]]


def test_runner_installed_compiler_selection_respects_excluded_upper_bound(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = tmp_path / "Target.sol"
    target.write_text(
        "pragma solidity >=0.8.0 <0.8.20; contract Target {}",
        encoding="utf-8",
    )
    selected: list[list[str]] = []
    monkeypatch.setattr(
        runner,
        "_installed_solc_select_versions",
        lambda: ["0.8.19", "0.8.20", "0.8.30"],
    )
    monkeypatch.setattr(
        runner,
        "_stream_process",
        lambda command, **_kwargs: selected.append(command) or 0,
    )

    assert runner._run_solc_select(target, "vandal")
    assert selected == [["solc-select", "use", "0.8.19"]]


def test_runner_compiler_dependent_adapter_fails_without_compatible_install(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = tmp_path / "Target.sol"
    target.write_text(
        "pragma solidity ^0.8.20; contract Target {}",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        runner,
        "_installed_solc_select_versions",
        lambda: ["0.8.19"],
    )
    monkeypatch.setattr(
        runner,
        "_stream_process",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("incompatible compiler must fail before launch")
        ),
    )

    assert not runner._run_solc_select(target, "gptscan")


def test_feasibility_checks_tool_range_against_the_full_target_constraint(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _disable_ast(monkeypatch)
    target = tmp_path / "Target.sol"
    target.write_text(
        "pragma solidity >=0.5.0 <0.8.0; contract Target {}",
        encoding="utf-8",
    )
    features = analyze_target(str(target))
    budget = BudgetProfile(tool_slots=1, runtime_cap_minutes=1.0)

    supported = ToolCard(
        tool_id="slither",
        tool_name="slither",
        d7_input_support={"sol": True},
        d8_mode="static",
        d2_solidity_versions="0.7.x",
        d3_multifile_support="yes",
    )
    excluded_upper_bound_only = supported.model_copy(
        update={"tool_id": "gptscan", "tool_name": "gptscan", "d2_solidity_versions": "0.8.x"}
    )

    assert check_feasibility(supported, features, budget).feasible
    assert not check_feasibility(excluded_upper_bound_only, features, budget).feasible


@pytest.mark.parametrize(
    ("filename", "source_kind"),
    [
        ("deployment.bin", "bytecode"),
        ("deployment.hex", "bytecode"),
        ("deployed.runtime.bin", "runtime"),
        ("deployed.runtime.hex", "runtime"),
        ("deployed.rt.bin", "runtime"),
        ("deployed.rt.hex", "runtime"),
        ("deployed.runtime", "runtime"),
        ("deployed.rt", "runtime"),
    ],
)
def test_directory_profile_classifies_all_runner_bytecode_inputs(
    tmp_path,
    filename: str,
    source_kind: str,
) -> None:
    (tmp_path / filename).write_text("6000", encoding="utf-8")

    features = analyze_target(str(tmp_path))

    assert features.source_kind == source_kind
    assert features.present_input_kinds == [source_kind]
    assert features.file_count == 1


def test_directory_profile_marks_creation_and_runtime_bytecode_as_mixed(tmp_path) -> None:
    (tmp_path / "deployment.hex").write_text("6000", encoding="utf-8")
    (tmp_path / "deployed.rt.bin").write_text("6001", encoding="utf-8")

    features = analyze_target(str(tmp_path))

    assert features.source_kind == "mixed"
    assert features.present_input_kinds == ["bytecode", "runtime"]
    assert features.file_count == 2


def test_profile_counts_source_import_graph_roots_as_execution_inputs(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _disable_ast(monkeypatch)
    (tmp_path / "Lib.sol").write_text(
        "pragma solidity ^0.8.20; library Lib {}",
        encoding="utf-8",
    )
    (tmp_path / "Main.sol").write_text(
        'pragma solidity ^0.8.20; import "./Lib.sol"; contract Main {}',
        encoding="utf-8",
    )
    (tmp_path / "Deploy.bin").write_text("6000", encoding="utf-8")

    features = analyze_target(str(tmp_path))

    assert features.file_count == 3
    assert features.execution_input_count == 2


@pytest.mark.parametrize(
    ("present_kinds", "tool_id", "input_support"),
    [
        (["sol", "bytecode"], "vulhunter", {"sol": True, "bytecode": True}),
        (["sol", "runtime"], "conkas", {"sol": True, "runtime": True}),
    ],
)
def test_mixed_feasibility_requires_only_the_input_kinds_actually_present(
    present_kinds: list[str],
    tool_id: str,
    input_support: dict[str, bool],
) -> None:
    features = ContractFeatures(
        source_kind="mixed",
        present_input_kinds=present_kinds,
        file_count=2,
    )
    card = ToolCard(
        tool_id=tool_id,
        tool_name=tool_id,
        d7_input_support=input_support,
        d8_mode="static",
        d2_solidity_versions="0.4.0-0.8.99",
        d3_multifile_support="yes",
    )

    result = check_feasibility(
        card,
        features,
        BudgetProfile(tool_slots=1, runtime_cap_minutes=1.0),
    )

    assert result.feasible, result.reasons


@pytest.mark.parametrize("target_kind", ["empty_directory", "unsupported_file", "missing"])
def test_real_target_without_supported_inputs_is_not_feasible(
    tmp_path,
    target_kind: str,
) -> None:
    if target_kind == "empty_directory":
        target = tmp_path / "empty"
        target.mkdir()
    elif target_kind == "unsupported_file":
        target = tmp_path / "notes.txt"
        target.write_text("not an analyzer input", encoding="utf-8")
    else:
        target = tmp_path / "missing.sol"
    features = analyze_target(str(target))
    card = ToolCard(
        tool_id="extension-tool",
        tool_name="extension-tool",
        d7_input_support={"sol": True},
        d8_mode="static",
        d2_solidity_versions="0.4.0-0.8.99",
        d3_multifile_support="yes",
    )

    result = check_feasibility(
        card,
        features,
        BudgetProfile(tool_slots=1, runtime_cap_minutes=1.0),
    )

    assert not result.feasible
    assert "target has no supported input files" in result.reasons


def test_synthetic_unknown_profile_without_target_path_remains_usable() -> None:
    card = ToolCard(
        tool_id="fixture-tool",
        tool_name="fixture-tool",
        d7_input_support={"sol": True},
        d8_mode="static",
        d2_solidity_versions="0.4.0-0.8.99",
        d3_multifile_support="yes",
    )

    result = check_feasibility(
        card,
        ContractFeatures(),
        BudgetProfile(tool_slots=1, runtime_cap_minutes=1.0),
    )

    assert result.feasible, result.reasons


def test_real_target_requires_a_registered_executable_adapter(tmp_path) -> None:
    target = tmp_path / "Target.sol"
    target.write_text("pragma solidity ^0.8.20; contract Target {}", encoding="utf-8")
    features = analyze_target(str(target))
    card = ToolCard(
        tool_id="extension-tool",
        tool_name="extension-tool",
        d7_input_support={"sol": True},
        d8_mode="static",
        d2_solidity_versions="0.4.0-0.8.99",
        d3_multifile_support="yes",
    )

    result = check_feasibility(
        card,
        features,
        BudgetProfile(tool_slots=1, runtime_cap_minutes=1.0),
    )

    assert not result.feasible
    assert "no executable adapter registered" in result.reasons
