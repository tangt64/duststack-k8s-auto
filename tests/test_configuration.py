"""Local regression checks; never connect to inventory hosts."""
import json
import base64
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

import yaml
from ansible.parsing.dataloader import DataLoader
from ansible.template import Templar
from ansible.template import trust_as_template

ROOT = Path(__file__).resolve().parents[1]


def read_yaml(path):
    return yaml.safe_load((ROOT / path).read_text(encoding='utf-8'))


def variables(**overrides):
    values = read_yaml('inventory/group_vars/kubernetes/default')
    values.update(read_yaml('inventory/group_vars/kubernetes/addons'))
    values.update({
        'nodename': 'master1.example.com', 'k8s_ip4': '10.10.10.10/24',
        'ansible_version': {'full': '2.21.5'},
        'ansible_facts': {
            'os_family': 'RedHat', 'distribution_major_version': '9',
            'kernel': '5.14.0', 'eth1': {'ipv4': {'address': '10.10.10.10'}},
        },
        'groups': {'k8s_master': ['cp1', 'cp2', 'cp3'], 'k8s_node': ['worker1'], 'lb': ['lb1']},
        'hostvars': {
            'cp1': {'k8s_ip4': '10.10.10.10/24', 'nodename': 'master1.example.com'},
            'cp2': {'k8s_ip4': '10.10.10.20/24', 'nodename': 'master2.example.com'},
            'cp3': {'k8s_ip4': '10.10.10.30/24', 'nodename': 'master3.example.com'},
            'worker1': {'k8s_ip4': '10.10.10.40/24', 'nodename': 'worker1.example.com'},
        },
        'k8s_join_control_plane': False,
        'k8s_join_command': {'stdout': 'kubeadm join api.example.com:6443 --token abcdef.0123456789abcdef --discovery-token-ca-cert-hash sha256:' + 'a' * 64},
        'k8s_upload_certs': {'stdout_lines': ['[upload-certs] certificate key:', 'b' * 64]},
        'keepalived_node': 'backup', 'keepalived_pri': 99,
    })
    values.update(overrides)
    # Configuration files are trusted project sources, as they are in a playbook.
    def trust(value):
        if isinstance(value, str):
            return trust_as_template(value)
        if isinstance(value, dict):
            return {k: trust(v) for k, v in value.items()}
        if isinstance(value, list):
            return [trust(v) for v in value]
        return value
    return trust(values)


def templar(values):
    return Templar(loader=DataLoader(), variables=values)


def render(path, values):
    return templar(values).template(trust_as_template((ROOT / path).read_text(encoding='utf-8')))


class ConfigurationTests(unittest.TestCase):
    def test_init_single_ha_runtimes_and_audit(self):
        for runtime in ('crio', 'containerd'):
            for ha in (False, True):
                for audit in (False, True):
                    with self.subTest(runtime=runtime, ha=ha, audit=audit):
                        text = render('roles/kubernetes/k8s-prepare/templates/kubeadm-config.yaml', variables(
                            k8s_runtime_environment=runtime, k8s_proxy_mode_enable=ha, k8s_audit_enabled=audit))
                        init, cluster, kubelet, proxy = list(yaml.safe_load_all(text))
                        self.assertEqual(init['apiVersion'], 'kubeadm.k8s.io/v1beta4')
                        self.assertIn(runtime, init['nodeRegistration']['criSocket'])
                        self.assertEqual(cluster['controlPlaneEndpoint'], 'api.example.com:6443' if ha else '10.10.10.10:6443')
                        self.assertEqual(cluster['networking']['podSubnet'], '10.88.0.0/16')
                        self.assertIsInstance(cluster['apiServer']['extraArgs'], list)
                        self.assertEqual('extraVolumes' in cluster['apiServer'], audit)
                        self.assertEqual(kubelet['cgroupDriver'], 'systemd')
                        self.assertTrue(kubelet['seccompDefault'])
                        self.assertNotIn('certificateKey', init)
                        self.assertNotIn('token:', text)

    def test_join_workers_and_control_planes(self):
        for control_plane in (False, True):
            for runtime in ('crio', 'containerd'):
                with self.subTest(control_plane=control_plane, runtime=runtime):
                    value = yaml.safe_load(render('roles/kubernetes/k8s-join/templates/kubeadm-join.yaml.j2', variables(
                        k8s_join_control_plane=control_plane, k8s_runtime_environment=runtime)))
                    self.assertEqual(value['apiVersion'], 'kubeadm.k8s.io/v1beta4')
                    self.assertEqual(value['discovery']['bootstrapToken']['apiServerEndpoint'], 'api.example.com:6443')
                    self.assertTrue(value['discovery']['bootstrapToken']['caCertHashes'][0].startswith('sha256:'))
                    self.assertEqual('controlPlane' in value, control_plane)
                    self.assertEqual(value['nodeRegistration']['kubeletExtraArgs'], [{'name': 'node-ip', 'value': '10.10.10.10'}])
                    if control_plane:
                        self.assertEqual(value['controlPlane']['certificateKey'], 'b' * 64)

    def test_cni_can_use_kubelet_addresses_with_different_nic_names(self):
        for interface in ['ens3', 'ens7']:
            values = variables(k8s_interface=interface, calico_use_node_internal_ip=True)
            install = list(yaml.safe_load_all(render('roles/cni/cni-calico/templates/custom-resources.yaml', values)))[0]
            self.assertEqual(install['spec']['calicoNetwork']['nodeAddressAutodetectionV4'],
                             {'kubernetes': 'NodeInternalIP'})

    def test_mixed_calico_nics_require_explicit_address_policy(self):
        task = next(t for t in read_yaml('tasks/preflight.yaml')
                    if t.get('name', '').startswith('Require explicit Calico'))
        for nics, opt_in, expected in [(['ens7', 'ens7'], False, True),
                                       (['ens7', 'ens3'], False, False),
                                       (['ens7', 'ens3'], True, True)]:
            engine = templar(variables(calico_private_nics=nics, calico_use_node_internal_ip=opt_in))
            self.assertEqual(all(engine.evaluate_conditional(trust_as_template(x))
                                 for x in task['ansible.builtin.assert']['that']), expected)

    def test_cni_matches_custom_cidr_and_interface(self):
        values = variables(k8s_pod_cidr='172.20.0.0/16', k8s_interface='ens192')
        install = list(yaml.safe_load_all(render('roles/cni/cni-calico/templates/custom-resources.yaml', values)))[0]
        self.assertEqual(install['spec']['calicoNetwork']['ipPools'][0]['cidr'], '172.20.0.0/16')
        self.assertEqual(install['spec']['calicoNetwork']['nodeAddressAutodetectionV4']['interface'], 'ens192')
        flannel = list(yaml.safe_load_all(render('roles/cni/cni-flanned/templates/flanned-config.yaml', values)))
        config = next(x for x in flannel if x['kind'] == 'ConfigMap')
        self.assertEqual(json.loads(config['data']['net-conf.json'])['Network'], '172.20.0.0/16')
        daemon = next(x for x in flannel if x['kind'] == 'DaemonSet')
        self.assertIn('--iface=ens192', daemon['spec']['template']['spec']['containers'][0]['args'])

    def test_calico_reapply_preserves_operator_pool_defaults(self):
        extra = {'allowedUses': ['Workload', 'Tunnel'], 'assignmentMode': 'Automatic',
                 'disableBGPExport': False, 'name': 'default-ipv4-ippool'}
        install = list(yaml.safe_load_all(render('roles/cni/cni-calico/templates/custom-resources.yaml',
                                                variables(calico_preserved_pool=extra))))[0]
        pool = install['spec']['calicoNetwork']['ipPools'][0]
        self.assertEqual({key: pool[key] for key in extra}, extra)
        self.assertEqual(pool['cidr'], variables()['k8s_pod_cidr'])

    def test_calico_reapply_rejects_existing_pool_policy_changes(self):
        task = next(t for t in read_yaml('roles/cni/cni-calico/tasks/main.yaml')
                    if t.get('name', '').startswith('Reject changes'))
        pool = {'cidr': variables()['k8s_pod_cidr'], 'blockSize': 26,
                'encapsulation': 'VXLAN', 'natOutgoing': 'Enabled', 'nodeSelector': 'all()'}
        for change, expected in [({}, True), ({'cidr': '172.22.0.0/16'}, False),
                                 ({'blockSize': 24}, False), ({'encapsulation': 'IPIP'}, False)]:
            engine = templar(variables(calico_existing_pools=[dict(pool, **change)],
                                       calico_existing_network={'bgp': 'Disabled'}))
            self.assertEqual(all(engine.evaluate_conditional(trust_as_template(x))
                                 for x in task['ansible.builtin.assert']['that']), expected)

    def test_existing_operator_is_preserved_and_version_changes_are_rejected(self):
        tasks = read_yaml('roles/cni/cni-calico/tasks/main.yaml')
        guard = next(t for t in tasks if t.get('name') == 'Reject implicit operator version changes')
        bootstrap = next(t for t in tasks if t.get('name', '').startswith('Bootstrap Calico CRDs'))
        expected = {'kind': 'Deployment', 'metadata': {'name': 'tigera-operator'},
                    'spec': {'template': {'spec': {'containers': [{'image': 'operator:pinned'}]}}}}
        content = base64.b64encode(yaml.safe_dump(expected).encode()).decode()
        for image, allowed in [('operator:pinned', True), ('operator:other', False)]:
            current = {'spec': {'template': {'spec': {'containers': [{'image': image}]}}}}
            engine = templar(variables(calico_operator_existing={'stdout': json.dumps(current)},
                calico_operator_manifest={'content': content},
                calico_expected_operator=guard['vars']['calico_expected_operator'], ansible_check_mode=False))
            self.assertEqual(all(engine.evaluate_conditional(trust_as_template(x))
                                 for x in guard['ansible.builtin.assert']['that']), allowed)
            self.assertFalse(engine.evaluate_conditional(trust_as_template(bootstrap['when'])))
        for checking in [False, True]:
            engine = templar(variables(calico_operator_existing={'stdout': ''}, ansible_check_mode=checking))
            self.assertEqual(engine.evaluate_conditional(trust_as_template(bootstrap['when'])), not checking)

    def test_containerd_configuration_is_valid_toml(self):
        import tomllib
        config = tomllib.loads(render('roles/core/core-containerd/templates/config.toml.j2', variables()))
        self.assertEqual(config['version'], 3)
        runtime = config['plugins']['io.containerd.cri.v1.runtime']
        self.assertTrue(runtime['enable_selinux'])
        self.assertTrue(runtime['containerd']['runtimes']['runc']['options']['SystemdCgroup'])

    def test_load_balancer_uses_internal_addresses(self):
        text = render('roles/core/core-haproxy/templates/haproxy.conf.j2', variables())
        self.assertIn('bind *:6443', text)
        self.assertIn('10.10.10.20:6443 check', text)
        self.assertNotIn('httpchk', text)
        keepalived = render('roles/core/core-keepalived/templates/keepalived.conf.j2', variables())
        self.assertIn('priority 99', keepalived)
        self.assertIn('state BACKUP', keepalived)

    def test_preflight_rejects_unsupported_and_unsafe_settings(self):
        assertions = read_yaml('tasks/preflight.yaml')[0]['ansible.builtin.assert']['that']
        def valid(values):
            return all(templar(values).evaluate_conditional(trust_as_template(x)) for x in assertions)
        self.assertTrue(valid(variables()))
        for overrides in (
            {'k8s_version': '1.28.0'}, {'k8s_runtime_environment': 'docker'},
            {'k8s_instmethod': 'cmd'}, {'enabled_virtual': True},
            {'k8s_proxy_mode_enable': False}, {'manage_os_network': True},
            {'crio_version': '1.28.0'}, {'use_firewalld': True},
            {'ansible_version': {'full': '2.19.0'}},
        ):
            with self.subTest(overrides=overrides):
                self.assertFalse(valid(variables(**overrides)))
        self.assertTrue(valid(variables(k8s_proxy_mode_enable=False, groups={'k8s_master': ['cp1'], 'k8s_node': [], 'lb': []})))

    def test_existing_cluster_version_guard(self):
        task = next(x for x in read_yaml('tasks/preflight.yaml') if x.get('name') == 'Prevent implicit upgrades of existing clusters')
        expression = task['ansible.builtin.assert']['that']
        for installed, expected in [('v1.28.0', False), ('v1.37.1', False), ('v1.37.2', True)]:
            self.assertEqual(templar(variables(k8s_existing_version={'stdout': 'Kubernetes ' + installed})).evaluate_conditional(trust_as_template(expression)), expected)

    def test_cidr_preflight_rejects_overlaps(self):
        task = next(x for x in read_yaml('tasks/preflight.yaml') if x.get('name', '').startswith('Check pod and service'))
        code = task['ansible.builtin.command']['argv'][2]
        for pods, services, node, success in [
            ('10.88.0.0/16', '10.96.0.0/12', '10.10.10.10/24', True),
            ('10.96.0.0/16', '10.96.0.0/12', '10.10.10.10/24', False),
            ('10.88.0.0/16', '10.96.0.0/12', '10.88.0.10/24', False),
            ('10.88.0.0/28', '10.96.0.0/12', '10.10.10.10/24', False),
        ]:
            result = subprocess.run([os.sys.executable, '-c', code, pods, services, node], capture_output=True)
            self.assertEqual(result.returncode == 0, success)

    @unittest.skipUnless(os.environ.get('KUBEADM_BINARY'), 'Set KUBEADM_BINARY for upstream schema validation')
    def test_kubeadm_schema(self):
        with tempfile.TemporaryDirectory(dir=ROOT / '.tools') as tmp:
            for runtime in ('crio', 'containerd'):
                for ha in (False, True):
                    path = Path(tmp) / 'init.yaml'
                    path.write_text(render('roles/kubernetes/k8s-prepare/templates/kubeadm-config.yaml', variables(
                        k8s_runtime_environment=runtime, k8s_proxy_mode_enable=ha)), encoding='utf-8')
                    result = subprocess.run([os.environ['KUBEADM_BINARY'], 'config', 'validate', '--config', str(path)], capture_output=True, text=True)
                    self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            for control_plane in (False, True):
                path = Path(tmp) / 'join.yaml'
                path.write_text(render('roles/kubernetes/k8s-join/templates/kubeadm-join.yaml.j2', variables(k8s_join_control_plane=control_plane)), encoding='utf-8')
                result = subprocess.run([os.environ['KUBEADM_BINARY'], 'config', 'validate', '--config', str(path)], capture_output=True, text=True)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == '__main__':
    unittest.main()
