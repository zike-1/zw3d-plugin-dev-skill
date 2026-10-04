"""Verify embedded payloads/bootstrap using a bounded PE reader, without execution."""
import argparse
import json
import struct
import zipfile
from pathlib import Path

from package_lib import (PE, PackageError, descriptor, read_json, required_apis,
                         require, sha256, validate_package, validate_icon)

def inspect_application_icon(binary: bytes, png: bytes) -> None:
    """Follow the ICO group to its image; resource presence alone is insufficient."""
    resources = PE(binary).resources()
    groups = [(key, data) for key, data in resources.items() if key[0] == 14 and key[1] == 101]
    require(len(groups) == 1, 'application icon group 101 is missing or ambiguous')
    key, group = groups[0]
    require(len(group) == 20 and group[:6] == struct.pack('<HHH', 0, 1, 1), 'unexpected application icon group')
    image_id = struct.unpack_from('<H', group, 18)[0]
    require(resources.get((3, image_id, key[2])) == png, 'application icon does not match its command PNG')


def inspect(installer: Path, package: Path, framework_bin: Path, sdk: Path | None = None) -> dict:
    package_report = validate_package(package, sdk)
    with zipfile.ZipFile(package) as archive:
        manifest = read_json(archive.read("plugin.json"))
        files = {name[8:]: archive.read(name) for name in archive.namelist() if name.startswith("payload/")}
    binary = PE(installer.read_bytes())
    require(not binary.is_dll, "installer is not an EXE")
    resources = binary.resources()
    blobs = {}
    for key, data in resources.items():
        if key[0] == 10:
            require(len(key) == 3 and key[1] not in blobs, "duplicate embedded resource language/id")
            blobs[key[1]] = data
    expected_ids = {900, 901, 902, 903, 1000, 2000, *range(1001, 1001 + len(files))}
    require(set(blobs) == expected_ids, "installer RCDATA set differs from expected contract")
    require(blobs[900] == (framework_bin / "ZwPluginHub.dll").read_bytes(), "hub bootstrap mismatch")
    require(blobs[901] == (framework_bin / "HubManager.exe").read_bytes(), "manager bootstrap mismatch")
    metadata = {}
    for line in blobs[902].decode("utf-8").splitlines():
        key, value = line.split("=", 1)
        require(key not in metadata, "duplicate framework metadata key")
        metadata[key] = value
    require(set(metadata) == {"protocol", "version", "hub", "manager"} and metadata["protocol"] == "1",
            "invalid framework protocol metadata")
    require(metadata["hub"] == sha256(blobs[900]) and metadata["manager"] == sha256(blobs[901]),
            "framework metadata hashes differ")
    validate_icon(blobs[903])
    if tuple(map(int, metadata['version'].split('.'))) >= (1, 1, 3):
        primary = manifest['commands'][0].get('icon')
        inspect_application_icon(installer.read_bytes(), files[primary] if primary else blobs[903])
        inspect_application_icon(blobs[901], blobs[903])
    manager_icons = [data for key, data in PE(blobs[901]).resources().items() if key[:2] == (10, 903)]
    require(manager_icons == [blobs[903]], "manager and installer defaults differ")
    manager_manifest = [data for key, data in PE(blobs[901]).resources().items() if key[0] == 24]
    require(len(manager_manifest) == 1 and b'level="asInvoker"' in manager_manifest[0],
            "manager lacks its explicit read-only UAC policy")
    api_names = sorted(set(required_apis(files)) | set(required_apis({"ZwPluginHub.dll": blobs[900]})))
    if sdk is not None:
        absent = sorted(set(api_names) - PE((sdk / "ZW3D.dll").read_bytes()).exports())
        require(not absent, f"framework/plugin APIs absent from SDK: {', '.join(absent)}")
    require(blobs[2000] == descriptor(manifest, api_names), "embedded descriptor mismatch")
    rows = []
    for index, (path, data) in enumerate(sorted(files.items())):
        require(blobs[1001 + index] == data, f"embedded payload mismatch: {path}")
        rows.append(f"{path}|{len(data)}|{sha256(data)}")
    require(blobs[1000] == ("\r\n".join(rows) + "\r\n").encode(), "embedded file index mismatch")
    manifest_resources = [data for key, data in resources.items() if key[0] == 24]
    require(len(manifest_resources) == 1 and b'level="asInvoker"' in manifest_resources[0],
            "installer lacks the expected explicit UAC manifest")
    return {"status": "PASS", "id": manifest["id"], "files": len(files), "frameworkVersion": metadata["version"],
            "installerSha256": sha256(installer.read_bytes()),
            "hubSha256": sha256(blobs[900]), "managerSha256": sha256(blobs[901]),
            "requiredApis": api_names, "packageValidation": package_report}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("installer", type=Path)
    parser.add_argument("package", type=Path)
    parser.add_argument("--framework-bin", type=Path, required=True)
    parser.add_argument("--sdk", type=Path)
    args = parser.parse_args()
    try:
        print(json.dumps(inspect(args.installer, args.package, args.framework_bin, args.sdk),
                         ensure_ascii=False, indent=2))
        return 0
    except (PackageError, OSError, UnicodeError) as error:
        print(json.dumps({"status": "FAIL", "error": str(error)}, ensure_ascii=False))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
