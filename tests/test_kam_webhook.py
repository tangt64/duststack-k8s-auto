import copy
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
import yaml

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

    def test_bundle_rotation_restarts_static_pod_and_remains_idempotent(self):
        first, _ = webhook.configure(self.pod(), bundle_sha256='a' * 64)
        same, _ = webhook.configure(copy.deepcopy(first), bundle_sha256='a' * 64)
        self.assertEqual(first, same)
        renewed, _ = webhook.configure(copy.deepcopy(first), bundle_sha256='b' * 64)
        self.assertNotEqual(first, renewed)
        self.assertEqual(first['spec'], renewed['spec'])
        self.assertEqual(renewed['metadata']['annotations']['access.kam.dustbox.kr/webhook-bundle-sha256'], 'b' * 64)
        with self.assertRaises(ValueError):
            webhook.configure(self.pod(), bundle_sha256='invalid')

    @unittest.skipUnless(shutil.which('ansible-playbook'), 'Ansible expression integration')
    def test_actual_mirror_readiness_expression_requires_new_uid_and_bundle(self):
        play = yaml.safe_load((ROOT / 'playbooks/k8s-kam-webhook.yaml').read_text())[1]
        block = next(t['block'] for t in play['tasks'] if 'block' in t)
        condition = next(t['until'] for t in block if t['name'].startswith('Observe the new API mirror'))
        def response(uid, checksum):
            return {'rc': 0, 'stdout': json.dumps({'items': [{'metadata': {'uid': uid, 'annotations': {'access.kam.dustbox.kr/webhook-bundle-sha256': checksum}}, 'status': {'conditions': [{'type': 'Ready', 'status': 'True'}]}}]})}
        cases = [('new-mirror', response('new', 'b' * 64), True),
                 ('old-mirror', response('old', 'b' * 64), False),
                 ('wrong-bundle', response('new', 'a' * 64), False)]
        not_ready = response('new', 'b' * 64)
        pod = json.loads(not_ready['stdout'])
        pod['items'][0]['status']['conditions'][0]['status'] = 'False'
        not_ready['stdout'] = json.dumps(pod)
        cases.append(('new-but-not-ready', not_ready, False))
        no_annotation = response('new', 'b' * 64)
        pod = json.loads(no_annotation['stdout'])
        del pod['items'][0]['metadata']['annotations']
        no_annotation['stdout'] = json.dumps(pod)
        cases.append(('missing-bundle-annotation', no_annotation, False))
        plays = [{'name': name, 'hosts': 'localhost', 'gather_facts': False,
                  'vars': {'kam_old_mirror': response('old', 'a' * 64), 'kam_new_mirror': result, 'kam_bundle_sha256': 'b' * 64},
                  'tasks': [{'ansible.builtin.assert': {'that': [condition if expected else 'not (' + condition + ')']}}]}
                 for name, result, expected in cases]
        with tempfile.TemporaryDirectory(prefix='kam-mirror-expression-') as folder:
            path = Path(folder) / 'test.yaml'
            path.write_text(yaml.safe_dump(plays), encoding='utf-8')
            result = subprocess.run(['ansible-playbook', '-i', 'localhost,', str(path)], cwd=ROOT, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == '__main__':
    unittest.main()
