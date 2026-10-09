"""Package an already compiled ZW3D plugin without a C++ toolchain.

This creates a validated .zwplug archive, NOT a self-installing EXE. The
current HubManager cannot import .zwplug files directly. To deliver a normal
installer, use build_plugin.py on a compatible Windows build machine.
"""
from __future__ import annotations

import argparse
import json
import os
import tempfile
from pathlib import Path

from package_lib import (PackageError, build_package, read_json, read_payload,
                         require, validate_manifest, validate_package)


def package_existing(project: Path, output: Path, sdk: Path | None = None) -> dict:
    project = project.resolve()
    payload = project / "payload"
    output = output.resolve()
    require(not output.is_relative_to(payload),
            "output directory must not be inside project/payload")
    manifest = validate_manifest(read_json((project / "plugin.json").read_bytes(), "plugin.json"))
    files = read_payload(payload)
    require(manifest["entry"] in files,
            "prebuilt DLL/EXE entry is missing from payload; compile it first")
    filename = f"{manifest['id']}-{manifest['version']}.zwplug"
    output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".zwplug-stage-", dir=output) as temporary:
        stage = Path(temporary) / filename
        report = build_package(manifest, files, stage, sdk)
        check = validate_package(stage, sdk)
        published = output / filename
        if published.exists():
            require(published.is_file() and not published.is_symlink(),
                    "existing output is not an ordinary file")
            require(published.read_bytes() == stage.read_bytes(),
                    "same plugin version has different content; increase version before publishing")
        else:
            os.replace(stage, published)
    return {"status": "PASS", "package": str(published),
            "installerGenerated": False, "hostApisChecked": sdk is not None,
            "packageValidation": check, "sha256": report["sha256"]}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("project", type=Path, help="Folder containing plugin.json and prebuilt payload/")
    parser.add_argument("--out", type=Path, required=True, help="Output directory (outside payload)")
    parser.add_argument("--sdk", type=Path, help="Optional ZW3D 2027 host path for API export checks")
    args = parser.parse_args()
    try:
        result = package_existing(args.project, args.out, args.sdk)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (OSError, PackageError, ValueError) as error:
        print(json.dumps({"status": "FAIL", "error": str(error)}, ensure_ascii=False))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
