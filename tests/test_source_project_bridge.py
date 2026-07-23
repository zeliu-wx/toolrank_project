from __future__ import annotations

from pathlib import Path

from toolrank.smartbugs_project import select_project_solc_version
from toolrank.source_project import copy_dependency_tree, source_entrypoints


def test_bridge_stages_only_entrypoint_import_closure_without_symlinks(
    tmp_path: Path,
) -> None:
    project = tmp_path / "project"
    contracts = project / "contracts"
    libraries = project / "lib"
    contracts.mkdir(parents=True)
    libraries.mkdir()
    entrypoint = contracts / "Main.sol"
    dependency = libraries / "Lib.sol"
    unrelated = contracts / "Unrelated.sol"
    entrypoint.write_text(
        'pragma solidity ^0.8.20; import "../lib/Lib.sol"; '
        'import "../.env"; contract Main {}',
        encoding="utf-8",
    )
    dependency.write_text(
        "pragma solidity ^0.8.20; library Lib {}",
        encoding="utf-8",
    )
    unrelated.write_text(
        "pragma solidity ^0.8.20; contract Unrelated {}",
        encoding="utf-8",
    )
    (project / ".env").write_text(
        "SECRET=must-not-cross-boundary",
        encoding="utf-8",
    )
    outside = tmp_path / "Outside.sol"
    outside.write_text("contract Outside {}", encoding="utf-8")
    (libraries / "Outside.sol").symlink_to(outside)
    destination = tmp_path / "staged"

    copy_dependency_tree(entrypoint, project, destination)

    assert (destination / "contracts" / "Main.sol").is_file()
    assert (destination / "lib" / "Lib.sol").is_file()
    assert not (destination / "contracts" / "Unrelated.sol").exists()
    assert not (destination / "lib" / "Outside.sol").exists()
    assert not (destination / ".env").exists()


def test_source_entrypoints_do_not_execute_imported_dependencies(
    tmp_path: Path,
) -> None:
    project = tmp_path / "project"
    contracts = project / "contracts"
    libraries = project / "lib"
    contracts.mkdir(parents=True)
    libraries.mkdir()
    entrypoint = contracts / "Main.sol"
    dependency = libraries / "Lib.sol"
    entrypoint.write_text(
        'import {Lib} from "../lib/Lib.sol"; contract Main {}',
        encoding="utf-8",
    )
    dependency.write_text("library Lib {}", encoding="utf-8")

    assert source_entrypoints([entrypoint, dependency], project) == [
        entrypoint.resolve()
    ]


def test_source_entrypoints_cover_isolated_import_cycle_and_normal_root(
    tmp_path: Path,
) -> None:
    project = tmp_path / "project"
    project.mkdir()
    normal = project / "Main.sol"
    cycle_a = project / "A.sol"
    cycle_b = project / "B.sol"
    normal.write_text("contract Main {}", encoding="utf-8")
    cycle_a.write_text('import "./B.sol"; contract A {}', encoding="utf-8")
    cycle_b.write_text('import "./A.sol"; contract B {}', encoding="utf-8")

    entrypoints = source_entrypoints([normal, cycle_a, cycle_b], project)

    assert entrypoints == [cycle_a.resolve(), normal.resolve()]


def test_quoted_fake_import_does_not_hide_an_independent_source_root(
    tmp_path: Path,
) -> None:
    project = tmp_path / "project"
    project.mkdir()
    main = project / "Main.sol"
    independent = project / "Independent.sol"
    main.write_text(
        "contract Main { "
        "string constant FAKE = 'import \"./Independent.sol\";';"
        " }",
        encoding="utf-8",
    )
    independent.write_text("contract Independent {}", encoding="utf-8")

    assert source_entrypoints([main, independent], project) == [
        independent.resolve(),
        main.resolve(),
    ]


def test_project_bridge_compiler_selection_uses_full_constraint_intersection() -> None:
    assert select_project_solc_version(
        ["^0.8.0", "<0.8.20"],
        {"0.8.19", "0.8.20", "0.8.30"},
    ) == "0.8.19"
    assert select_project_solc_version(
        ["^0.8.20"],
        {"0.8.19", "0.8.30"},
    ) == "0.8.30"
    assert select_project_solc_version(
        ["0.8.20"],
        {"0.8.19", "0.8.30"},
    ) is None
