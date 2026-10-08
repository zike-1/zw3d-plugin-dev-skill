"""Windows-only regression: a result dialog must not hold the installation mutex.

Run with a candidate installer built from the modified framework source:
  python tests/test_modal_lock.py --installer <setup.exe> --sdk <ZW3D-2027-directory>
Creates only an isolated temporary host. Never points an installer at a real host.
"""
import argparse
import ctypes
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import time


def find_notice(pid):
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    callback_type = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
    user32.GetWindowThreadProcessId.argtypes = (ctypes.c_void_p, ctypes.POINTER(ctypes.c_ulong))
    user32.GetWindowThreadProcessId.restype = ctypes.c_ulong
    user32.GetClassNameW.argtypes = (ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_int)
    user32.GetClassNameW.restype = ctypes.c_int
    user32.GetWindowTextW.argtypes = (ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_int)
    user32.GetWindowTextW.restype = ctypes.c_int
    user32.EnumWindows.argtypes = (callback_type, ctypes.c_void_p)
    user32.EnumWindows.restype = ctypes.c_bool
    found = []
    def each(hwnd, _):
        owner = ctypes.c_ulong()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(owner))
        if owner.value != pid:
            return True
        cls = ctypes.create_unicode_buffer(256)
        title = ctypes.create_unicode_buffer(256)
        user32.GetClassNameW(hwnd, cls, 256)
        user32.GetWindowTextW(hwnd, title, 256)
        if cls.value == "#32770" and title.value == "扩展工具":
            found.append(hwnd)
        return True
    user32.EnumWindows(callback_type(each), None)
    return found[0] if found else None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--installer", required=True, type=Path)
    parser.add_argument("--sdk", required=True, type=Path)
    args = parser.parse_args()
    if os.name != "nt":
        raise SystemExit("Windows required")
    installer = args.installer.resolve(strict=True)
    sdk = args.sdk.resolve(strict=True)
    with tempfile.TemporaryDirectory(prefix="zwplug_modal_lock_") as temporary:
        target = Path(temporary) / "ZW3D isolated host"
        target.mkdir()
        for name in ("zw3d.exe", "ZW3D.dll"):
            shutil.copy2(sdk / name, target / name)
        arguments = [str(installer), "/install", "/target=" + str(target)]
        child = subprocess.Popen(arguments)
        notice = None
        try:
            deadline = time.monotonic() + 20
            while time.monotonic() < deadline:
                notice = find_notice(child.pid)
                if notice or child.poll() is not None:
                    break
                time.sleep(0.1)
            if not notice:
                raise AssertionError("First install did not reach a live result dialog")
            # The dialog remains visible. The second transaction must not wait 30s
            # for the first process to release its mutex.
            second = subprocess.run([str(installer), "/quiet", "/install",
                                     "/target=" + str(target)], capture_output=True,
                                    timeout=10)
            if second.returncode != 0:
                raise AssertionError(f"Second install failed while dialog open: {second.returncode}")
            print("PASS: another installation completes with first result dialog open")
        finally:
            if notice:
                user32 = ctypes.WinDLL("user32", use_last_error=True)
                user32.PostMessageW.argtypes = (ctypes.c_void_p, ctypes.c_uint, ctypes.c_size_t, ctypes.c_ssize_t)
                user32.PostMessageW(notice, 0x0010, 0, 0)  # WM_CLOSE
            try:
                child.wait(timeout=5)
            except subprocess.TimeoutExpired:
                child.terminate()  # Only the test-owned process inside isolated target.
                child.wait(timeout=5)


if __name__ == "__main__":
    main()
