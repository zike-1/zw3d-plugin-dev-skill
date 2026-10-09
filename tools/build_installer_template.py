"""Maintainer-only: build the reusable installer once, without the ZW3D SDK.

Plugin authors use package_existing.py --installer and never run this tool.
Build into a new output directory; frozen templates must not be overwritten.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import shutil
import tempfile

from build_plugin import (ROOT, SYSTEM_LIBRARIES, application_icon,
                          application_manifest, compiler_settings, run, static_runtime)
from package_lib import PE, PackageError, canonical_json, require, sha256


def build_template(toolchain: Path, output: Path) -> dict:
    require(not output.exists(), "template output exists; use a new directory")
    with tempfile.TemporaryDirectory(prefix="zwplug_template_") as temporary:
        stage = Path(temporary)
        require(str(stage).isascii(), "set TEMP/TMP to an ASCII directory for this compiler")
        compiler, resource_compiler, flags, env = compiler_settings(toolchain, stage)
        framework = stage / "framework"
        shutil.copytree(ROOT / "framework", framework)
        icon = (framework / "default-icon.png").read_bytes()
        (stage / "setup.manifest").write_text(application_manifest(), encoding="utf-8")
        (stage / "setup.ico").write_bytes(application_icon(icon))
        (stage / "default-icon.bin").write_bytes(icon)
        (stage / "template.rc").write_text('#include <windows.h>\nLANGUAGE 9, 1\n'
            '1 RT_MANIFEST "setup.manifest"\n101 ICON "setup.ico"\n'
            '903 RCDATA "default-icon.bin"\n', encoding="utf-8")
        run([resource_compiler, "-i", "template.rc", "-o", "template.o"], stage, env=env)
        executable = stage / "SetupTemplate.exe"
        run([compiler, *flags, "-s", "-mwindows", str(framework / "setup.cpp"),
             str(stage / "template.o"), *SYSTEM_LIBRARIES, "-o", str(executable)], stage, env=env)
        static_runtime(executable)
        require(not PE(executable.read_bytes()).is_dll, "template is not an EXE")
        checksums = {"SetupTemplate.exe": sha256(executable.read_bytes())}
        (stage / "checksums.json").write_bytes(canonical_json(checksums))
        output.mkdir(parents=True)
        for name in ("SetupTemplate.exe", "checksums.json"):
            shutil.copy2(stage / name, output / name)
        return {"status": "PASS", "output": str(output), "checksums": checksums}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--toolchain", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    try:
        print(json.dumps(build_template(args.toolchain.resolve(), args.out.resolve()), indent=2))
        return 0
    except (OSError, PackageError) as error:
        print(json.dumps({"status": "FAIL", "error": str(error)}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
