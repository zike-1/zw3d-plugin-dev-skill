"""Inspect compiled deliverables. This does not install or execute native code."""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from inspect_installer import inspect
from package_lib import PackageError, canonical_json, require


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sdk", type=Path, required=True)
    parser.add_argument("--out", type=Path, default=ROOT / "dist")
    parser.add_argument("--framework-bin", type=Path, default=ROOT / "dist" / "framework")
    args = parser.parse_args()
    try:
        reports = []
        for package in sorted(args.out.glob("*.zwplug")):
            installer = package.with_name(package.stem + "-setup.exe")
            report = inspect(installer, package, args.framework_bin, args.sdk)
            reports.append({key: value for key, value in report.items() if key != "packageValidation"})
        require(bool(reports), "no packages to inspect")
        require(len({report["hubSha256"] for report in reports}) == 1
                and len({report["managerSha256"] for report in reports}) == 1,
                "examples do not share identical framework bytes")
        result = {"status": "PASS", "verification": "static embedded resources and SDK APIs only", "packages": reports}
        (ROOT / "tests" / "package_delivery_result.json").write_bytes(canonical_json(result))
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (PackageError, OSError) as error:
        print(json.dumps({"status": "FAIL", "error": str(error)}, ensure_ascii=False))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
