"""Exercise version evolution with real installers and isolated fake hosts only."""
import ctypes, hashlib, json, os, shutil, subprocess, sys, tempfile, time, zlib, struct
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
import build_plugin as builder
from test_installation import build_busy_host
SDK = Path(r'D:\Program Files\ZWSOFT\ZW3D WuKong 2027')
TOOLS = Path(r'D:\Tools\mingw64')
DIST = ROOT / 'dist/0.2.2'
rows = []
si = subprocess.STARTUPINFO(); si.dwFlags |= subprocess.STARTF_USESHOWWINDOW; si.wShowWindow = 0
def check(ok, name):
    if not ok: raise AssertionError(name)
    rows.append(name); print('PASS ' + name, flush=True)
def inventory(root):
    return {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in root.rglob('*') if p.is_file()}
def recolor(png):
    offset=8; parts=[]
    while offset < len(png):
        size=int.from_bytes(png[offset:offset+4], 'big'); kind=png[offset+4:offset+8]
        data=png[offset+8:offset+8+size]
        if kind == b'IDAT': data=zlib.compress(zlib.decompress(data).replace(bytes((45,114,196,255)), bytes((212,115,35,255))))
        parts.append(struct.pack('>I',len(data))+kind+data+struct.pack('>I',zlib.crc32(kind+data)&0xffffffff));offset+=12+size
    return png[:8]+b''.join(parts)
def main():
    with tempfile.TemporaryDirectory(prefix='evolution-', dir=ROOT/'verification') as temp:
        stage=Path(temp); env=os.environ.copy();env['LOCALAPPDATA']=str(stage/'user-data')
        def run(exe,args,success=True):
            log=stage/'operation.log'
            result=subprocess.run([str(exe),'/quiet',*args,'/log='+str(log)],env=env,startupinfo=si,timeout=60)
            if (result.returncode == 0) != success:
                print(log.read_text(encoding='utf-8'), flush=True)
            check((result.returncode == 0) == success, ('accepted ' if success else 'rejected ')+args[0])
            return log.read_text(encoding='utf-8')
        def target(name):
            root=stage/name;root.mkdir();shutil.copy2(SDK/'zw3d.exe',root/'zw3d.exe');shutil.copy2(SDK/'ZW3D.dll',root/'ZW3D.dll');return root
        def build(project, out, framework=DIST/'framework'):
            return Path(builder.build(project,SDK,TOOLS,out,False,framework)['installer'])
        a=DIST/'org.zwtools.art-hello-1.1.0-setup.exe';b=DIST/'org.zwtools.art-notes-1.1.0-setup.exe'
        root=target('中文 共存'); flag='/target='+str(root);store=root/'apilibs/ZwPluginHub';manager=store/'HubManager.exe'
        run(a,['/install',flag]);run(b,['/install',flag]);original=inventory(root);run(a,['/install',flag])
        check(original == inventory(root),'identical reinstall changes no installed bytes')
        icons=root/'apilibs/icons';helloIcon=icons/'~ZpHub_ArtHelloShow.png'
        check(helloIcon.exists() and (icons/'~ZpHub_ArtNotesOpen.png').exists(),'both commands install independently owned PNG projections')
        run(manager,['/ui-probe='+str(stage/'ui.txt'),flag])
        check((stage/'ui.txt').exists(),'manager probe exercises invalidated target and default data preservation')
        changed=stage/'changed';shutil.copytree(ROOT/'examples/art-hello',changed)
        m=json.loads((changed/'plugin.json').read_text(encoding='utf-8'));m['commands'][0]['label']='另一菜单文字'
        (changed/'plugin.json').write_text(json.dumps(m,ensure_ascii=False),encoding='utf-8');bad=build(changed,stage/'changed-dist')
        before=inventory(root);run(bad,['/install',flag],False);check(inventory(root)==before,'same-version manifest change is rejected without writes')
        m['version']='1.1.1';(changed/'plugin.json').write_text(json.dumps(m,ensure_ascii=False),encoding='utf-8')
        asset=changed/'payload/resources/tool.png';asset.write_bytes(recolor(asset.read_bytes()));upgrade=build(changed,stage/'upgrade-dist')
        noteBytes=(store/'state/org.zwtools.art-notes.ini').read_bytes();noteIcon=(icons/'~ZpHub_ArtNotesOpen.png').read_bytes();oldIcon=helloIcon.read_bytes()
        run(upgrade,['/install',flag]);check(helloIcon.read_bytes()!=oldIcon and helloIcon.read_bytes()==asset.read_bytes(),'independent icon update replaces only its owned projection')
        check(noteBytes==(store/'state/org.zwtools.art-notes.ini').read_bytes() and noteIcon==(icons/'~ZpHub_ArtNotesOpen.png').read_bytes(),'other plugin registry and icon remain unchanged')
        # Synthetic later release: same ABI, a distinguishable valid PE manager, higher metadata version.
        futureBin=stage/'future-runtime';futureBin.mkdir();shutil.copy2(DIST/'framework/ZwPluginHub.dll',futureBin/'ZwPluginHub.dll')
        (futureBin/'HubManager.exe').write_bytes((DIST/'framework/HubManager.exe').read_bytes()+b'\nfuture-release-fixture\n')
        saved=builder.FRAMEWORK_VERSION;builder.FRAMEWORK_VERSION='1.2.0'
        futureProject=stage/'future-project';futureProject.mkdir()
        shutil.copy2(changed/'plugin.json',futureProject/'plugin.json')
        shutil.copytree(stage/'upgrade-dist/org.zwtools.art-hello-1.1.1-payload',futureProject/'payload')
        try: future=build(futureProject,stage/'future-dist',futureBin)
        finally:builder.FRAMEWORK_VERSION=saved
        kernel=ctypes.WinDLL('kernel32',use_last_error=True)
        kernel.CreateFileW.argtypes=[ctypes.c_wchar_p,ctypes.c_uint32,ctypes.c_uint32,ctypes.c_void_p,ctypes.c_uint32,ctypes.c_uint32,ctypes.c_void_p]
        kernel.CreateFileW.restype=ctypes.c_void_p;kernel.CloseHandle.argtypes=[ctypes.c_void_p]
        locked=kernel.CreateFileW(str(root/'apilibs/ZwPluginHub.dll'),0x80000000,1,None,3,0,None)
        check(locked not in (None,ctypes.c_void_p(-1).value),'hold framework DLL without delete sharing')
        before=inventory(root)
        try:
            run(future,['/install',flag],False)
            check(inventory(root)==before,'failed framework replacement restores every installed file')
        finally:kernel.CloseHandle(locked)
        run(future,['/install',flag]);frameworkBytes=(store/'HubManager.exe').read_bytes();run(upgrade,['/install',flag])
        check((store/'HubManager.exe').read_bytes()==frameworkBytes and b'version=1.2.0' in (store/'framework.ini').read_bytes(),'older protocol-aware installer reuses newer compatible framework without downgrade')
        before=inventory(root);(store/'HubManager.exe').write_bytes(frameworkBytes+b'tampered')
        tampered=inventory(root);run(upgrade,['/install',flag],False);check(inventory(root)==tampered,'modified framework is rejected without writes')
        (store/'HubManager.exe').write_bytes(frameworkBytes)
        corrupt=store/'state/org.example.broken.ini';corrupt.write_text('broken',encoding='utf-8')
        run(manager,['/ui-probe='+str(stage/'bad-ui.txt'),flag]);check('登记损坏' in (stage/'bad-ui.txt').read_text(encoding='utf-8'),'manager displays the broken registration alongside healthy plugins');corrupt.unlink()
        before=inventory(root)
        run(manager,['/uninstall=org.zwtools.art-notes','/purge','/initiator=S-1-5-21-0000000000',flag],False)
        check(inventory(root)==before,'different initiating account cannot purge another account data or uninstall implicitly')
        # Running-time migration from the exact verified 0.1.1 predecessor.
        legacy=target('待重启迁移');legacyFlag='/target='+str(legacy)
        run(ROOT/'dist/org.zwtools.art-hello-1.0.0-setup.exe',['/install',legacyFlag])
        oldHub=(legacy/'apilibs/ZwPluginHub.dll').read_bytes();busy=build_busy_host(stage);shutil.copy2(busy,legacy/'zw3d.exe')
        process=subprocess.Popen([str(legacy/'zw3d.exe')],env=env,startupinfo=si)
        try:
            time.sleep(.3);before=inventory(legacy);run(a,['/install',legacyFlag],False)
            check(inventory(legacy)==before,'one-time migration from legacy rejects a running host without writes')
        finally: process.terminate();process.wait(timeout=10)
        run(a,['/install',legacyFlag])
        check((legacy/'apilibs/ZwPluginHub.dll').read_bytes()!=oldHub,'closed legacy host migrates to versioned framework')
        oldHub=(legacy/'apilibs/ZwPluginHub.dll').read_bytes()
        process=subprocess.Popen([str(legacy/'zw3d.exe')],env=env,startupinfo=si)
        try:
            time.sleep(.3);run(future,['/install',legacyFlag])
            check((legacy/'apilibs/ZwPluginHub.dll').read_bytes()==oldHub,'running upgrade does not replace the active framework')
            check((legacy/'apilibs/ZwPluginHub/framework-next/metadata.ini').exists(),'framework and plugin upgrade requests are durably staged')
            queued=inventory(legacy);run(a,['/install',legacyFlag],False)
            check(inventory(legacy)==queued,'older plugin installer cannot overwrite a newer queued plugin request')
        finally: process.terminate();process.wait(timeout=10)
        deadline=time.monotonic()+30;newStore=legacy/'apilibs/ZwPluginHub'
        while time.monotonic()<deadline and (not (newStore/'framework.ini').exists() or (newStore/'pending/org.zwtools.art-hello/operation.ini').exists()):time.sleep(.2)
        check((newStore/'framework.ini').exists() and not (newStore/'pending/org.zwtools.art-hello/operation.ini').exists(),'background updater commits framework then business version after host exit')
        check(b'version=1.1.1' in (newStore/'state/org.zwtools.art-hello.ini').read_bytes(),'plugin and its icon version upgrade after framework commit')
        # Cancel a queued uninstall; the active state and menus stay intact.
        process=subprocess.Popen([str(legacy/'zw3d.exe')],env=env,startupinfo=si)
        try:
            time.sleep(.3);active=(newStore/'state/org.zwtools.art-hello.ini').read_bytes();newManager=newStore/'HubManager.exe'
            run(newManager,['/uninstall=org.zwtools.art-hello',legacyFlag]);run(newManager,['/cancel=org.zwtools.art-hello',legacyFlag])
            check((newStore/'state/org.zwtools.art-hello.ini').read_bytes()==active and not (newStore/'pending/org.zwtools.art-hello/operation.ini').exists(),'cancel pending uninstall keeps current plugin unchanged')
        finally:process.terminate();process.wait(timeout=10)
        executable=DIST/'org.zwtools.art-notes-1.1.0-payload/ArtNotes.exe';notesEnv=env.copy();notesEnv['ZW_PLUGIN_DATA_DIR']=str(stage/'notes-settings')
        log=stage/'notes-test.txt';result=subprocess.run([str(executable),'/self-test='+str(log)],env=notesEnv,startupinfo=si,timeout=20)
        check(result.returncode==0 and log.read_text().startswith('PASS'),'real notes EXE preserves legacy backup and round-trips Chinese settings')
        run(manager,['/uninstall=org.zwtools.art-hello',flag]);check(not helloIcon.exists() and (icons/'~ZpHub_ArtNotesOpen.png').read_bytes()==noteIcon,'uninstall removes its icon and keeps the other plugin')
    (ROOT/'verification/evolution-0.2.2-result.json').write_text(json.dumps({'status':'PASS','cases':rows,'limits':['Future release is a synthetic ABI fixture, not a shipped release.','Fake hosts verify file and process lifecycle; actual 2027 rendering requires separate acceptance.']},ensure_ascii=False,indent=2),encoding='utf-8')
    print('PASS evolution acceptance',flush=True)
if __name__=='__main__':main()
