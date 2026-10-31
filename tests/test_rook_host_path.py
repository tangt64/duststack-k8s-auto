"""Reject relabeling scope escapes before touching any host directory."""
import importlib.util
from pathlib import Path
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('rook_host_path', ROOT / 'scripts/prepare_rook_host_path.py')
host_path = importlib.util.module_from_spec(spec)
spec.loader.exec_module(host_path)


class RookHostPathTests(unittest.TestCase):
    def test_broad_relative_nested_and_regex_paths_are_rejected_before_changes(self):
        for value in ['/', '/var', '/var/lib', 'var/lib/rook', '/var/lib/rook/../etc',
                      '/var/lib/rook/data', '/var/lib/rook.*', '/var/lib/rook-', '/etc/rook']:
            with self.subTest(value=value), self.assertRaises(ValueError):
                host_path.checked_path(value)

    def test_dedicated_paths_are_accepted_but_symlink_resolution_escapes_are_rejected(self):
        self.assertEqual(host_path.checked_path('/var/lib/rook'), Path('/var/lib/rook'))
        self.assertEqual(host_path.checked_path('/var/lib/rook-lab_01'), Path('/var/lib/rook-lab_01'))
        with patch.object(Path, 'resolve', return_value=Path('/etc')):
            with self.assertRaises(ValueError):
                host_path.checked_path('/var/lib/rook')
        with patch.object(Path, 'is_symlink', return_value=True):
            with self.assertRaises(ValueError):
                host_path.checked_path('/var/lib/rook')


if __name__ == '__main__':
    unittest.main()
