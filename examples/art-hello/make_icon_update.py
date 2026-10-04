"""Create a new 1.1.1 project changing only the icon and release version."""
import argparse
import json
from pathlib import Path
import shutil
import struct
import zlib

def create(destination: Path) -> None:
    source = Path(__file__).resolve().parent
    if destination.exists():
        raise FileExistsError("输出目录已经存在，请使用新目录")
    destination.mkdir(parents=True)
    shutil.copytree(source / "src", destination / "src")
    shutil.copytree(source / "payload", destination / "payload")
    manifest = json.loads((source / "plugin.json").read_text(encoding="utf-8"))
    manifest["version"] = "1.1.1"
    (destination / "plugin.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    path = destination / "payload/resources/tool.png"
    png = path.read_bytes()
    chunks, offset = [], 8
    while offset < len(png):
        size = int.from_bytes(png[offset:offset + 4], "big")
        kind, content = png[offset + 4:offset + 8], png[offset + 8:offset + 8 + size]
        if kind == b"IDAT":
            content = zlib.compress(zlib.decompress(content).replace(
                bytes((45, 114, 196, 255)), bytes((212, 115, 35, 255))))
        chunks.append(struct.pack(">I", len(content)) + kind + content +
                      struct.pack(">I", zlib.crc32(kind + content) & 0xffffffff))
        offset += size + 12
    path.write_bytes(png[:8] + b"".join(chunks))
    print("已创建图标升级示例：" + str(destination.resolve()))

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    create(parser.parse_args().out)
