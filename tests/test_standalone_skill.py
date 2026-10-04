"""Verify the released skill as an author, without importing repository code.

Build the candidate ZIP first, then use a fresh isolated output directory.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import sys
import xml.etree.ElementTree as ET
import zipfile


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class ReleasedSkillVerification:
    def __init__(self, args: argparse.Namespace):
        self.args = args
        self.root = args.work_root.resolve()
        require(not self.root.exists(), "use a new workspace; preserve earlier evidence")
        self.root.mkdir(parents=True)
        self.events: list[dict] = []
        self.artifacts: dict[str, str] = {}
        self.runtime_hashes: dict[str, str] = {}
        self.skill_hash = sha256(args.skill_zip)
        self.kit: Path | None = None

    def record(self, name: str, **facts) -> None:
        self.events.append({"name": name, **facts})
        self.save_report("RUNNING")
        print(name, flush=True)

    def save_report(self, status: str, error: str | None = None) -> None:
        report = {"status": status, "skillZip": str(self.args.skill_zip.resolve()),
                  "skillSha256": self.skill_hash, "workspace": str(self.root),
                  "events": self.events, "artifacts": self.artifacts,
                  "notVerified": ["real ZW3D UI and native DLL loading",
                                  "normal greeting dialog visual appearance"]}
        if error:
            report["error"] = error
        (self.root / "standalone-report.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    def run(self, arguments: list[str], name: str, cwd: Path | None = None,
            timeout: int = 120) -> str:
        startup = subprocess.STARTUPINFO()
        startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startup.wShowWindow = subprocess.SW_HIDE
        result = subprocess.run(arguments, cwd=cwd or self.root, startupinfo=startup,
                                timeout=timeout, capture_output=True, text=True,
                                encoding="utf-8", errors="replace")
        output = result.stdout + result.stderr
        evidence = self.root / (re.sub(r"[^A-Za-z0-9_-]", "_", name) + ".txt")
        evidence.write_text(output, encoding="utf-8")
        require(result.returncode == 0,
                f"{name}: exit {result.returncode}; see {evidence}: {output[-2000:]}")
        self.record(name, exitCode=result.returncode, evidence=str(evidence))
        return result.stdout

    def python_tool(self, relative: str, *arguments: str, name: str,
                    timeout: int = 120) -> str:
        require(self.kit is not None, "extract released skill first")
        script = self.kit / relative
        require(script.is_file(), f"released kit is missing {relative}")
        return self.run([sys.executable, "-X", "utf8", str(script), *arguments],
                        name, cwd=self.kit, timeout=timeout)

    def extract_skill(self) -> None:
        extracted = self.root / "released-skill"
        extracted.mkdir()
        seen = set()
        with zipfile.ZipFile(self.args.skill_zip) as archive:
            for info in archive.infolist():
                name = info.filename.rstrip("/")
                require(name and "\\" not in name and not name.startswith("/")
                        and ":" not in name and all(part not in ("", ".", "..")
                                                  for part in name.split("/")),
                        f"unsafe released ZIP member: {info.filename}")
                require(name.casefold() not in seen, f"duplicate ZIP member: {name}")
                seen.add(name.casefold())
                require(not stat.S_ISLNK(info.external_attr >> 16), "symlink in released ZIP")
                destination = extracted.joinpath(*name.split("/"))
                if info.is_dir():
                    destination.mkdir(parents=True, exist_ok=True)
                else:
                    require(info.file_size <= 128 * 1024 * 1024, "oversized released member")
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    destination.write_bytes(archive.read(info))
        entries = list(extracted.rglob("SKILL.md"))
        require(len(entries) == 1, "released ZIP must contain one skill entry point")
        skill = entries[0]
        text = skill.read_text(encoding="utf-8")
        require("assets/kit" in text, "skill does not tell standalone authors where tools live")
        self.kit = skill.parent / "assets" / "kit"
        require(self.kit.is_dir(), "standalone skill has no assets/kit")
        for relative in ("references/package-contract.md", "references/acceptance.md"):
            require((skill.parent / relative).is_file(), f"missing referenced document: {relative}")
            (skill.parent / relative).read_text(encoding="utf-8")
        runtime = self.kit / "runtime" / "1.1.3"
        require((runtime / "ZwPluginHub.dll").is_file()
                and (runtime / "HubManager.exe").is_file(), "frozen common runtime is missing")
        self.runtime_hashes = {name: sha256(runtime / name)
                               for name in ("ZwPluginHub.dll", "HubManager.exe")}
        self.record("released-skill-discoverable", entry=str(skill), kit=str(self.kit),
                    runtimeHubSha256=self.runtime_hashes["ZwPluginHub.dll"],
                    runtimeManagerSha256=self.runtime_hashes["HubManager.exe"])
        for relative in ("templates/new_plugin.py", "tools/build_plugin.py",
                         "tools/validate_package.py", "tools/inspect_installer.py"):
            self.python_tool(relative, "--help", name=Path(relative).stem + "-help")

    def make_plugin(self, prefix: str, plugin_id: str, greeting: str) -> dict:
        project = self.root / "authors" / prefix
        self.python_tool("templates/new_plugin.py", "--type", "exe", "--id", plugin_id,
                         "--prefix", prefix, "--name", prefix, "--out", str(project),
                         name=prefix + "-generate")
        source = project / "src" / (prefix + ".cpp")
        body = source.read_text(encoding="utf-8")
        pattern = r'(MessageBoxW\(nullptr,\s*)L"(?:\\.|[^"\\])*"'
        replacement = lambda match: match.group(1) + 'L"' + greeting + '"'
        body, count = re.subn(pattern, replacement, body)
        require(count == 1, "template must expose one normal business dialog")
        source.write_text(body, encoding="utf-8", newline="\n")
        output = project / "out"
        # Author flow: no framework source build and no private framework-bin.
        stdout = self.python_tool("tools/build_plugin.py", str(project), "--sdk", str(self.args.sdk),
                                  "--toolchain", str(self.args.toolchain), "--out", str(output),
                                  name=prefix + "-build", timeout=240)
        build = json.loads(stdout)
        require(build.get("status") == "PASS", "builder did not report PASS")
        packages = list(output.glob("*.zwplug"))
        installers = list(output.glob("*.exe"))
        require(len(packages) == len(installers) == 1, "one package and installer expected")
        package, installer = packages[0], installers[0]
        validation = json.loads(self.python_tool("tools/validate_package.py", str(package),
                                                "--sdk", str(self.args.sdk),
                                                name=prefix + "-validate"))
        require(validation.get("status") == "PASS", "package validator did not report PASS")
        self.python_tool("tools/inspect_installer.py", str(installer), str(package),
                         "--framework-bin", str(self.kit / "runtime" / "1.1.3"),
                         "--sdk", str(self.args.sdk), name=prefix + "-inspect")
        run_directory = project / "只读测试 路径"
        run_directory.mkdir()
        with zipfile.ZipFile(package) as archive:
            manifest = json.loads(archive.read("plugin.json").decode("utf-8"))
            require(manifest["entry"] == prefix + ".exe", "unexpected entry")
            executable = run_directory / (prefix + ".exe")
            executable.write_bytes(archive.read("payload/" + manifest["entry"]))
        log = run_directory / "probe log.txt"
        self.run([str(executable), "/probe=" + str(log)], prefix + "-readonly-probe", timeout=10)
        require(log.read_bytes() == f"exe|{prefix}|ok\n".encode("ascii"), "probe marker missing")
        self.artifacts[prefix + ".package"] = str(package)
        self.artifacts[prefix + ".installer"] = str(installer)
        self.record(prefix + "-artifact-verified", id=plugin_id, packageSha256=sha256(package),
                    installerSha256=sha256(installer), probeEvidence=str(log))
        return {"id": plugin_id, "prefix": prefix, "installer": installer,
                "entry": manifest["entry"], "command": manifest["commands"][0]["id"]}

    def installed_files(self, plugin: dict, target: Path) -> dict[str, str]:
        directory = target / "apilibs" / "ZwPluginHub" / "plugins" / plugin["id"]
        return {str(path.relative_to(directory)): sha256(path)
                for path in directory.rglob("*") if path.is_file()}

    def ui(self, target: Path) -> tuple[list[ET.Element], str]:
        pages = []
        documents = []
        settings = target / "apilibs" / "Settings" / "Default"
        for path in settings.rglob("*.zcui"):
            text = path.read_text(encoding="utf-8-sig")
            documents.append(text)
            tree = ET.fromstring(text)
            pages.extend(element for element in tree.iter()
                         if element.tag.rsplit("}", 1)[-1] == "RibbonPage")
        return pages, "\n".join(documents)

    def verify_installation(self, first: dict, second: dict) -> None:
        target = self.root / "隔离 宿主 2027"
        target.mkdir()
        # This is a test fixture, never delivered or launched as a CAD process.
        for filename in ("zw3d.exe", "ZW3D.dll"):
            original = self.args.sdk / filename
            require(original.is_file(), f"host fixture file missing: {original}")
            shutil.copyfile(original, target / filename)
        self.run([str(first["installer"]), "/quiet", "/install", "/target=" + str(target)],
                 "install-first", timeout=120)
        hub = target / "apilibs" / "ZwPluginHub.dll"
        require(hub.is_file(), "first install did not establish the shared hub")
        shared_hash = sha256(hub)
        require(shared_hash == self.runtime_hashes["ZwPluginHub.dll"],
                "author build did not use the released frozen hub")
        first_snapshot = self.installed_files(first, target)
        require(any(path.endswith(first["entry"]) for path in first_snapshot), "first payload missing")
        self.run([str(second["installer"]), "/quiet", "/install", "/target=" + str(target)],
                 "install-second", timeout=120)
        require(sha256(hub) == shared_hash, "second install changed the frozen shared hub")
        require(self.installed_files(first, target) == first_snapshot, "second install changed first plugin")
        second_snapshot = self.installed_files(second, target)
        require(any(path.endswith(second["entry"]) for path in second_snapshot), "second payload missing")
        pages, document = self.ui(target)
        require(len(pages) == 1, "both plugins must share exactly one ribbon page")
        require(first["command"] in document and second["command"] in document,
                "both command declarations must be installed")
        managers = list((target / "apilibs" / "ZwPluginHub").rglob("HubManager.exe"))
        require(len(managers) == 1, "expected one common manager")
        manager = managers[0]
        manager_hash = sha256(manager)
        require(manager_hash == self.runtime_hashes["HubManager.exe"],
                "author build did not use the released frozen manager")
        self.record("shared-framework-confirmed", target=str(target), pageCount=len(pages),
                    hubSha256=shared_hash, managerSha256=manager_hash)
        self.run([str(manager), "/quiet", "/uninstall=" + first["id"], "/target=" + str(target)],
                 "uninstall-first", timeout=120)
        require(not any(path.endswith(first["entry"]) for path in self.installed_files(first, target)),
                "first plugin executable remains after uninstall")
        require(self.installed_files(second, target) == second_snapshot, "uninstall first changed second plugin")
        require(sha256(hub) == shared_hash and sha256(manager) == manager_hash,
                "uninstall first changed the shared framework")
        pages, document = self.ui(target)
        require(first["command"] not in document and second["command"] in document,
                "uninstall first did not independently remove its UI")
        second_directory = target / "apilibs" / "ZwPluginHub" / "plugins" / second["id"]
        executables = list(second_directory.rglob(second["entry"]))
        require(len(executables) == 1, "remaining plugin has no unique installed entry")
        surviving_log = self.root / "remaining-plugin-probe.txt"
        self.run([str(executables[0]), "/probe=" + str(surviving_log)],
                 "remaining-plugin-runs", timeout=10)
        require(surviving_log.read_bytes() == f"exe|{second['prefix']}|ok\n".encode("ascii"),
                "remaining plugin failed its independent probe")
        self.run([str(manager), "/quiet", "/uninstall=" + second["id"], "/target=" + str(target)],
                 "uninstall-second", timeout=120)
        require(not any(path.endswith(second["entry"]) for path in self.installed_files(second, target)),
                "second plugin executable remains after uninstall")
        require(sha256(hub) == shared_hash and sha256(manager) == manager_hash,
                "uninstall second removed the shared framework")
        _, document = self.ui(target)
        require(first["command"] not in document and second["command"] not in document,
                "plugin declarations remain after both uninstalls")
        self.record("independent-uninstall-confirmed", target=str(target))

    def verify(self) -> None:
        try:
            self.extract_skill()
            first = self.make_plugin("SkillGreeting", "org.zwtools.skill-greeting", "你好，欢迎使用问候工具。")
            second = self.make_plugin("SkillFarewell", "org.zwtools.skill-farewell", "再见，感谢使用告别工具。")
            self.verify_installation(first, second)
            require(sha256(self.args.skill_zip) == self.skill_hash, "released ZIP changed during verification")
            self.save_report("PASS")
            print("PASS standalone released skill workflow; real-host UI remains unverified", flush=True)
        except Exception as error:
            self.save_report("FAIL", str(error))
            raise


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--skill-zip", type=Path, required=True)
    parser.add_argument("--work-root", type=Path, required=True)
    parser.add_argument("--sdk", type=Path, required=True)
    parser.add_argument("--toolchain", type=Path, required=True)
    args = parser.parse_args()
    require(os.name == "nt", "native skill verification requires Windows")
    ReleasedSkillVerification(args).verify()


if __name__ == "__main__":
    main()
