"""Read SDK group state in an owned empty session; keep installed plugins intact.

No mouse input or rendering claim. The only installed test file is a temporary
probe, removed after the owned host exits. Existing startup log bytes are restored.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def host_closed(sdk):
    result = subprocess.run(
        ['powershell', '-NoProfile', '-Command',
         'Get-Process zw3d -ErrorAction SilentlyContinue | ForEach-Object { $_.Path }'],
        capture_output=True, text=True, check=False)
    if str(sdk / 'zw3d.exe').casefold() in result.stdout.casefold():
        raise RuntimeError('Close the target 2027 before this test; user sessions are never stopped')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--sdk', type=Path, required=True)
    parser.add_argument('--toolchain', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--expect-groups-visible', type=int, choices=(0, 1),
                        help='Optional strict check, mainly for an activated interactive page')
    parser.add_argument('--interactive', action='store_true',
                        help='Show an owned host and wait up to 120 seconds for you to select its plugin page')
    args = parser.parse_args()
    sdk, out = args.sdk.resolve(), args.out.resolve()
    if not out.is_relative_to((ROOT / 'verification').resolve()) or out.exists():
        raise RuntimeError('Use a fresh result folder inside verification')
    host_closed(sdk)
    apilibs = sdk / 'apilibs'
    probe = apilibs / 'ZzHubAcceptanceProbe.dll'
    if probe.exists():
        raise RuntimeError('Test probe already exists; do not replace it')
    # Exclude unrelated data and secrets; only record plugin/UI integrity.
    before = {p: digest(p) for p in apilibs.rglob('*')
              if p.is_file() and p.suffix.lower() in ('.dll', '.exe', '.zcui', '.ini', '.txt')}
    profiles = Path(os.environ['APPDATA']) / 'ZWSOFT/ZW3D' / sdk.name / 'custom/profiles'
    profile_before = {p: digest(p) for p in profiles.rglob('*.zcui')} if profiles.exists() else {}
    key = hashlib.sha256(str(sdk).lower().encode('utf8')).hexdigest()[:16]
    data_root = Path(os.environ['LOCALAPPDATA']) / 'ZwPluginHub' / key
    dirs = [data_root / name for name in
            ('org.zwtools.plugin-hub', 'org.zwtools.art-hello', 'org.zwtools.art-notes')]
    previous_dirs = {p: p.exists() for p in [data_root.parent, data_root, *dirs]}
    log = dirs[0] / 'startup.log'
    old_log = log.read_bytes() if log.exists() else None
    out.mkdir(parents=True)
    si = subprocess.STARTUPINFO()
    si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    si.wShowWindow = 1 if args.interactive else 0
    live, probe_hash = None, None
    try:
        with tempfile.TemporaryDirectory(prefix='hub_group_probe_') as tmp:
            stage = Path(tmp)
            shutil.copytree(ROOT / 'framework', stage / 'framework')
            (stage / 'tests').mkdir()
            shutil.copy2(ROOT / 'tests/native_probe.cpp', stage / 'tests/native_probe.cpp')
            binary = stage / probe.name
            subprocess.run([
                str(args.toolchain / 'bin/g++.exe'), '-std=c++17', '-shared', '-static',
                '-m64', '-DUNICODE', '-D_UNICODE', '-I' + str(sdk / 'api/inc'),
                str(stage / 'tests/native_probe.cpp'), str(sdk / 'ZW3D.lib'),
                '-lbcrypt', '-lversion', '-lshell32', '-ladvapi32', '-o', str(binary)],
                check=True)
            probe_hash = digest(binary)
            host_closed(sdk)
            shutil.copy2(binary, probe)
        env = os.environ.copy()
        env.update(ZW_HUB_PROBE=str(out / 'host.log'),
                   ZW_HUB_DEMO_LOG=str(out / 'dll.log'),
                   ZW_HUB_EXE_PROBE=str(out / 'exe.log'))
        env.pop('ZW3D_BATCHSAVE_JOB', None)
        env.pop('ZW_TOOLBOX_PROBE', None)
        env.pop('ZW_HUB_REQUIRE_PAGE_SELECTION', None)
        if args.interactive:
            env['ZW_HUB_REQUIRE_PAGE_SELECTION'] = '1'
            print('Select the new 小插件 page in this empty test window; do not open a model.', flush=True)
        live = subprocess.Popen([str(sdk / 'zw3d.exe')], cwd=sdk, env=env, startupinfo=si)
        deadline = time.monotonic() + 150
        while not (out / 'host.log').exists() and time.monotonic() < deadline:
            if live.poll() is not None:
                raise RuntimeError('Owned host exited before callback: ' + str(live.returncode))
            time.sleep(1)
        if not (out / 'host.log').exists():
            raise RuntimeError('Owned host callback timed out')
        lines = (out / 'host.log').read_text(encoding='utf8').splitlines()
        group_values = {}
        for group in ('HubManagementGroup', 'HubPlugin_ArtHello', 'HubPlugin_ArtNotes'):
            records = [line for line in lines if line.startswith(f'group|{group}|')]
            if len(records) != 1 or records[0].split('|')[2] != '0' or records[0].split('|')[3] not in ('0','1'):
                raise AssertionError('SDK parent group missing or invalid: ' + group)
            group_values[group] = int(records[0].split('|')[3])
            if args.expect_groups_visible is not None and group_values[group] != args.expect_groups_visible:
                raise AssertionError('SDK parent group value differs: ' + group)
        for record in ('page|0|1', 'manager|0|1', 'module|ArtHello|1',
                       'action|ArtHelloShow|0|1', 'action|ArtNotesOpen|0|1'):
            if lines.count(record) != 1:
                raise AssertionError('SDK state mismatch: ' + record)
        for name in ('dll.log', 'exe.log'):
            if not (out / name).exists() or '|ok' not in (out / name).read_text():
                raise AssertionError('Command not executed: ' + name)
        for kind in ('page', 'group', 'control'):
            records = [s for s in lines if s.startswith('negative|' + kind + '|')]
            if len(records) != 1 or int(records[0].split('|')[2]) == 0:
                raise AssertionError('Missing object reported successful: ' + kind)
        result = {'status': 'PASS', 'groupVisibility': group_values,
                  'verification': 'SDK states and DLL command; EXE direct CLI probe. No toolbar click or rendered UI check.'}
        (out / 'result.json').write_text(json.dumps(result, indent=2), encoding='utf8')
        print(json.dumps(result), flush=True)
    finally:
        if live and live.poll() is None:
            live.terminate()
            live.wait(timeout=20)
        if probe.exists():
            if probe.resolve().parent != apilibs.resolve() or digest(probe) != probe_hash:
                raise RuntimeError('Probe changed; refusing cleanup')
            probe.unlink()
        if old_log is None:
            if log.exists():
                log.unlink()
        else:
            log.write_bytes(old_log)
        for directory in [*dirs, data_root, data_root.parent]:
            if not previous_dirs[directory] and directory.exists() and not any(directory.iterdir()):
                directory.rmdir()
        for path, checksum in before.items():
            if not path.is_file() or digest(path) != checksum:
                raise RuntimeError('Installed plugin/interface changed during probe: ' + str(path))
        profile_after = {p: digest(p) for p in profiles.rglob('*.zcui')} if profiles.exists() else {}
        if profile_after != profile_before:
            raise RuntimeError('User profile changed during probe; inspect evidence before continuing')
        if (out / 'result.json').exists():
            result = json.loads((out / 'result.json').read_text())
            result['unchangedProfileFiles'] = len(profile_before)
            (out / 'result.json').write_text(json.dumps(result, indent=2), encoding='utf8')
        host_closed(sdk)


if __name__ == '__main__':
    main()
