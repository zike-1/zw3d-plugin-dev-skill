"""Compile a plugin and its self-contained installer; recipients need no Python."""
from __future__ import annotations

import argparse
import json
import os
import shutil
import struct
import subprocess
import tempfile
from pathlib import Path

from package_lib import (PE, PackageError, build_package, canonical_json, descriptor,
                         read_json, read_payload, require, sha256, validate_manifest,
                         validate_package, required_apis, validate_icon)

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_RUNTIME = ROOT / "runtime" / "1.1.3"
FRAMEWORK_VERSION = "1.1.3"
SYSTEM_LIBRARIES = ["-lcomctl32", "-lshell32", "-lole32", "-loleaut32", "-ladvapi32",
                    "-lshlwapi", "-lbcrypt", "-lversion", "-luuid", "-luser32", "-lgdi32", "-lcomdlg32"]


def run(arguments: list[str], cwd: Path) -> None:
    result = subprocess.run(arguments, cwd=cwd, text=True, encoding="utf-8", errors="replace",
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    if result.returncode:
        raise PackageError(f"command failed ({result.returncode}): {' '.join(arguments)}\n{result.stdout}")


def compiler_settings(toolchain: Path, stage: Path) -> tuple[str, str, list[str]]:
    compiler = toolchain / "bin" / "g++.exe"
    resource = toolchain / "bin" / "windres.exe"
    require(compiler.is_file() and resource.is_file(), "MinGW g++/windres not found")
    # MinGW embeds a default manifest unless removed. Supply our own asInvoker manifest.
    dump = subprocess.run([str(compiler), "-dumpspecs"], check=True, stdout=subprocess.PIPE,
                          text=True, encoding="utf-8").stdout
    specs = stage / "compiler.specs"
    specs.write_text(dump.replace("default-manifest.o%s", ""), encoding="utf-8")
    flags = ["-std=c++17", "-O2", "-Wall", "-Wextra", "-m64", "-finput-charset=UTF-8",
             "-fexec-charset=UTF-8", "-municode", "-DUNICODE", "-D_UNICODE",
             "-static", "-static-libgcc", "-static-libstdc++", "-Wl,--no-insert-timestamp", f"-specs={specs}"]
    return str(compiler), str(resource), flags


def static_runtime(binary: Path) -> None:
    imports = PE(binary.read_bytes()).imports()
    forbidden = {"libstdc++-6.dll", "libgcc_s_seh-1.dll", "libwinpthread-1.dll"}
    require(not (set(imports) & forbidden), f"{binary.name}: compiler runtime is not self-contained")


def application_manifest() -> str:
    return ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
            '<assembly xmlns="urn:schemas-microsoft-com:asm.v1" manifestVersion="1.0">'
            '<trustInfo xmlns="urn:schemas-microsoft-com:asm.v3"><security><requestedPrivileges>'
            '<requestedExecutionLevel level="asInvoker" uiAccess="false"/>'
            '</requestedPrivileges></security></trustInfo>'
            '<application xmlns="urn:schemas-microsoft-com:asm.v3"><windowsSettings>'
            '<dpiAware xmlns="http://schemas.microsoft.com/SMI/2005/WindowsSettings">true</dpiAware>'
            '</windowsSettings></application></assembly>')


def application_icon(png: bytes) -> bytes:
    """Wrap the validated command PNG in an ICO without changing its pixels."""
    validate_icon(png)
    width, height = struct.unpack('>II', png[16:24])
    return (struct.pack('<HHH', 0, 1, 1) +
            struct.pack('<BBBBHHII', width % 256, height % 256, 0, 0, 1, 32, len(png), 22) + png)


def primary_icon(manifest: dict, files: dict[str, bytes]) -> bytes:
    name = manifest['commands'][0].get('icon')
    if name:
        require(name in files, 'primary command icon is missing')
        return files[name]
    return (ROOT / 'framework/default-icon.png').read_bytes()


def compile_source(source: Path, output: Path, kind: str, sdk: Path, compiler: str,
                   flags: list[str], stage: Path, extra: list[str] | None = None,
                   app_icon: bytes | None = None) -> None:
    local_source = stage / (output.stem + "_src")
    shutil.copytree(source, local_source)
    sources = sorted(local_source.rglob("*.cpp"))
    require(bool(sources), f"no C++ sources in {source}")
    arguments = [compiler, *flags, "-I" + str(local_source)]
    if kind == "dll":
        arguments += ["-shared", "-I" + str(sdk / "api" / "inc")]
    else:
        arguments += ["-mwindows"]
    arguments += [str(path) for path in sources]
    if kind == "dll":
        arguments += [str(sdk / "ZW3D.lib")]
    arguments += (extra or []) + SYSTEM_LIBRARIES + ["-o", str(output)]
    for index, rc in enumerate(sorted(local_source.rglob("*.rc"))):
        obj = stage / (output.stem + f"_resource_{index}.o")
        run([str(Path(compiler).with_name("windres.exe")), "-I", str(rc.parent), "-i", str(rc), "-o", str(obj)], rc.parent)
        arguments.append(str(obj))
    if app_icon is not None:
        icon = stage / (output.stem + '-app.ico')
        icon.write_bytes(application_icon(app_icon))
        rc = stage / (output.stem + '-app.rc')
        rc.write_text(f'101 ICON "{icon.name}"\n', encoding='utf-8')
        obj = stage / (output.stem + '-app.o')
        run([str(Path(compiler).with_name('windres.exe')), '-i', str(rc), '-o', str(obj)], stage)
        arguments.append(str(obj))
    run(arguments, stage)
    static_runtime(output)


def build_framework(sdk: Path, compiler: str, flags: list[str], stage: Path) -> tuple[Path, Path]:
    require((ROOT / "framework" / "ZwPluginHub.cpp").is_file(), "shared hub framework is not ready")
    framework = stage / "framework"
    shutil.copytree(ROOT / "framework", framework)
    hub = stage / "ZwPluginHub.dll"
    manager = stage / "HubManager.exe"
    run([compiler, *flags, "-shared", "-I" + str(sdk / "api" / "inc"),
         str(framework / "ZwPluginHub.cpp"), str(sdk / "ZW3D.lib"),
         *SYSTEM_LIBRARIES, "-o", str(hub)], stage)
    (stage / "default-icon.bin").write_bytes((ROOT / "framework" / "default-icon.png").read_bytes())
    (stage / "manager.manifest").write_text(application_manifest(), encoding="utf-8")
    (stage / 'manager.ico').write_bytes(application_icon((ROOT / 'framework/default-icon.png').read_bytes()))
    (stage / "manager.rc").write_text('#include <windows.h>\n1 RT_MANIFEST "manager.manifest"\n101 ICON "manager.ico"\n903 RCDATA "default-icon.bin"\n', encoding="utf-8")
    run([str(Path(compiler).with_name("windres.exe")), "-i", "manager.rc", "-o", "manager-resource.o"], stage)
    run([compiler, *flags, "-mwindows", "-DHUB_MANAGER", str(framework / "setup.cpp"), str(stage / "manager-resource.o"),
         *SYSTEM_LIBRARIES, "-o", str(manager)], stage)
    static_runtime(hub)
    static_runtime(manager)
    return hub, manager


def installer_resources(manifest: dict, files: dict[str, bytes], hub: Path,
                        manager: Path, stage: Path) -> Path:
    entries = []
    index = []
    for number, (path, data) in enumerate(sorted(files.items())):
        filename = f"payload_{number}.bin"
        (stage / filename).write_bytes(data)
        entries.append(f'{1001 + number} RCDATA "{filename}"')
        index.append(f"{path}|{len(data)}|{sha256(data)}")
    (stage / "fileindex.bin").write_bytes(("\r\n".join(index) + "\r\n").encode("utf-8"))
    api_names = sorted(set(required_apis(files)) | set(required_apis({"ZwPluginHub.dll": hub.read_bytes()})))
    (stage / "descriptor.bin").write_bytes(descriptor(manifest, api_names))
    (stage / "default-icon.bin").write_bytes((ROOT / "framework" / "default-icon.png").read_bytes())
    shutil.copy2(hub, stage / "hub.bin")
    shutil.copy2(manager, stage / "manager.bin")
    meta = f"protocol=1\r\nversion={FRAMEWORK_VERSION}\r\nhub={sha256(hub.read_bytes())}\r\nmanager={sha256(manager.read_bytes())}\r\n"
    (stage / "framework-meta.bin").write_text(meta, encoding="utf-8", newline="")
    (stage / "setup.manifest").write_text(application_manifest(), encoding="utf-8")
    (stage / 'setup.ico').write_bytes(application_icon(primary_icon(manifest, files)))
    resource = stage / "resources.rc"
    resource.write_text('\n'.join(['#include <windows.h>', '1 RT_MANIFEST "setup.manifest"',
                        '101 ICON "setup.ico"', '900 RCDATA "hub.bin"', '901 RCDATA "manager.bin"',
                        '903 RCDATA "default-icon.bin"', '902 RCDATA "framework-meta.bin"',
                        '1000 RCDATA "fileindex.bin"', '2000 RCDATA "descriptor.bin"',
                        *entries]) + "\n", encoding="utf-8")
    return resource


def publish_artifacts(output: Path, sources: dict[str, Path | None]) -> None:
    """Publish a checked set; on ordinary failure restore the previous set."""
    output = output.resolve()
    for name in sources:
        destination = output / name
        require(Path(name).name == name and destination.resolve().is_relative_to(output),
                "artifact destination leaves output directory")
        candidates = [destination, *destination.rglob("*")] if destination.is_dir() else [destination]
        require(all(not path.is_symlink() and not getattr(path.lstat(), "st_file_attributes", 0) & 0x400
                    for path in candidates if path.exists() or path.is_symlink()),
                "artifact destination contains linked paths")
    publication = Path(tempfile.mkdtemp(prefix=".zwplug-publish-", dir=output))
    moved, published = [], []
    keep_recovery = False
    try:
        # All copies finish on the output volume before touching any existing artifact.
        for index, (name, source) in enumerate(sources.items()):
            if source is not None:
                staged = publication / f"new-{index}"
                if source.is_dir():
                    shutil.copytree(source, staged)
                else:
                    shutil.copy2(source, staged)
        try:
            for index, (name, source) in enumerate(sources.items()):
                destination = output / name
                if destination.exists():
                    backup = publication / f"old-{index}"
                    os.replace(destination, backup)
                    moved.append((destination, backup))
                if source is not None:
                    os.replace(publication / f"new-{index}", destination)
                    published.append(destination)
        except Exception:
            try:
                for index, destination in enumerate(reversed(published)):
                    os.replace(destination, publication / f"failed-{index}")
                for destination, backup in reversed(moved):
                    os.replace(backup, destination)
            except Exception as recovery_error:
                keep_recovery = True
                raise PackageError(f"publication recovery incomplete; retained files: {publication}") from recovery_error
            raise
    finally:
        if not keep_recovery:
            shutil.rmtree(publication)


def build(project: Path, sdk: Path, toolchain: Path, output: Path,
          compile_framework: bool, framework_bin: Path | None, package_only: bool = False) -> dict:
    require(os.name == "nt", "native build requires Windows")
    manifest = validate_manifest(read_json((project / "plugin.json").read_bytes(), "plugin.json"))
    require((sdk / "api" / "inc").is_dir() and (sdk / "ZW3D.lib").is_file(), "SDK headers/import library missing")
    output.mkdir(parents=True, exist_ok=True)
    # The compiler and resource compiler have inconsistent Unicode-path handling.
    # Every source/resource lives in a fresh ASCII staging directory during build.
    with tempfile.TemporaryDirectory(prefix="zwplug_build_") as temporary:
        stage = Path(temporary)
        require(str(stage).isascii(), "set TEMP/TMP to an ASCII directory for this compiler")
        compiler, resource_compiler, flags = compiler_settings(toolchain, stage)
        payload = stage / "payload"
        if (project / "payload").exists():
            read_payload(project / "payload")  # Reject symlinks before copying.
            shutil.copytree(project / "payload", payload)
        else:
            payload.mkdir()
        primary = payload / manifest["entry"]
        primary.parent.mkdir(parents=True, exist_ok=True)
        if (project / "src").is_dir():
            compile_source(project / "src", primary, manifest["type"], sdk,
                           compiler, flags, stage,
                           app_icon=primary_icon(manifest, read_payload(payload)) if manifest['type'] == 'exe' else None)
        else:
            require(primary.is_file(), "project needs src/*.cpp or a prebuilt payload entry")
        files = read_payload(payload)
        filename = f"{manifest['id']}-{manifest['version']}"
        package = output / (filename + ".zwplug")
        staged_package = stage / package.name
        package_report = build_package(manifest, files, staged_package, sdk)
        validate_package(staged_package, sdk)
        if package_only:
            # An explicitly package-only rebuild must not leave a stale installer/report.
            publish_artifacts(output, {package.name: staged_package,
                                      filename + "-setup.exe": None,
                                      filename + "-payload": None,
                                      filename + "-build.json": None})
            return {"status": "PASS", "package": str(package.resolve()), "packageValidation": package_report}
        if compile_framework:
            hub, manager = build_framework(sdk, compiler, flags, stage)
        else:
            framework_bin = framework_bin or DEFAULT_RUNTIME
            hub = framework_bin / "ZwPluginHub.dll"
            manager = framework_bin / "HubManager.exe"
            require(hub.is_file() and manager.is_file(), "shared framework binaries are missing")
            if framework_bin.resolve() == DEFAULT_RUNTIME.resolve():
                checksums = read_json((framework_bin / "checksums.json").read_bytes(), "runtime checksums")
                require(isinstance(checksums, dict) and set(checksums) == {"ZwPluginHub.dll", "HubManager.exe"},
                        "fixed runtime checksums are invalid")
                require(all(sha256((framework_bin / name).read_bytes()) == digest for name, digest in checksums.items()),
                        "fixed runtime was modified; restore the released runtime")
            static_runtime(hub)
            static_runtime(manager)
        rc = installer_resources(manifest, files, hub, manager, stage)
        resource_object = stage / "resources.o"
        run([resource_compiler, "-i", str(rc), "-o", str(resource_object)], stage)
        framework = stage / "installer"
        shutil.copytree(ROOT / "framework", framework)
        executable = stage / "Setup.exe"
        run([compiler, *flags, "-mwindows", str(framework / "setup.cpp"), str(resource_object),
             *SYSTEM_LIBRARIES, "-o", str(executable)], stage)
        static_runtime(executable)
        destination = output / (filename + "-setup.exe")
        # Retain exact frozen plugin binaries for debugging without the SDK.
        frozen = output / (filename + "-payload")
        # Verify the embedded installer against the exact staged package before release.
        from inspect_installer import inspect
        inspect(executable, staged_package, hub.parent, sdk)
        report = {"status": "PASS", "package": str(package.resolve()),
                  "installer": str(destination.resolve()), "installerSha256": sha256(executable.read_bytes()),
                  "hubSha256": sha256(hub.read_bytes()), "managerSha256": sha256(manager.read_bytes()),
                  "packageValidation": package_report}
        staged_report = stage / (filename + "-build.json")
        staged_report.write_bytes(canonical_json(report))
        publication = {package.name: staged_package, destination.name: executable,
                       frozen.name: payload, staged_report.name: staged_report}
        if compile_framework:
            cache = stage / "framework-release"
            cache.mkdir()
            shutil.copy2(hub, cache / "ZwPluginHub.dll")
            shutil.copy2(manager, cache / "HubManager.exe")
            publication["framework"] = cache
        publish_artifacts(output, publication)
        return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("project", type=Path, help="Folder containing plugin.json and src/ or payload/")
    parser.add_argument("--sdk", type=Path, required=True, help="Installed ZW3D 2027 SDK/host directory")
    parser.add_argument("--toolchain", type=Path, required=True,
                        help="MinGW root containing bin/g++.exe and bin/windres.exe")
    parser.add_argument("--out", type=Path, default=ROOT / "dist")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--build-framework", action="store_true", help="Framework maintainers only: compile a new runtime")
    group.add_argument("--framework-bin", type=Path, help="Test override; default is the fixed runtime/1.1.3 release")
    group.add_argument("--package-only", action="store_true", help="Compile and validate the plugin without an installer")
    args = parser.parse_args()
    try:
        report = build(args.project.resolve(), args.sdk.resolve(), args.toolchain.resolve(),
                       args.out.resolve(), args.build_framework,
                       args.framework_bin.resolve() if args.framework_bin else None, args.package_only)
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0
    except (PackageError, OSError, subprocess.SubprocessError) as error:
        print(json.dumps({"status": "FAIL", "error": str(error)}, ensure_ascii=False))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
