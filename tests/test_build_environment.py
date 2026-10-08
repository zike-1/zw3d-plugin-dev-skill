"""Offline regression tests for MinGW child-process environment isolation."""
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import build_plugin as build
from package_lib import PackageError


class Result:
    def __init__(self, output="", code=0):
        self.stdout = output
        self.returncode = code


class ToolchainEnvironmentTests(unittest.TestCase):
    def fake_toolchain(self, directory: Path) -> Path:
        root = directory / "MinGW 工具链"
        (root / "bin").mkdir(parents=True)
        for file in ("g++.exe", "gcc.exe", "windres.exe"):
            (root / "bin" / file).write_bytes(b"mock executable")
        return root

    def test_prefer_selected_toolchain_without_modifying_parent_path(self):
        with tempfile.TemporaryDirectory() as temporary:
            toolchain = self.fake_toolchain(Path(temporary))
            original = os.environ.get("PATH", "")
            with patch.dict(os.environ, {"PATH": "other-compiler"}, clear=False):
                env = build.toolchain_environment(toolchain)
                self.assertEqual(env["PATH"].split(os.pathsep)[0], str(toolchain / "bin"))
                self.assertEqual(os.environ["PATH"], "other-compiler")
            self.assertEqual(os.environ.get("PATH", ""), original)

    def test_missing_toolchain_produces_readable_error(self):
        with tempfile.TemporaryDirectory() as temporary:
            with self.assertRaisesRegex(PackageError, "g\\+\\+/gcc/windres missing"):
                build.toolchain_environment(Path(temporary))

    def test_compiler_probes_and_spec_use_same_environment(self):
        with tempfile.TemporaryDirectory() as temporary:
            toolchain = self.fake_toolchain(Path(temporary))
            stage = Path(temporary) / "stage"
            stage.mkdir()
            observations = []
            def fake_run(args, **kwargs):
                observations.append((args, kwargs))
                if "-dumpmachine" in args:
                    return Result("x86_64-w64-mingw32\\n")
                if "-dumpspecs" in args:
                    return Result("before default-manifest.o%s after")
                return Result()
            with patch.object(build.subprocess, "run", side_effect=fake_run):
                compiler, resource, flags, env = build.compiler_settings(toolchain, stage)
            self.assertTrue(Path(compiler).name == "g++.exe")
            self.assertTrue(Path(resource).name == "windres.exe")
            self.assertTrue(any("-specs=" in flag for flag in flags))
            self.assertEqual(len(observations), 4)
            self.assertTrue(all(call[1]["env"]["PATH"].startswith(str(toolchain / "bin"))
                                for call in observations))
            self.assertIn("int zwplug_probe;", observations[2][1]["input"])
            self.assertNotIn("default-manifest.o%s", (stage / "compiler.specs").read_text())

    def test_missing_runtime_dll_has_actionable_error(self):
        with patch.object(build.subprocess, "run", return_value=Result("", -1073741515)):
            with self.assertRaisesRegex(PackageError, "0xC0000135"):
                build.tool_probe(["g++.exe", "-x", "c++", "-E", "-"], {"PATH": "bin"},
                                 input_text="int probe;\\n")

    def test_reject_32_bit_compiler(self):
        with tempfile.TemporaryDirectory() as temporary:
            toolchain = self.fake_toolchain(Path(temporary))
            with patch.object(build.subprocess, "run", return_value=Result("i686-w64-mingw32")):
                with self.assertRaisesRegex(PackageError, "Expected x64"):
                    build.compiler_settings(toolchain, Path(temporary))

    def test_build_subprocess_receives_explicit_environment(self):
        with patch.object(build.subprocess, "run", return_value=Result()) as call:
            build.run(["windres.exe", "--version"], Path("."), env={"PATH": "toolchain-bin"})
        self.assertEqual(call.call_args.kwargs["env"]["PATH"], "toolchain-bin")


if __name__ == "__main__":
    unittest.main(verbosity=2)
