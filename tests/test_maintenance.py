"""Reproduce 0.2.0 review failures against the maintenance release, in isolation."""
import argparse
import ctypes
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
import build_plugin as builder
from package_lib import PackageError, validate_package

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--sdk', type=Path, required=True)
    parser.add_argument('--toolchain', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    out = args.out.resolve(); out.mkdir(parents=True, exist_ok=False)
    dist = ROOT / 'dist/0.2.1'
    env = os.environ.copy(); env['LOCALAPPDATA'] = str(out / 'isolated-data')
    si = subprocess.STARTUPINFO(); si.dwFlags |= subprocess.STARTF_USESHOWWINDOW; si.wShowWindow = 0
    events = []
    def check(condition, name):
        if not condition: raise AssertionError(name)
        events.append(name); print('PASS ' + name, flush=True)
    def inventory(folder):
        # Windows aliases can change displayed letter casing without changing file identity.
        return {p.relative_to(folder).as_posix().lower(): hashlib.sha256(p.read_bytes()).hexdigest()
                for p in folder.rglob('*') if p.is_file()}
    def host(name):
        target = out / name; target.mkdir()
        for file in ('zw3d.exe', 'ZW3D.dll'): shutil.copy2(args.sdk / file, target / file)
        return target
    def run(exe, target, flags, name, success=True):
        log = out / (name + '.log')
        result = subprocess.run([str(exe), '/quiet', '/target=' + str(target), *flags,
                                 '/log=' + str(log)], env=env, startupinfo=si, timeout=60)
        text = log.read_text(encoding='utf-8') if log.exists() else ''
        check((result.returncode == 0) == success, name + ': ' + text.strip())
        return text
    project = out / 'project'; project.mkdir()
    manifest = json.loads((ROOT / 'examples/art-notes/plugin.json').read_text(encoding='utf-8'))
    manifest['version'] = '1.1.1'; manifest['commands'][0]['id'] = 'ArtNotesOPEN'
    (project / 'plugin.json').write_text(json.dumps(manifest, ensure_ascii=False), encoding='utf-8')
    shutil.copytree(dist / 'org.zwtools.art-notes-1.1.0-payload', project / 'payload')
    upgrade = Path(builder.build(project, args.sdk, args.toolchain, out / 'build', False, None)['installer'])
    baseline = dist / 'org.zwtools.art-notes-1.1.0-setup.exe'
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.CreateFileW.argtypes = [ctypes.c_wchar_p, ctypes.c_uint32, ctypes.c_uint32, ctypes.c_void_p,
                                  ctypes.c_uint32, ctypes.c_uint32, ctypes.c_void_p]
    kernel.CreateFileW.restype = ctypes.c_void_p; kernel.CloseHandle.argtypes = [ctypes.c_void_p]
    for locked_case in (False, True):
        target = host('locked' if locked_case else 'normal'); store = target / 'apilibs/ZwPluginHub'
        run(baseline, target, ['/install'], target.name + '-baseline')
        before = inventory(target); lock = None
        if locked_case:
            lock = kernel.CreateFileW(str(target / 'apilibs/icons/~ZpHub_ZwPluginHubManage.png'),
                                     0x80000000, 1, None, 3, 0, None)
            check(lock not in (None, ctypes.c_void_p(-1).value), 'hold management icon')
        try: run(upgrade, target, ['/install'], target.name + '-upgrade', not locked_case)
        finally:
            if lock is not None: kernel.CloseHandle(lock)
        if locked_case:
            check(inventory(target) == before, 'occupied case-change upgrade restores all files')
            run(store / 'HubManager.exe', target, ['/apply'], 'unlocked-apply')
        check((target / 'apilibs/icons/~ZpHub_ArtNotesOPEN.png').is_file(), 'case-change keeps command icon')
        check(not (store / 'transaction/journal.txt').exists(), 'no unrecoverable journal')
    target = host('bad-registry'); store = target / 'apilibs/ZwPluginHub'
    run(baseline, target, ['/install'], 'bad-registry-notes')
    run(dist / 'org.zwtools.art-hello-1.1.0-setup.exe', target, ['/install'], 'bad-registry-hello')
    current = store / 'state/org.zwtools.art-hello.ini'; healthy = current.read_bytes()
    pending = store / 'pending/org.zwtools.art-hello'; pending.mkdir(parents=True)
    (pending / 'operation.ini').write_bytes(healthy + b'operation=install\n')
    current.write_bytes(b'broken')
    probe = out / 'manager-probe.txt'
    text = run(store / 'HubManager.exe', target, ['/ui-probe=' + str(probe)], 'bad-active-valid-pending')
    listed = probe.read_text(encoding='utf-8')
    check('失败' not in text and '优雅问候' in listed and '示例便签' in listed
          and '登记损坏' in listed and '当前登记损坏' in listed, 'complete manager list with damaged current and healthy pending')
    run(store / 'HubManager.exe', out / 'missing-host', ['/ui-probe=' + str(out / 'invalid.txt')], 'invalid-probe', False)
    previous = inventory(out / 'build')
    manifest['commands'][0]['tooltip'] = 'failed rebuild must not publish this change'
    (project / 'plugin.json').write_text(json.dumps(manifest), encoding='utf-8')
    try: builder.build(project, args.sdk, args.toolchain, out / 'build', False, out / 'missing-framework')
    except PackageError: pass
    else: raise AssertionError('missing framework unexpectedly built')
    check(inventory(out / 'build') == previous, 'failed real build leaves complete previous artifacts unchanged')
    builder.build(project, args.sdk, args.toolchain, out / 'build', False, None, True)
    check(not upgrade.exists() and not list((out / 'build').glob('*-build.json'))
          and not list((out / 'build').glob('*-payload')), 'package-only rebuild removes stale full-delivery companions')
    invalid = ROOT / 'verification/review-0.2.0/toolchain/invalid-icon.zwplug'
    if invalid.exists():
        try: validate_package(invalid)
        except PackageError: events.append('previously admitted invalid icon now rejected')
        else: raise AssertionError('invalid PNG still admitted')
    (out / 'result.json').write_text(json.dumps({'status':'PASS', 'events':events,
        'scope':'real installers and helper in isolated host directories; no CAD launched'}, ensure_ascii=False, indent=2), encoding='utf-8')

if __name__ == '__main__': main()
