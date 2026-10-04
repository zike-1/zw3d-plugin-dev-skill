"""Adversarial contract tests, independent of the GUI and local SDK."""
import copy
import json
import stat
import struct
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import package_lib as pkg


def binary(prefix="ArtHello", dll=True):
    """Small PE fixture with an actual bounded export directory."""
    data = bytearray(1536)
    data[:2] = b"MZ"
    struct.pack_into("<I", data, 60, 128)
    data[128:132] = b"PE\0\0"
    struct.pack_into("<HHIIIHH", data, 132, 0x8664, 1, 0, 0, 0, 240, 0x2022 if dll else 0x22)
    optional = 152
    struct.pack_into("<H", data, optional, 0x20B)
    struct.pack_into("<I", data, optional + 60, 512)
    struct.pack_into("<I", data, optional + 108, 16)
    section = optional + 240
    data[section:section + 8] = b".rdata\0\0"
    struct.pack_into("<IIII", data, section + 8, 1024, 4096, 1024, 512)
    if dll:
        struct.pack_into("<II", data, optional + 112, 4096, 128)
        struct.pack_into("<IIHHIIIIIII", data, 512, 0, 0, 0, 0, 0, 1, 2, 2, 4160, 4176, 4192)
        struct.pack_into("<II", data, 576, 4300, 4300)
        struct.pack_into("<II", data, 592, 4224, 4256)
        struct.pack_into("<HH", data, 608, 0, 1)
        for offset, name in ((640, prefix + "Init"), (672, prefix + "Exit")):
            value = name.encode("ascii") + b"\0"
            data[offset:offset + len(value)] = value
    return bytes(data)


def manifest():
    return {"schemaVersion": 1, "id": "com.example.art-hello", "name": "优雅问候",
            "version": "1.0.0", "prefix": "ArtHello", "type": "dll",
            "host": {"product": "ZW3D", "versions": [2027], "architecture": "x64"},
            "entry": "ArtHello.dll", "commands": [{"id": "ArtHelloShow", "label": "问候",
            "environments": ["top", "part", "assembly", "drawing"]}],
            "dataPolicy": "preserve", "hotUnload": False}


def imported_binary(library, function, dll=True):
    data = bytearray(binary(dll=dll))
    struct.pack_into("<II", data, 152 + 120, 4400, 40)
    struct.pack_into("<IIIII", data, 816, 4480, 0, 0, 4520, 4480)
    struct.pack_into("<QQ", data, 896, 4560, 0)
    lib = library.encode("ascii") + b"\0"
    symbol = function.encode("ascii") + b"\0"
    data[936:936 + len(lib)] = lib
    data[978:978 + len(symbol)] = symbol
    return bytes(data)


class PackageTests(unittest.TestCase):
    def test_icon_validation_and_ownership(self):
        icon = (Path(__file__).resolve().parents[1] / "framework/default-icon.png").read_bytes()
        m = manifest(); m["commands"][0].update(icon="中文 图标/tool.png", tooltip="说明")
        pkg.validate_manifest(m)
        pkg.validate_binaries(m, {"ArtHello.dll": binary(), "中文 图标/tool.png": icon})
        for data in (b"", icon[:33], icon + b"trailing", icon[:45] + b"bad" + icon[48:]):
            with self.subTest(data_size=len(data)), self.assertRaises(pkg.PackageError):
                pkg.validate_binaries(m, {"ArtHello.dll": binary(), "中文 图标/tool.png": data})
        m["commands"][0]["icon"] = "../outside.png"
        with self.assertRaises(pkg.PackageError): pkg.validate_manifest(m)

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="zwplug_test_")
        self.directory = Path(self.temporary.name)
        self.m = manifest()
        self.files = {"ArtHello.dll": binary(), "readme.txt": "说明".encode()}

    def tearDown(self):
        self.temporary.cleanup()

    def write_zip(self, entries):
        path = self.directory / "bad.zwplug"
        with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
            for name, data in entries:
                archive.writestr(name, data)
        return path

    def entries(self):
        return [("plugin.json", pkg.canonical_json(self.m)),
                ("checksums.json", pkg.canonical_json({name: pkg.sha256(data) for name, data in self.files.items()})),
                *(("payload/" + name, data) for name, data in self.files.items())]

    def test_valid_package_and_deterministic_bytes(self):
        first = self.directory / "one.zwplug"
        second = self.directory / "two.zwplug"
        pkg.build_package(self.m, self.files, first)
        pkg.build_package(self.m, dict(reversed(list(self.files.items()))), second)
        self.assertEqual(first.read_bytes(), second.read_bytes())
        self.assertEqual(pkg.validate_package(first)["files"], 2)

    def test_unsafe_windows_paths(self):
        for path in ("../a.dll", "a/../../b", "C:/a", "/a", "a\\b", "a//b", "a:stream",
                     "NUL.txt", "CON", "com1.dat", "NUL .txt", "COM¹.txt", "a.", "a ", "a/./b", "a\n.ini"):
            with self.subTest(path=path), self.assertRaises(pkg.PackageError):
                pkg.relative_path(path)

    def test_native_extra_device_names_are_rejected(self):
        for path in ("CLOCK$.txt", "com0.dll", "resources/LPT0.txt", "clock$ /data.txt"):
            with self.subTest(path=path), self.assertRaises(pkg.PackageError):
                pkg.relative_path(path)
        pkg.relative_path("resources/COM10.txt")

    def test_path_limit_counts_utf8_bytes(self):
        boundary = "中" * 60
        self.assertEqual(len(boundary.encode("utf-8")), 180)
        pkg.relative_path(boundary)
        for path in (boundary + "a", "中" * 61):
            self.assertLess(len(path), 180)
            with self.assertRaises(pkg.PackageError):
                pkg.relative_path(path)

    def test_name_limit_matches_native_utf8_buffer(self):
        # Both names satisfy the 80-character manifest bound. Only the second
        # exceeds the native descriptor's 255-byte display-name limit.
        self.m["name"] = "😀" * 63 + "abc"
        self.assertEqual(len(self.m["name"].encode("utf-8")), 255)
        pkg.validate_manifest(self.m)
        self.m["name"] = "😀" * 64
        self.assertEqual(len(self.m["name"].encode("utf-8")), 256)
        with self.assertRaises(pkg.PackageError):
            pkg.validate_manifest(self.m)

    def test_manifest_boundaries(self):
        mutations = [("schemaVersion", True), ("id", "Example.Art"), ("id", "com.x-"),
                     ("id", "single"), ("version", "01.0.0"), ("version", "1.0.0-01"),
                     ("version", "1.0.0-beta.1"), ("version", "1.0.0+build"), ("version", "1000000.0.0"),
                     ("prefix", "HubTools"), ("prefix", "ZwPluginHubX"),
                     ("prefix", "中文"), ("hotUnload", True), ("dataPolicy", "delete"),
                     ("entry", "file.exe"), ("entry", "Other.dll"), ("name", "hello\nentry=x")]
        for key, value in mutations:
            m = copy.deepcopy(self.m)
            m[key] = value
            with self.subTest(key=key, value=value), self.assertRaises(pkg.PackageError):
                pkg.validate_manifest(m)

    def test_manifest_unknown_fields_commands_and_arguments(self):
        for change in (lambda m: m.update(title="other"),
                       lambda m: m["commands"].append(copy.deepcopy(m["commands"][0])),
                       lambda m: m["commands"][0].update(id="OtherShow"),
                       lambda m: m["commands"][0].update(environments=[]),
                       lambda m: m["commands"][0].update(environments=["part"]),
                       lambda m: m["commands"][0].update(environments=["top", "top"]),
                       lambda m: m["commands"][0].update(arguments="fixed")):
            m = copy.deepcopy(self.m)
            change(m)
            with self.assertRaises(pkg.PackageError):
                pkg.validate_manifest(m)
        m = copy.deepcopy(self.m)
        m.update(type="exe", entry="ArtHello.exe")
        m["commands"][0]["arguments"] = '/file="a b.txt"'
        pkg.validate_manifest(m)
        m["commands"][0]["arguments"] = "ok\r\nentry=other.exe"
        with self.assertRaises(pkg.PackageError):
            pkg.validate_manifest(m)

    def test_duplicate_json_keys_and_nonfinite(self):
        for data in (b'{"schemaVersion":1,"schemaVersion":2}', b'{"x":NaN}', b'\xff', b'\xef\xbb\xbf{}',
                     b"[" * 1100 + b"]" * 1100):
            with self.assertRaises(pkg.PackageError):
                pkg.read_json(data)

    def test_checksum_tamper_missing_and_extra(self):
        entries = self.entries()
        for index, value in ((2, b"tamper"), (1, b"{}"),
                             (1, pkg.canonical_json({**{name: pkg.sha256(data) for name, data in self.files.items()},
                                                      "other.txt": "0" * 64}))):
            changed = list(entries)
            changed[index] = (changed[index][0], value)
            with self.assertRaises(pkg.PackageError):
                pkg.validate_package(self.write_zip(changed))

    def test_archive_traversal_case_collision_and_extraneous(self):
        for entry in (("../evil", b"x"), ("payload/../evil", b"x"),
                      ("payload/ARTHELLO.dll", binary()), ("installer.exe", binary(dll=False)),
                      ("payload/start.ps1", b"echo x")):
            with self.subTest(entry=entry[0]), self.assertRaises(pkg.PackageError):
                pkg.validate_package(self.write_zip([*self.entries(), entry]))

    def test_file_directory_collision(self):
        with self.assertRaises(pkg.PackageError):
            pkg.validate_payload_files({"a": b"file", "A/b": b"nested"})

    def test_sdk_redistribution_is_rejected(self):
        for path in ("ZW3D.dll", "sdk/ZW3D.lib", "ZW3D.exe"):
            with self.assertRaises(pkg.PackageError):
                pkg.validate_payload_files({path: binary()})

    def test_framework_metadata_names_are_reserved(self):
        for path in ("descriptor.ini", "FILES.TXT", "descriptor.ini/nested.txt"):
            with self.assertRaises(pkg.PackageError):
                pkg.validate_payload_files({path: b"x"})
        pkg.validate_payload_files({"data/descriptor.ini": b"plugin data"})

    def test_lone_unicode_surrogates_are_rejected(self):
        for key in ("name", "entry"):
            m = copy.deepcopy(self.m)
            m[key] = "bad\ud800"
            with self.assertRaises(pkg.PackageError):
                pkg.validate_manifest(m)

    def test_symlink_zip_entry(self):
        path = self.directory / "symlink.zwplug"
        with zipfile.ZipFile(path, "w") as archive:
            for name, data in self.entries():
                archive.writestr(name, data)
            info = zipfile.ZipInfo("payload/link.txt")
            info.create_system = 3
            info.external_attr = (stat.S_IFLNK | 0o777) << 16
            archive.writestr(info, "outside")
        with self.assertRaises(pkg.PackageError):
            pkg.validate_package(path)

    def test_expansion_size_limits(self):
        original = pkg.MAX_FILE_SIZE
        pkg.MAX_FILE_SIZE = 128
        try:
            with self.assertRaises(pkg.PackageError):
                pkg.validate_package(self.write_zip(self.entries()))
        finally:
            pkg.MAX_FILE_SIZE = original

    def test_broken_binary_architecture_and_missing_exports(self):
        for data in (b"not a binary", binary(dll=False), binary(prefix="Other")):
            with self.assertRaises(pkg.PackageError):
                pkg.validate_binaries(self.m, {"ArtHello.dll": data})
        data = bytearray(binary())
        struct.pack_into("<H", data, 132, 0x14C)
        with self.assertRaises(pkg.PackageError):
            pkg.validate_binaries(self.m, {"ArtHello.dll": bytes(data)})

    def test_private_dependency_dll_is_rejected(self):
        with self.assertRaises(pkg.PackageError):
            pkg.validate_binaries(self.m, {"ArtHello.dll": binary(), "Helper.dll": binary("Helper")})

    def test_missing_dependency_is_rejected(self):
        with self.assertRaises(pkg.PackageError):
            pkg.validate_binaries(self.m, {"ArtHello.dll": imported_binary("Missing.dll", "missing")})

    def test_import_library_must_be_a_plain_filename(self):
        with self.assertRaises(pkg.PackageError):
            pkg.validate_binaries(self.m, {"ArtHello.dll": imported_binary("../ZW3D.dll", "cvxCmdFunc")})

    def test_disguised_dependency_dll_is_rejected(self):
        with self.assertRaises(pkg.PackageError):
            pkg.validate_binaries(self.m, {"ArtHello.dll": binary(), "Hidden.exe": binary()})

    def test_standalone_exe_cannot_import_inprocess_sdk(self):
        m = copy.deepcopy(self.m)
        m.update(type="exe", entry="ArtHello.exe")
        with self.assertRaises(pkg.PackageError):
            pkg.validate_binaries(m, {"ArtHello.exe": imported_binary("ZW3D.dll", "cvxCmdFunc", dll=False)})

    def test_actual_pe_import_table_is_parsed(self):
        self.assertEqual(pkg.PE(imported_binary("ZW3D.dll", "cvxCmdFunc")).imports(),
                         {"zw3d.dll": ["cvxCmdFunc"]})

    def test_pe_rva_bounds(self):
        data = bytearray(binary())
        struct.pack_into("<I", data, 592, 0xFFFFFF00)
        with self.assertRaises(pkg.PackageError):
            pkg.PE(bytes(data)).exports()

    def test_descriptor_is_exact_utf8_no_bom(self):
        data = pkg.descriptor(self.m)
        self.assertTrue(data.startswith(b"schema=1\r\n"))
        self.assertIn("name=优雅问候\r\n".encode(), data)
        self.assertIn(b"cmd.0.environments=top,part,assembly,drawing\r\n", data)
        self.assertNotIn(b"\xef\xbb\xbf", data)


if __name__ == "__main__":
    unittest.main(verbosity=2)
