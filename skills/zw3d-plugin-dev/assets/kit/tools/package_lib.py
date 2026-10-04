"""The v1 package contract. Validation never loads or executes a plugin."""
from __future__ import annotations

import hashlib
import json
import re
import stat
import struct
import zipfile
import zlib
from pathlib import Path

SCHEMA_VERSION = 1
MAX_FILES = 256
MAX_FILE_SIZE = 64 * 1024 * 1024
MAX_TOTAL_SIZE = 128 * 1024 * 1024
MAX_MANIFEST_SIZE = 64 * 1024
ENVIRONMENTS = {"top", "part", "assembly", "drawing"}
RESERVED = {"CON", "PRN", "AUX", "NUL", "CLOCK$", *(f"COM{i}" for i in range(10)),
            *(f"LPT{i}" for i in range(10)), *(f"COM{i}" for i in "¹²³"),
            *(f"LPT{i}" for i in "¹²³")}
DENIED_EXTENSIONS = {".bat", ".cmd", ".ps1", ".vbs", ".vbe", ".wsf", ".wsh",
                     ".sh", ".py", ".msi", ".reg", ".lnk", ".scr", ".com"}
WINDOWS_DLLS = {"kernel32.dll", "kernelbase.dll", "ntdll.dll", "user32.dll", "gdi32.dll",
               "advapi32.dll", "shell32.dll", "shlwapi.dll", "ole32.dll", "oleaut32.dll",
               "comctl32.dll", "comdlg32.dll", "bcrypt.dll", "crypt32.dll", "version.dll",
               "ws2_32.dll", "winmm.dll", "winspool.drv", "imm32.dll", "uxtheme.dll",
               "dwmapi.dll", "setupapi.dll", "rpcrt4.dll", "secur32.dll", "netapi32.dll",
               "iphlpapi.dll", "userenv.dll", "winhttp.dll", "wininet.dll", "msvcrt.dll",
               "ucrtbase.dll", "opengl32.dll", "glu32.dll", "d3d11.dll", "dxgi.dll",
               "dwrite.dll", "d2d1.dll", "propsys.dll", "urlmon.dll", "normaliz.dll",
               "msimg32.dll", "oleacc.dll", "mpr.dll", "psapi.dll", "dbghelp.dll"}
ID_PATTERN = r"^[a-z][a-z0-9]*(?:-[a-z0-9]+)*(?:\.[a-z][a-z0-9]*(?:-[a-z0-9]+)*)+$"
PREFIX_PATTERN = r"^[A-Z][A-Za-z0-9]{1,31}$"
COMMAND_PATTERN = r"^[A-Za-z][A-Za-z0-9_]{1,63}$"
VERSION_PATTERN = r"^(0|[1-9][0-9]{0,5})\.(0|[1-9][0-9]{0,5})\.(0|[1-9][0-9]{0,5})$"


class PackageError(ValueError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise PackageError(message)


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def canonical_json(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True,
                       separators=(",", ":")) + "\n").encode("utf-8")


def read_json(data: bytes, description: str = "JSON") -> object:
    require(len(data) <= MAX_MANIFEST_SIZE, f"{description}: file too large")

    def unique(pairs):
        result = {}
        for key, value in pairs:
            require(key not in result, f"{description}: duplicate key {key!r}")
            result[key] = value
        return result

    try:
        def reject_constant(value):
            raise PackageError(f"{description}: invalid number {value}")

        value = json.loads(data.decode("utf-8"), object_pairs_hook=unique, parse_constant=reject_constant)
        pending = [(value, 0)]
        while pending:
            item, depth = pending.pop()
            require(depth <= 16, f"{description}: excessive JSON nesting")
            if isinstance(item, dict):
                pending.extend((child, depth + 1) for child in item.values())
            elif isinstance(item, list):
                pending.extend((child, depth + 1) for child in item)
        return value
    except (UnicodeError, json.JSONDecodeError, RecursionError) as error:
        raise PackageError(f"{description}: invalid UTF-8 JSON: {error}") from error


def relative_path(value: object) -> str:
    require(isinstance(value, str) and bool(value), "path must be a nonempty string")
    require(not any(0xD800 <= ord(char) <= 0xDFFF for char in value), "invalid Unicode in path")
    require(len(value.encode("utf-8")) <= 180, f"path exceeds 180 UTF-8 bytes: {value!r}")
    require(not any(ord(char) < 32 or ord(char) == 127 for char in value), "control character in path")
    require("\\" not in value and not value.startswith("/"), f"use relative forward-slash paths: {value!r}")
    require(not any(char in value for char in ':*?"<>|'), f"invalid Windows path: {value!r}")
    parts = value.split("/")
    for part in parts:
        require(part not in ("", ".", ".."), f"unsafe path: {value!r}")
        require(not part.endswith((" ", ".")), f"Windows-normalized path: {value!r}")
        require(part.split(".", 1)[0].rstrip(" ").upper() not in RESERVED, f"reserved Windows filename: {value!r}")
    return value


def text(value: object, name: str, maximum: int = 100) -> str:
    require(isinstance(value, str) and bool(value.strip()), f"{name}: nonempty string required")
    require(len(value) <= maximum, f"{name}: too long")
    require(not any(0xD800 <= ord(char) <= 0xDFFF for char in value), f"{name}: invalid Unicode")
    require(not any(ord(char) < 32 or ord(char) == 127 for char in value), f"{name}: control character")
    # INI is embedded into the installer; separators cannot become extra fields.
    require("=" not in value, f"{name}: '=' is reserved")
    return value


def validate_manifest(manifest: object) -> dict:
    require(isinstance(manifest, dict), "plugin.json must be an object")
    expected = {"schemaVersion", "id", "name", "version", "prefix", "type", "host",
                "entry", "commands", "dataPolicy", "hotUnload"}
    require(expected <= set(manifest) <= expected | {"description"}, "plugin.json: missing or unknown fields")
    if "description" in manifest:
        text(manifest["description"], "description", 240)
    require(type(manifest["schemaVersion"]) is int and manifest["schemaVersion"] == 1,
            "unsupported schemaVersion")
    plugin_id = text(manifest["id"], "id", 80)
    require(re.fullmatch(ID_PATTERN, plugin_id) is not None, "id must be lowercase reverse DNS")
    text(manifest["name"], "name", 80)
    require(len(manifest["name"].encode("utf-8")) < 256, "name exceeds native UTF-8 byte limit")
    version = text(manifest["version"], "version", 80)
    require(re.fullmatch(VERSION_PATTERN, version) is not None,
            "v1 version must be numeric major.minor.patch, 1-6 digits each, no leading zeros")
    prefix = text(manifest["prefix"], "prefix", 32)
    require(re.fullmatch(PREFIX_PATTERN, prefix) is not None, "prefix must be 2-32 ASCII letters/digits, starting uppercase")
    require(not prefix.casefold().startswith(("hub", "zwpluginhub", "idzphub")),
            "shared toolbox prefix is reserved")
    require(manifest["type"] in ("dll", "exe"), "type must be dll or exe")
    require(manifest["host"] == {"product": "ZW3D", "versions": [2027], "architecture": "x64"}
            and type(manifest["host"]["versions"][0]) is int, "v1 supports ZW3D 2027 x64 only")
    entry = relative_path(manifest["entry"])
    require(Path(entry).suffix.lower() == "." + manifest["type"], "entry extension must match type")
    if manifest["type"] == "dll":
        require(Path(entry).stem == prefix, "DLL entry filename must match prefix for host lifecycle loading")
    require(manifest["dataPolicy"] == "preserve", "dataPolicy must be preserve")
    require(manifest["hotUnload"] is False, "hotUnload must be false")
    commands = manifest["commands"]
    require(isinstance(commands, list) and 1 <= len(commands) <= 32, "commands: 1-32 entries required")
    seen = set()
    for command in commands:
        require(isinstance(command, dict), "command must be an object")
        required = {"id", "label", "environments"}
        allowed = required | {"icon", "tooltip"} | ({"arguments"} if manifest["type"] == "exe" else set())
        require(required <= set(command) <= allowed, "command: missing or unknown fields")
        command_id = text(command["id"], "command.id", 64)
        require(re.fullmatch(COMMAND_PATTERN, command_id) is not None and command_id.startswith(prefix),
                "command.id must use the plugin prefix followed by an ASCII symbol")
        require(len(command_id) > len(prefix), "command.id must have a symbol after prefix")
        require(command_id.casefold() not in seen, "duplicate command id")
        seen.add(command_id.casefold())
        text(command["label"], "command.label", 80)
        if "icon" in command:
            icon = relative_path(command["icon"])
            require(icon.lower().endswith(".png"), "command.icon must be a package PNG path")
        if "tooltip" in command:
            text(command["tooltip"], "command.tooltip", 240)
        environments = command["environments"]
        require(isinstance(environments, list) and len(environments) == 4
                and all(isinstance(env, str) and env in ENVIRONMENTS for env in environments)
                and set(environments) == ENVIRONMENTS,
                "v1 commands must declare all four environments exactly once")
        if "arguments" in command:
            arguments = command["arguments"]
            require(isinstance(arguments, str) and len(arguments) <= 1024
                    and not any(0xD800 <= ord(char) <= 0xDFFF for char in arguments)
                    and not any(ord(char) < 32 or ord(char) == 127 for char in arguments),
                    "arguments must be a fixed, single-line string")
    return manifest


class PE:
    """Bounded PE32+ reader: no LoadLibrary, no process execution."""
    def __init__(self, data: bytes):
        self.data = data
        require(len(data) >= 64 and data[:2] == b"MZ", "entry must be a Windows PE binary")
        pe = self.unpack("<I", 60)[0]
        require(self.slice(pe, 4) == b"PE\0\0", "invalid PE signature")
        machine, sections, _, _, _, optional_size, characteristics = self.unpack("<HHIIIHH", pe + 4)
        require(machine == 0x8664, "binary must be x64")
        require(1 <= sections <= 96, "invalid PE section count")
        optional = pe + 24
        require(optional_size >= 112 and self.unpack("<H", optional)[0] == 0x20B, "binary must be PE32+")
        self.is_dll = bool(characteristics & 0x2000)
        self.header_size = self.unpack("<I", optional + 60)[0]
        directory_count = min(self.unpack("<I", optional + 108)[0], 16)
        require(optional_size >= 112 + directory_count * 8, "truncated PE optional header")
        self.directories = [self.unpack("<II", optional + 112 + i * 8) for i in range(directory_count)]
        self.sections = []
        for i in range(sections):
            section = optional + optional_size + 40 * i
            virtual_size, virtual_address, raw_size, raw_offset = self.unpack("<IIII", section + 8)
            self.slice(raw_offset, raw_size)
            self.sections.append((virtual_address, virtual_size, raw_size, raw_offset))

    def slice(self, offset: int, size: int) -> bytes:
        require(0 <= offset <= len(self.data) and 0 <= size <= len(self.data) - offset, "truncated PE data")
        return self.data[offset:offset + size]

    def unpack(self, fmt: str, offset: int):
        return struct.unpack(fmt, self.slice(offset, struct.calcsize(fmt)))

    def offset(self, rva: int, size: int = 1) -> int:
        if rva < self.header_size:
            self.slice(rva, size)
            return rva
        for address, virtual_size, raw_size, raw_offset in self.sections:
            if address <= rva < address + max(virtual_size, raw_size):
                delta = rva - address
                require(delta + size <= raw_size, "PE RVA references uninitialized data")
                self.slice(raw_offset + delta, size)
                return raw_offset + delta
        raise PackageError("PE RVA is outside mapped sections")

    def string(self, rva: int) -> str:
        offset = self.offset(rva)
        end = self.data.find(b"\0", offset, min(offset + 4096, len(self.data)))
        require(end >= 0, "unterminated PE string")
        try:
            return self.data[offset:end].decode("ascii")
        except UnicodeError as error:
            raise PackageError("invalid PE import/export name") from error

    def directory(self, index: int) -> tuple[int, int]:
        return self.directories[index] if index < len(self.directories) else (0, 0)

    def imports(self) -> dict[str, list[str]]:
        rva, size = self.directory(1)
        if not rva:
            return {}
        require(size >= 20, "invalid PE import directory")
        result = {}
        for i in range(min(size // 20, 4096)):
            values = self.unpack("<IIIII", self.offset(rva + i * 20, 20))
            if not any(values):
                return result
            original, _, _, name, first = values
            dll = self.string(name).lower()
            require(dll not in result, "duplicate PE import descriptor")
            result[dll] = []
            for n in range(65536):
                thunk = self.unpack("<Q", self.offset((original or first) + n * 8, 8))[0]
                if not thunk:
                    break
                result[dll].append(f"#{thunk & 0xFFFF}" if thunk & (1 << 63) else self.string(thunk + 2))
            else:
                raise PackageError("unterminated PE thunk table")
        raise PackageError("unterminated PE import directory")

    def exports(self) -> set[str]:
        rva, _ = self.directory(0)
        if not rva:
            return set()
        values = self.unpack("<IIHHIIIIIII", self.offset(rva, 40))
        base, functions, count, _, names, _ = values[5:]
        require(count <= 100000 and functions <= 100000, "unreasonable PE export count")
        result = {f"#{base + i}" for i in range(functions)}
        result.update(self.string(self.unpack("<I", self.offset(names + i * 4, 4))[0]) for i in range(count))
        return result

    def resources(self) -> dict[tuple, bytes]:
        rva, size = self.directory(2)
        if not rva:
            return {}
        result = {}

        def inside(offset, length):
            require(0 <= offset and offset + length <= size, "resource directory outside declared bounds")
            return self.offset(rva + offset, length)

        def visit(offset, path):
            require(len(path) <= 3, "resource directory nesting limit")
            values = self.unpack("<IIHHHH", inside(offset, 16))
            count = values[-2] + values[-1]
            require(count <= 4096, "too many resource entries")
            for index in range(count):
                name, target = self.unpack("<II", inside(offset + 16 + index * 8, 8))
                if name & 0x80000000:
                    string_offset = name & 0x7FFFFFFF
                    length = self.unpack("<H", inside(string_offset, 2))[0]
                    label = self.slice(inside(string_offset + 2, 2 * length), 2 * length).decode("utf-16le")
                else:
                    label = name
                item = (*path, label)
                if target & 0x80000000:
                    visit(target & 0x7FFFFFFF, item)
                else:
                    address, length, _, _ = self.unpack("<IIII", inside(target, 16))
                    require(item not in result, "duplicate resource entry")
                    result[item] = self.slice(self.offset(address, length), length)

        visit(0, ())
        return result


def validate_icon(data: bytes) -> None:
    """Bounded non-interlaced RGB/RGBA PNGs; validate chunks and decoded size."""
    require(len(data) <= 1024 * 1024 and data[:8] == b"\x89PNG\r\n\x1a\n", "icon is absent or not PNG")
    offset, header, compressed, ended = 8, None, bytearray(), False
    while offset < len(data):
        require(offset + 12 <= len(data), "truncated PNG chunk")
        size = int.from_bytes(data[offset:offset + 4], "big")
        kind = data[offset + 4:offset + 8]
        require(offset + 12 + size <= len(data), "truncated PNG content")
        content = data[offset + 8:offset + 8 + size]
        crc = int.from_bytes(data[offset + 8 + size:offset + 12 + size], "big")
        require(zlib.crc32(kind + content) & 0xffffffff == crc, "PNG checksum differs")
        if header is None:
            require(kind == b"IHDR" and size == 13, "PNG must start with one IHDR")
            header = content
        elif kind == b"IHDR":
            raise PackageError("duplicate PNG header")
        elif kind == b"IDAT":
            compressed.extend(content)
        elif kind == b"IEND":
            require(size == 0 and offset + 12 == len(data), "PNG has trailing content")
            ended = True
        offset += 12 + size
    require(header is not None and ended and compressed, "incomplete PNG")
    width, height = struct.unpack(">II", header[:8])
    depth, color, compression, filtering, interlace = header[8:]
    require(width == height and 16 <= width <= 256 and depth == 8 and color in (2, 6)
            and (compression, filtering, interlace) == (0, 0, 0),
            "icon must be square 16-256px, non-interlaced 8-bit RGB/RGBA PNG")
    expected = (width * (3 if color == 2 else 4) + 1) * height
    decoder = zlib.decompressobj()
    try:
        decoded = decoder.decompress(bytes(compressed), expected + 1)
    except zlib.error as error:
        raise PackageError("invalid PNG image stream") from error
    require(len(decoded) == expected and decoder.eof and not decoder.unused_data
            and not decoder.unconsumed_tail, "PNG decoded size differs")
    stride = width * (3 if color == 2 else 4) + 1
    require(all(decoded[row * stride] <= 4 for row in range(height)),
            "PNG has an invalid scanline filter")


def validate_binaries(manifest: dict, files: dict[str, bytes], sdk: Path | None = None) -> dict:
    require(manifest["entry"] in files, "entry file is absent from payload")
    for command in manifest["commands"]:
        if "icon" in command:
            validate_icon(files.get(command["icon"], b""))
    primary = PE(files[manifest["entry"]])
    require(primary.is_dll == (manifest["type"] == "dll"), "entry PE kind does not match type")
    if primary.is_dll:
        exports = primary.exports()
        expected = {manifest["prefix"] + "Init", manifest["prefix"] + "Exit"}
        require(expected <= exports, f"DLL must export {', '.join(sorted(expected))}")
    report = {}
    sdk_exports = None
    if sdk is not None:
        host = sdk / "ZW3D.dll"
        require(host.is_file(), f"SDK host binary missing: {host}")
        sdk_exports = PE(host.read_bytes()).exports()
        require(len(sdk_exports) > 1000, "ZW3D host export table is unexpectedly small")
    for path, data in files.items():
        if Path(path).suffix.lower() not in (".dll", ".exe"):
            continue
        require(Path(path).suffix.lower() != ".dll" or path == manifest["entry"],
                "v1 does not support private dependency DLLs; link private libraries statically")
        binary = PE(data)
        require(binary.is_dll == (Path(path).suffix.lower() == ".dll"),
                f"{path}: PE kind does not match filename extension")
        imports = binary.imports()
        for library in imports:
            require(re.fullmatch(r"[a-z0-9][a-z0-9_.-]*\.(?:dll|drv)", library) is not None,
                    f"{path}: imported libraries must use plain filenames")
            system = library in WINDOWS_DLLS or library.startswith(("api-ms-win-", "ext-ms-win-"))
            resolved = system or library == "zw3d.dll"
            if not resolved and sdk is not None:
                resolved = (sdk / library).is_file()
            require(resolved, f"{path}: missing dependency {library}; include it in payload or validate with --sdk")
        host_apis = imports.get("zw3d.dll", [])
        require(not host_apis or (manifest["type"] == "dll" and binary.is_dll),
                "standalone EXE tools cannot import in-process ZW3D APIs")
        require(all(re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name) for name in host_apis),
                "ZW3D APIs must use named C identifiers, not ordinal imports")
        if sdk_exports is not None:
            absent = sorted(set(imports.get("zw3d.dll", [])) - sdk_exports)
            require(not absent, f"{path}: APIs absent from selected SDK: {', '.join(absent)}")
        report[path] = {"imports": imports, "hostApisChecked": sdk_exports is not None}
    return report


def validate_payload_files(files: dict[str, bytes]) -> None:
    require(1 <= len(files) <= MAX_FILES, f"payload: 1-{MAX_FILES} files required")
    seen = set()
    total = 0
    for path, data in files.items():
        relative_path(path)
        require(path.split("/", 1)[0].casefold() not in {"descriptor.ini", "files.txt"},
                "descriptor.ini and files.txt are reserved at the payload root")
        require(Path(path).name.casefold() not in {"zw3d.dll", "zw3d.lib", "zw3d.exe"},
                "the ZW3D host/SDK must not be redistributed in a plugin package")
        require(path.casefold() not in seen, "Windows case-insensitive path collision")
        seen.add(path.casefold())
        require(Path(path).suffix.lower() not in DENIED_EXTENSIONS, f"unsupported executable script: {path}")
        require(isinstance(data, bytes) and len(data) <= MAX_FILE_SIZE, f"payload file too large: {path}")
        total += len(data)
    require(total <= MAX_TOTAL_SIZE, "payload total size exceeds limit")
    for path in seen:
        components = path.split("/")
        require(not any("/".join(components[:i]) in seen for i in range(1, len(components))),
                "payload file/directory collision")


def read_payload(directory: Path) -> dict[str, bytes]:
    require(directory.is_dir() and not directory.is_symlink(), "payload directory is missing or a symlink")
    require(not getattr(directory.stat(), "st_file_attributes", 0) & 0x400, "payload reparse point is forbidden")
    files = {}
    for item in sorted(directory.rglob("*")):
        require(not item.is_symlink() and not (item.stat().st_file_attributes & 0x400
                if hasattr(item.stat(), "st_file_attributes") else False), "payload reparse point is forbidden")
        if item.is_file():
            require(item.stat().st_size <= MAX_FILE_SIZE, f"payload file too large: {item}")
            files[item.relative_to(directory).as_posix()] = item.read_bytes()
        else:
            require(item.is_dir(), "payload contains a nonregular file")
    validate_payload_files(files)
    return files


def build_package(manifest: dict, files: dict[str, bytes], output: Path,
                  sdk: Path | None = None) -> dict:
    validate_manifest(manifest)
    validate_payload_files(files)
    binary_report = validate_binaries(manifest, files, sdk)
    checksums = {path: sha256(data) for path, data in sorted(files.items())}
    entries = {"plugin.json": canonical_json(manifest), "checksums.json": canonical_json(checksums),
               **{f"payload/{path}": data for path, data in files.items()}}
    output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for name, data in sorted(entries.items()):
            info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            info.create_system = 3
            info.external_attr = (stat.S_IFREG | 0o644) << 16
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, data, compresslevel=9)
    return {"id": manifest["id"], "version": manifest["version"], "files": len(files),
            "sha256": sha256(output.read_bytes()), "binaries": binary_report}


def validate_package(path: Path, sdk: Path | None = None) -> dict:
    require(path.stat().st_size <= MAX_TOTAL_SIZE + 1024 * 1024, "package is too large")
    files = {}
    documents = {}
    seen = set()
    total = 0
    try:
        with zipfile.ZipFile(path) as archive:
            entries = archive.infolist()
            require(3 <= len(entries) <= MAX_FILES + 2, "invalid ZIP entry count")
            for info in entries:
                name = relative_path(info.filename)
                require(name.casefold() not in seen, "duplicate or case-colliding ZIP entry")
                seen.add(name.casefold())
                require(not info.is_dir() and not info.flag_bits & 1, "directories/encrypted entries are forbidden")
                mode = info.external_attr >> 16
                require(stat.S_IFMT(mode) in (0, stat.S_IFREG), "ZIP symlink/special entry is forbidden")
                require(info.compress_type in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED), "unsupported ZIP compression")
                limit = MAX_MANIFEST_SIZE if name in ("plugin.json", "checksums.json") else MAX_FILE_SIZE
                require(info.file_size <= limit, "ZIP member exceeds size limit")
                total += info.file_size
                require(total <= MAX_TOTAL_SIZE + 2 * MAX_MANIFEST_SIZE, "ZIP expansion exceeds total limit")
                require(name in ("plugin.json", "checksums.json") or name.startswith("payload/"), "unexpected ZIP entry")
                data = archive.read(info)
                require(len(data) == info.file_size, "ZIP size mismatch")
                if name.startswith("payload/"):
                    files[relative_path(name[8:])] = data
                else:
                    documents[name] = read_json(data, name)
    except (zipfile.BadZipFile, RuntimeError, OSError) as error:
        raise PackageError(f"invalid package: {error}") from error
    require(set(documents) == {"plugin.json", "checksums.json"}, "package metadata is missing")
    manifest = validate_manifest(documents["plugin.json"])
    validate_payload_files(files)
    checksums = documents["checksums.json"]
    require(isinstance(checksums, dict) and set(checksums) == set(files), "checksums must cover exactly all payload files")
    for name, digest in checksums.items():
        require(isinstance(digest, str) and re.fullmatch(r"[0-9a-f]{64}", digest) is not None,
                "checksum must be lowercase SHA256")
        require(sha256(files[name]) == digest, f"checksum mismatch: {name}")
    return {"id": manifest["id"], "version": manifest["version"], "files": len(files),
            "sha256": sha256(path.read_bytes()), "binaries": validate_binaries(manifest, files, sdk)}


def required_apis(files: dict[str, bytes]) -> list[str]:
    return sorted({name for path, data in files.items() if Path(path).suffix.lower() in (".dll", ".exe")
                   for name in PE(data).imports().get("zw3d.dll", [])})


def descriptor(manifest: dict, api_names: list[str] | None = None) -> bytes:
    validate_manifest(manifest)
    api_names = api_names or []
    require(len(api_names) <= 4096 and len(api_names) == len(set(api_names))
            and all(isinstance(name, str) and re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name) for name in api_names),
            "invalid descriptor API list")
    lines = ["schema=1", *[f"{key}={manifest[key]}" for key in
             ("id", "name", "version", "type", "entry", "prefix")], "hotUnload=0",
             f"commands={len(manifest['commands'])}"]
    lines.append("manifest.sha256=" + sha256(canonical_json(manifest)))
    if "description" in manifest:
        lines.append("description=" + manifest["description"])
    for index, command in enumerate(manifest["commands"]):
        for key in ("icon", "tooltip"):
            if key in command:
                lines.append(f"cmd.{index}.{key}={command[key]}")
        lines.extend((f"cmd.{index}.id={command['id']}", f"cmd.{index}.label={command['label']}",
                      f"cmd.{index}.environments={','.join(command['environments'])}"))
        if manifest["type"] == "exe":
            lines.append(f"cmd.{index}.arguments={command.get('arguments', '')}")
    lines.append(f"api.count={len(api_names)}")
    lines.extend(f"api.{index}={name}" for index, name in enumerate(api_names))
    return ("\r\n".join(lines) + "\r\n").encode("utf-8")
