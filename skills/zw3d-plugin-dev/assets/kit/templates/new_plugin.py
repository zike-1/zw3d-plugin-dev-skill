"""Generate a small DLL or EXE project without overwriting existing work."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import shutil
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from package_lib import validate_manifest


def cpp_text(value: str) -> str:
    """Escape user text for one wide C++ string literal."""
    return value.replace("\\", "\\\\").replace('"', '\\"').replace("\r", "\\r").replace("\n", "\\n")


def create_plugin(kind: str, plugin_id: str, prefix: str, name: str, output: Path) -> None:
    if kind not in ("dll", "exe"):
        raise ValueError("type must be dll or exe")
    if output.exists():
        raise FileExistsError(f"refusing to overwrite {output}")

    suffix = "Show" if kind == "dll" else "Open"
    command = prefix + suffix
    manifest = {
        "schemaVersion": 1,
        "id": plugin_id,
        "name": name,
        "version": "1.0.0",
        "type": kind,
        "entry": f"{prefix}.{kind}",
        "prefix": prefix,
        "host": {"product": "ZW3D", "versions": [2027], "architecture": "x64"},
        "commands": [{"id": command, "label": name,
                      "environments": ["top", "part", "assembly", "drawing"],
                      "icon": "resources/tool.png", "tooltip": name}],
        "dataPolicy": "preserve",
        "hotUnload": False,
    }
    if kind == "exe":
        manifest["commands"][0]["arguments"] = ""
    # The generator and installer have one contract, rather than parallel rules.
    validate_manifest(manifest)

    message = "这是一个最小插件示例。它只显示提示，不修改当前模型。"
    source = (Path(__file__).parent / kind / "plugin.cpp.in").read_text(encoding="utf-8")
    for token, value in {"PREFIX": prefix, "NAME": cpp_text(name), "MESSAGE": cpp_text(message)}.items():
        source = source.replace(f"@{token}@", value)

    # Build the whole tree beside its destination, then publish it in one rename.
    output.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=".zwplugin-", dir=output.parent))
    try:
        (staging / "src").mkdir()
        resources = staging / "payload" / "resources"
        resources.mkdir(parents=True)
        shutil.copy2(Path(__file__).resolve().parents[1] / "framework" / "default-icon.png", resources / "tool.png")
        shutil.copy2(Path(__file__).resolve().parents[1] / "framework" / "HubData.h", staging / "src" / "HubData.h")
        (staging / "src" / f"{prefix}.cpp").write_text(source, encoding="utf-8", newline="\n")
        (staging / "plugin.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
                                            encoding="utf-8", newline="\n")
        (staging / "README.md").write_text(project_readme(kind, prefix, name), encoding="utf-8", newline="\n")
        staging.rename(output)
    except BaseException:
        shutil.rmtree(staging)
        raise


def project_readme(kind: str, prefix: str, name: str) -> str:
    contract = (f"DLL 名称为 `{prefix}.dll`，导出 `{prefix}Init` 和 `{prefix}Exit`；"
                f"SDK 命令为 `{prefix}Show`，工具箱通过 `~{prefix}Show` 调用。"
                if kind == "dll" else
                f"工具箱启动 `{prefix}.exe`，并传递该命令的固定 `arguments`。")
    test = ("仅在专用测试进程中设置 `ZW_HUB_DEMO_LOG` 为绝对文件路径后调用命令："
            "写入测试标记，并跳过提示窗口。普通使用不读写文件。"
            if kind == "dll" else
            "仅在测试时传入 `/probe=<绝对文件路径>`：写入测试标记后退出。"
            "普通使用不读写文件。")
    return f"""# {name}

这是一个不修改模型的最小示例。请先验证编译、安装和卸载，再实现业务功能。

{contract}

源码不包含 SDK 安装路径。DLL 从自己的模块路径、EXE 从自己的程序路径确定目录，
不要用当前工作目录查找随包资源。

{test}

修改 ID、prefix、文件名、导出函数名和命令名时应同步修改。一个包只能声明自己的
命令；界面、安装、升级和卸载由共用工具箱处理。

使用工具包的 `tools/build_plugin.py`，向它传入本插件目录。工具包位于源码仓库根目录或独立技能的 `assets/kit/`；本插件目录不自带构建脚本。不要把 SDK 头文件或库复制到插件包。
"""


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--type", choices=("dll", "exe"), required=True, dest="kind")
    parser.add_argument("--id", required=True, dest="plugin_id")
    parser.add_argument("--prefix", required=True)
    parser.add_argument("--name", required=True)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()
    try:
        create_plugin(args.kind, args.plugin_id, args.prefix, args.name, args.out.resolve())
    except (OSError, ValueError) as error:
        parser.error(str(error))
    print(f"Created {args.out.resolve()}")


if __name__ == "__main__":
    main()
