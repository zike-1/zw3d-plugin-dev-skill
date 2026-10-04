"""Exercise actual repair controls/EXEs against isolated copies of a host."""
import argparse, ctypes, hashlib, json, os, shutil, subprocess, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tests'))
from test_installation import build_busy_host

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--dist', type=Path, default=ROOT / 'dist/0.2.2')
    parser.add_argument('--notes-version', default='1.1.0')
    args = parser.parse_args()
    out = args.out.resolve(); out.mkdir(parents=True, exist_ok=False)
    sdk = Path('D:/Program Files/ZWSOFT/ZW3D WuKong 2027')
    dist = args.dist.resolve()
    env = os.environ.copy(); env['LOCALAPPDATA'] = str(out / 'user-data')
    si = subprocess.STARTUPINFO(); si.dwFlags |= subprocess.STARTF_USESHOWWINDOW; si.wShowWindow = 0
    rows = []
    def check(ok, label):
        if not ok: raise AssertionError(label)
        rows.append(label); print('PASS ' + label, flush=True)
    def inventory(folder):
        return {p.relative_to(folder).as_posix().lower(): hashlib.sha256(p.read_bytes()).hexdigest()
                for p in folder.rglob('*') if p.is_file()}
    def run(exe, target, operation, name, success=True):
        log = out / (name + '.log')
        r = subprocess.run([str(exe), '/quiet', '/target=' + str(target), operation,
                            '/log=' + str(log)], env=env, startupinfo=si, timeout=60)
        text = log.read_text(encoding='utf-8') if log.exists() else ''
        check((r.returncode == 0) == success, name + ': ' + text.strip())
        return text
    def host(name):
        target = out / name; target.mkdir()
        for file in ('zw3d.exe', 'ZW3D.dll'): shutil.copy2(sdk / file, target / file)
        for stem in ('art-hello-1.1.0', 'art-notes-' + args.notes_version):
            run(dist / ('org.zwtools.' + stem + '-setup.exe'), target, '/install', name + '-' + stem)
        return target, target / 'apilibs/ZwPluginHub'
    source = 'state/org.zwtools.art-hello.ini'
    target, store = host('中文 修复')
    manager = store / 'HubManager.exe'; current = store / source
    healthy = current.read_bytes(); note_before = inventory(store / 'plugins/org.zwtools.art-notes')
    key = hashlib.sha256(str(target).lower().encode('utf-8')).hexdigest()[:16]
    data = Path(env['LOCALAPPDATA']) / 'ZwPluginHub' / key / 'org.zwtools.art-hello'
    data.mkdir(parents=True); (data / 'settings.txt').write_text('私人设置保留', encoding='utf-8')
    damaged = b'broken'; current.write_bytes(damaged)
    run(manager, target, '/ui-probe=' + str(out / 'ui.txt'), 'repair-controls')
    check('登记损坏' in (out / 'ui.txt').read_text(encoding='utf-8'), 'damaged row exposes repair/isolate and invalidates selection on target change')
    run(manager, target, '/repair=' + source, 'verified-repair')
    check(current.read_bytes() == healthy, 'repair restores exact verified descriptor')
    check(any(p.read_bytes() == damaged for p in (store / 'recovery').rglob('org.zwtools.art-hello.ini')), 'original damaged registry retained in backup')
    check(inventory(store / 'plugins/org.zwtools.art-notes') == note_before and
          (data / 'settings.txt').read_text(encoding='utf-8') == '私人设置保留', 'other payload and private settings unchanged')
    before = inventory(target)
    run(manager, target, '/repair=' + source, 'healthy-repair-rejected', False)
    run(manager, target, '/isolate=state/../../ZW3D.dll', 'path-escape-rejected', False)
    check(inventory(target) == before, 'valid state and unsafe paths cannot be modified')
    # A locked projection must not leave a repaired state or partially published backup.
    current.write_bytes(damaged); before = inventory(target)
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.CreateFileW.argtypes = [ctypes.c_wchar_p, ctypes.c_uint32, ctypes.c_uint32, ctypes.c_void_p, ctypes.c_uint32, ctypes.c_uint32, ctypes.c_void_p]
    kernel.CreateFileW.restype = ctypes.c_void_p; kernel.CloseHandle.argtypes = [ctypes.c_void_p]
    lock = kernel.CreateFileW(str(target / 'apilibs/icons/~ZpHub_ZwPluginHubManage.png'), 0x80000000, 1, None, 3, 0, None)
    check(lock not in (None, ctypes.c_void_p(-1).value), 'hold icon for repair rollback')
    try: run(manager, target, '/repair=' + source, 'occupied-repair-rejected', False)
    finally: kernel.CloseHandle(lock)
    check(inventory(target) == before and not (store / 'transaction/journal.txt').exists(), 'repair failure rolls back state, menus and backup files')
    run(manager, target, '/repair=' + source, 'repair-retry')
    original_entry = store / 'plugins/org.zwtools.art-hello/1.1.0/ArtHello.dll'
    entry_bytes = original_entry.read_bytes(); current.write_bytes(damaged)
    original_entry.write_bytes(entry_bytes + b'externally-changed')
    before = inventory(target)
    run(manager, target, '/repair=' + source, 'changed-payload-rejected', False)
    check(inventory(target) == before, 'payload hash mismatch cannot become a recovery source')
    original_entry.write_bytes(entry_bytes)
    run(manager, target, '/repair=' + source, 'repair-after-restoring-payload')
    # Multiple complete versions must not cause an arbitrary downgrade or latest-version guess.
    run(dist / 'org.zwtools.art-hello-1.1.1-setup.exe', target, '/install', 'upgrade-hello')
    current.write_bytes(damaged); before = inventory(target)
    run(manager, target, '/repair=' + source, 'ambiguous-repair-rejected', False)
    check(inventory(target) == before, 'ambiguous version leaves all installed files unchanged')
    payload_before = inventory(store / 'plugins')
    run(manager, target, '/isolate=' + source, 'isolate-ambiguous-state')
    check(not current.exists() and inventory(store / 'plugins') == payload_before, 'isolation preserves both versions and other plugin payload')
    check('ID_ZpHub_ArtHelloShow' not in (target / 'apilibs/Settings/Default/ResourcePool/ZwPluginHubActions.zcui').read_text(encoding='utf-8'), 'isolated command removed from menus')
    run(dist / 'org.zwtools.art-hello-1.1.1-setup.exe', target, '/install', 'reinstall-isolated')
    check((data / 'settings.txt').exists(), 'reinstall after isolation keeps personal settings')
    # An identifiable original version may be restored even with historical versions present.
    current.write_bytes(b'version=1.1.0\nname=damaged\n')
    run(manager, target, '/repair=' + source, 'identified-original-version')
    check(current.read_bytes() == healthy, 'known version is restored instead of choosing newest')
    # A healthy pending install is preserved, and maintenance runs before that install.
    own_pending = store / 'pending/org.zwtools.art-hello'; own_pending.mkdir(parents=True)
    (own_pending / 'operation.ini').write_bytes(healthy + b'operation=install\n')
    version = store / 'plugins/org.zwtools.art-hello/1.1.0'
    shutil.copy2(version / 'files.txt', own_pending / 'files.txt')
    (own_pending / 'payload/resources').mkdir(parents=True)
    shutil.copy2(version / 'ArtHello.dll', own_pending / 'payload/ArtHello.dll')
    shutil.copy2(version / 'resources/tool.png', own_pending / 'payload/resources/tool.png')
    pending_before = inventory(own_pending); current.write_bytes(b'version=1.1.0\nname=broken\n')
    before = inventory(target)
    run(manager, target, '/isolate=' + source, 'isolate-with-pending-rejected', False)
    check(inventory(target) == before, 'isolation cannot silently keep a request that would reactivate its plugin')
    run(manager, target, '/repair=' + source, 'repair-with-healthy-pending')
    check(inventory(own_pending) == pending_before, 'repair preserves the healthy pending install byte for byte')
    run(manager, target, '/apply', 'apply-preserved-install')
    check(current.read_bytes() == healthy and not (own_pending / 'operation.ini').exists(), 'pending install completes after registry repair')
    # A damaged request cannot have its lost intent reconstructed. Quarantine backs up all bytes.
    pending = store / 'pending/org.example.broken'; pending.mkdir(parents=True)
    (pending / 'operation.ini').write_bytes(damaged)
    (pending / 'payload').mkdir(); (pending / 'payload/private.bin').write_bytes(b'preserve-request-payload')
    request_before = inventory(pending); before = inventory(target)
    bad_source = 'pending/org.example.broken/operation.ini'
    run(manager, target, '/repair=' + bad_source, 'lost-intent-repair-rejected', False)
    check(inventory(target) == before, 'lost intent failure preserves every request byte')
    run(manager, target, '/isolate=' + bad_source, 'isolate-bad-pending')
    backups = list((store / 'recovery').glob('*/original/pending/org.example.broken'))
    check(len(backups) == 1 and inventory(backups[0]) == request_before and not list(pending.rglob('*.*')), 'entire damaged request preserved outside pending queue')
    # Simulate the owned host process to cover waiting, cancellation and safe startup apply.
    busy_stage = out / 'busy-source'; busy_stage.mkdir(); busy = build_busy_host(busy_stage)
    busy_target, busy_store = host('等待重启')
    shutil.copy2(busy, busy_target / 'zw3d.exe')
    busy_manager = busy_store / 'HubManager.exe'; broken = busy_store / source
    pristine = broken.read_bytes(); broken.write_bytes(damaged)
    child = subprocess.Popen([str(busy_target / 'zw3d.exe')], env=env, startupinfo=si)
    try:
        run(busy_manager, busy_target, '/repair=' + source, 'defer-repair')
        check(broken.read_bytes() == damaged and len(list((busy_store / 'maintenance').glob('*.ini'))) == 1, 'live host state unchanged and one repair queued')
        run(busy_manager, busy_target, '/cancel-maintenance=' + source, 'cancel-repair')
        check(broken.read_bytes() == damaged and not list((busy_store / 'maintenance').glob('*.ini')), 'cancel keeps original damage and payload')
        run(busy_manager, busy_target, '/repair=' + source, 'queue-repair-again')
        run(busy_manager, busy_target, '/apply', 'cannot-apply-in-running-host', False)
    finally: child.terminate(); child.wait(timeout=10)
    run(busy_manager, busy_target, '/apply', 'apply-after-exit')
    check(broken.read_bytes() == pristine and not list((busy_store / 'maintenance').glob('*.ini')), 'queued repair commits after host exit and request removed atomically')
    child = subprocess.Popen([str(busy_target / 'zw3d.exe')], env=env, startupinfo=si)
    try:
        broken.write_bytes(damaged)
        run(busy_manager, busy_target, '/repair=' + source, 'queue-stale-repair')
        broken.write_bytes(pristine)
    finally: child.terminate(); child.wait(timeout=10)
    before = inventory(busy_target)
    run(busy_manager, busy_target, '/apply', 'reject-changed-record', False)
    check(inventory(busy_target) == before, 'changed record never overwritten by stale maintenance request')
    run(busy_manager, busy_target, '/ui-probe=' + str(out / 'stale-ui.txt'), 'stale-request-ui')
    check('待修复／隔离' in (out / 'stale-ui.txt').read_text(encoding='utf-8'), 'stale request remains visible and cancellable when state became healthy')
    run(busy_manager, busy_target, '/cancel-maintenance=' + source, 'cancel-stale-request')
    (out / 'result.json').write_text(json.dumps({'status': 'PASS', 'checks': rows,
        'scope': 'real installers and manager controls; isolated copied host and owned fake process; no real CAD UI clicks'}, ensure_ascii=False, indent=2), encoding='utf-8')

if __name__ == '__main__': main()
