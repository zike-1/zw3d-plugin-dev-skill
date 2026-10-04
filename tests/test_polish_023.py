"""Verify icon linkage and upgrading the notes EXE without touching user CAD."""
import hashlib, json, os, shutil, subprocess, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'tools'))
from inspect_installer import inspect, inspect_application_icon

def main():
    out = ROOT/'verification/polish-0.2.3'; out.mkdir(exist_ok=False)
    sdk = Path('D:/Program Files/ZWSOFT/ZW3D WuKong 2027')
    dist = ROOT/'dist/0.2.3'; framework = ROOT/'work/candidate-0.2.3/framework'
    events = []
    def check(ok, why):
        if not ok: raise AssertionError(why)
        events.append(why); print('PASS '+why, flush=True)
    for package in dist.glob('*.zwplug'):
        inspect(package.with_name(package.stem+'-setup.exe'), package, framework, sdk)
        check(True, 'installer command PNG and manager icon match: '+package.stem)
    png = (ROOT/'examples/art-notes/payload/resources/tool.png').read_bytes()
    notes = dist/'org.zwtools.art-notes-1.1.1-payload/ArtNotes.exe'
    inspect_application_icon(notes.read_bytes(), png)
    check(True, 'notes executable icon uses exact package PNG')
    target=out/'中文 升级测试';target.mkdir()
    for name in ('zw3d.exe','ZW3D.dll'):shutil.copy2(sdk/name,target/name)
    env=os.environ.copy();env['LOCALAPPDATA']=str(out/'data')
    si=subprocess.STARTUPINFO();si.dwFlags|=subprocess.STARTF_USESHOWWINDOW;si.wShowWindow=0
    def run(exe, flag, label):
        log=out/(label+'.txt')
        r=subprocess.run([str(exe),'/quiet','/target='+str(target),flag,'/log='+str(log)],env=env,startupinfo=si,timeout=60)
        check(r.returncode==0,label+': '+log.read_text(encoding='utf-8').strip())
    run(ROOT/'dist/0.2.2/org.zwtools.art-hello-1.1.1-setup.exe','/install','old-hello')
    run(ROOT/'dist/0.2.2/org.zwtools.art-notes-1.1.0-setup.exe','/install','old-notes')
    store=target/'apilibs/ZwPluginHub'
    hello={p:p.read_bytes() for p in (store/'plugins/org.zwtools.art-hello').rglob('*') if p.is_file()}
    hello[store/'state/org.zwtools.art-hello.ini']=(store/'state/org.zwtools.art-hello.ini').read_bytes()
    hello[target/'apilibs/icons/~ZpHub_ArtHelloShow.png']=(target/'apilibs/icons/~ZpHub_ArtHelloShow.png').read_bytes()
    key=hashlib.sha256(str(target).lower().encode('utf-8')).hexdigest()[:16]
    notesdata=Path(env['LOCALAPPDATA'])/'ZwPluginHub'/key/'org.zwtools.art-notes';notesdata.mkdir(parents=True)
    setting='ZWN1\n旧版便签内容，升级应保留\r\n第二行'.encode('utf-8');(notesdata/'settings.txt').write_bytes(setting)
    run(dist/'org.zwtools.art-notes-1.1.1-setup.exe','/install','upgrade-notes')
    check(all(p.read_bytes()==b for p,b in hello.items()),'notes/framework update keeps hello payload, state and icon unchanged')
    check((notesdata/'settings.txt').read_bytes()==setting,'old saved Chinese text remains byte-identical')
    check(b'version=1.1.1' in (store/'state/org.zwtools.art-notes.ini').read_bytes() and
          b'version=1.1.3' in (store/'framework.ini').read_bytes(),'new notes and independent framework versions committed')
    run(store/'HubManager.exe','/ui-probe='+str(out/'ui.txt'),'manager-icons')
    check('示例便签' in (out/'ui.txt').read_text(encoding='utf-8'),'manager still lists both plugins with window icon checks passed')
    run(dist/'org.zwtools.art-notes-1.1.1-setup.exe','/install','repeat-notes')
    run(store/'HubManager.exe','/uninstall=org.zwtools.art-notes','remove-notes')
    check((notesdata/'settings.txt').read_bytes()==setting and all(p.read_bytes()==b for p,b in hello.items()),'ordinary notes uninstall preserves data and other plugin')
    run(dist/'org.zwtools.art-notes-1.1.1-setup.exe','/install','reinstall-notes')
    check((notesdata/'settings.txt').read_bytes()==setting,'notes reinstall retains saved text')
    selfenv=env.copy();selfenv['ZW_PLUGIN_DATA_DIR']=str(out/'isolated-settings')
    r=subprocess.run([str(notes),'/self-test='+str(out/'notes-self-test.txt')],env=selfenv,startupinfo=si,timeout=15)
    check(r.returncode==0,'updated notes EXE passes legacy migration and UTF-8 save/read')
    (out/'result.json').write_text(json.dumps({'status':'PASS','events':events,
        'scope':'real installer resources, manager window icon handles, isolated host update and business self-test; real screen appearance and keyboard input still need user check'},ensure_ascii=False,indent=2),encoding='utf-8')

if __name__=='__main__':main()
