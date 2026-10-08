"""Assemble the self-contained skill from this repository; never upload it."""

from __future__ import annotations

import hashlib
import io
import json
import os
from pathlib import Path
import re
import shutil
import stat
import tempfile
import uuid
import zipfile


PROJECT = Path(__file__).resolve().parents[1]
SKILL_NAME = "zw3d-plugin-dev"
VERSION = "0.2.4"
OWNER = "zw3d-plugin-dev-skill.release.pack_skill"
MARKER = ".kit-owner.json"
HASHES = "kit-sha256.json"
IDENTITY = {"schemaVersion": 1, "owner": OWNER}
DIRECTORIES = ("framework", "tools", "templates", "schema")
EXAMPLES = ("art-hello", "art-notes")
SKIP_DIRECTORIES = {"__pycache__", ".git", ".pytest_cache", ".idea", ".vscode",
                    "node_modules", "build", ".build", "dist", "logs", "verification"}
TEXT_SUFFIXES = {".py", ".md", ".json", ".h", ".cpp", ".in", ".yaml", ".yml",
                 ".manifest", ".rc", ".clang-format"}
RUNTIME_FILES = {"ZwPluginHub.dll", "HubManager.exe", "checksums.json"}


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def json_bytes(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")


def lf_text(data: bytes) -> bytes:
    """Match Git's LF text representation before recording hashes or ZIP bytes."""
    data.decode("utf-8")
    return data.replace(b"\r\n", b"\n")


def read_json(data: bytes) -> object:
    def unique(pairs):
        result = {}
        for key, value in pairs:
            require(key not in result, f"Duplicate JSON key: {key}")
            result[key] = value
        return result

    return json.loads(data.decode("utf-8"), object_pairs_hook=unique)


def contained(root: Path, path: Path) -> Path:
    """Check the absolute destination before copying, moving or deleting it."""
    root = root.resolve()
    absolute = Path(os.path.abspath(path))
    require(absolute.is_relative_to(root), f"Path leaves the project: {path}")
    require(absolute.resolve().is_relative_to(root), f"Resolved path leaves the project: {path}")
    current = root
    for part in absolute.relative_to(root).parts:
        current /= part
        if current.exists() or current.is_symlink():
            info = current.lstat()
            require(not current.is_symlink() and not getattr(info, "st_file_attributes", 0) & 0x400,
                    f"Linked paths are not accepted: {current}")
    return absolute


def relative_name(name: str) -> None:
    parts = name.split("/")
    require(bool(name) and not any(part in ("", ".", "..") for part in parts)
            and "\\" not in name and ":" not in name, f"Unsafe relative name: {name}")


def ignored_file(name: str) -> bool:
    lower = name.lower()
    return lower.startswith(".env") or lower.endswith((".pyc", ".pyo", ".log", ".o", ".obj", ".pdb", ".tmp"))


def files_in(root: Path, folder: Path, *, source: bool = False) -> dict[str, bytes]:
    folder = contained(root, folder)
    require(folder.is_dir(), f"Required directory is missing: {folder}")
    result = {}
    for directory, folders, files in os.walk(folder, followlinks=False):
        current = contained(root, Path(directory))
        if source:
            folders[:] = [name for name in folders if name not in SKIP_DIRECTORIES]
        for name in folders:
            contained(root, current / name)
        for name in files:
            if source and ignored_file(name):
                continue
            item = contained(root, current / name)
            require(stat.S_ISREG(item.lstat().st_mode), f"Nonregular file: {item}")
            relative = item.relative_to(folder).as_posix()
            relative_name(relative)
            result[relative] = item.read_bytes()
    return result


def source_bytes(root: Path, name: str, data: bytes) -> None:
    """Source releases contain text; the only binaries are the frozen runtime."""
    suffix = Path(name).suffix.lower()
    if suffix == ".png":
        require(data[:8] == b"\x89PNG\r\n\x1a\n" and len(data) <= 1024 * 1024,
                f"Invalid or oversized icon asset: {name}")
        return
    require(suffix in TEXT_SUFFIXES or Path(name).name == ".clang-format",
            f"Unexpected source artifact: {name}")
    text = data.decode("utf-8")
    roots = {str(root), root.as_posix(), str(PROJECT), PROJECT.as_posix()}
    for value in roots:
        require(value.lower() not in text.lower() and value.replace("\\", "\\\\").lower() not in text.lower(),
                f"Developer workspace path in {name}")
    require(not re.search(r"[A-Za-z]:[\\/]+Users[\\/]+|/Users/[^/]+/|/home/[^/]+/", text),
            f"Personal machine path in {name}")


def kit_files(root: Path) -> dict[str, bytes]:
    result = {}
    for directory in (*DIRECTORIES, *(f"examples/{name}" for name in EXAMPLES)):
        for name, data in files_in(root, root / directory, source=True).items():
            relative = f"{directory}/{name}"
            if Path(name).suffix.lower() != ".png":
                data = lf_text(data)
            source_bytes(root, relative, data)
            result[relative] = data
    runtime = files_in(root, root / "runtime" / "1.1.3")
    require(set(runtime) == RUNTIME_FILES, "runtime/1.1.3 must contain only the two framework binaries and checksums.json")
    runtime["checksums.json"] = lf_text(runtime["checksums.json"])
    checksums = read_json(runtime["checksums.json"])
    require(isinstance(checksums, dict) and set(checksums) == RUNTIME_FILES - {"checksums.json"},
            "Frozen runtime checksum table is invalid")
    for name, checksum in checksums.items():
        require(isinstance(checksum, str) and re.fullmatch(r"[0-9a-f]{64}", checksum) is not None
                and digest(runtime[name]) == checksum, f"Frozen runtime was modified: {name}")
    result.update({f"runtime/1.1.3/{name}": data for name, data in runtime.items()})
    result[MARKER] = json_bytes(IDENTITY)
    result[HASHES] = json_bytes({"schemaVersion": 1, "files": {name: digest(data) for name, data in sorted(result.items())}})
    return result


def verify_owned(root: Path, folder: Path) -> None:
    actual = files_in(root, folder)
    require(MARKER in actual and read_json(actual[MARKER]) == IDENTITY,
            f"Refusing to replace an unknown directory: {folder}")
    require(HASHES in actual, f"Generated directory has no checksum record: {folder}")
    table = read_json(actual[HASHES])
    require(isinstance(table, dict) and set(table) == {"schemaVersion", "files"}
            and table["schemaVersion"] == 1 and isinstance(table["files"], dict), "Invalid kit checksum record")
    expected = table["files"]
    require(set(actual) == set(expected) | {HASHES}, f"Unknown files were added to generated kit: {folder}")
    for name, checksum in expected.items():
        relative_name(name)
        require(digest(actual[name]) == checksum, f"Generated kit was edited: {name}; preserve it before rebuilding")
    # An unrecorded empty directory might belong to the user too.
    parents = {""}
    for name in actual:
        parents.update(parent.as_posix() for parent in Path(name).parents if parent.as_posix() != ".")
    for directory, folders, _ in os.walk(folder, followlinks=False):
        for name in folders:
            require((Path(directory) / name).relative_to(folder).as_posix() in parents,
                    "Unknown empty directory was added to generated kit")


def remove_owned(root: Path, folder: Path) -> None:
    folder = contained(root, folder)
    assets = root / "skills" / SKILL_NAME / "assets"
    require(folder.parent == assets and (folder.name == "kit" or folder.name.startswith((".kit-stage-", ".kit-previous-"))),
            "Only this tool's generated kit directories may be removed")
    verify_owned(root, folder)
    shutil.rmtree(folder)


def atomic_write(root: Path, path: Path, data: bytes) -> None:
    path = contained(root, path)
    temporary = contained(root, path.with_name(path.name + ".tmp-" + uuid.uuid4().hex))
    try:
        with temporary.open("xb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            contained(root, temporary).unlink()


def skill_files(root: Path, kit: dict[str, bytes]) -> dict[str, bytes]:
    folder = contained(root, root / "skills" / SKILL_NAME)
    result = {}
    # Skill instructions and metadata are handwritten; generated assets are supplied below.
    for directory in ("references", "agents"):
        for name, data in files_in(root, folder / directory, source=True).items():
            data = lf_text(data)
            source_bytes(root, name, data)
            result[f"{directory}/{name}"] = data
    entry = lf_text(contained(root, folder / "SKILL.md").read_bytes())
    source_bytes(root, "SKILL.md", entry)
    result["SKILL.md"] = entry
    result.update({f"assets/kit/{name}": data for name, data in kit.items()})
    return result


def archive_bytes(files: dict[str, bytes]) -> bytes:
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for name, data in sorted(files.items()):
            info = zipfile.ZipInfo(f"{SKILL_NAME}/{name}", date_time=(1980, 1, 1, 0, 0, 0))
            info.create_system = 3
            info.external_attr = (stat.S_IFREG | 0o644) << 16
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, data, compresslevel=9)
    return output.getvalue()


def assemble(root: Path = PROJECT) -> dict:
    root = contained(PROJECT, root)
    kit = kit_files(root)  # Validate everything before changing a previous release.
    archive = archive_bytes(skill_files(root, kit))
    assets = contained(root, root / "skills" / SKILL_NAME / "assets")
    assets.mkdir(exist_ok=True)
    destination = contained(root, assets / "kit")
    if destination.exists():
        verify_owned(root, destination)
    release = contained(root, root / "release")
    release.mkdir(exist_ok=True)
    artifact = contained(root, release / f"{SKILL_NAME}-{VERSION}.zip")
    record = contained(root, release / f"{SKILL_NAME}-{VERSION}.release.json")
    old_archive = artifact.read_bytes() if artifact.exists() else None
    old_record = record.read_bytes() if record.exists() else None
    require((old_archive is None) == (old_record is None), "Unknown or incomplete prior release; refusing to overwrite it")
    if old_record is not None:
        previous = read_json(old_record)
        require(isinstance(previous, dict) and previous.get("owner") == OWNER
                and previous.get("artifact") == {"file": artifact.name, "sha256": digest(old_archive)},
                "Prior release ownership or checksum does not match")
    new_record = json_bytes({**IDENTITY, "version": VERSION,
                            "artifact": {"file": artifact.name, "sha256": digest(archive)},
                            "kitManifestSha256": digest(kit[HASHES])})
    stage = contained(root, Path(tempfile.mkdtemp(prefix=".kit-stage-", dir=assets)))
    backup = contained(root, assets / (".kit-previous-" + uuid.uuid4().hex))
    for name, data in kit.items():
        path = contained(root, stage / name)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    verify_owned(root, stage)
    moved_previous = installed = False
    try:
        if destination.exists():
            os.replace(destination, backup)
            moved_previous = True
        os.replace(stage, destination)
        installed = True
        atomic_write(root, artifact, archive)
        atomic_write(root, record, new_record)
    except Exception:
        if installed:
            remove_owned(root, destination)
        if moved_previous:
            os.replace(contained(root, backup), contained(root, destination))
        for path, original in ((artifact, old_archive), (record, old_record)):
            if original is None:
                if path.exists():
                    contained(root, path).unlink()
            else:
                atomic_write(root, path, original)
        raise
    warnings = []
    for folder in (stage, backup):
        if folder.exists():
            try:
                remove_owned(root, folder)
            except (OSError, ValueError) as error:
                warnings.append(str(error))
    return {"status": "PASS", "artifact": str(artifact), "sha256": digest(archive),
            "kitFiles": len(kit), "kitManifest": str(destination / HASHES), "cleanupWarnings": warnings}


def main() -> int:
    try:
        print(json.dumps(assemble(), ensure_ascii=False, indent=2))
        return 0
    except (OSError, UnicodeError, ValueError) as error:
        print(json.dumps({"status": "FAIL", "error": str(error)}, ensure_ascii=False))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
