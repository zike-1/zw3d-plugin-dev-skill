"""Validate a .zwplug without installing or executing its contents."""
import argparse
import json
from pathlib import Path

from package_lib import PackageError, validate_package


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("package", type=Path)
    parser.add_argument("--sdk", type=Path, help="Check imported ZW3D APIs against this host directory")
    args = parser.parse_args()
    try:
        print(json.dumps({"status": "PASS", **validate_package(args.package, args.sdk)}, ensure_ascii=False, indent=2))
        return 0
    except (PackageError, OSError) as error:
        print(json.dumps({"status": "FAIL", "error": str(error)}, ensure_ascii=False))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
