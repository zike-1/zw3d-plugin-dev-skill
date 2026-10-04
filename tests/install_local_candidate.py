"""Install the two reviewed examples after backing up owned files; preserve foreign UI."""
import argparse, hashlib, json, os, shutil, subprocess
from pathlib import Path
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
def digest(path): return hashlib.sha256(path.read_bytes()).hexdigest()
def semantic(node):
    name = node.get('name','')
    if (node.tag == 'RibbonPage' and name == 'ZwPluginHubPage' or
        node.tag == 'Action' and name.startswith('ID_ZpHub_') or
        node.tag == 'Insert' and name == 'ZwPluginHubPage'):
        return None
    children = [item for child in node if (item := semantic(child)) is not None]
    text = node.text if node.text and node.text.strip() else ''
    return node.tag, sorted(node.attrib.items()), text, children
def host_closed(sdk):
    result = subprocess.run(['powershell','-NoProfile','-Command',
        "Get-CimInstance Win32_Process -Filter \"Name = 'zw3d.exe' OR Name = 'HubManager.exe'\" | Select-Object -ExpandProperty ExecutablePath"],
        capture_output=True,text=True,check=True)
    paths = {line.strip().casefold() for line in result.stdout.splitlines()}
    if str(sdk/'zw3d.exe').casefold() in paths or str(sdk/'apilibs/ZwPluginHub/HubManager.exe').casefold() in paths:
        raise RuntimeError('先关闭目标2027及其管理器，用户会话不会被强制关闭。')
def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--sdk',type=Path,required=True)
    parser.add_argument('--out',type=Path,required=True);args=parser.parse_args()
    sdk=args.sdk.resolve();out=args.out.resolve()
    assert out.is_relative_to((ROOT/'verification').resolve()) and not out.exists()
    host_closed(sdk);libs=sdk/'apilibs';store=libs/'ZwPluginHub'
    for path in [store, *store.rglob('*')]:
        assert not path.is_symlink() and not path.is_junction(), 'Linked backup source is unsupported'
    pending=store/'pending'
    assert not pending.exists() or not any(pending.rglob('operation.ini')), 'Existing requests must be resolved first'
    out.mkdir(parents=True);backup=out/'backup'
    before={p.relative_to(libs).as_posix():digest(p) for p in libs.rglob('*') if p.is_file()}
    ui={name:semantic(ET.parse(libs/name).getroot()) for name in before
        if name.endswith('.zcui') and (name.endswith('RibbonPagesUser.zcui') or name.endswith('LayoutStrategy.zcui') or name.endswith('ZwPluginHubActions.zcui'))}
    for file in (libs/'ZwPluginHub.dll',store/'HubManager.exe'):
        if file.exists():
            destination=backup/file.relative_to(libs);destination.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(file,destination)
    if store.exists(): shutil.copytree(store,backup/'ZwPluginHub',dirs_exist_ok=True)
    for name in ui:
        destination=backup/name;destination.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(libs/name,destination)
    actions=libs/'Settings/Default/ResourcePool/ZwPluginHubActions.zcui'
    if actions.exists():
        destination=backup/actions.relative_to(libs);destination.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(actions,destination)
    profiles=Path(os.environ['APPDATA'])/'ZWSOFT/ZW3D'/sdk.name/'custom/profiles'
    profileBefore={str(p):digest(p) for p in profiles.rglob('*.zcui')}
    key=hashlib.sha256(str(sdk).lower().encode('utf-8')).hexdigest()[:16]
    data=Path(os.environ['LOCALAPPDATA'])/'ZwPluginHub'/key
    dataBefore={str(p):digest(p) for p in data.rglob('*') if p.is_file()}
    for name in ('org.zwtools.art-hello-1.1.0','org.zwtools.art-notes-1.1.0'):
        host_closed(sdk)
        log=out/(name+'.log')
        result=subprocess.run([str(ROOT/'dist/0.2.1'/(name+'-setup.exe')),'/quiet','/install',
            '/target='+str(sdk),'/log='+str(log)],timeout=60)
        if result.returncode: raise RuntimeError(log.read_text(encoding='utf-8'))
    checks=json.loads((ROOT/'runtime/1.1.1/checksums.json').read_text(encoding='utf-8'))
    assert digest(libs/'ZwPluginHub.dll')==checks['ZwPluginHub.dll'] and digest(store/'HubManager.exe')==checks['HubManager.exe']
    mutable={'ZwPluginHub.dll','ZwPluginHub/HubManager.exe','ZwPluginHub/framework.ini',
             'ZwPluginHub/state/org.zwtools.art-hello.ini','ZwPluginHub/state/org.zwtools.art-notes.ini',
             'Settings/Default/ResourcePool/ZwPluginHubActions.zcui',*ui.keys()}
    preserved=0
    for name,sha in before.items():
        if name not in mutable:
            assert (libs/name).exists() and digest(libs/name)==sha, 'Unexpected change: '+name
            preserved+=1
    for name,original in ui.items(): assert semantic(ET.parse(libs/name).getroot())==original, 'Foreign UI changed: '+name
    assert all(Path(name).exists() and digest(Path(name))==sha for name,sha in profileBefore.items())
    assert all(Path(name).exists() and digest(Path(name))==sha for name,sha in dataBefore.items())
    for plugin in ('org.zwtools.art-hello','org.zwtools.art-notes'):
        assert 'version=1.1.0' in (store/'state'/(plugin+'.ini')).read_text(encoding='utf-8')
    report={'status':'PASS','scope':'Disk installation and preservation; rendered UI unverified',
            'preservedFiles':preserved,'preservedForeignUi':len(ui),'preservedProfiles':len(profileBefore),
            'preservedUserData':len(dataBefore),'runtime':checks,'backup':str(backup)}
    (out/'result.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False),flush=True)
if __name__=='__main__':main()
