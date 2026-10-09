"""Exercise resource-filled EXEs against an isolated copy of a 2027 installation.

Requires two previously compiled example packages (ArtHello DLL and ArtNotes
EXE). No compiler is invoked and no real CAD session is started or modified.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from build_plugin import DEFAULT_RUNTIME
from inspect_installer import inspect
from package_lib import validate_package


def acceptance(sdk: Path, dll_package: Path, exe_package: Path) -> dict:
    rows = []
    def check(condition, label):
        if not condition:
            raise AssertionError(label)
        rows.append(label)
        print("PASS " + label, flush=True)
    with tempfile.TemporaryDirectory(prefix="prebuilt_installation_") as temporary:
        stage = Path(temporary)
        env = dict(os.environ, PATH="", LOCALAPPDATA=str(stage / "user-data"))
        target = stage / "中文 安装位置" / "ZW3D 2027"
        target.mkdir(parents=True)
        for name in ("zw3d.exe", "ZW3D.dll"):
            shutil.copy2(sdk / name, target / name)
        store = target / "apilibs/ZwPluginHub"
        resource_pool = target / "apilibs/Settings/Default/ResourcePool"
        resource_pool.mkdir(parents=True)
        ribbon = resource_pool / "RibbonPagesUser.zcui"
        ribbon.write_text('<RibbonPages><RibbonPage name="ForeignPage" text="其他插件"/></RibbonPages>',
                          encoding="utf-8")
        def command(executable, arguments, success=True):
            log = stage / "operation.log"
            result = subprocess.run([str(executable), "/quiet", *arguments,
                "/target=" + str(target), "/log=" + str(log)], env=env,
                creationflags=subprocess.CREATE_NO_WINDOW, timeout=30)
            check((result.returncode == 0) == success,
                  "native operation " + arguments[0] + (" accepted" if success else " rejected"))
            return log.read_text(encoding="utf-8")
        def prepare(package, project):
            validate_package(package, sdk)
            with zipfile.ZipFile(package) as archive:
                for name in archive.namelist():
                    if name == "plugin.json" or name.startswith("payload/"):
                        file = project / name
                        file.parent.mkdir(parents=True, exist_ok=True)
                        file.write_bytes(archive.read(name))
            return json.loads((project / "plugin.json").read_text(encoding="utf-8"))
        def package_project(project):
            result = subprocess.run([sys.executable, "-X", "utf8", str(ROOT / "tools/package_existing.py"),
                str(project), "--out", str(stage / "dist"), "--installer"], env=env,
                capture_output=True, text=True, encoding="utf-8", timeout=30)
            check(result.returncode == 0, "compiler-free CLI generated " + project.name)
            report = json.loads(result.stdout)
            check(not report["compilerInvoked"] and not report["hostApisChecked"],
                  "packaging used neither compiler nor SDK for " + project.name)
            inspect(Path(report["installer"]), Path(report["package"]), DEFAULT_RUNTIME, sdk)
            return Path(report["installer"])
        a, b = stage / "A", stage / "B"
        am, bm = prepare(dll_package, a), prepare(exe_package, b)
        ae, be = package_project(a), package_project(b)
        command(ae, ["/install"])
        hub = (target / "apilibs/ZwPluginHub.dll").read_bytes()
        command(be, ["/install"])
        check((target / "apilibs/ZwPluginHub.dll").read_bytes() == hub,
              "two installers reuse frozen framework bytes")
        check(len(list((store / "state").glob("*.ini"))) == 2, "A and B have separate registrations")
        pages = ET.parse(ribbon).getroot()
        page = pages.findall("RibbonPage[@name='ZwPluginHubPage']")
        check(len(page) == 1 and page[0].get("text") == "扩展工具" and
              all(g.get("visible") == "true" for g in page[0].findall("RibbonGroup")),
              "installed XML has one shared page and visible parent groups")
        check(pages.find("RibbonPage[@name='ForeignPage']") is not None,
              "foreign menu is preserved")
        b_record = (store / "state" / (bm["id"] + ".ini")).read_bytes()
        b_entry = store / "plugins" / bm["id"] / bm["version"] / bm["entry"]
        b_bytes = b_entry.read_bytes()
        key = hashlib.sha256(str(target).lower().encode("utf-8")).hexdigest()[:16]
        a_data = Path(env["LOCALAPPDATA"]) / "ZwPluginHub" / key / am["id"]
        a_data.mkdir(parents=True)
        (a_data / "settings.txt").write_text("preserve", encoding="utf-8")
        manager = store / "HubManager.exe"
        # Upgrade one plugin's label/assets, preserving its business binary.
        parts = am["version"].split(".")
        parts[-1] = str(int(parts[-1]) + 1)
        am["version"] = ".".join(parts)
        am["commands"][0]["label"] = "更新后的问候"
        (a / "payload/upgrade.txt").write_text("new asset", encoding="utf-8")
        (a / "plugin.json").write_text(json.dumps(am, ensure_ascii=False), encoding="utf-8")
        update = package_project(a)
        command(update, ["/install"])
        check((store / "state" / (bm["id"] + ".ini")).read_bytes() == b_record and
              b_entry.read_bytes() == b_bytes, "upgrade A preserves B registration and executable")
        check((a_data / "settings.txt").read_text() == "preserve", "upgrade A preserves user settings")
        command(ae, ["/install"], success=False)
        command(manager, ["/uninstall=" + am["id"]])
        check(not (store / "state" / (am["id"] + ".ini")).exists() and
              b_entry.read_bytes() == b_bytes, "uninstall A keeps B installed")
        check((a_data / "settings.txt").exists(), "ordinary uninstall retains A settings")
        probe = stage / "B-probe.txt"
        probe_env = dict(env, ZW_PLUGIN_DATA_DIR=str(stage / "probe-data"))
        result = subprocess.run([str(b_entry), "/probe=" + str(probe)], env=probe_env,
            creationflags=subprocess.CREATE_NO_WINDOW, timeout=30)
        check(result.returncode == 0 and probe.exists(), "remaining real B EXE executes its probe")
        command(update, ["/install"])
        # A suspended test-owned host runs no CAD initialization or UI.
        busy = subprocess.Popen([str(target / "zw3d.exe")], env=env,
            creationflags=0x00000004 | subprocess.CREATE_NO_WINDOW)
        try:
            original = ribbon.read_bytes()
            command(manager, ["/uninstall=" + am["id"]])
            pending = store / "pending" / am["id"] / "operation.ini"
            check(pending.exists() and ribbon.read_bytes() == original,
                  "running test host defers uninstall without changing active menu")
            command(manager, ["/apply"], success=False)
        finally:
            busy.terminate()
            busy.wait(timeout=10)
        command(manager, ["/apply"])
        check(not (store / "state" / (am["id"] + ".ini")).exists(),
              "deferred uninstall applies after test host exits")
        command(update, ["/install"])
        command(manager, ["/uninstall=" + am["id"], "/purge"])
        check(not a_data.exists() and b_entry.exists(), "purge removes only A data")
    return {"status": "PASS", "scope": "isolated native install/upgrade/uninstall; no CAD GUI",
            "checks": rows}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sdk", type=Path, required=True)
    parser.add_argument("--dll-package", type=Path, required=True)
    parser.add_argument("--exe-package", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    result = acceptance(args.sdk, args.dll_package, args.exe_package)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
