"""Run the production Hub startup with mock SDK calls and real isolated helpers.

This tests the startup gate, not real CAD menu parsing or the SDK loader ABI.
Only fixture compilation replaces ShellExecute/Wait/MessageBox boundaries.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile


ROOT = Path(__file__).resolve().parents[1]
OWNER = "zw3d-plugin-dev-skill.tests.startup-handshake"


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def checksum(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def hidden_startup():
    startup = subprocess.STARTUPINFO()
    startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    startup.wShowWindow = 0
    return startup


def compile_fixtures(stage: Path, toolchain: Path) -> dict[str, Path]:
    compiler = toolchain / "bin" / "g++.exe"
    require(compiler.is_file(), "MinGW root must contain bin/g++.exe")
    native = ROOT / "tests" / "native"
    framework = stage / "framework"
    shutil.copytree(ROOT / "framework", framework)
    flags = [str(compiler), "-std=c++17", "-O2", "-m64", "-DUNICODE", "-D_UNICODE",
             "-static", "-static-libgcc", "-static-libstdc++", "-Wl,--no-insert-timestamp"]
    outputs = {}
    for name, source, dll in (("hub", "startup_sdk_shim.cpp", True),
                              ("host", "startup_host.cpp", False),
                              ("manager", "startup_manager.cpp", False),
                              ("business", "startup_business.cpp", True)):
        destination = stage / (name + (".dll" if dll else ".exe"))
        command = [*flags, *( ["-shared"] if dll else ["-municode"] ),
                   "-I" + str(framework), "-I" + str(native / "mock_sdk"), str(native / source),
                   "-lbcrypt", "-lversion", "-lshell32", "-ladvapi32", "-lole32", "-luser32",
                   "-o", str(destination)]
        completed = subprocess.run(command, cwd=stage, capture_output=True, text=True,
                                   encoding="utf-8", errors="replace", timeout=120,
                                   startupinfo=hidden_startup())
        require(completed.returncode == 0, completed.stdout + completed.stderr)
        outputs[name] = destination
    return outputs


def make_target(stage: Path, name: str, binaries: dict[str, Path], sdk: Path) -> Path:
    target = stage / name
    plugins = target / "apilibs" / "ZwPluginHub" / "plugins" / "org.zwtools.art-fixture" / "1.0.0"
    plugins.mkdir(parents=True)
    # Version/existence checks use real installed SDK files, which are never executed here.
    shutil.copy2(sdk / "zw3d.exe", target / "zw3d.exe")
    shutil.copy2(sdk / "ZW3D.dll", target / "ZW3D.dll")
    shutil.copy2(binaries["hub"], target / "apilibs" / "ZwPluginHub.dll")
    shutil.copy2(binaries["manager"], target / "apilibs" / "ZwPluginHub" / "HubManager.exe")
    shutil.copy2(binaries["business"], plugins / "ArtFixture.dll")
    descriptor = ("schema=1\nid=org.zwtools.art-fixture\nname=Fixture\nversion=1.0.0\n"
                  "prefix=ArtFixture\ntype=dll\nentry=ArtFixture.dll\nhotUnload=0\ncommands=1\n"
                  "cmd.0.id=ArtFixtureShow\ncmd.0.label=Fixture\n"
                  "cmd.0.environments=top,part,assembly,drawing\napi.count=0\n")
    state = target / "apilibs" / "ZwPluginHub" / "state"
    state.mkdir()
    (state / "org.zwtools.art-fixture.ini").write_text(descriptor, encoding="utf-8")
    (plugins / "descriptor.ini").write_text(descriptor, encoding="utf-8")
    business = plugins / "ArtFixture.dll"
    (plugins / "files.txt").write_text(f"ArtFixture.dll|{business.stat().st_size}|{checksum(business)}\n",
                                       encoding="utf-8")
    return target


def run_case(stage: Path, binaries: dict[str, Path], sdk: Path, name: str,
             scenario: str = "success", unfinished: bool = False,
             missing_manager: bool = False, broken_registry: bool = False,
             maintenance: bool = False) -> dict:
    target = make_target(stage, name, binaries, sdk)
    store = target / "apilibs" / "ZwPluginHub"
    if maintenance:
        (store / "maintenance").mkdir()
        (store / "maintenance" / "fixture.ini").write_text("fixture request; application tested by real manager separately\n", encoding="utf-8")
    if broken_registry:
        (store / "state" / "org.example.broken.ini").write_text("broken record", encoding="utf-8")
    if unfinished:
        transaction = store / "transaction"
        transaction.mkdir()
        (transaction / "journal.txt").write_text("fixture marker; restoration tested separately\n", encoding="utf-8")
    if missing_manager:
        (store / "HubManager.exe").unlink()
    event_log = target / "events.txt"
    environment = os.environ.copy()
    environment.update(ZW_HUB_FIXTURE_EVENTS=str(event_log), ZW_HUB_FIXTURE_SCENARIO=scenario,
                       LOCALAPPDATA=str(target / "user-data"))
    completed = subprocess.run([str(binaries["host"]), str(target / "apilibs" / "ZwPluginHub.dll")],
                               cwd=target, env=environment, capture_output=True, text=True,
                               encoding="utf-8", errors="replace", timeout=15,
                               startupinfo=hidden_startup())
    require(completed.returncode == 0, f"{name}: fixture host failed: {completed.returncode} {completed.stderr}")
    observed = json.loads(completed.stdout.strip())
    events = event_log.read_text(encoding="utf-8").splitlines()
    require("MANAGER_DISPATCH" in events, f"{name}: startup skipped the manager handshake")
    require(observed["managerRegistered"] == 1, f"{name}: recovery manager entry was not available")
    success = scenario == "success" and not missing_manager
    if success:
        require(observed["dataDirectoryResult"] == 0,
                f"{name}: healthy plugin data lookup was blocked by another record")
        require(observed["queued"] == 1 and observed["finalLoads"] == 1,
                f"{name}: successful handshake did not load exactly one business plugin: {observed}")
        require(events.index("MANAGER_FINISHED_SUCCESS") < events.index("QUEUE_BUSINESS_START")
                < events.index("SDK_BUSINESS_LOAD"), f"{name}: loading preceded completed handshake")
        require(events.index("HANDSHAKE_PROCESS_ENDED") < events.index("SDK_BUSINESS_LOAD"),
                f"{name}: business code loaded before the manager process actually exited")
        require("BUSINESS_DLL_MAPPED" in events and "BUSINESS_INIT" in events,
                f"{name}: fake business DLL did not actually initialize")
        if broken_registry:
            logs = list((target / "user-data").rglob("startup.log"))
            require(len(logs) == 1 and "registry:org.example.broken.ini" in logs[0].read_text(encoding="utf-8"),
                    "Bad registry was not reported separately from healthy loading")
    else:
        require(observed["beforeHelperExit"] == 0 and observed["finalLoads"] == 0,
                f"{name}: failed handshake actually loaded business code: {observed}")
        require("SDK_BUSINESS_LOAD" not in events and "BUSINESS_DLL_MAPPED" not in events,
                f"{name}: business code loaded in a blocked session")
    if unfinished:
        require("MANAGER_SAW_UNFINISHED_TRANSACTION" in events,
                "No-pending unfinished transaction did not reach the external manager")
    if maintenance:
        logs = list((target / "user-data").rglob("startup.log"))
        require(len(logs) == 1 and ("pending|applied" if success else "pending|deferred") in
                logs[0].read_text(encoding="utf-8"), "Maintenance queue not recognized by production startup gate")
    if scenario == "timeout":
        require(observed["helperAlive"] == 1 and "HANDSHAKE_TIMED_OUT" in events,
                "Timeout did not exercise a helper that was still running")
        require("MANAGER_FINISHED_SUCCESS" in events,
                "Slow helper never finished; post-timeout session guard was not exercised")
    return {"case": name, "status": "PASS", "observed": observed, "events": events}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sdk", type=Path, required=True)
    parser.add_argument("--toolchain", type=Path, required=True)
    parser.add_argument("--out", type=Path, default=ROOT / "tests" / "startup-handshake-result.json")
    args = parser.parse_args()
    require(os.name == "nt", "This native fixture test requires Windows")
    sdk, toolchain = args.sdk.resolve(), args.toolchain.resolve()
    require((sdk / "zw3d.exe").is_file() and (sdk / "ZW3D.dll").is_file(), "Select an installed SDK")
    stage = Path(tempfile.mkdtemp(prefix=".startup-handshake-", dir=ROOT / "tests"))
    marker = stage / ".fixture-owner.json"
    marker.write_text(json.dumps({"owner": OWNER}), encoding="utf-8")
    report = {"owner": OWNER, "status": "FAIL", "results": [],
              "hubSourceSha256": checksum(ROOT / "framework" / "ZwPluginHub.cpp"),
              "limitations": ["Mock SDK validates the startup gate, not real CAD loading or menus.",
                              "Fixture launch suppresses UAC and shortens waits only at compile time.",
                              "The unfinished marker verifies dispatch; real recovery is tested separately."]}
    try:
        binaries = compile_fixtures(stage, toolchain)
        for name, options in (("success_without_pending", {}),
                              ("broken_registry_keeps_healthy_plugin", {"broken_registry": True}),
                              ("unfinished_without_pending", {"unfinished": True}),
                              ("maintenance_without_business_pending", {"maintenance": True}),
                              ("maintenance_apply_failure", {"maintenance": True, "scenario": "failure"}),
                              ("manager_exit_failure", {"scenario": "failure"}),
                              ("manager_timeout_still_running", {"scenario": "timeout"}),
                              ("manager_launch_failure", {"missing_manager": True})):
            report["results"].append(run_case(stage, binaries, sdk, name, **options))
            print("PASS " + name, flush=True)
        report["status"] = "PASS"
    except (AssertionError, OSError, ValueError, subprocess.SubprocessError) as error:
        report["error"] = str(error)
        print("FAIL " + str(error), flush=True)
    finally:
        # The absolute, owned fixture is checked before recursive cleanup. SDK sources stay untouched.
        require(stage.resolve().is_relative_to((ROOT / "tests").resolve())
                and stage.name.startswith(".startup-handshake-")
                and json.loads(marker.read_text(encoding="utf-8")) == {"owner": OWNER},
                "Fixture cleanup path is not owned")
        shutil.rmtree(stage)
        args.out.write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
