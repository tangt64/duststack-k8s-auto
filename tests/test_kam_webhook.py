import copy
import importlib.util
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('kam_webhook', ROOT / 'scripts/configure_kam_webhook.py')
webhook = importlib.util.module_from_spec(spec)
spec.loader.exec_module(webhook)


class WebhookTests(unittest.TestCase):
    def pod(self):
        return {'kind': 'Pod', 'spec': {'containers': [{'name': 'kube-apiserver', 'command': [
            'kube-apiserver', '--client-ca-file=/etc/kubernetes/pki/ca.crt',
            '--service-account-issuer=https://kubernetes.default.svc', '--authorization-mode=Node,RBAC',
            '--advertise-address=10.0.0.1', '--service-cluster-ip-range=172.25.0.0/16']} ]}}

    def test_native_auth_addresses_and_cidrs_survive_idempotent_update(self):
        original = self.pod()
        configured, audience = webhook.configure(copy.deepcopy(original))
        self.assertEqual(audience, 'https://kubernetes.default.svc')
        command = configured['spec']['containers'][0]['command']
        for flag in original['spec']['containers'][0]['command']:
            self.assertIn(flag, command)
        second, _ = webhook.configure(copy.deepcopy(configured))
        self.assertEqual(configured, second)
        self.assertNotIn('api-audiences', '\n'.join(command))

    def test_existing_webhook_and_volume_conflicts_fail_closed(self):
        p = self.pod()
        p['spec']['containers'][0]['command'].append('--authentication-token-webhook-config-file=/other/config')
        with self.assertRaises(ValueError):
            webhook.configure(p)
        p = self.pod()
        p['spec']['volumes'] = [{'name': 'kiki-kam-webhook', 'hostPath': {'path': '/other'}}]
        with self.assertRaises(ValueError):
            webhook.configure(p)


if __name__ == '__main__':
    unittest.main()
