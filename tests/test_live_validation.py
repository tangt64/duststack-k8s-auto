"""Guard the live test harness against false positives and unsafe namespace reuse."""
import importlib.util
import contextlib
import io
import json
from pathlib import Path
import subprocess
import tempfile
from unittest import mock
import unittest


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('live_validation', ROOT / 'scripts/test_live_cluster.py')
LIVE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(LIVE)


class LiveValidationTests(unittest.TestCase):
    def test_ceph_key_reporting_contains_metadata_only(self):
        ceph = {'status': {'phase': 'Ready', 'ceph': {'health': 'HEALTH_OK'}, 'cephx': {
            'csi': {'keyType': 'aes', 'keyGeneration': 2, 'priorKeyCount': 1, 'key': 'SYNTHETIC-DO-NOT-EXPORT'},
            'mgr': {'keyType': 'aes256k'}, 'osd': {'keyType': 'aes256k'}}}}
        result = LIVE.ceph_health_result(ceph)
        self.assertEqual(result['csi_key_metadata'], {'keyType': 'aes', 'keyGeneration': 2, 'priorKeyCount': 1})
        self.assertNotIn('SYNTHETIC', json.dumps(result))
        self.assertEqual(result['daemon_key_types'], {'mgr': 'aes256k', 'osd': 'aes256k'})

    def test_compatibility_mode_does_not_accept_clock_storage_or_security_errors(self):
        import copy
        value = {'status': {'phase': 'Ready', 'ceph': {'health': 'HEALTH_WARN', 'details': {
            'AUTH_INSECURE_KEYS_ALLOWED': {'severity': 'HEALTH_WARN', 'message': 'legacy clients'}}},
            'cephx': {'mgr': {'keyType': 'aes256k'}, 'osd': {'keyType': 'aes256k'}}}}
        self.assertIsNone(LIVE.ceph_health_result(value))
        self.assertEqual(LIVE.ceph_health_result(value, True)['health'], 'HEALTH_WARN')
        for warning in ['MON_CLOCK_SKEW', 'OSD_DOWN', 'PG_DEGRADED', 'AUTH_INSECURE_SERVICE_KEY_TYPE', 'UNKNOWN']:
            changed = copy.deepcopy(value)
            changed['status']['ceph']['details'][warning] = {'severity': 'HEALTH_WARN'}
            with self.subTest(warning=warning):
                self.assertIsNone(LIVE.ceph_health_result(changed, True))
        changed = copy.deepcopy(value)
        changed['status']['cephx']['osd']['keyType'] = 'aes'
        self.assertIsNone(LIVE.ceph_health_result(changed, True))
        for cipher in ['aes', None]:
            with self.assertRaises(RuntimeError):
                LIVE.require_secure_service_cipher({'monmap': {'auth_service_cipher': {'name': cipher}}})

    def test_full_run_with_acknowledged_warnings_never_reports_unqualified_pass(self):
        nodes = [{'metadata': {'name': 'worker' + str(i)}, 'spec': {},
                  'status': {'conditions': [{'type': 'Ready', 'status': 'True'}]}} for i in range(1, 4)]
        ceph = {'status': {'phase': 'Ready', 'ceph': {'health': 'HEALTH_WARN', 'details': {
            'AUTH_INSECURE_KEYS_ALLOWED': {'severity': 'HEALTH_WARN', 'message': 'legacy clients'}}},
            'cephx': {'mgr': {'keyType': 'aes256k'}, 'osd': {'keyType': 'aes256k'}}}}
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder) / 'result.json'
            stdout = io.StringIO()
            with mock.patch('sys.argv', ['test_live_cluster.py', '--confirm-test-workloads',
                            '--allow-ceph-legacy-client-key-warnings', '--output', str(output)]), \
                    mock.patch.object(LIVE, 'Cluster') as cluster_type, \
                    mock.patch.object(LIVE, 'network_tests'), mock.patch.object(LIVE, 'storage_tests'), \
                    mock.patch.object(LIVE, 'rook_csi_runtime', return_value={'warnings': []}), \
                    contextlib.redirect_stdout(stdout):
                cluster_type.return_value.read.side_effect = [
                    {'items': nodes}, {'status': {'desiredNumberScheduled': 4, 'numberReady': 4}},
                    ceph, {'spec': {'replicated': {'size': 3}}}]
                cluster_type.return_value.run.return_value.stdout = json.dumps({
                    'monmap': {'auth_service_cipher': {'name': 'aes256k'}}})
                LIVE.main()
            result = json.loads(output.read_text())
            self.assertEqual(result['status'], 'passed_with_warnings')
            self.assertEqual(result['completed_providers'], ['nfs', 'rook'])
            self.assertIn('AUTH_INSECURE_KEYS_ALLOWED', result['warnings'])
            self.assertIn('LIVE_CLUSTER_VALIDATION=PASS_WITH_WARNINGS', stdout.getvalue().splitlines())
            self.assertNotIn('LIVE_CLUSTER_VALIDATION=PASS', stdout.getvalue().splitlines())

    def test_legacy_csi_runtime_requires_explicit_lab_flag_and_preserves_actual_versions(self):
        cluster = mock.Mock()
        cluster.read.return_value = {'status': {'desiredNumberScheduled': 3, 'numberReady': 3},
            'spec': {'template': {'spec': {'containers': [{'name': 'csi-rbdplugin',
                'image': 'quay.io/cephcsi/cephcsi:v3.16.3@sha256:' + 'a' * 64}]}}}}
        cluster.run.return_value.stdout = json.dumps({'serverVersion': {'gitVersion': 'v1.36.6'}})
        with self.assertRaisesRegex(RuntimeError, 'explicit --allow-legacy-csi-lab'):
            LIVE.rook_csi_runtime(cluster, 'rook-ceph')
        result = LIVE.rook_csi_runtime(cluster, 'rook-ceph', True)
        self.assertEqual(result['kubernetes'], 'v1.36.6')
        self.assertIn('1.32-1.34', result['warnings'][0])
        cluster.run.return_value.stdout = json.dumps({'serverVersion': {'gitVersion': 'v1.37.2'}})
        with self.assertRaises(RuntimeError):
            LIVE.rook_csi_runtime(cluster, 'rook-ceph', True)

    def test_legacy_csi_alone_cannot_produce_unqualified_full_pass(self):
        nodes = [{'metadata': {'name': 'worker' + str(i)}, 'spec': {},
                  'status': {'conditions': [{'type': 'Ready', 'status': 'True'}]}} for i in range(1, 4)]
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder) / 'result.json'
            with mock.patch('sys.argv', ['test_live_cluster.py', '--confirm-test-workloads',
                            '--allow-legacy-csi-lab', '--output', str(output)]), \
                    mock.patch.object(LIVE, 'Cluster') as cluster_type, \
                    mock.patch.object(LIVE, 'network_tests'), mock.patch.object(LIVE, 'storage_tests'), \
                    mock.patch.object(LIVE, 'rook_csi_runtime', return_value={'warnings': ['legacy lab']}), \
                    contextlib.redirect_stdout(io.StringIO()):
                cluster_type.return_value.read.side_effect = [
                    {'items': nodes}, {'status': {'desiredNumberScheduled': 4, 'numberReady': 4}},
                    {'status': {'phase': 'Ready', 'ceph': {'health': 'HEALTH_OK'}}},
                    {'spec': {'replicated': {'size': 3}}}]
                LIVE.main()
            result = json.loads(output.read_text())
            self.assertEqual(result['status'], 'passed_with_warnings')
            self.assertEqual(result['warnings'], {})
            self.assertEqual(result['compatibility_warnings'], ['legacy lab'])

    def test_partial_storage_run_is_never_reported_as_full_cluster_success(self):
        nodes = [{'metadata': {'name': 'worker' + str(i)}, 'spec': {},
                  'status': {'conditions': [{'type': 'Ready', 'status': 'True'}]}}
                 for i in range(1, 4)]
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder) / 'result.json'
            stdout = io.StringIO()
            with mock.patch('sys.argv', ['test_live_cluster.py', '--confirm-test-workloads',
                            '--providers', 'nfs', '--output', str(output)]), \
                    mock.patch.object(LIVE, 'Cluster') as cluster_type, \
                    mock.patch.object(LIVE, 'network_tests'), \
                    mock.patch.object(LIVE, 'storage_tests'), contextlib.redirect_stdout(stdout):
                cluster_type.return_value.read.side_effect = [
                    {'items': nodes}, {'status': {'desiredNumberScheduled': 4, 'numberReady': 4}}]
                LIVE.main()
            result = json.loads(output.read_text(encoding='utf-8'))
            self.assertEqual(result['status'], 'partial_passed')
            self.assertEqual(result['requested_providers'], ['nfs'])
            self.assertEqual(result['completed_providers'], ['nfs'])
            self.assertIn('LIVE_CLUSTER_VALIDATION=PARTIAL_PASS', stdout.getvalue().splitlines())
            self.assertNotIn('LIVE_CLUSTER_VALIDATION=PASS', stdout.getvalue().splitlines())

    def test_pod_wait_is_not_cut_short_by_a_metadata_request_timeout(self):
        with mock.patch.object(LIVE.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0, '', '')) as run:
            LIVE.Cluster('/unused', 'duststack-e2e-test').ready('reader')
            command = run.call_args.args[0]
            self.assertIn('--timeout=600s', command)
            self.assertIn('--request-timeout=620s', command)
            self.assertNotIn('--request-timeout=30s', command)
            self.assertGreater(run.call_args.kwargs['timeout'], 620)

    def test_production_namespace_is_rejected_before_any_kubectl_call(self):
        with mock.patch('sys.argv', ['test_live_cluster.py', '--confirm-test-workloads', '--namespace', 'production']), \
                mock.patch.object(LIVE.subprocess, 'run') as execute, contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit) as result:
                LIVE.main()
            self.assertEqual(result.exception.code, 2)
            execute.assert_not_called()

    def test_api_or_exec_errors_cannot_count_as_network_policy_denial(self):
        cluster = LIVE.Cluster('/unused', 'duststack-e2e-test')
        with mock.patch.object(LIVE.subprocess, 'run', return_value=subprocess.CompletedProcess(
                [], 1, stdout='', stderr='container exec unavailable')):
            with self.assertRaisesRegex(RuntimeError, 'container exec unavailable'):
                cluster.execute('client', 'echo DENIED')

    def test_workload_scheduling_preserves_wait_for_first_consumer_binding(self):
        value = LIVE.pod('duststack-e2e-test', 'reader', 'worker2', 'busybox:1.37.0', claim='rbd-io')
        self.assertNotIn('nodeName', value['spec'])
        self.assertEqual(value['spec']['nodeSelector'], {'kubernetes.io/hostname': 'worker2'})
        self.assertFalse(value['spec']['automountServiceAccountToken'])
        self.assertTrue(value['spec']['securityContext']['runAsNonRoot'])

    def test_no_ready_worker_selection_can_include_the_control_plane(self):
        def node(name, labels=None, ready=True):
            return {'metadata': {'name': name, 'labels': labels or {}}, 'spec': {},
                    'status': {'conditions': [{'type': 'Ready', 'status': str(ready)}]}}
        nodes = [node('cp1', {'node-role.kubernetes.io/control-plane': ''}),
                 node('worker1'), node('worker2'), node('worker3', ready=False)]
        with self.assertRaisesRegex(RuntimeError, 'three Ready'):
            LIVE.require_ready_workers(nodes)
        nodes.append(node('worker4'))
        self.assertEqual(LIVE.require_ready_workers(nodes), ['worker1', 'worker2', 'worker4'])


if __name__ == '__main__':
    unittest.main()
