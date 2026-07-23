from __future__ import annotations

import json
from pathlib import Path

import pytest

from toolrank.compilation import (
    CompilationBundleError,
    CompilationSettings,
    CompilerProcessResult,
    build_compilation_bundle,
    compute_bundle_id,
    validate_compilation_bundle,
)


def _compiler(tmp_path: Path, version: str) -> Path:
    path = tmp_path / f"solc-{version}"
    path.write_bytes(f"fake-solc-{version}".encode())
    path.chmod(0o755)
    return path


def _success_output(
    request: dict,
    *,
    contracts: dict[str, dict[str, dict]] | None = None,
    errors: list[dict] | None = None,
) -> str:
    if contracts is None:
        contracts = {}
        for source_name in request["sources"]:
            stem = Path(source_name).stem
            contracts[source_name] = {
                stem: {
                    "abi": [{"type": "constructor"}],
                    "evm": {
                        "bytecode": {"object": f"60{len(stem):02x}"},
                        "deployedBytecode": {"object": f"61{len(stem):02x}"},
                    },
                }
            }
    return json.dumps({"contracts": contracts, "errors": errors or []})


def _capturing_invoker(calls: list[dict], *, timed_out: bool = False):
    def invoke(binary: Path, request_bytes: bytes, timeout_seconds: float):
        request = json.loads(request_bytes)
        calls.append(
            {
                "binary": binary,
                "request": request,
                "timeout_seconds": timeout_seconds,
            }
        )
        if timed_out:
            return CompilerProcessResult(
                returncode=None,
                stdout="",
                stderr="compiler deadline exceeded",
                timed_out=True,
            )
        return CompilerProcessResult(
            returncode=0,
            stdout=_success_output(request),
            stderr="",
        )

    return invoke


def test_smartian_and_vandal_consume_one_shared_standard_json_compile(
    tmp_path: Path,
) -> None:
    source = tmp_path / "Main.sol"
    source.write_text("pragma solidity ^0.8.20; contract Main {}", encoding="utf-8")
    calls: list[dict] = []

    bundle = build_compilation_bundle(
        source,
        ["smartian", "vandal"],
        installed_compilers={"0.8.24": _compiler(tmp_path, "0.8.24")},
        compiler_invoker=_capturing_invoker(calls),
    )

    assert bundle.manifest.status == "READY"
    assert len(calls) == 1
    selection = calls[0]["request"]["settings"]["outputSelection"]["*"]["*"]
    assert selection == ["abi", "evm.bytecode.object", "evm.deployedBytecode.object"]
    smartian = bundle.route_for("smartian", "Main.sol")
    vandal = bundle.route_for("vandal", "Main.sol")
    assert smartian is not None and vandal is not None
    assert smartian.bundle_id == vandal.bundle_id == bundle.manifest.bundle_id
    assert smartian.components == ["abi", "creation_bytecode"]
    assert vandal.components == ["runtime_bytecode"]
    contract = bundle.contracts[smartian.fully_qualified_contract]
    assert contract.abi == [{"type": "constructor"}]
    assert contract.creation_bytecode
    assert contract.runtime_bytecode


@pytest.mark.parametrize(
    ("tool", "expected"),
    [
        ("smartian", ["abi", "evm.bytecode.object"]),
        ("vandal", ["evm.deployedBytecode.object"]),
    ],
)
def test_compile_bundle_requests_only_components_with_real_consumers(
    tmp_path: Path,
    tool: str,
    expected: list[str],
) -> None:
    source = tmp_path / "Main.sol"
    source.write_text("pragma solidity ^0.8.20; contract Main {}", encoding="utf-8")
    calls: list[dict] = []

    bundle = build_compilation_bundle(
        source,
        [tool],
        installed_compilers={"0.8.24": _compiler(tmp_path, "0.8.24")},
        compiler_invoker=_capturing_invoker(calls),
    )

    assert calls[0]["request"]["settings"]["outputSelection"]["*"]["*"] == expected
    assert "ast" not in json.dumps(bundle.model_dump(mode="json")).lower()
    assert bundle.manifest.requested_components == (
        ["abi", "creation_bytecode"] if tool == "smartian" else ["runtime_bytecode"]
    )


def test_source_only_plan_skips_decorative_compilation(tmp_path: Path) -> None:
    source = tmp_path / "Main.sol"
    source.write_text("pragma solidity ^0.8.20; contract Main {}", encoding="utf-8")
    calls: list[dict] = []

    bundle = build_compilation_bundle(
        source,
        ["slither", "solhint"],
        installed_compilers={"0.8.24": _compiler(tmp_path, "0.8.24")},
        compiler_invoker=_capturing_invoker(calls),
    )

    assert calls == []
    assert bundle.manifest.status == "NOT_APPLICABLE"
    assert bundle.manifest.consumer_routes == []
    assert bundle.tool_consumption["slither"].mode == "SOURCE_ONLY"
    assert bundle.tool_consumption["solhint"].mode == "SOURCE_ONLY"


def test_explicit_bytecode_inputs_do_not_trigger_compilation(tmp_path: Path) -> None:
    (tmp_path / "Deploy.bin").write_text("6000", encoding="utf-8")
    (tmp_path / "Live.runtime").write_text("6001", encoding="utf-8")
    calls: list[dict] = []

    bundle = build_compilation_bundle(
        tmp_path,
        ["vandal", "mythril"],
        installed_compilers={"0.8.24": _compiler(tmp_path, "0.8.24")},
        compiler_invoker=_capturing_invoker(calls),
    )

    assert calls == []
    assert bundle.manifest.status == "NOT_APPLICABLE"
    assert all(item.mode == "NOT_APPLICABLE" for item in bundle.tool_consumption.values())


def test_execution_solc_is_one_exact_common_version(tmp_path: Path) -> None:
    source = tmp_path / "Main.sol"
    source.write_text(
        "pragma solidity >=0.8.20 <0.8.30; contract Main {}",
        encoding="utf-8",
    )
    calls: list[dict] = []
    compilers = {
        version: _compiler(tmp_path, version)
        for version in ("0.8.19", "0.8.24", "0.8.30")
    }

    bundle = build_compilation_bundle(
        source,
        ["smartian", "vandal"],
        selected_tool_solc_ranges={
            "smartian": "0.8.0-0.8.25",
            "vandal": "0.7.0-0.8.99",
        },
        installed_compilers=compilers,
        compiler_invoker=_capturing_invoker(calls),
    )

    assert bundle.manifest.status == "READY"
    assert bundle.manifest.compiler_version == "0.8.24"
    assert calls[0]["binary"] == compilers["0.8.24"]

    no_common = build_compilation_bundle(
        source,
        ["smartian"],
        selected_tool_solc_ranges={"smartian": "0.4.0-0.4.99"},
        installed_compilers=compilers,
        compiler_invoker=lambda *_args: pytest.fail("compiler must not launch"),
    )
    assert no_common.manifest.status == "FAILED"
    assert no_common.manifest.failure_reason is not None
    assert no_common.manifest.failure_reason.code == "NO_COMMON_EXECUTION_SOLC"


def test_compile_bundle_uses_unmodified_safe_import_closure(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    (project / "lib").mkdir()
    main_text = (
        'pragma solidity ^0.8.20; import "./lib/Lib.sol"; '
        "contract Main { string constant S = 'pragma solidity 0.4.0;'; }"
    )
    lib_text = "pragma solidity ^0.8.20; library Lib {}"
    main = project / "Main.sol"
    main.write_text(main_text, encoding="utf-8")
    (project / "lib" / "Lib.sol").write_text(lib_text, encoding="utf-8")
    (project / "Unrelated.sol").write_text("contract Unrelated {}", encoding="utf-8")
    (project / ".env").write_text("SECRET=not-source", encoding="utf-8")
    outside = tmp_path / "Outside.sol"
    outside.write_text("contract Outside {}", encoding="utf-8")
    (project / "Escape.sol").symlink_to(outside)
    calls: list[dict] = []

    bundle = build_compilation_bundle(
        main,
        ["smartian"],
        installed_compilers={"0.8.24": _compiler(tmp_path, "0.8.24")},
        compiler_invoker=_capturing_invoker(calls),
    )

    sources = calls[0]["request"]["sources"]
    assert list(sources) == ["Main.sol", "lib/Lib.sol"]
    assert sources["Main.sol"]["content"] == main_text
    assert sources["lib/Lib.sol"]["content"] == lib_text
    assert bundle.manifest.entrypoints == ["Main.sol"]


def test_multi_contract_output_requires_deterministic_contract_identity(
    tmp_path: Path,
) -> None:
    source = tmp_path / "Main.sol"
    source.write_text("pragma solidity ^0.8.20; contract Main {}", encoding="utf-8")
    compiler = _compiler(tmp_path, "0.8.24")

    def output_with(contracts: dict[str, dict[str, dict]]):
        def invoke(_binary, request_bytes, _timeout):
            request = json.loads(request_bytes)
            return CompilerProcessResult(
                returncode=0,
                stdout=_success_output(request, contracts=contracts),
                stderr="",
            )

        return invoke

    artifact = {
        "abi": [],
        "evm": {
            "bytecode": {"object": "6000"},
            "deployedBytecode": {"object": "6001"},
        },
    }
    stem_match = build_compilation_bundle(
        source,
        ["smartian", "vandal"],
        installed_compilers={"0.8.24": compiler},
        compiler_invoker=output_with(
            {"Main.sol": {"Other": artifact, "Main": artifact}}
        ),
    )
    assert stem_match.route_for("smartian", "Main.sol").fully_qualified_contract == "Main.sol:Main"

    ambiguous = build_compilation_bundle(
        source,
        ["smartian"],
        installed_compilers={"0.8.24": compiler},
        compiler_invoker=output_with(
            {"Main.sol": {"Alpha": artifact, "Beta": artifact}}
        ),
    )
    assert ambiguous.manifest.status == "FAILED"
    assert ambiguous.manifest.failure_reason.code == "AMBIGUOUS_TARGET_CONTRACT"

    missing = build_compilation_bundle(
        source,
        ["smartian", "vandal"],
        installed_compilers={"0.8.24": compiler},
        compiler_invoker=output_with(
            {
                "Main.sol": {
                    "Main": {
                        "abi": [],
                        "evm": {
                            "bytecode": {"object": ""},
                            "deployedBytecode": {"object": "6001"},
                        },
                    }
                }
            }
        ),
    )
    assert missing.manifest.status == "FAILED"
    assert missing.manifest.failure_reason.code == "MISSING_REQUESTED_ARTIFACT"


def test_compile_failure_and_timeout_are_typed(tmp_path: Path) -> None:
    source = tmp_path / "Main.sol"
    source.write_text("pragma solidity ^0.8.20; contract Main {}", encoding="utf-8")
    compiler = _compiler(tmp_path, "0.8.24")

    def diagnostic_error(_binary, _request, _timeout):
        return CompilerProcessResult(
            returncode=0,
            stdout=json.dumps(
                {
                    "contracts": {},
                    "errors": [
                        {
                            "severity": "error",
                            "errorCode": "1234",
                            "formattedMessage": "TypeError: broken",
                        }
                    ],
                }
            ),
            stderr="",
        )

    failed = build_compilation_bundle(
        source,
        ["smartian"],
        installed_compilers={"0.8.24": compiler},
        compiler_invoker=diagnostic_error,
    )
    assert failed.manifest.status == "FAILED"
    assert failed.manifest.failure_reason.code == "COMPILER_DIAGNOSTIC_ERROR"

    timed_out = build_compilation_bundle(
        source,
        ["vandal"],
        installed_compilers={"0.8.24": compiler},
        compiler_invoker=_capturing_invoker([], timed_out=True),
    )
    assert timed_out.manifest.status == "FAILED"
    assert timed_out.manifest.failure_reason.code == "COMPILATION_TIMEOUT"


def test_optimizer_policy_and_output_are_digest_bound(tmp_path: Path) -> None:
    source = tmp_path / "Main.sol"
    source.write_text("pragma solidity ^0.8.20; contract Main {}", encoding="utf-8")
    calls: list[dict] = []
    bundle = build_compilation_bundle(
        source,
        ["smartian", "vandal"],
        installed_compilers={"0.8.24": _compiler(tmp_path, "0.8.24")},
        compiler_invoker=_capturing_invoker(calls),
    )

    settings = bundle.manifest.settings
    assert settings == CompilationSettings(
        optimizer_enabled=False,
        optimizer_runs=None,
        via_ir=False,
        evm_version=None,
        remappings=[],
    )
    assert calls[0]["request"]["settings"]["optimizer"] == {"enabled": False}
    assert "evmVersion" not in calls[0]["request"]["settings"]
    assert bundle.manifest.bundle_id == compute_bundle_id(bundle)
    assert compute_bundle_id(
        bundle.model_copy(
            update={
                "manifest": bundle.manifest.model_copy(
                    update={
                        "settings": settings.model_copy(
                            update={"optimizer_enabled": True, "optimizer_runs": 200}
                        )
                    }
                )
            }
        )
    ) != bundle.manifest.bundle_id


def test_source_digest_mismatch_invalidates_ready_bundle(tmp_path: Path) -> None:
    source = tmp_path / "Main.sol"
    source.write_text("pragma solidity ^0.8.20; contract Main {}", encoding="utf-8")
    bundle = build_compilation_bundle(
        source,
        ["smartian"],
        installed_compilers={"0.8.24": _compiler(tmp_path, "0.8.24")},
        compiler_invoker=_capturing_invoker([]),
    )
    source.write_text("pragma solidity ^0.8.20; contract Main { uint x; }", encoding="utf-8")

    with pytest.raises(CompilationBundleError) as exc_info:
        validate_compilation_bundle(bundle, source, ["smartian"])

    assert exc_info.value.code == "SOURCE_DIGEST_MISMATCH"
