"""Package an already compiled ZW3D plugin without a C++ toolchain.

Creates a validated .zwplug archive. On Windows, --installer also creates a
self-contained installer EXE by filling the frozen template. Neither route
compiles business code or requires MinGW; --sdk adds optional API checks.
"""
from __future__ import annotations

import argparse
import json
import tempfile
from pathlib import Path

from package_lib import (PackageError, build_package, read_json, read_payload,
                         require, validate_manifest, validate_package)
from build_plugin import DEFAULT_RUNTIME, publish_artifacts
from inspect_installer import inspect
from prebuilt_installer import create_installer


def package_existing(project: Path, output: Path, sdk: Path | None = None,
                     *, installer: bool = False) -> dict:
    project = project.resolve()
    payload = project / "payload"
    output = output.resolve()
    require(not output.is_relative_to(payload),
            "output directory must not be inside project/payload")
    manifest = validate_manifest(read_json((project / "plugin.json").read_bytes(), "plugin.json"))
    files = read_payload(payload)
    require(manifest["entry"] in files,
            "prebuilt DLL/EXE entry is missing from payload; compile it first")
    stem = f"{manifest['id']}-{manifest['version']}"
    filename = stem + ".zwplug"
    output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".zwplug-stage-", dir=output) as temporary:
        folder = Path(temporary)
        stage = folder / filename
        report = build_package(manifest, files, stage, sdk)
        check = validate_package(stage, sdk)
        artifacts = {filename: stage}
        result = {"status": "PASS", "package": str(output / filename),
                  "installerGenerated": installer, "hostApisChecked": sdk is not None,
                  "compilerInvoked": False, "packageValidation": check, "sha256": report["sha256"]}
        if installer:
            executable = folder / (stem + "-setup.exe")
            result.update(create_installer(manifest, files, executable))
            result["installerValidation"] = inspect(executable, stage, DEFAULT_RUNTIME, sdk)
            result["installer"] = str(output / executable.name)
            artifacts[executable.name] = executable
        # Check the whole set before publishing either file. Never silently change
        # an already delivered version, including its installer code/resources.
        for name, source in artifacts.items():
            published = output / name
            if published.exists() or published.is_symlink():
                require(published.is_file() and not published.is_symlink(),
                        "existing output is not an ordinary file")
                require(published.read_bytes() == source.read_bytes(),
                        "same plugin version has different content; increase version before publishing")
        publish_artifacts(output, artifacts)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("project", type=Path, help="Folder containing plugin.json and prebuilt payload/")
    parser.add_argument("--out", type=Path, required=True, help="Output directory (outside payload)")
    parser.add_argument("--sdk", type=Path, help="Optional ZW3D 2027 host path for API export checks")
    parser.add_argument("--installer", action="store_true",
                        help="Also create an installer EXE from the frozen template (Windows, no MinGW)")
    args = parser.parse_args()
    try:
        result = package_existing(args.project, args.out, args.sdk, installer=args.installer)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (OSError, PackageError, ValueError) as error:
        print(json.dumps({"status": "FAIL", "error": str(error)}, ensure_ascii=False))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
