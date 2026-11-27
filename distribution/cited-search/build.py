"""Assemble a wheel-only, offline install kit for the builder's Python and platform."""

import hashlib
import json
import os
import shutil
import subprocess
import sys
import sysconfig
from pathlib import Path
from tempfile import TemporaryDirectory
from zipfile import ZIP_STORED, ZipFile, ZipInfo

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
RESOURCES = ROOT / "packages/harness/src/brain_harness/workflows/cited_search"
MANIFEST = json.loads((RESOURCES / "manifest.json").read_text())


def run(*args: str | Path) -> None:
    subprocess.run(args, cwd=ROOT, check=True, env={**os.environ, "SOURCE_DATE_EPOCH": "315532800"})


def export(lock: Path, *selection: str) -> None:
    run(
        "uv",
        "export",
        "--locked",
        "--no-emit-workspace",
        "--no-header",
        "--no-annotate",
        *selection,
        "--output-file",
        lock,
        "--quiet",
    )


def build() -> Path:
    target = f"{sys.implementation.cache_tag}-{sysconfig.get_platform()}"
    label = f"cited-search-{MANIFEST['version']}-{target}"
    output = ROOT / "dist"
    output.mkdir(exist_ok=True)
    with TemporaryDirectory(dir=output) as work:
        stage = Path(work)
        kit = stage / label
        wheels = kit / "wheels"
        wheels.mkdir(parents=True)
        build_lock = stage / "build.txt"
        export(build_lock, "--only-group", "wheel-build")
        for pkg in MANIFEST["runtime"]["packages"]:
            run(
                "uv",
                "build",
                "--wheel",
                "--package",
                pkg,
                "--python",
                sys.executable,
                "--build-constraints",
                build_lock,
                "--require-hashes",
                "--no-create-gitignore",
                "--out-dir",
                wheels,
            )
        runtime_lock = stage / "runtime.txt"
        export(runtime_lock, "--package", "brain-harness", "--no-dev")
        run(
            sys.executable,
            "-m",
            "pip",
            "--disable-pip-version-check",
            "download",
            "--only-binary=:all:",
            "--no-deps",
            "--require-hashes",
            "-r",
            runtime_lock,
            "--dest",
            wheels,
        )
        requirements = []
        for wheel in sorted(wheels.glob("*.whl")):
            name, version, _ = wheel.name.split("-", 2)
            with wheel.open("rb") as f:
                digest = hashlib.file_digest(f, "sha256").hexdigest()
            requirements.append(f"{name}=={version} --hash=sha256:{digest}\n")
        (kit / "requirements.txt").write_bytes("".join(requirements).encode())
        shutil.copyfile(HERE / "README.md", kit / "README.md")
        shutil.copyfile(RESOURCES / "manifest.json", kit / "manifest.json")
        archive = stage / f"{label}.zip"
        with ZipFile(archive, "w", compression=ZIP_STORED) as dest:
            for path in sorted(kit.rglob("*")):
                if path.is_file():
                    entry = ZipInfo(path.relative_to(stage).as_posix(), (1980, 1, 1, 0, 0, 0))
                    entry.create_system = 3
                    entry.external_attr = 0o100644 << 16
                    dest.writestr(entry, path.read_bytes())
        return archive.replace(output / archive.name)


if __name__ == "__main__":
    print(build())
