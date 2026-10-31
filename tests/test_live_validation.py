"""Guard the live test harness against false positives and unsafe namespace reuse."""
import importlib.util
import contextlib
import io
from pathlib import Path
import subprocess
from unittest import mock
import unittest


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('live_validation', ROOT / 'scripts/test_live_cluster.py')
LIVE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(LIVE)


class LiveValidationTests(unittest.TestCase):
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
