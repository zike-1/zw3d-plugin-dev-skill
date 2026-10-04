"""Regression guards for publication failure and malformed PNG admission."""
import importlib.util
from pathlib import Path
import struct
import sys
import tempfile
import unittest
from unittest.mock import patch
import zlib

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
import build_plugin as build
import package_lib as package


class ReleaseGuards(unittest.TestCase):
    def test_failed_publication_restores_every_previous_artifact(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); out = root / 'out'; out.mkdir()
            sources = {}
            for name in ('demo.zwplug', 'demo-setup.exe', 'demo-build.json'):
                (out / name).write_bytes(('old ' + name).encode())
                source = root / name; source.write_bytes(('new ' + name).encode())
                sources[name] = source
            before = {p.name: p.read_bytes() for p in out.iterdir()}
            original = build.os.replace
            def blocked(source, target):
                if Path(source).name == 'new-1':
                    raise PermissionError('simulated installer destination failure')
                return original(source, target)
            with patch.object(build.os, 'replace', side_effect=blocked):
                with self.assertRaises(PermissionError):
                    build.publish_artifacts(out, sources)
            self.assertEqual({p.name: p.read_bytes() for p in out.iterdir()}, before)

    def test_failed_recovery_retains_original_and_reports_location(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); out = root / 'out'; out.mkdir()
            (out / 'demo.zwplug').write_bytes(b'old')
            source = root / 'new'; source.write_bytes(b'new')
            original = build.os.replace
            def blocked(source, target):
                if Path(source).name in ('new-0', 'old-0'):
                    raise PermissionError('simulated external occupation')
                return original(source, target)
            with patch.object(build.os, 'replace', side_effect=blocked):
                with self.assertRaisesRegex(package.PackageError, 'retained files'):
                    build.publish_artifacts(out, {'demo.zwplug': source})
            backups = list(out.glob('.zwplug-publish-*/old-0'))
            self.assertEqual(len(backups), 1)
            self.assertEqual(backups[0].read_bytes(), b'old')

    def test_scanline_filters(self):
        def chunk(kind, data):
            return struct.pack('>I', len(data)) + kind + data + struct.pack('>I', zlib.crc32(kind + data) & 0xffffffff)
        for filter_type in range(6):
            image = (b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', 16, 16, 8, 6, 0, 0, 0))
                     + chunk(b'IDAT', zlib.compress((bytes([filter_type]) + bytes(64)) * 16)) + chunk(b'IEND', b''))
            with self.subTest(filter_type=filter_type):
                if filter_type <= 4:
                    package.validate_icon(image)
                else:
                    with self.assertRaisesRegex(package.PackageError, 'scanline filter'):
                        package.validate_icon(image)


if __name__ == '__main__':
    unittest.main(verbosity=2)
