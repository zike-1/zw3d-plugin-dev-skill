"""Exercise the real EXEs in an isolated Unicode target, never the user's host."""
import argparse,ctypes,hashlib,json,os,shutil,subprocess,sys,tempfile,time
import xml.etree.ElementTree as ET
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
SDK=Path(r'D:\Program Files\ZWSOFT\ZW3D WuKong 2027')
TOOLS=Path(r'D:\Tools\mingw64\bin')
DIST=ROOT/'dist/0.2.2'
HELLO=DIST/'org.zwtools.art-hello-1.1.0-setup.exe'
NOTES=DIST/'org.zwtools.art-notes-1.1.0-setup.exe'
PREVIOUS=ROOT/'verification/ribbon-fix-build/previous/org.zwtools.art-hello-1.1.0-setup.exe'
PREVIOUS_MANAGER_SHA='e8d49eaddfb89077b074ca6c57cd158d5c97d374b68bb242530e9be9d7df107f'
rows=[]
si=subprocess.STARTUPINFO();si.dwFlags|=subprocess.STARTF_USESHOWWINDOW;si.wShowWindow=0
def check(ok,label):
    if not ok:raise AssertionError(label)
    rows.append('PASS '+label);print(rows[-1],flush=True)
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def run(exe,args,success=True):
    log=ROOT/'verification/current-operation.log';log.parent.mkdir(exist_ok=True)
    r=subprocess.run([str(exe),'/quiet',*args,'/log='+str(log)],startupinfo=si,timeout=60)
    if (r.returncode==0)!=success:print(log.read_text(encoding='utf8'),flush=True)
    check((r.returncode==0)==success,'operation '+','.join(args[:1])+(' accepted' if success else ' rejected'))
    return log.read_text(encoding='utf8')
def inventory(root):return {p.relative_to(root).as_posix():sha(p) for p in root.rglob('*') if p.is_file()}

def check_ribbon_bindings(ribbon, phase, include_notes=True):
    """Verify the installed hierarchy, including visibility inherited by controls."""
    pages=ET.parse(ribbon).getroot()
    hub=pages.findall("RibbonPage[@name='ZwPluginHubPage']")
    check(len(hub)==1 and hub[0].get('visible')=='true',phase+' has one visible hub page')
    expected={
        'HubManagementGroup':('HubManagementCommands',{'ID_ZpHub_ZwPluginHubManage':'~ZwPluginHubManage'}),
        'HubPlugin_ArtHello':('HubCommands_ArtHello',{'ID_ZpHub_ArtHelloShow':'~ArtHelloShow'}),
    }
    if include_notes:
        expected['HubPlugin_ArtNotes']=('HubCommands_ArtNotes',{'ID_ZpHub_ArtNotesOpen':'~ArtNotesOpen'})
    groups=hub[0].findall('RibbonGroup')
    check(len(groups)==len(expected) and {g.get('name') for g in groups}==set(expected),
          phase+' contains its management and plugin groups exactly once')
    actions=ET.parse(ribbon.parent/'ZwPluginHubActions.zcui').getroot()
    for group in groups:
        name=group.get('name')
        check(group.get('visible')=='true',phase+' group '+name+' explicitly visible')
        panel_name,bindings=expected[name]
        panels=group.findall('GroupPanel')
        check(len(panels)==1 and panels[0].get('name')==panel_name,
              phase+' group '+name+' uses its migrated command panel')
        controls=panels[0].findall('Control')
        check(len(controls)==len(bindings) and {c.get('action') for c in controls}==set(bindings),
              phase+' group '+name+' has its expected controls')
        for control in controls:
            action_id=control.get('action')
            check(control.get('visible')=='true',phase+' control '+action_id+' explicitly visible')
            matches=actions.findall("Action[@name='"+action_id+"']")
            check(len(matches)==1 and matches[0].findtext('Script')==bindings[action_id],
                  phase+' control '+action_id+' resolves to its registered command')
    foreign=pages.findall("RibbonPage[@name='ForeignPage']")
    check(len(foreign)==1 and foreign[0].attrib=={'name':'ForeignPage','text':'其他插件'}
          and len(foreign[0])==0,phase+' preserves the foreign page unchanged')
def data(root,plugin):
    key=hashlib.sha256(str(root).lower().encode('utf8')).hexdigest()[:16]
    return Path(os.environ['LOCALAPPDATA'])/'ZwPluginHub'/key/plugin
def build_busy_host(stage):
    (stage/'busy.cpp').write_text('#include <windows.h>\nint WINAPI wWinMain(HINSTANCE,HINSTANCE,LPWSTR,int){Sleep(600000);return 0;}\n')
    (stage/'busy.rc').write_text('#include <windows.h>\n1 VERSIONINFO\nFILEVERSION 32,0,1,0\nPRODUCTVERSION 32,0,1,0\nFILEFLAGSMASK 0x3fL\nFILEFLAGS 0\nFILEOS 0x40004L\nFILETYPE 1\nBEGIN\nBLOCK "VarFileInfo" BEGIN VALUE "Translation", 0x804, 1200 END\nEND\n')
    subprocess.run([str(TOOLS/'windres.exe'),'-i','busy.rc','-o','busy.o'],cwd=stage,check=True)
    subprocess.run([str(TOOLS/'g++.exe'),'-municode','-mwindows','-static','busy.cpp','busy.o','-o','zw3d.exe'],cwd=stage,check=True)
    return stage/'zw3d.exe'

def main():
  parser=argparse.ArgumentParser(description=__doc__)
  parser.parse_args()
  with tempfile.TemporaryDirectory(prefix='hub_acceptance_') as tmp:
    stage=Path(tmp)
    os.environ["LOCALAPPDATA"] = str(stage / "isolated-user-data")
    target=stage/'中文 安装位置'/'ZW3D 2027';target.mkdir(parents=True)
    shutil.copy2(SDK/'ZW3D.dll',target/'ZW3D.dll');shutil.copy2(SDK/'zw3d.exe',target/'zw3d.exe')
    store=target/'apilibs/ZwPluginHub';ribbon=target/'apilibs/Settings/Default/ResourcePool/RibbonPagesUser.zcui';ribbon.parent.mkdir(parents=True)
    ribbon.write_text('<RibbonPages><RibbonPage name="ForeignPage" text="其他插件"/></RibbonPages>',encoding='utf8')
    flag='/target='+str(target)
    run(HELLO,['/install',flag]);framework=sha(target/'apilibs/ZwPluginHub.dll')
    run(NOTES,['/install',flag]);check(len(list((store/'state').glob('*.ini')))==2,'two separate installers share one registry')
    check(sha(target/'apilibs/ZwPluginHub.dll')==framework,'second installer reuses identical shared framework')
    check_ribbon_bindings(ribbon,'A+B install')
    run(HELLO,['/install',flag]);text=ribbon.read_text(encoding='utf8');check(text.count('name="ZwPluginHubPage"')==1 and 'ForeignPage' in text,'repeat install has one hub page and preserves foreign page')
    check_ribbon_bindings(ribbon,'repeat install')
    for plugin in ('org.zwtools.art-hello','org.zwtools.art-notes'):
        p=data(target,plugin);p.mkdir(parents=True);(p/'settings.txt').write_text('keep me',encoding='utf8')
    manager=store/'HubManager.exe'
    run(manager,['/ui-probe='+str(stage/'ui.txt'),flag]);check('PASS' in (stage/'ui.txt').read_text(),'manager window and uninstall controls created')
    run(manager,['/uninstall=org.zwtools.art-hello',flag]);check(not (store/'state/org.zwtools.art-hello.ini').exists() and (store/'state/org.zwtools.art-notes.ini').exists(),'remove A keeps B registered')
    check((data(target,'org.zwtools.art-hello')/'settings.txt').exists(),'ordinary uninstall retains personal data')
    check((target/'apilibs/ZwPluginHub.dll').exists() and manager.exists(),'ordinary uninstall retains shared hub and manager')
    run(HELLO,['/install',flag]);run(manager,['/uninstall=org.zwtools.art-hello','/purge',flag]);check(not data(target,'org.zwtools.art-hello').exists() and data(target,'org.zwtools.art-notes').exists(),'purge removes only specified plugin data')
    run(HELLO,['/install',flag])
    p=store/'plugins/org.zwtools.art-hello/1.1.0/ArtHello.dll';original=p.read_bytes();p.write_bytes(original+b'changed')
    before=inventory(target);run(manager,['/uninstall=org.zwtools.art-hello',flag],False);check(inventory(target)==before,'externally changed plugin blocks uninstall without changing other files');p.write_bytes(original)
    original=ribbon.read_bytes();ribbon.write_bytes(b'<broken');before=inventory(target);run(manager,['/uninstall=org.zwtools.art-hello',flag],False);check(inventory(target)==before,'invalid shared XML blocks entire operation');ribbon.write_bytes(original)
    # A leftover committed journal is cleanup, never a rollback.
    tx=store/'transaction';tx.mkdir();(tx/'committed.txt').write_text('already committed')
    run(HELLO,['/install',flag]);check(not tx.exists(),'committed transaction residue does not block reinstall')
    # Simulate a durable unfinished journal, then recover before writing.
    tx.mkdir();record=store/'state/org.zwtools.art-hello.ini';original=record.read_bytes();(tx/'0.bin').write_bytes(original)
    (tx/'journal.txt').write_bytes(('apilibs/ZwPluginHub/state/org.zwtools.art-hello.ini|old|0.bin|'+hashlib.sha256(original).hexdigest()+'\n').encode('utf8'))
    record.write_bytes(b'broken');run(HELLO,['/install',flag]);check(record.read_bytes()==original,'unfinished transaction restores original record')
    # Simulate an owned host process to exercise running/deferred paths.
    busy=build_busy_host(stage);shutil.copy2(busy,target/'zw3d.exe');proc=subprocess.Popen([str(target/'zw3d.exe')],startupinfo=si)
    try:
        time.sleep(.3);before=sha(ribbon);versionHash=sha(store/'plugins/org.zwtools.art-notes/1.1.0/ArtNotes.exe')
        pending=store/'pending/org.zwtools.art-notes/operation.ini';pending.parent.mkdir(parents=True)
        pending.write_bytes((store/'state/org.zwtools.art-notes.ini').read_bytes()+b'operation=remove\n')
        kernel=ctypes.WinDLL('kernel32',use_last_error=True)
        kernel.CreateFileW.argtypes=[ctypes.c_wchar_p,ctypes.c_uint32,ctypes.c_uint32,ctypes.c_void_p,ctypes.c_uint32,ctypes.c_uint32,ctypes.c_void_p];kernel.CreateFileW.restype=ctypes.c_void_p
        kernel.CloseHandle.argtypes=[ctypes.c_void_p]
        locked=kernel.CreateFileW(str(pending),0x80000000,1,None,3,0,None);check(locked not in (None,ctypes.c_void_p(-1).value),'hold pending file without delete sharing')
        state=inventory(target)
        try:
            run(manager,['/uninstall=org.zwtools.art-notes',flag],False);check(inventory(target)==state,'failed pending write rolls back safely while host remains running')
        finally:kernel.CloseHandle(locked)
        pending.unlink()
        run(manager,['/uninstall=org.zwtools.art-notes',flag]);check(sha(ribbon)==before and sha(store/'plugins/org.zwtools.art-notes/1.1.0/ArtNotes.exe')==versionHash,'running host keeps active menu and plugin bytes unchanged')
        check((store/'pending/org.zwtools.art-notes/operation.ini').exists(),'uninstall is durably pending restart')
        run(manager,['/apply',flag],False);check((store/'state/org.zwtools.art-notes.ini').exists(),'apply refuses an unrecognized running phase')
    finally:proc.terminate();proc.wait(timeout=10)
    run(manager,['/apply',flag]);check(not (store/'state/org.zwtools.art-notes.ini').exists() and (store/'state/org.zwtools.art-hello.ini').exists(),'after restart apply removes only pending B')
    check(data(target,'org.zwtools.art-notes').exists(),'pending ordinary uninstall preserves B data')
    # Add nested assets, then uninstall and upgrade, testing empty directory cleanup.
    project=stage/'asset-example';shutil.copytree(ROOT/'examples/art-hello',project);(project/'payload/resources').mkdir(parents=True,exist_ok=True);(project/'payload/resources/readme.txt').write_text('asset')
    manifest=json.loads((project/'plugin.json').read_text(encoding='utf8'));manifest['version']='1.1.1';(project/'plugin.json').write_text(json.dumps(manifest),encoding='utf8')
    built=subprocess.run(['python','-X','utf8',str(ROOT/'tools/build_plugin.py'),str(project),'--sdk',str(SDK),'--toolchain',str(TOOLS.parent),'--framework-bin',str(DIST/'framework'),'--out',str(stage/'dist')],capture_output=True,text=True,encoding='utf8')
    if built.returncode:raise RuntimeError(built.stdout+'\n'+built.stderr)
    asset=stage/'dist/org.zwtools.art-hello-1.1.1-setup.exe';run(asset,['/install',flag]);run(manager,['/uninstall=org.zwtools.art-hello',flag]);check(not (store/'plugins/org.zwtools.art-hello').exists(),'uninstall clears strictly empty nested resource directories')
    run(asset,['/install',flag]);run(HELLO,['/install',flag],False);run(manager,['/uninstall=org.zwtools.art-hello',flag]);check(not (store/'state/org.zwtools.art-hello.ini').exists(),'nested resource upgrade and repeat uninstall succeed; downgrade refused')
    for plugin in ('org.zwtools.art-hello','org.zwtools.art-notes'):
        p=data(target,plugin)
        if p.exists():check(p.is_relative_to(Path(os.environ['LOCALAPPDATA'])/'ZwPluginHub'),'temporary user data cleanup bounded');shutil.rmtree(p)
  (ROOT/'verification').mkdir(exist_ok=True);(ROOT/'verification/installation-tests.txt').write_text('\n'.join(rows)+'\n',encoding='utf8')
  print('PASS isolated installer acceptance',flush=True)
if __name__=='__main__':main()
