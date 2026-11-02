"""A cache refresh must not truncate an executable used by another API test."""
import importlib.util
import io
from pathlib import Path
import subprocess
import tarfile
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('envtest_cache', ROOT / 'scripts/prepare_kam_envtest.py')
cache = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cache)


@unittest.skipUnless(Path('/bin/sleep').is_file(), 'Linux executable cache regression')
class EnvtestCacheTests(unittest.TestCase):
    def test_refresh_during_execution_and_corrupt_file_repair(self):
        binary = Path('/bin/sleep').read_bytes()
        archive = io.BytesIO()
        with tarfile.open(fileobj=archive, mode='w') as bundle:
            for name in ['etcd', 'kube-apiserver', 'kubectl']:
                item = tarfile.TarInfo('controller-tools/envtest/' + name)
                item.size = len(binary)
                bundle.addfile(item, io.BytesIO(binary))
        with tempfile.TemporaryDirectory(prefix='envtest-cache-') as folder:
            directory = Path(folder)
            def refresh():
                with tarfile.open(fileobj=io.BytesIO(archive.getvalue())) as bundle:
                    cache.extract_verified(bundle, directory)
            refresh()
            running = subprocess.Popen([str(directory / 'controller-tools/envtest/etcd'), '30'])
            try:
                (directory / 'controller-tools/envtest/kubectl').write_bytes(b'tampered')
                refresh()
                self.assertIsNone(running.poll())
                self.assertEqual((directory / 'controller-tools/envtest/kubectl').read_bytes(), binary)
            finally:
                running.terminate()
                running.wait(timeout=5)
