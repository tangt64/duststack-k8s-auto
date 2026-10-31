"""CNI/CSI configuration, destructive-operation guards and quick setup tests."""
import argparse
import copy
import importlib.util
import json
from pathlib import Path
import stat
import subprocess
import tempfile
from types import SimpleNamespace
import unittest

from ansible.template import trust_as_template
import yaml
from test_configuration import ROOT, read_yaml, variables, templar, render


def load_script(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / 'scripts' / (name + '.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


configure = load_script('configure')
devices = load_script('check_rook_devices')


class AddonTests(unittest.TestCase):
    def test_cilium_requires_a_supported_kubernetes_profile(self):
        expressions = read_yaml('tasks/preflight.yaml')[0]['ansible.builtin.assert']['that']
        for version, allowed in [('1.36.6', True), ('1.37.2', False)]:
            engine = templar(variables(k8s_network='cilium', k8s_version=version, crio_version=version))
            self.assertEqual(all(engine.evaluate_conditional(trust_as_template(x)) for x in expressions), allowed)
        value = yaml.safe_load(render('roles/cni/cni-cilium/templates/values.yaml.j2', variables()))
        self.assertFalse(value['kubeProxyReplacement'])
        self.assertEqual(value['ipam']['mode'], 'kubernetes')
        self.assertEqual(value['routingMode'], 'tunnel')
        self.assertFalse(value['hubble']['ui']['enabled'])

    def test_nfs_retains_data_and_only_marks_selected_default(self):
        for selected in ('', 'nfs-csi'):
            value = yaml.safe_load(render('roles/storage/csi-nfs/templates/storageclass.yaml.j2', variables(
                nfs_server='192.0.2.50', nfs_share='/exports/k8s', k8s_default_storage_class=selected)))
            self.assertEqual(value['provisioner'], 'nfs.csi.k8s.io')
            self.assertEqual(value['reclaimPolicy'], 'Retain')
            self.assertEqual(value['parameters']['onDelete'], 'retain')
            self.assertEqual(value['metadata']['annotations']['storageclass.kubernetes.io/is-default-class'], str(bool(selected)).lower())
            self.assertIn('${pv.metadata.name}', value['parameters']['subDir'])

    def ceph_variables(self):
        values = variables()
        values['groups']['k8s_storage_ceph'] = ['worker1', 'worker2', 'worker3']
        values['groups']['k8s_node'] = ['worker1', 'worker2', 'worker3']
        for i, name in enumerate(values['groups']['k8s_node']):
            values['hostvars'][name] = {'nodename': name, 'rook_devices': ['sdb']}
        return values

    def test_ceph_uses_only_explicit_devices_and_safe_replication(self):
        values = self.ceph_variables()
        cluster = yaml.safe_load(render('roles/storage/csi-rook/templates/ceph-cluster.yaml.j2', values))
        self.assertFalse(cluster['spec']['storage']['useAllNodes'])
        self.assertFalse(cluster['spec']['storage']['useAllDevices'])
        self.assertEqual(len(cluster['spec']['storage']['nodes']), 3)
        self.assertEqual(cluster['spec']['storage']['nodes'][1]['devices'], [{'name': 'sdb'}])
        self.assertEqual(cluster['spec']['cleanupPolicy']['confirmation'], '')
        pool = yaml.safe_load(render('roles/storage/csi-rook/templates/block-pool.yaml.j2', values))
        self.assertEqual(pool['spec']['replicated']['size'], 3)
        self.assertTrue(pool['spec']['replicated']['requireSafeReplicaSize'])
        storage = yaml.safe_load(render('roles/storage/csi-rook/templates/storageclass.yaml.j2', values))
        self.assertEqual(storage['reclaimPolicy'], 'Retain')
        self.assertEqual(storage['volumeBindingMode'], 'WaitForFirstConsumer')

    def test_rook_rbd_driver_identity_matches_storageclass_and_keeps_selinux_mount_support(self):
        values = self.ceph_variables()
        for namespace in ['rook-ceph', 'storage-lab']:
            values['rook_namespace'] = namespace
            resources = list(yaml.safe_load_all(render('roles/storage/csi-rook/templates/csi-driver.yaml.j2', values)))
            self.assertEqual([r['kind'] for r in resources], ['OperatorConfig', 'Driver'])
            driver = resources[1]
            storage = yaml.safe_load(render('roles/storage/csi-rook/templates/storageclass.yaml.j2', values))
            self.assertEqual(driver['metadata']['name'], storage['provisioner'])
            self.assertEqual(driver['metadata']['namespace'], namespace)
            self.assertEqual(driver['spec']['fsGroupPolicy'], 'File')
            self.assertEqual(driver['spec']['snapshotPolicy'], 'none')
            self.assertTrue(driver['spec']['nodePlugin']['enableSeLinuxHostMount'])

    def test_rbd_accounts_and_bindings_match_with_namespace_isolated_cluster_roles(self):
        for namespace in ['rook-ceph', 'storage-lab']:
            values = self.ceph_variables()
            values['rook_namespace'] = namespace
            resources = list(yaml.safe_load_all(render('roles/storage/csi-rook/templates/csi-rbac.yaml.j2', values)))
            self.assertEqual(len(resources), 10)
            accounts = {r['metadata']['name'] for r in resources if r['kind'] == 'ServiceAccount'}
            self.assertEqual(accounts, {'rbd-ctrlplugin-sa', 'rbd-nodeplugin-sa'})
            driver = list(yaml.safe_load_all(render('roles/storage/csi-rook/templates/csi-driver.yaml.j2', values)))[1]
            for plugin in ['nodePlugin', 'controllerPlugin']:
                self.assertIn(driver['spec'][plugin]['serviceAccountName'], accounts)
            roles = {(r['kind'], r['metadata']['name']) for r in resources if r['kind'] in ['Role', 'ClusterRole']}
            for resource in resources:
                if resource['kind'].startswith('Cluster'):
                    self.assertTrue(resource['metadata']['name'].startswith(namespace + '-rbd-'))
                else:
                    self.assertEqual(resource['metadata']['namespace'], namespace)
                if resource['kind'].endswith('Binding'):
                    self.assertIn((resource['roleRef']['kind'], resource['roleRef']['name']), roles)
                    self.assertEqual(resource['subjects'][0]['namespace'], namespace)
                    self.assertIn(resource['subjects'][0]['name'], accounts)
                for rule in resource.get('rules', []):
                    self.assertNotIn('*', rule['verbs'])
                    self.assertNotIn('*', rule['resources'])

    def test_rook_csi_cpu_guard_and_official_compatibility_image(self):
        task = next(x for x in read_yaml('tasks/rook-csi-cpu.yaml') if 'ansible.builtin.assert' in x)
        expression = task['ansible.builtin.assert']['that'][0]
        for legacy, flags, accepted in [(False, 'x86-64-v2 (supported, searched)', False),
                                        (True, 'x86-64-v2 (supported, searched)', True),
                                        (True, 'x86-64-v2', False),
                                        (False, 'x86-64-v3 (supported, searched)', True)]:
            engine = templar(variables(rook_csi_legacy_lab=legacy, rook_csi_cpu_probe={'stdout': flags}))
            self.assertEqual(engine.evaluate_conditional(trust_as_template(expression)), accepted)
            version = 'v3.16.3' if legacy else 'v3.18.1'
            values = variables(rook_csi_legacy_lab=legacy, rook_csi_version=version)
            rendered = yaml.safe_load(render('roles/storage/csi-rook/templates/values.yaml.j2', values))
            self.assertEqual(rendered['csi']['cephcsi']['tag'], version + '@sha256:' + values['rook_csi_image_digests'][version])

    def test_storage_guards_reject_missing_backends_and_conflicting_defaults(self):
        expressions = next(x['ansible.builtin.assert']['that'] for x in read_yaml('tasks/storage-settings.yaml') if 'ansible.builtin.assert' in x)
        def valid(**options):
            engine = templar(variables(**options))
            return all(engine.evaluate_conditional(trust_as_template(x)) for x in expressions)
        self.assertTrue(valid())
        self.assertFalse(valid(k8s_csi_providers=['nfs']))
        self.assertFalse(valid(k8s_csi_providers=['rook']))
        self.assertFalse(valid(k8s_default_storage_class='nfs-csi'))
        self.assertFalse(valid(k8s_csi_providers=['nfs', 'nfs']))
        self.assertTrue(valid(k8s_csi_providers=['nfs'], nfs_server='192.0.2.50', nfs_share='/export', k8s_default_storage_class='nfs-csi'))
        task = next(x for x in read_yaml('tasks/storage-preflight.yaml') if x.get('name') == 'Prevent replacing a different default StorageClass')
        conflict = {'metadata': {'name': 'another-sc', 'annotations': {'storageclass.kubernetes.io/is-default-class': 'true'}}}
        engine = templar(variables(item=conflict, k8s_default_storage_class='nfs-csi'))
        self.assertFalse(all(engine.evaluate_conditional(trust_as_template(x)) for x in task['ansible.builtin.assert']['that']))

    def test_csi_image_guard_requires_explicit_change_acknowledgement(self):
        block = next(x['block'] for x in read_yaml('tasks/storage-preflight.yaml') if 'block' in x)
        guard = next(x for x in block if x['name'] == 'Prevent unacknowledged CSI image replacement')
        current = {'spec': {'template': {'spec': {'containers': [{'name': 'csi-rbdplugin', 'image': 'old:image'}]}}}}
        for acknowledge, desired, accepted in [(False, 'new:image', False), (True, 'new:image', True), (False, 'old:image', True)]:
            engine = templar(variables(rook_csi_before={'stdout': json.dumps(current)}, rook_allow_csi_image_change=acknowledge,
                                       rook_desired_csi_image=desired))
            self.assertEqual(engine.evaluate_conditional(trust_as_template(guard['ansible.builtin.assert']['that'][0])), accepted)

    def test_rook_rejects_kubernetes_beyond_official_csi_tested_range(self):
        expressions = next(x['ansible.builtin.assert']['that'] for x in read_yaml('tasks/storage-settings.yaml') if 'ansible.builtin.assert' in x)
        for version, accepted in [('1.36.6', True), ('1.37.2', False)]:
            values = self.ceph_variables()
            values.update(k8s_version=version, k8s_csi_providers=['rook'], rook_confirm_devices=True)
            engine = templar(values)
            self.assertEqual(all(engine.evaluate_conditional(trust_as_template(x)) for x in expressions), accepted)

    def test_existing_cni_and_cidr_changes_are_rejected(self):
        tasks = read_yaml('tasks/cluster-config-guard.yaml')
        task = next(x for x in tasks if x.get('name') == 'Prevent installing a second CNI')
        settings = dict(task['vars'])
        settings.update(item={'metadata': {'name': 'calico-node'}}, k8s_network='cilium')
        engine = templar(variables(**settings))
        self.assertFalse(engine.evaluate_conditional(trust_as_template(task['ansible.builtin.assert']['that'])))
        expressions = tasks[1]['ansible.builtin.assert']['that']
        engine = templar(variables(existing_configuration={'networking': {'podSubnet': '172.16.0.0/16', 'serviceSubnet': '10.96.0.0/12'}, 'controlPlaneEndpoint': 'api.example.com:6443'}))
        self.assertFalse(all(engine.evaluate_conditional(trust_as_template(x)) for x in expressions))


class DiskGuardTests(unittest.TestCase):
    def validate(self, **changes):
        disk = {'type': 'disk', 'fstype': None, 'mountpoints': [None], 'size': 50 * 1024 ** 3}
        disk.update(changes.pop('disk', {}))
        signatures = changes.pop('signatures', [])
        calls = []
        def run(argv, **kwargs):
            calls.append(argv)
            result = {'blockdevices': [disk]} if argv[0] == 'lsblk' else {'signatures': signatures}
            return SimpleNamespace(stdout=json.dumps(result))
        result = devices.validate_device('sdb', run=run, inspect=lambda _: SimpleNamespace(st_mode=stat.S_IFBLK, st_rdev=42))
        self.assertIn('--no-act', calls[1])
        return result

    def test_empty_disk_is_accepted_without_writes(self):
        self.assertEqual(self.validate()['device'], 'sdb')

    def test_used_partitioned_small_or_signed_disks_are_rejected(self):
        for change in [{'disk': {'type': 'part'}}, {'disk': {'children': [{}]}},
                       {'disk': {'fstype': 'xfs'}}, {'disk': {'mountpoints': ['/']}},
                       {'disk': {'size': 1024}}, {'signatures': [{'type': 'ceph_bluestore'}]}]:
            with self.subTest(change=change), self.assertRaises(ValueError):
                self.validate(**change)

    def test_path_injection_and_regular_files_are_rejected(self):
        with self.assertRaises(ValueError):
            devices.validate_device('../sda')
        with self.assertRaises(ValueError):
            devices.validate_device('sdb', inspect=lambda _: SimpleNamespace(st_mode=stat.S_IFREG))


class SetupTests(unittest.TestCase):
    def arguments(self, **changes):
        values = dict(control='cp1=192.0.2.10@10.10.10.10/24', worker=['worker1=192.0.2.11@10.10.10.11/24'],
                      interface='eth1', ssh_user='rocky', cni='calico', storage='none', nfs_server=None,
                      nfs_share=None, rook_device=[], confirm_rook_devices=False)
        values.update(changes)
        return argparse.Namespace(**values)

    def test_generated_cilium_inventory_pins_compatible_versions(self):
        data = configure.build_inventory(self.arguments(cni='cilium'))
        self.assertEqual(data['all']['vars']['k8s_version'], '1.36.6')
        self.assertEqual(data['all']['vars']['crio_version'], '1.36.7')
        self.assertFalse(data['all']['vars']['k8s_proxy_mode_enable'])
        self.assertIn('worker1', data['all']['children']['kubernetes']['children']['k8s_node']['hosts'])

    def test_invalid_or_missing_backend_configuration_is_rejected(self):
        for options in [{'worker': []}, {'worker': ['cp1=192.0.2.11@10.10.10.11/24']},
                        {'worker': ['worker1=192.0.2.11@10.88.0.1/16']},
                        {'storage': 'nfs'}, {'storage': 'rook'}]:
            with self.subTest(options=options), self.assertRaises(ValueError):
                configure.build_inventory(self.arguments(**options))

    def test_calico_rook_generator_uses_supported_csi_kubernetes_and_explicit_cpu_option(self):
        data = configure.build_inventory(self.arguments(storage='rook',
            worker=[f'worker{i}=192.0.2.{10+i}@10.10.10.{10+i}/24' for i in range(1, 4)],
            rook_device=[f'worker{i}=sdb' for i in range(1, 4)], rook_csi_legacy_lab=True))
        self.assertEqual(data['all']['vars']['k8s_network'], 'calico')
        self.assertEqual(data['all']['vars']['k8s_version'], '1.36.6')
        self.assertTrue(data['all']['vars']['rook_csi_legacy_lab'])
        self.assertEqual(data['all']['vars']['rook_csi_version'], 'v3.16.3')

    def test_custom_ranges_avoid_a_broad_node_network(self):
        nodes = dict(control='cp1=192.0.2.10@10.250.253.84/8',
                     worker=['worker1=192.0.2.11@10.250.253.226/8'])
        with self.assertRaises(ValueError):
            configure.build_inventory(self.arguments(**nodes))
        data = configure.build_inventory(self.arguments(**nodes, pod_cidr='172.22.0.0/16', service_cidr='172.23.0.0/16'))
        self.assertEqual(data['all']['vars']['k8s_pod_cidr'], '172.22.0.0/16')
        self.assertEqual(data['all']['vars']['k8s_cluster_svc_ip'], '172.23.0.0/16')
        for ranges in [dict(pod_cidr='172.22.0.0/16', service_cidr='172.22.0.0/24'),
                       dict(pod_cidr='2001:db8::/48'), dict(service_cidr='172.23.0.1/16')]:
            with self.subTest(ranges=ranges), self.assertRaises(ValueError):
                configure.build_inventory(self.arguments(**ranges))

    def test_cli_creates_inventory_once_and_refuses_overwrite(self):
        with tempfile.TemporaryDirectory(dir=ROOT / '.tools') as folder:
            output = Path(folder) / 'hosts.yaml'
            args = ['python', str(ROOT / 'scripts/configure.py'), '--control', self.arguments().control,
                    '--worker', self.arguments().worker[0], '--output', str(output)]
            first = subprocess.run(args, capture_output=True)
            self.assertEqual(first.returncode, 0, first.stderr)
            second = subprocess.run(args, capture_output=True)
            self.assertNotEqual(second.returncode, 0)
            self.assertEqual(yaml.safe_load(output.read_text(encoding='utf-8'))['all']['vars']['k8s_network'], 'calico')


if __name__ == '__main__':
    unittest.main()
