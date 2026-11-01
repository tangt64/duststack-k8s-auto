import copy
from datetime import datetime, timezone, timedelta
import importlib.util
from pathlib import Path
import unittest
from test_configuration import variables, render, read_yaml

ROOT = Path(__file__).resolve().parents[1]


def module(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / 'addons/kam' / (name + '.py'))
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


kam = module('controller')
renderer = module('render')


def grant(**spec):
    return {'metadata': {'name': 'alice', 'namespace': 'dev', 'uid': 'grant-uid', 'generation': 1},
            'spec': {'subject': {'kind': 'User', 'name': 'Alice@example.com'}, 'profile': 'view', **spec}}


class FakeAPI:
    def __init__(self):
        self.obj = None
        self.calls = []

    def call(self, method, path, body=None):
        self.calls.append((method, path, copy.deepcopy(body)))
        if method == 'GET':
            return copy.deepcopy(self.obj)
        if method in ('POST', 'PUT'):
            self.obj = copy.deepcopy(body)
            self.obj['metadata'].update(uid='binding-uid', resourceVersion='1')
        if method == 'DELETE':
            assert body['preconditions']['uid'] == self.obj['metadata']['uid']
            self.obj = None


class KamTests(unittest.TestCase):
    def test_repeat_reconciliation_creates_only_once(self):
        api = FakeAPI()
        for _ in range(3):
            kam.reconcile(api, grant(), 'dev', {'view'})
        self.assertEqual(sum(c[0] == 'POST' for c in api.calls), 1)
        self.assertEqual(api.obj['subjects'][0]['name'], 'Alice@example.com')

    def test_expiry_removes_only_owned_binding(self):
        api = FakeAPI()
        kam.reconcile(api, grant(), 'dev', {'view'})
        self.assertEqual(kam.reconcile(api, grant(expiresAt='2020-01-01T00:00:00Z'), 'dev', {'view'}), 'Expired')
        self.assertIsNone(api.obj)

    def test_foreign_binding_is_never_adopted_or_removed(self):
        api = FakeAPI()
        api.obj = {'metadata': {'uid': 'foreign'}}
        with self.assertRaisesRegex(ValueError, 'adopt'):
            kam.reconcile(api, grant(), 'dev', {'view'})
        self.assertEqual([c[0] for c in api.calls], ['GET'])

    def test_disallowed_profile_and_cross_namespace_fail_before_mutation(self):
        for g, ns in [(grant(profile='admin'), 'dev'), (grant(), 'other')]:
            api = FakeAPI()
            with self.assertRaises(ValueError):
                kam.reconcile(api, g, ns, {'view'})
            self.assertFalse(api.calls)

    def test_role_ref_change_replaces_instead_of_updating(self):
        api = FakeAPI()
        kam.reconcile(api, grant(), 'dev', {'view', 'edit'})
        kam.reconcile(api, grant(profile='edit'), 'dev', {'view', 'edit'})
        self.assertEqual([c[0] for c in api.calls], ['GET', 'POST', 'GET', 'DELETE', 'POST'])

    def test_delete_failure_is_propagated(self):
        class Failing(FakeAPI):
            def call(self, method, path, body=None):
                if method == 'DELETE':
                    raise RuntimeError('API denied')
                return super().call(method, path, body)
        api = Failing()
        kam.reconcile(api, grant(), 'dev', {'view'})
        with self.assertRaisesRegex(RuntimeError, 'denied'):
            kam.reconcile(api, grant(expiresAt='2020-01-01T00:00:00Z'), 'dev', {'view'})

    def test_lease_prevents_second_writer_and_allows_expired_takeover(self):
        api = FakeAPI()
        at = datetime(2026, 1, 1, tzinfo=timezone.utc)
        self.assertTrue(kam.acquire(api, 'dev', 'one', at))
        self.assertFalse(kam.acquire(api, 'dev', 'two', at + timedelta(seconds=20)))
        self.assertTrue(kam.acquire(api, 'dev', 'two', at + timedelta(seconds=61)))

    def test_manifests_have_no_cluster_admin_secret_access_or_cr_writer(self):
        docs = renderer.manifests('dev', 'python@sha256:' + 'a' * 64, ['view'])
        role = next(d for d in docs if d['kind'] == 'Role')
        for rule in role['rules']:
            self.assertNotIn('secrets', rule['resources'])
            self.assertNotIn('escalate', rule['verbs'])
            if 'kamaccessgrants' in rule['resources']:
                self.assertEqual(rule['verbs'], ['get', 'list'])
        self.assertFalse(any(d['kind'] == 'ClusterRoleBinding' for d in docs))
        for doc in docs:
            if doc['kind'] in ('ServiceAccount', 'ConfigMap', 'Deployment'):
                self.assertEqual(doc['metadata']['namespace'], 'kam-system')

    def test_requires_pinned_image(self):
        with self.assertRaises(ValueError):
            renderer.manifests('dev', 'python:latest', ['view'])


class HATests(unittest.TestCase):
    def test_combined_mode_unicast_and_local_proxy_probe(self):
        values = variables(k8s_proxy_mode='haproxy_keepalived', inventory_hostname='lb1',
                           groups={'lb': ['lb1', 'lb2'], 'k8s_master': ['cp1', 'cp2', 'cp3']},
                           hostvars={'lb2': {'k8s_ip4': '10.10.10.252/24'}})
        text = render('roles/core/core-keepalived/templates/keepalived.conf.j2', values)
        self.assertIn('unicast_peer', text)
        self.assertIn('10.10.10.252', text)
        self.assertNotIn('weight -50', text)

    def test_proxy_tls_readiness_checks_and_bootstrap(self):
        for enabled in (False, True):
            text = render('roles/core/core-haproxy/templates/haproxy.conf.j2', variables(
                k8s_proxy_mode='haproxy_keepalived', k8s_lb_ready_checks=enabled))
            self.assertIn('bind 127.0.0.1:8404', text)
            self.assertEqual('http-check expect status 200' in text, enabled)
            self.assertEqual('verify required' in text, enabled)
            self.assertEqual(sum(line.startswith('    server control') for line in text.splitlines()), 3)


if __name__ == '__main__':
    unittest.main()
