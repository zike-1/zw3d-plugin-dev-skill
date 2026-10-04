"""Create a recipient test ZIP with only owned installers, instructions and hashes."""
import hashlib, json, sys, zipfile
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
VERSION = '0.2.2'
sys.path.insert(0, str(ROOT / 'tools'))
from inspect_installer import inspect

def main():
    sdk = Path('D:/Program Files/ZWSOFT/ZW3D WuKong 2027')
    dist = ROOT / 'dist' / VERSION
    runtime = ROOT / 'runtime/1.1.2'
    entries = {}
    for name, stem in (
        ('01_安装优雅问候.exe', 'org.zwtools.art-hello-1.1.0'),
        ('02_安装示例便签.exe', 'org.zwtools.art-notes-1.1.0'),
        ('03_更新问候图标.exe', 'org.zwtools.art-hello-1.1.1')):
        binary = dist / (stem + '-setup.exe')
        inspect(binary, dist / (stem + '.zwplug'), runtime, sdk)
        entries[name] = binary.read_bytes()
    entries['先读我_测试步骤.txt'] = (ROOT / 'docs/second-pc-acceptance-0.2.2.txt').read_bytes()
    entries['验收结果.txt'] = ('测试包0.2.2／工具箱1.1.2\n'
        '测试日期：\nWindows版本：\n2027完整版本（帮助→关于）：\n显示缩放：\n'
        '是否首次安装这套工具箱：\n\n'
        '每项填“通过／失败／未测”；失败时写步骤编号和提示。\n'
        '初装两个插件，共用一页，有图标：\n问候按钮与管理入口：\n便签保存再打开：\n'
        '修复和隔离按钮存在（正常记录灰色）：\n运行中更新，等待重启：\n'
        '问候图标变橙色，便签内容不变：\n重复安装不增加按钮：\n'
        '卸载问候后便签继续可用：\n重装问候不影响便签：\n'
        '普通卸载便签后重装保留文字：\n彻底清理便签后文字消失（可选）：\n'
        '首页实际点击：\n零件实际点击：\n装配实际点击：\n工程图实际点击：\n'
        '100%缩放：\n125%缩放：\n150%缩放：\n\n问题与截图说明：\n').encode('utf-8')
    hashes = {name: hashlib.sha256(data).hexdigest() for name, data in entries.items()}
    entries['文件校验.json'] = (json.dumps({'version': VERSION, 'framework': '1.1.2', 'sha256': hashes},
        ensure_ascii=False, indent=2) + '\n').encode('utf-8')
    archive = ROOT / 'release' / ('ZW3D2027-插件工具箱测试包-' + VERSION + '.zip')
    if archive.exists(): raise RuntimeError('Test release already exists; use a new version rather than overwrite it')
    with zipfile.ZipFile(archive, 'x', compression=zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for name, data in entries.items(): z.writestr(name, data)
    with zipfile.ZipFile(archive) as z:
        assert set(z.namelist()) == set(entries) and z.testzip() is None
        assert all(z.read(name) == data for name, data in entries.items())
    report = {'status': 'PASS', 'artifact': str(archive), 'sha256': hashlib.sha256(archive.read_bytes()).hexdigest(),
              'size': archive.stat().st_size, 'files': list(entries), 'installerHashes': hashes,
              'scope': 'verified embedded installers and exact ZIP contents; second real PC remains untested'}
    (ROOT / 'verification/test-bundle-0.2.2.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False, indent=2))

if __name__ == '__main__': main()
