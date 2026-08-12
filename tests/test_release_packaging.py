from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import zipfile


ROOT = Path(__file__).resolve().parents[1]


def _python_with_wheel_backend() -> str:
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import setuptools.build_meta, wheel",
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, (
        "wheel regression requires setuptools and wheel in the test environment: "
        + result.stderr
    )
    return sys.executable


def test_fresh_wheel_contains_default_toolcards_and_cli_resolves_them(
    tmp_path: Path,
) -> None:
    build_python = _python_with_wheel_backend()
    source_root = tmp_path / "source"
    source_root.mkdir()
    for filename in ("pyproject.toml", "README.md"):
        shutil.copy2(ROOT / filename, source_root / filename)
    for package in ("toolrank", "toolcards"):
        shutil.copytree(
            ROOT / package,
            source_root / package,
            ignore=shutil.ignore_patterns("__pycache__", "*.pyc", ".private"),
        )
    private_payloads = {
        "performance_db.json": "PRIVATE_PERFORMANCE_SENTINEL",
        "contract_profiles.json": "PRIVATE_PROFILE_SENTINEL",
        "passage_store.json": "PRIVATE_PASSAGE_SENTINEL",
        "vector_index/index.json": "PRIVATE_VECTOR_SENTINEL",
        "recovery_source.json": "PRIVATE_RECOVERY_SENTINEL",
        "credentials.json": "PRIVATE_CREDENTIAL_SENTINEL",
    }
    for relative_path, sentinel in private_payloads.items():
        private_path = source_root / "toolcards" / ".private" / relative_path
        private_path.parent.mkdir(parents=True, exist_ok=True)
        private_path.write_text(sentinel, encoding="utf-8")
    wheel_dir = tmp_path / "wheel"
    wheel_dir.mkdir()
    build = subprocess.run(
        [
            build_python,
            "-c",
            (
                "import pathlib, setuptools.build_meta as backend, sys; "
                "print(backend.build_wheel(str(pathlib.Path(sys.argv[1]).resolve())))"
            ),
            str(wheel_dir),
        ],
        cwd=source_root,
        capture_output=True,
        text=True,
    )
    assert build.returncode == 0, build.stdout + build.stderr

    wheels = list(wheel_dir.glob("lakes-*.whl"))
    assert len(wheels) == 1
    expected_toolcard_files = {
        "toolcards/__init__.py",
        "toolcards/vector_index/index.json",
    } | {
        f"toolcards/{path.name}" for path in (ROOT / "toolcards").glob("*.json")
    }
    with zipfile.ZipFile(wheels[0]) as archive:
        names = set(archive.namelist())
        packaged_toolcard_files = {
            name
            for name in names
            if name.startswith("toolcards/") and not name.endswith("/")
        }
        assert packaged_toolcard_files == expected_toolcard_files
        archive_payload = b"".join(
            archive.read(name) for name in sorted(names) if not name.endswith("/")
        )
        for sentinel in private_payloads.values():
            assert sentinel.encode("utf-8") not in archive_payload

        installed = tmp_path / "installed"
        archive.extractall(installed)

    probe = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "from pathlib import Path; "
                "from toolrank.cli import _DEFAULT_TOOLCARDS_DIR; "
                "root=Path(_DEFAULT_TOOLCARDS_DIR); "
                "assert root == Path(__import__('toolcards').__file__).parent; "
                "assert (root/'performance_db.json').is_file(); "
                "assert (root/'contract_profiles.json').is_file(); "
                "assert (root/'contract_profile_manifest.json').is_file(); "
                "assert (root/'passage_store.json').is_file(); "
                "assert (root/'vector_index'/'index.json').is_file()"
            ),
        ],
        cwd=tmp_path,
        env={
            **os.environ,
            "PYTHONPATH": str(installed),
        },
        capture_output=True,
        text=True,
    )
    assert probe.returncode == 0, probe.stdout + probe.stderr


def test_public_profile_artifacts_are_manifest_and_audit_digest_bound() -> None:
    manifest_path = ROOT / "toolcards" / "contract_profile_manifest.json"
    profile_path = ROOT / "toolcards" / "contract_profiles.json"
    audit_path = ROOT / "toolcards" / "contract_profiles_migration_audit.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    profile = json.loads(profile_path.read_text(encoding="utf-8"))
    audit = json.loads(audit_path.read_text(encoding="utf-8"))

    included_names = [
        row["name"] for row in manifest["datasets"] if row["include"]
    ]
    excluded_rows = [row for row in manifest["datasets"] if not row["include"]]
    assert all(row.get("duplicate_of") in included_names for row in excluded_rows)
    assert profile["_meta"]["dataset_names"] == included_names
    assert profile["_meta"]["manifest_digest"] == hashlib.sha256(
        manifest_path.read_bytes()
    ).hexdigest()
    assert audit["replay_provenance"]["rebuilt_artifact_sha256"] == (
        hashlib.sha256(profile_path.read_bytes()).hexdigest()
    )


def test_docker_builds_smartian_from_tracked_source_with_pinned_dependencies() -> None:
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    dockerignore = (ROOT / ".dockerignore").read_text(encoding="utf-8")
    gitignore = (ROOT / ".gitignore").read_text(encoding="utf-8")
    smartian_runner = (
        ROOT / "docker" / "runners" / "run_smartian.py"
    ).read_text(encoding="utf-8")
    gptscan_requirements = (
        ROOT / "docker" / "vendor" / "gptscan" / "requirements-docker.txt"
    ).read_text(encoding="utf-8")
    dockerignore_entries = {
        line.strip()
        for line in dockerignore.splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    }

    assert "build/" in dockerignore_entries
    assert "docker/vendor/smartian/build/" in dockerignore
    assert "toolcards/.private/" in dockerignore
    assert "toolcards/.private/" in gitignore
    tracked_private = subprocess.run(
        ["git", "ls-files", "--", "toolcards/.private"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    assert tracked_private.stdout == ""
    assert "ARG LAKES_IMAGE_PLATFORM=$BUILDPLATFORM" in dockerfile
    assert "ARG SMARTIAN_REF=" in dockerfile
    assert "ARG FALCON_REF=" in dockerfile
    assert "FROM --platform=$BUILDPLATFORM" in dockerfile
    assert "git clone --no-checkout" in dockerfile
    assert "nethermind EVMAnalysis/B2R2" in dockerfile
    assert "src/Dirichlet src/rocksdb-sharp" in dockerfile
    assert "submodule update --init --recursive" not in dockerfile
    assert "--runtime \"${smartian_runtime}\"" in dockerfile
    assert "COPY --from=smartian-builder" in dockerfile
    assert "rm -rf /tmp/smartian-build" in dockerfile
    assert "DOTNET_SYSTEM_GLOBALIZATION_INVARIANT=1" in dockerfile
    assert (
        "DOTNET_SYSTEM_GLOBALIZATION_INVARIANT=1 \\\n"
        "        /opt/dotnet/dotnet"
    ) in dockerfile
    assert "dpkg --add-architecture amd64" in dockerfile
    assert "libc6:amd64 libstdc++6:amd64" in dockerfile
    assert "solc --version" in dockerfile
    assert "qemu-user-static" not in dockerfile
    assert "falcon_z3_version=4.13.0.0" in dockerfile
    assert "git -C /tmp/falcon-metatrust checkout --detach" in dockerfile
    assert "pip install --no-deps" in dockerfile
    assert "pip install --retries 5 --timeout 120 -e ." in dockerfile
    assert "z3-solver==4.11.2.0" in gptscan_requirements
    assert "crytic-compile==0.3.3" in gptscan_requirements
    assert "pysha3==1.0.2" in gptscan_requirements
    assert "falcon-analyzer@git+" not in gptscan_requirements
    assert '_ensure_executable(args.dotnet, "--info")' in smartian_runner
    assert '_ensure_executable(args.dotnet, "--version")' not in smartian_runner
    assert "docker/vendor/smartian/src" in dockerfile
    assert (
        "dotnet build /work/docker/vendor/smartian/src/Smartian.fsproj"
        in dockerfile
    )
    assert "/tmp/smartian-build/src/Smartian.fsproj" not in dockerfile
    assert "test -s /work/docker/vendor/smartian/build/Smartian.dll" in dockerfile
    assert (
        "test -s /work/docker/vendor/smartian/src/Agent/AttackerContract.bin"
        in dockerfile
    )
    assert "/Users/" not in dockerfile
    assert "COPY docker/vendor/smartian/build" not in dockerfile

    project = (
        ROOT / "docker" / "vendor" / "smartian" / "src" / "Smartian.fsproj"
    ).read_text(encoding="utf-8")
    assert "..\\nethermind\\" in project
    assert "..\\EVMAnalysis\\" in project
    assert "Nethermind.Logging.csproj" in project
    assert "Nethermind.Store.csproj" in project
    assert 'PackageReference Include="MathNet.Numerics.FSharp"' in project
    assert not (ROOT / "docker" / "vendor" / "smartian" / "nethermind").exists()
    assert not (ROOT / "docker" / "vendor" / "smartian" / "EVMAnalysis").exists()
