import importlib.util
from pathlib import Path
import subprocess
import unittest

spec = importlib.util.spec_from_file_location('kam_live_helm', Path(__file__).resolve().parents[1]/'scripts/test_live_kam_helm.py')
live = importlib.util.module_from_spec(spec)
spec.loader.exec_module(live)


class LiveHelmTests(unittest.TestCase):
    def test_rollback_confirmation_accepts_stderr_but_not_generic_failure_or_success(self):
        message = 'Webhook update failed; captured manifest and dedicated TLS/config files were restored.'
        for stdout, stderr in [(message, ''), ('', message)]:
            self.assertTrue(live.restored_failure(subprocess.CompletedProcess([], 2, stdout, stderr)))
        self.assertFalse(live.restored_failure(subprocess.CompletedProcess([], 0, message, '')))
        self.assertFalse(live.restored_failure(subprocess.CompletedProcess([], 2, '', 'generic failure')))
