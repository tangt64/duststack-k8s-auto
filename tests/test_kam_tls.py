import importlib.util
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('kam_tls_checked', ROOT / 'scripts/check_kam_tls.py')
tls = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tls)


class TLSPreflightTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix='kam-tls-preflight-')
        cls.folder = Path(cls.temp.name) / 'pki'
        subprocess.run([sys.executable, str(ROOT / 'scripts/kam_tls.py'), '--out', str(cls.folder), '--hostname', '127.0.0.1'], check=True, capture_output=True)

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def test_valid_dedicated_chain_and_wrong_endpoint(self):
        result = tls.validate(self.folder, 'https://127.0.0.1:30443')
        self.assertRegex(result['ca_fingerprint'], '^[a-f0-9]{64}$')
        with self.assertRaises(subprocess.CalledProcessError):
            tls.validate(self.folder, 'https://wrong.example.internal:30443')
        for origin in ['http://127.0.0.1', 'https://user:pass@127.0.0.1', 'https://127.0.0.1/path']:
            with self.assertRaises(ValueError):
                tls.validate(self.folder, origin)

    def test_mismatched_certificate_key_rejected(self):
        key = self.folder / 'kam-server.key'
        before = key.read_bytes()
        try:
            key.write_bytes((self.folder / 'kam-apiserver.key').read_bytes())
            with self.assertRaises(ValueError):
                tls.validate(self.folder, 'https://127.0.0.1')
        finally:
            key.write_bytes(before)

    @unittest.skipUnless(os.name == 'posix', 'Unix private permission check')
    def test_world_readable_private_key_rejected(self):
        key = self.folder / 'kam-server.key'
        try:
            key.chmod(0o644)
            with self.assertRaises(ValueError):
                tls.validate(self.folder, 'https://127.0.0.1')
        finally:
            key.chmod(0o600)
