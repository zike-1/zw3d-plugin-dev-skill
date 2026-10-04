"""Add licensing materials to frozen 0.2.3 artifacts; never upload or rebuild them."""

from __future__ import annotations

import hashlib
import io
import json
from pathlib import Path
import stat
import sys
import tempfile
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from build_plugin import publish_artifacts

VERSION = "0.2.3"
SKILL = "zw3d-plugin-dev"
FROZEN_SKILL = "f6fa70ef663617c9a6ce8c10ff95f202c95f1b1f3f183728bf2b95b57ca6d5c3"
INSTALLERS = {
    "01_ArtHello-1.1.0-setup.exe": (
        "org.zwtools.art-hello-1.1.0-setup.exe",
        "6b495622565dd2a2724f19eb7218cc4817a1994ff80e67e3d1ac2c8e507b0bb8"),
    "02_ArtNotes-1.1.1-setup.exe": (
        "org.zwtools.art-notes-1.1.1-setup.exe",
        "312adcda7aac94cccd65dfa7b6946e7dc71d929cc0eec16b1f43dace982e0130"),
    "03_ArtHello-1.1.1-update.exe": (
        "org.zwtools.art-hello-1.1.1-setup.exe",
        "16a1a115fd783f3b9ac33c6b35983125821b120e3d40d1ca07547c275403530a"),
}

START_HERE = """中望3D 2027示例包0.2.3
共用工具箱1.1.3；问候初装1.1.0／图标更新1.1.1；便签1.1.1。

这是公开源码、非商业授权的项目。非商业使用、修改和分享须署名；商用需
作者事先单独书面同意，详见LICENSE和THIRD_PARTY_NOTICES.md。
来源：https://github.com/zike-1/zw3d-plugin-dev-skill

初次安装
1. 完整解压本ZIP；不要在压缩软件内直接运行EXE。
2. 保存工作，退出2027和已打开的便签、管理窗口。
3. 依次运行01_ArtHello-1.1.0-setup.exe、02_ArtNotes-1.1.1-setup.exe，
   核对2027安装位置，点击“安装这个插件”；需要安装权限时按提示确认。
4. 打开2027，进入“小插件”页，确认问候、便签及管理插件共用该页。
5. 点问候查看提示；点便签输入文字并保存，再打开确认保留。

演示单插件更新
6. 运行03_ArtHello-1.1.1-update.exe。2027运行时应显示等待重启，
   正常退出2027，等更新完成后重新启动；问候图标变为橙色。
7. 便签仍为1.1.1，其保存内容不变；重复安装不会增加重复按钮。

已有新版问候时不要运行较低版本的01，使用03即可；本框架不允许降级。
管理插件可分别卸载；默认保留个人设置，勾选清理才清除所选插件的数据。
运行中的安装、更新及卸载按提示等待重启，不强制结束2027。
便签没有修改时Esc关闭；有修改时询问保存／放弃／取消，不隐式保存。

三个EXE复用已验收的冻结程序，没有重新编译。普通用户不需要Python、SDK
或编译器。本包不包含SDK、CAD图纸、既有供应商插件或用户设置。
其他中望年份、跨Windows账户并发等未验证范围不在本次验收结论内。
"""


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def safe_read(path: Path) -> bytes:
    require(path.resolve().is_relative_to(ROOT), "path leaves the project")
    require(not path.is_symlink(), "linked source is not accepted")
    return path.read_bytes()


def text_bytes(data: bytes) -> bytes:
    data.decode("utf-8")
    return data.replace(b"\r\n", b"\n")


def legal_files() -> dict[str, bytes]:
    sources = json.loads(safe_read(ROOT / "licenses/sources.json"))
    files = {name: text_bytes(safe_read(ROOT / name))
             for name in ("LICENSE", "THIRD_PARTY_NOTICES.md", "licenses/sources.json")}
    for name, info in sources["files"].items():
        require(Path(name).name == name, "invalid notice filename")
        data = safe_read(ROOT / "licenses" / name)
        require(digest(data) == info["sha256"], f"notice checksum mismatch: {name}")
        files["licenses/" + name] = data
    return files


def archive(files: dict[str, bytes]) -> bytes:
    result = io.BytesIO()
    with zipfile.ZipFile(result, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as output:
        for name, data in sorted(files.items()):
            require(not name.startswith("/") and "\\" not in name
                    and all(part not in ("", ".", "..") for part in name.split("/")),
                    "invalid archive entry")
            info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            info.create_system = 3
            info.external_attr = (stat.S_IFREG | 0o644) << 16
            info.compress_type = zipfile.ZIP_DEFLATED
            output.writestr(info, data, compresslevel=9)
    return result.getvalue()


def main() -> None:
    original = safe_read(ROOT / "release" / f"{SKILL}-{VERSION}.zip")
    require(digest(original) == FROZEN_SKILL, "accepted skill ZIP changed")
    with zipfile.ZipFile(io.BytesIO(original)) as source:
        require(source.testzip() is None, "frozen ZIP is damaged")
        names = source.namelist()
        require(len(names) == len(set(names)), "duplicate frozen skill ZIP entries")
        files = {name: source.read(name) for name in names}
    require(all(name.startswith(SKILL + "/") for name in files), "unexpected skill ZIP root")
    legal = legal_files()
    for name, data in legal.items():
        key = SKILL + "/" + name
        require(key not in files, "notice would replace an accepted skill file")
        files[key] = data

    examples = dict(legal)
    for filename, (source_name, expected) in INSTALLERS.items():
        data = safe_read(ROOT / "dist" / VERSION / source_name)
        require(digest(data) == expected, f"accepted installer changed: {source_name}")
        examples[filename] = data
    examples["START-HERE.txt"] = START_HERE.encode("utf-8")
    examples["CONTENTS-SHA256.json"] = (json.dumps(
        {name: digest(data) for name, data in sorted(examples.items())},
        ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    outputs = {
        f"{SKILL}-{VERSION}-github.zip": archive(files),
        f"ZW3D2027-examples-{VERSION}.zip": archive(examples),
    }
    sums = "".join(f"{digest(data)}  {name}\n" for name, data in sorted(outputs.items()))
    outputs[f"SHA256SUMS-{VERSION}.txt"] = sums.encode("ascii")
    for name, data in outputs.items():
        target = ROOT / "release" / name
        require(not target.exists() or safe_read(target) == data,
                f"existing public artifact differs; use a new version or filename: {name}")
    skill_root = ROOT / "skills" / SKILL
    for name, data in legal.items():
        target = skill_root / name
        require(not target.exists() or safe_read(target) == data,
                f"existing skill notice differs: {name}")
    (ROOT / "work").mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="github-release-", dir=ROOT / "work") as temporary:
        staging = Path(temporary)
        for name, data in outputs.items():
            (staging / name).write_bytes(data)
        publish_artifacts(ROOT / "release", {name: staging / name for name in outputs})
    for name, data in legal.items():
        target = skill_root / name
        target.parent.mkdir(parents=True, exist_ok=True)
        if not target.exists():
            target.write_bytes(data)
    print(json.dumps({"status": "PASS", "frozenSkillUnchanged": True,
                      "artifacts": {name: {"bytes": len(data), "sha256": digest(data)}
                                    for name, data in outputs.items()}}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
