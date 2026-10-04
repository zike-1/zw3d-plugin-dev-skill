"""Check SDK visibility state and commands in owned empty host sessions.

This hidden driver does not verify rendered buttons or mouse interactions.
Snapshot and restore all touched UI files afterward.
"""
import hashlib,json,os,shutil,subprocess,time,tempfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
SDK=Path(r'D:\Program Files\ZWSOFT\ZW3D WuKong 2027')
RUN=ROOT/'verification'/time.strftime('host_%Y%m%d_%H%M%S');RUN.mkdir(parents=True)
si=subprocess.STARTUPINFO();si.dwFlags|=subprocess.STARTF_USESHOWWINDOW;si.wShowWindow=0
rows=[]
def check(ok,label):
    if not ok:raise AssertionError(label)
    rows.append('PASS '+label);print(rows[-1],flush=True)
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def sdk_visibility(lines,kind,name=None):
    prefix=kind+'|'+(name+'|' if name is not None else '')
    matching=[line for line in lines if line.startswith(prefix)]
    if len(matching)!=1:raise AssertionError('expected one SDK record '+prefix)
    values=matching[0][len(prefix):].split('|')
    if len(values)!=2:raise AssertionError('invalid SDK record '+matching[0])
    return tuple(int(value) for value in values)

def visible_state(lines,kind,label,name=None):
    check(sdk_visibility(lines,kind,name)==(0,1),label)

def negative_states(lines,label):
    for kind in ('page','group','control'):
        rc,visible=sdk_visibility(lines,'negative',kind)
        check(rc!=0,'SDK rejects nonexistent '+kind+' '+label)
    rc,visible=sdk_visibility(lines,'negative','control-list')
    check(rc!=0 or visible==0,'SDK batch query cannot report missing control visible or unchanged '+label)

def invoke(exe,args):
    log=RUN/('operation_'+str(len(rows))+'.log')
    r=subprocess.run([str(exe),'/quiet',*args,'/target='+str(SDK),'/log='+str(log)],startupinfo=si,timeout=60)
    check(r.returncode==0,'native operation '+','.join(args));return log
def launch(label,groups):
    env=os.environ.copy();d=RUN/label;d.mkdir();env['ZW_HUB_PROBE']=str(d/'host.log');env['ZW_HUB_DEMO_LOG']=str(d/'dll.log');env['ZW_HUB_EXE_PROBE']=str(d/'exe.log')
    env.pop('ZW3D_BATCHSAVE_JOB',None);env.pop('ZW_TOOLBOX_PROBE',None)
    p=subprocess.Popen([str(SDK/'zw3d.exe')],cwd=SDK,env=env,startupinfo=si);deadline=time.monotonic()+150
    try:
        while not (d/'host.log').exists() and time.monotonic()<deadline:
            if p.poll() is not None:raise RuntimeError(f'Host ended {p.returncode}')
            time.sleep(1)
        check((d/'host.log').exists(),'real host callback completed '+label)
        lines=(d/'host.log').read_text(encoding='utf8').splitlines()
        visible_state(lines,'page','SDK page visible flag '+label)
        for group in ['HubManagementGroup',*('HubPlugin_'+prefix for prefix in groups)]:
            rc,visibility=sdk_visibility(lines,'group',group)
            check(rc==0 and visibility in (0,1),
                  'SDK parent group exists; rendered visibility requires active page '+group+' '+label)
        visible_state(lines,'manager','SDK manager control visible flag '+label)
        negative_states(lines,label)
        return p,d,lines
    except:
        if p.poll() is None:p.terminate();p.wait(timeout=20)
        raise
def stop(p):
    if p.poll() is None:p.terminate()
    p.wait(timeout=20)
def main():
    check(not (SDK/'apilibs/ZwPluginHub.dll').exists() and not (SDK/'apilibs/ZwPluginHub').exists(),'test hub absent before test')
    check(not (SDK/'apilibs/ZzHubAcceptanceProbe.dll').exists(),'test-only probe absent before test')
    process_list=subprocess.run(['powershell','-NoProfile','-Command',"Get-Process zw3d -ErrorAction SilentlyContinue | ForEach-Object { $_.Path }"],capture_output=True,text=True).stdout
    check(str(SDK/'zw3d.exe').casefold() not in process_list.casefold(),'2027 target closed before test')
    paths=[SDK/'apilibs/Settings/Default/ResourcePool/ZwPluginHubActions.zcui',SDK/'apilibs/Settings/Default/ResourcePool/RibbonPagesUser.zcui']
    for e in json.loads((ROOT/'tests/fixtures/layouts.json').read_text(encoding='utf8')):paths.append(SDK/'apilibs/Settings/Default/Strategy'/e['folder']/'LayoutStrategy.zcui')
    backups={p:p.read_bytes() if p.exists() else None for p in paths}
    data_root=Path(os.environ['LOCALAPPDATA'])/'ZwPluginHub'/hashlib.sha256(str(SDK).lower().encode('utf8')).hexdigest()[:16]
    data_dirs=[data_root/name for name in ('org.zwtools.plugin-hub','org.zwtools.art-hello','org.zwtools.art-notes')]
    startup_log=data_dirs[0]/'startup.log'
    check(not startup_log.is_symlink(),'startup log has no link')
    previous_log=startup_log.read_bytes() if startup_log.exists() else None
    previous_dirs={p:p.exists() for p in [data_root.parent,data_root,*data_dirs]}
    # These are only plugin binaries and UI resources, no credentials or user models.
    foreign={p:sha(p) for p in (SDK/'apilibs').rglob('*') if p.is_file() and p.suffix.lower() in ('.dll','.zcui') and p not in backups}
    (RUN/'before.json').write_text(json.dumps({str(p):hashlib.sha256(b).hexdigest() if b else None for p,b in backups.items()},ensure_ascii=False,indent=2),encoding='utf8')
    live=None
    try:
        with tempfile.TemporaryDirectory(prefix='hub_probe_') as tmp:
            stage=Path(tmp);shutil.copytree(ROOT/'framework',stage/'framework');(stage/'tests').mkdir();shutil.copy2(ROOT/'tests/native_probe.cpp',stage/'tests/native_probe.cpp')
            command=[r'D:\Tools\mingw64\bin\g++.exe','-std=c++17','-shared','-static','-m64','-DUNICODE','-D_UNICODE','-I'+str(SDK/'api/inc'),str(stage/'tests/native_probe.cpp'),str(SDK/'ZW3D.lib'),'-lbcrypt','-lversion','-lshell32','-ladvapi32','-o',str(stage/'ZzHubAcceptanceProbe.dll')]
            subprocess.run(command,check=True)
            check(not (SDK/'apilibs/ZzHubAcceptanceProbe.dll').exists(),'test-only probe absent before test');shutil.copy2(stage/'ZzHubAcceptanceProbe.dll',SDK/'apilibs/ZzHubAcceptanceProbe.dll')
        invoke(ROOT/'dist/org.zwtools.art-hello-1.0.0-setup.exe',['/install'])
        live,d,lines=launch('first',['ArtHello'])
        check('module|ArtHello|1' in lines,'first plugin independently loads')
        visible_state(lines,'action','SDK first plugin control visible flag','ArtHelloShow')
        invoke(ROOT/'dist/org.zwtools.art-notes-1.0.0-setup.exe',['/install'])
        check(not (SDK/'apilibs/ZwPluginHub/state/org.zwtools.art-notes.ini').exists(),'second plugin installs pending while real host runs')
        stop(live);live=None
        live,d,lines=launch('both',['ArtHello','ArtNotes'])
        check('pending|applied' in lines,'pending new plugin is committed on next startup')
        check('load|org.zwtools.art-hello|0' in lines and 'module|ArtHello|1' in lines,'official loader loads template DLL')
        visible_state(lines,'action','SDK DLL control visible flag','ArtHelloShow')
        visible_state(lines,'action','SDK EXE control visible flag','ArtNotesOpen')
        check((d/'dll.log').exists() and 'dll|ArtHelloShow|ok' in (d/'dll.log').read_text(),'DLL command executed in 2027')
        check((d/'exe.log').exists() and 'exe|ArtNotes|ok' in (d/'exe.log').read_text(),'EXE launched through 2027 command')
        menu=SDK/'apilibs/Settings/Default/ResourcePool/RibbonPagesUser.zcui';before=sha(menu)
        invoke(SDK/'apilibs/ZwPluginHub/HubManager.exe',['/uninstall=org.zwtools.art-hello'])
        check(sha(menu)==before and (SDK/'apilibs/ZwPluginHub/state/org.zwtools.art-hello.ini').exists(),'running 2027 keeps loaded DLL and active menu until restart')
        stop(live);live=None
        live,d,lines=launch('after_restart',['ArtNotes'])
        check('pending|applied' in lines,'real startup applies pending uninstall before managed DLL loading')
        check('installed|org.zwtools.art-hello|1.0.0' not in lines and 'installed|org.zwtools.art-notes|1.0.0' in lines,'only A removed on real restart')
        visible_state(lines,'action','SDK remaining EXE control visible flag','ArtNotesOpen')
        check((d/'exe.log').exists(),'B command remains callable after A removed')
        stop(live);live=None
        for p,h in foreign.items():check(sha(p)==h,'foreign file unchanged '+p.name)
    finally:
        if live:stop(live)
        # Restore the exact UI snapshots, after all owned host sessions have exited.
        for p,b in backups.items():
            if b is None:
                if p.exists():p.unlink()
            else:p.write_bytes(b)
        for p in (SDK/'apilibs/ZwPluginHub.dll',SDK/'apilibs/ZwPluginHub',SDK/'apilibs/ZzHubAcceptanceProbe.dll'):
            check(p.resolve().is_relative_to((SDK/'apilibs').resolve()) and p.name in ('ZwPluginHub.dll','ZwPluginHub','ZzHubAcceptanceProbe.dll'),'owned test cleanup bounded')
            if p.is_dir():
                check(not any(x.is_symlink() for x in p.rglob('*')),'no linked files in test hub cleanup');shutil.rmtree(p)
            elif p.exists():p.unlink()
        if previous_log is None:
            if startup_log.exists():startup_log.unlink()
        else:startup_log.write_bytes(previous_log)
        for p in [*data_dirs,data_root,data_root.parent]:
            if not previous_dirs[p] and p.exists() and not any(p.iterdir()):p.rmdir()
    check(all((p.read_bytes()==b if b is not None else not p.exists()) for p,b in backups.items()),'original host interface bytes restored')
    (RUN/'result.txt').write_text('\n'.join(rows)+'\n',encoding='utf8')
    print('PASS real 2027 SDK state and command lifecycle; rendered UI/mouse clicks unverified; original installation restored',flush=True)
if __name__=='__main__':main()
