"""Fill a frozen Windows installer template; never invoke a compiler or plugin."""
from __future__ import annotations

import ctypes
import os
from pathlib import Path
import struct

from build_plugin import (DEFAULT_RUNTIME, FRAMEWORK_VERSION, ROOT,
                          application_manifest, primary_icon, static_runtime)
from package_lib import (PE, descriptor, read_json, require, required_apis,
                         sha256, validate_icon)

TEMPLATE_VERSION = "1.0.0"
DEFAULT_TEMPLATE = ROOT / "installer-runtime" / TEMPLATE_VERSION


def checked_template() -> bytes:
    table = read_json((DEFAULT_TEMPLATE / "checksums.json").read_bytes(), "installer template checksums")
    require(isinstance(table, dict) and set(table) == {"SetupTemplate.exe"},
            "installer template checksum table is invalid")
    data = (DEFAULT_TEMPLATE / "SetupTemplate.exe").read_bytes()
    require(sha256(data) == table["SetupTemplate.exe"], "frozen installer template was modified")
    pe = PE(data)
    require(not pe.is_dll and pe.directory(4) == (0, 0),
            "installer template must be an unsigned x64 EXE")
    resources = pe.resources()
    require(set(resources) == {(24, 1, 1033), (14, 101, 1033), (3, 1, 1033), (10, 903, 1033)},
            "installer template resource set differs from its contract")
    require(resources[(24, 1, 1033)].rstrip(b"\0").replace(b"\r\n", b"\n") == application_manifest().encode("utf-8"),
            "installer template UAC manifest differs")
    require(resources[(10, 903, 1033)] == (ROOT / "framework/default-icon.png").read_bytes(),
            "installer template default icon differs")
    return data


def checked_framework() -> tuple[bytes, bytes]:
    table = read_json((DEFAULT_RUNTIME / "checksums.json").read_bytes(), "runtime checksums")
    require(isinstance(table, dict) and set(table) == {"ZwPluginHub.dll", "HubManager.exe"},
            "fixed runtime checksums are invalid")
    result = {}
    for name, digest in table.items():
        data = (DEFAULT_RUNTIME / name).read_bytes()
        require(sha256(data) == digest, "fixed runtime was modified; restore the released runtime")
        result[name] = data
    return result["ZwPluginHub.dll"], result["HubManager.exe"]


def update_resources(path: Path, resources: dict[tuple[int, int, int], bytes]) -> None:
    """Replace resources in a private staging EXE using Windows' resource writer."""
    require(os.name == "nt", "installer generation requires Windows; package-only works elsewhere")
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    begin = kernel.BeginUpdateResourceW
    begin.argtypes = [ctypes.c_wchar_p, ctypes.c_int]
    begin.restype = ctypes.c_void_p
    update = kernel.UpdateResourceW
    update.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p,
                       ctypes.c_ushort, ctypes.c_void_p, ctypes.c_uint32]
    update.restype = ctypes.c_int
    end = kernel.EndUpdateResourceW
    end.argtypes = [ctypes.c_void_p, ctypes.c_int]
    end.restype = ctypes.c_int
    handle = begin(str(path), True)
    if not handle:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        for (kind, name, language), data in sorted(resources.items()):
            require(0 < kind < 65536 and 0 < name < 65536 and 0 <= language < 65536,
                    "invalid installer resource identity")
            buffer = ctypes.create_string_buffer(data)
            if not update(handle, ctypes.c_void_p(kind), ctypes.c_void_p(name), language,
                          buffer, len(data)):
                raise ctypes.WinError(ctypes.get_last_error())
    except BaseException:
        end(handle, True)
        raise
    if not end(handle, False):
        raise ctypes.WinError(ctypes.get_last_error())


def verify_code(template: bytes, generated: bytes) -> None:
    """Resource replacement must preserve every non-resource section byte."""
    before, after = PE(template), PE(generated)
    resource_rva = before.directory(2)[0]
    require(len(before.sections) == len(after.sections), "installer section count changed")
    for old, new in zip(before.sections, after.sections):
        address, virtual_size, size, offset = old
        if address <= resource_rva < address + max(virtual_size, size):
            continue
        # Windows moves later sections when .rsrc grows. Their bytes and sizes
        # must remain identical; sections before .rsrc retain their RVAs too.
        require(old[1:3] == new[1:3] and (address >= resource_rva or old[0] == new[0]) and
                template[offset:offset + size] == generated[new[3]:new[3] + new[2]],
                "installer executable code or non-resource data changed")
    require(before.imports() == after.imports(), "installer imports changed")


def create_installer(manifest: dict, files: dict[str, bytes], output: Path) -> dict:
    require(os.name == "nt", "installer generation requires Windows; use package-only elsewhere")
    template = checked_template()
    hub, manager = checked_framework()
    resources = PE(template).resources()
    png = primary_icon(manifest, files)
    validate_icon(png)
    width, height = struct.unpack(">II", png[16:24])
    resources[(3, 1, 1033)] = png
    resources[(14, 101, 1033)] = (struct.pack("<HHH", 0, 1, 1) +
        struct.pack("<BBBBHHIH", width % 256, height % 256, 0, 0, 1, 32, len(png), 1))
    blobs = {900: hub, 901: manager,
             902: (f"protocol=1\r\nversion={FRAMEWORK_VERSION}\r\nhub={sha256(hub)}\r\n"
                   f"manager={sha256(manager)}\r\n").encode("utf-8"),
             903: (ROOT / "framework/default-icon.png").read_bytes()}
    rows = []
    for index, (name, data) in enumerate(sorted(files.items())):
        blobs[1001 + index] = data
        rows.append(f"{name}|{len(data)}|{sha256(data)}")
    blobs[1000] = ("\r\n".join(rows) + "\r\n").encode("utf-8")
    apis = sorted(set(required_apis(files)) | set(required_apis({"ZwPluginHub.dll": hub})))
    blobs[2000] = descriptor(manifest, apis)
    resources.update({(10, identity, 1033): data for identity, data in blobs.items()})
    output.write_bytes(template)
    update_resources(output, resources)
    generated = output.read_bytes()
    require(PE(generated).resources() == resources, "generated installer resources differ")
    verify_code(template, generated)
    static_runtime(output)
    return {"templateVersion": TEMPLATE_VERSION, "templateSha256": sha256(template),
            "frameworkVersion": FRAMEWORK_VERSION, "installerSha256": sha256(generated)}
