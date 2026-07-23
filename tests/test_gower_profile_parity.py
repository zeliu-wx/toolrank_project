from __future__ import annotations

from pathlib import Path
from textwrap import dedent

import pytest

from toolrank import _complexity
from toolrank.contract_profile import analyze_target
from toolrank.profile_builder import profile_file
from toolrank.scene_pool import _target_phi
from toolrank.schemas import ContractFeatures


GOWER_KEYS = ("solc", *_complexity.NUM_DIMS)


def _sample_asts() -> list[dict]:
    return [
        {
            "nodeType": "SourceUnit",
            "nodes": [
                {
                    "nodeType": "ContractDefinition",
                    "id": 1,
                    "nodes": [
                        {
                            "nodeType": "VariableDeclaration",
                            "typeName": {
                                "nodeType": "UserDefinedTypeName",
                                "referencedDeclaration": 2,
                            },
                        },
                        {
                            "nodeType": "FunctionDefinition",
                            "body": {
                                "nodeType": "Block",
                                "statements": [
                                    {
                                        "nodeType": "IfStatement",
                                        "condition": {
                                            "nodeType": "BinaryOperation",
                                            "operator": "&&",
                                        },
                                        "trueBody": {
                                            "nodeType": "Block",
                                            "statements": [
                                                {
                                                    "nodeType": "ForStatement",
                                                    "body": {"nodeType": "Block"},
                                                }
                                            ],
                                        },
                                    }
                                ],
                            },
                        },
                    ],
                },
                {"nodeType": "ContractDefinition", "id": 2, "nodes": []},
            ],
        }
    ]


@pytest.fixture
def fixed_asts(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        _complexity,
        "_compile_asts",
        lambda sources: _complexity.AstCompilation(
            asts=tuple(_sample_asts()[0] for _name in sources),
            solc_bucket=str(_complexity.source_profile_facts(sources)["solc"]),
            profiling_compiler=_complexity.profiling_compiler_for_bucket(
                str(_complexity.source_profile_facts(sources)["solc"])
            ),
        ),
    )


def _profiles(path: Path) -> tuple[dict, dict]:
    runtime_profile = _target_phi(analyze_target(str(path)))
    assert runtime_profile is not None
    offline_profile = profile_file(str(path))
    return (
        {key: runtime_profile[key] for key in GOWER_KEYS},
        {key: offline_profile[key] for key in GOWER_KEYS},
    )


def test_runtime_and_offline_builder_share_or_range_gower_profile(
    tmp_path: Path,
    fixed_asts: None,
) -> None:
    constraint = ">=0.5.0 <0.6.0 || >=0.8.20 <0.9.0"
    target = tmp_path / "Target.sol"
    target.write_text(
        dedent(
            f'''\
            pragma solidity {constraint};
            contract Target {{
                string constant NOTE = "pragma solidity ^0.7.0;";
                function run(uint value) public pure returns (uint) {{
                    return value;
                }}
            }}
            '''
        ),
        encoding="utf-8",
    )

    runtime_profile, offline_profile = _profiles(target)
    features = analyze_target(str(target))

    assert runtime_profile == offline_profile
    assert features.gower_ast_available
    assert runtime_profile == {
        "solc": "0.5.x",
        "loc": 7,
        "avg_cyc": 4.0,
        "max_cyc": 4,
        "sum_cyc": 4,
        "max_nest": 2,
        "coupling": 1,
    }
    assert features.solidity_version_constraints == [constraint]
    assert features.primary_solidity_version == "0.5.0"


def test_comment_only_and_quoted_pragma_changes_do_not_change_gower_profile(
    tmp_path: Path,
    fixed_asts: None,
) -> None:
    base = tmp_path / "Base.sol"
    decorated = tmp_path / "Decorated.sol"
    base.write_text(
        dedent(
            '''\
            pragma solidity ^0.8.20;
            contract Target {
                string constant NOTE = "";
                function run() public pure {}
            }
            '''
        ),
        encoding="utf-8",
    )
    decorated.write_text(
        dedent(
            '''\
            // pragma solidity ^0.4.0;
            pragma solidity ^0.8.20;
            /*
             * pragma solidity ^0.6.0;
             */
            contract Target {
                string constant NOTE = "pragma solidity ^0.7.0;";
                // function fake() public {}
                function run() public pure {}
            }
            '''
        ),
        encoding="utf-8",
    )

    base_runtime, base_offline = _profiles(base)
    decorated_runtime, decorated_offline = _profiles(decorated)

    assert base_runtime == base_offline
    assert decorated_runtime == decorated_offline
    assert decorated_runtime == base_runtime


def test_known_blockscan_wrapper_is_profile_only_and_matches_clean_source(
    tmp_path: Path,
    fixed_asts: None,
) -> None:
    clean = tmp_path / "Clean.sol"
    wrapped = tmp_path / "Wrapped.sol"
    source = """/** verified */
pragma solidity ^0.8.20;
contract Target {}
"""
    clean.write_text(source, encoding="utf-8")
    wrapped.write_text(
        "Contract Source Code (Solidity) IDEBlockscan copied outline"
        + source
        + " Contract Security Audit No Contract Security Audit Submitted ABI Bytecode",
        encoding="utf-8",
    )

    clean_runtime, clean_offline = _profiles(clean)
    wrapped_runtime, wrapped_offline = _profiles(wrapped)
    wrapped_features = analyze_target(str(wrapped))

    assert clean_runtime == clean_offline == wrapped_runtime == wrapped_offline
    assert wrapped_features.solidity_version_constraints == ["^0.8.20"]
    assert wrapped_features.primary_solidity_version == "0.8.20"
    assert wrapped.read_text(encoding="utf-8").startswith("Contract Source Code")


def test_blockscan_words_in_ordinary_solidity_are_not_normalized() -> None:
    source = '''pragma solidity ^0.8.20;
contract Target {
    string constant NOTE = "Contract Security Audit No Contract Security Audit";
}
'''

    assert _complexity.normalize_profile_source(source) == source


def test_blockscan_normalization_preserves_offsets_newlines_and_original() -> None:
    source = (
        "Contract Source Code (Solidity) copied\noutline\n"
        "/** verified */\npragma solidity ^0.8.20;\ncontract Target {}\n"
        " Contract Security Audit No Contract Security Audit Submitted ABI"
    )
    original = source[:]

    normalized = _complexity.normalize_profile_source(source)

    assert source == original
    assert len(normalized) == len(source)
    assert [index for index, char in enumerate(normalized) if char == "\n"] == [
        index for index, char in enumerate(source) if char == "\n"
    ]
    pragma_at = source.index("pragma solidity")
    comment_at = source.index("/** verified */")
    assert normalized[pragma_at:].startswith("pragma solidity ^0.8.20;")
    assert normalized[:comment_at].strip() == ""
    assert normalized[comment_at:pragma_at].strip() == "/** verified */"
    assert "Contract Security Audit No Contract Security Audit" not in normalized


def test_blockscan_normalization_requires_the_exact_leading_signature() -> None:
    source = (
        " // Contract Source Code (Solidity)\n"
        "pragma solidity ^0.8.20;\ncontract Target {}\n"
    )

    assert _complexity.normalize_profile_source(source) == source


def test_single_entrypoint_import_closure_matches_offline_builder(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    library = tmp_path / "lib" / "Lib.sol"
    library.parent.mkdir()
    library.write_text(
        "pragma solidity >=0.8.25 <0.9.0;\nlibrary Lib { function id() internal {} }\n",
        encoding="utf-8",
    )
    target = tmp_path / "Target.sol"
    target.write_text(
        'pragma solidity ^0.8.20;\nimport "./lib/Lib.sol";\ncontract Target {}\n',
        encoding="utf-8",
    )
    captured: list[tuple[str, ...]] = []

    def compile_sources(sources: dict[str, str]) -> _complexity.AstCompilation:
        captured.append(tuple(sources))
        return _complexity.AstCompilation(
            asts=tuple(
                {"nodeType": "SourceUnit", "nodes": []} for _name in sources
            ),
            solc_bucket="0.8.x",
            profiling_compiler="0.8.30",
        )

    monkeypatch.setattr(_complexity, "_compile_asts", compile_sources)

    features = analyze_target(str(target))
    runtime_profile = _target_phi(features)
    offline_profile = profile_file(target, dataset_root=tmp_path)

    assert runtime_profile is not None
    assert runtime_profile == {key: offline_profile[key] for key in GOWER_KEYS}
    assert captured == [
        ("Target.sol", "lib/Lib.sol"),
        ("Target.sol", "lib/Lib.sol"),
    ]
    assert features.gower_ast_available
    assert features.loc_total == 5
    assert features.solidity_version_constraints == [
        "^0.8.20",
        ">=0.8.25 <0.9.0",
    ]
    assert features.primary_solidity_version == "0.8.25"
    assert features.file_count == 2
    assert features.execution_input_count == 1
    assert features.is_multifile


def test_runtime_ast_failure_keeps_canonical_source_facts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = tmp_path / "Target.sol"
    target.write_text(
        dedent(
            '''\
            pragma solidity ^0.8.20;
            // comment-only line
            contract Target {
                /* another comment-only line */
            }
            '''
        ),
        encoding="utf-8",
    )

    def fail_ast(_sources) -> list[dict]:
        raise _complexity.AstExtractionError("fixture AST failure")

    monkeypatch.setattr(_complexity, "_compile_asts", fail_ast)

    features = analyze_target(str(target))

    assert features.gower_solc_bucket == "0.8.x"
    assert not features.gower_ast_available
    assert features.loc_total == 3
    assert (
        features.cyclomatic_avg,
        features.cyclomatic_max,
        features.cyclomatic_sum,
        features.max_nesting,
        features.contract_coupling,
    ) == (0.0, 0, 0, 0, 0)
    assert _target_phi(features) is None
    assert features.solidity_version_constraints == ["^0.8.20"]
    assert features.primary_solidity_version == "0.8.20"
    assert features.present_input_kinds == ["sol"]
    assert features.file_count == 1
    assert features.execution_input_count == 1

    with pytest.raises(_complexity.AstExtractionError, match="fixture AST failure"):
        profile_file(str(target))


def test_contract_features_default_gower_bucket_is_unknown() -> None:
    assert ContractFeatures().gower_solc_bucket == "unknown"
    assert not ContractFeatures().gower_ast_available
