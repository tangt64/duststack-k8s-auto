import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import tarfile
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('kam_source_tested', ROOT / 'scripts/kam_source.py')
source = importlib.util.module_from_spec(spec)
spec.loader.exec_module(source)


class PinnedSourceTests(unittest.TestCase):
    def fixture(self, root, extra=None):
        files = {name: ('# ' + name + '\n').encode() for name in source.REQUIRED}
        archive = io.BytesIO()
        with tarfile.open(fileobj=archive, mode='w:gz') as tar:
            for name, data in files.items():
                member = tarfile.TarInfo('KAM-source/' + name)
                member.size = len(data)
                tar.addfile(member, io.BytesIO(data))
            if extra:
                tar.addfile(extra)
        data = archive.getvalue()
        pin = {'revision': 'a' * 40, 'archive_sha256': hashlib.sha256(data).hexdigest(),
               'files_sha256': {name: hashlib.sha256(value).hexdigest() for name, value in files.items()}}
        (root / 'config').mkdir()
        (root / 'artifacts').mkdir()
        (root / 'config/kam-source.json').write_text(json.dumps(pin))
        (root / 'artifacts' / ('kiki-kam-' + pin['revision'] + '.tar.gz')).write_bytes(data)
        return pin

    def test_verified_manual_source_and_cached_tampering_rejection(self):
        with tempfile.TemporaryDirectory() as folder, patch.dict(os.environ, {}, clear=True):
            root = Path(folder)
            self.fixture(root)
            with patch.object(source, 'ROOT', root):
                target = source.prepare()
                self.assertEqual(source.source_path(), target)
                (target / 'deploy/controller.py').write_text('modified')
                with self.assertRaises(ValueError):
                    source.prepare()

    def test_archive_traversal_and_links_are_rejected_before_extraction(self):
        for member in [tarfile.TarInfo('../../../../escape'), tarfile.TarInfo('KAM-source/link')]:
            if member.name.endswith('link'):
                member.type = tarfile.SYMTYPE
                member.linkname = '/etc/passwd'
            with tempfile.TemporaryDirectory() as folder, patch.dict(os.environ, {}, clear=True):
                root = Path(folder)
                self.fixture(root, member)
                with patch.object(source, 'ROOT', root), self.assertRaises(ValueError):
                    source.prepare()


if __name__ == '__main__':
    unittest.main()
