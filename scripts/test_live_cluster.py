"""Run real cross-node Cilium and retained NFS/RBD I/O tests in a fresh namespace."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import subprocess
import time
import uuid


class Cluster:
    def __init__(self, kubeconfig, namespace):
        self.base = ['kubectl', '--kubeconfig', kubeconfig]
        self.namespace = namespace

    def run(self, *args, namespace=None, body=None, required=True, timeout=90, request_timeout=30):
        command = self.base + ['--request-timeout=' + str(request_timeout) + 's'] + (['-n', namespace] if namespace else []) + list(args)
        result = subprocess.run(command, input=json.dumps(body) if body else None,
                                capture_output=True, text=True, timeout=timeout)
        if required and result.returncode:
            raise RuntimeError('kubectl ' + ' '.join(args) + ': ' + result.stderr[-4000:])
        return result

    def read(self, *args, namespace=None):
        return json.loads(self.run('get', *args, '-o', 'json', namespace=namespace).stdout)

    def create(self, value):
        self.run('create', '-f', '-', body=value)

    def execute(self, pod, script):
        return self.run('exec', pod, '--', 'sh', '-ec', script,
                        namespace=self.namespace, timeout=60).stdout.strip()

    def ready(self, pod):
        self.run('wait', '--for=condition=Ready', 'pod/' + pod, '--timeout=600s',
                 namespace=self.namespace, timeout=640, request_timeout=620)


def eventually(check, description, seconds=120):
    deadline = time.monotonic() + seconds
    last = None
    while time.monotonic() < deadline:
        try:
            result = check()
            if result:
                return result
        except (RuntimeError, subprocess.TimeoutExpired) as error:
            last = error
        time.sleep(2)
    raise RuntimeError(description + (': ' + str(last) if last else ' timed out'))


def pod(namespace, name, node, image, command=None, claim=None, labels=None):
    container = {
        'name': 'test', 'image': image, 'imagePullPolicy': 'IfNotPresent',
        'command': command or ['sh', '-ec', 'sleep 86400'],
        'resources': {'requests': {'cpu': '10m', 'memory': '32Mi'},
                      'limits': {'cpu': '250m', 'memory': '128Mi'}},
        'securityContext': {'allowPrivilegeEscalation': False,
                            'capabilities': {'drop': ['ALL']}, 'readOnlyRootFilesystem': True},
        'volumeMounts': [{'name': 'tmp', 'mountPath': '/tmp'}],
    }
    spec = {
        # WFFC PVCs require the scheduler: spec.nodeName would bypass binding.
        'nodeSelector': {'kubernetes.io/hostname': node},
        'restartPolicy': 'Never', 'terminationGracePeriodSeconds': 5,
        'automountServiceAccountToken': False,
        'securityContext': {'runAsNonRoot': True, 'runAsUser': 1000, 'runAsGroup': 1000,
                            'fsGroup': 1000, 'fsGroupChangePolicy': 'OnRootMismatch',
                            'seccompProfile': {'type': 'RuntimeDefault'}},
        'containers': [container], 'volumes': [{'name': 'tmp', 'emptyDir': {}}],
    }
    if claim:
        spec['volumes'].append({'name': 'data', 'persistentVolumeClaim': {'claimName': claim}})
        container['volumeMounts'].append({'name': 'data', 'mountPath': '/data'})
    return {'apiVersion': 'v1', 'kind': 'Pod',
            'metadata': {'namespace': namespace, 'name': name, 'labels': labels or {}}, 'spec': spec}


def require_ready_workers(nodes):
    workers = [x for x in nodes if not any(k in x['metadata'].get('labels', {}) for k in
               ['node-role.kubernetes.io/control-plane', 'node-role.kubernetes.io/master'])
               and not x['spec'].get('unschedulable')
               and any(c['type'] == 'Ready' and c['status'] == 'True'
                       for c in x['status'].get('conditions', []))]
    if len(workers) < 3:
        raise RuntimeError('At least three Ready, schedulable workers are required')
    return sorted(x['metadata']['name'] for x in workers)[:3]


LEGACY_CLIENT_KEY_WARNINGS = {
    'AUTH_INSECURE_KEYS_ALLOWED', 'AUTH_INSECURE_KEYS_CREATABLE', 'AUTH_INSECURE_CLIENT_KEY_TYPE',
}


def ceph_health_result(ceph, allow_legacy_client_warnings=False):
    status = ceph.get('status', {})
    if status.get('phase') != 'Ready':
        return None
    health = status.get('ceph', {}).get('health')
    details = status.get('ceph', {}).get('details', {})
    if health == 'HEALTH_OK' and not details:
        return {'health': health, 'warnings': {}}
    if (allow_legacy_client_warnings and health == 'HEALTH_WARN' and details
            and set(details) <= LEGACY_CLIENT_KEY_WARNINGS
            and all(value.get('severity') == 'HEALTH_WARN' for value in details.values())
            and all(status.get('cephx', {}).get(daemon, {}).get('keyType') == 'aes256k'
                    for daemon in ['mgr', 'osd'])):
        return {'health': health, 'warnings': details}
    return None


def require_secure_service_cipher(mon_status):
    cipher = mon_status.get('monmap', {}).get('auth_service_cipher', {}).get('name')
    if cipher != 'aes256k':
        raise RuntimeError('Legacy client compatibility requires verified AES256K Ceph service tickets')
    return cipher


def network_tests(cluster, workers, image, record, cluster_domain='cluster.local'):
    ns = cluster.namespace
    token = uuid.uuid4().hex
    server = pod(ns, 'network-server', workers[0], image,
                 ['sh', '-ec', 'mkdir -p /tmp/www; printf %s ' + token +
                  ' > /tmp/www/marker; exec httpd -f -p 8080 -h /tmp/www'],
                 labels={'app': 'e2e-server'})
    server['spec']['containers'][0]['readinessProbe'] = {
        'httpGet': {'path': '/marker', 'port': 8080}, 'periodSeconds': 2}
    cluster.create(server)
    cluster.create(pod(ns, 'network-client', workers[1], image, labels={'app': 'e2e-client'}))
    cluster.ready('network-server')
    cluster.ready('network-client')
    address = cluster.read('pod', 'network-server', namespace=ns)['status']['podIP']
    cluster.create({'apiVersion': 'v1', 'kind': 'Service',
                    'metadata': {'namespace': ns, 'name': 'network-server'},
                    'spec': {'selector': {'app': 'e2e-server'},
                             'ports': [{'port': 8080, 'targetPort': 8080}]}})
    service = cluster.read('service', 'network-server', namespace=ns)['spec']['clusterIP']

    def fetch(host):
        return cluster.execute('network-client', 'wget -T 3 -t 1 -qO- http://' + host + ':8080/marker')

    eventually(lambda: fetch(address) == token, 'Cross-node Pod HTTP')
    record('cilium-cross-node-pod-http', {'server': workers[0], 'client': workers[1]})
    eventually(lambda: fetch(service) == token, 'ClusterIP HTTP')
    dns = 'network-server.' + ns + '.svc.' + cluster_domain
    eventually(lambda: 'Address' in cluster.execute('network-client', 'nslookup ' + dns), 'CoreDNS lookup')
    eventually(lambda: fetch(dns) == token, 'Service DNS HTTP')
    record('clusterip-and-coredns', {'service': service})
    policy = {'apiVersion': 'networking.k8s.io/v1', 'kind': 'NetworkPolicy',
              'metadata': {'namespace': ns, 'name': 'server-ingress'},
              'spec': {'podSelector': {'matchLabels': {'app': 'e2e-server'}},
                       'policyTypes': ['Ingress'], 'ingress': [{
                           'from': [{'podSelector': {'matchLabels': {'app': 'e2e-client', 'allowed': 'true'}}}],
                           'ports': [{'protocol': 'TCP', 'port': 8080}]}]}}
    cluster.create(policy)
    # A failed exec/API call is an error, never evidence that policy denied traffic.
    probe = 'if wget -T 3 -t 1 -qO- http://' + address + ':8080/marker >/tmp/probe; then echo CONNECTED; else echo DENIED; fi'
    for _ in range(3):
        eventually(lambda: cluster.execute('network-client', probe) == 'DENIED', 'NetworkPolicy denial')
    record('cilium-networkpolicy-deny', {})
    cluster.run('label', 'pod', 'network-client', 'allowed=true', '--overwrite', namespace=ns)
    eventually(lambda: fetch(address) == token, 'NetworkPolicy allow after label change')
    record('cilium-networkpolicy-allow', {})


def rook_csi_runtime(cluster, namespace, allow_legacy_lab=False):
    driver = cluster.read('daemonset', namespace + '.rbd.csi.ceph.com-nodeplugin', namespace=namespace)
    state = driver.get('status', {})
    if not state.get('desiredNumberScheduled') or state.get('numberReady') != state['desiredNumberScheduled']:
        raise RuntimeError('RBD CSI node plugin is not fully Ready')
    images = [c['image'] for c in driver['spec']['template']['spec']['containers'] if c['name'] == 'csi-rbdplugin']
    if len(images) != 1:
        raise RuntimeError('Cannot identify the RBD CSI plugin image')
    match = re.fullmatch(r'quay\.io/cephcsi/cephcsi:(v3\.(?:16\.3|18\.1))(?:@sha256:[0-9a-f]{64})?', images[0])
    if not match:
        raise RuntimeError('RBD CSI image is outside the reviewed release profiles')
    server = json.loads(cluster.run('version', '--output=json').stdout)['serverVersion']['gitVersion']
    version = re.match(r'^v1\.([0-9]+)\.', server)
    if not version or not 32 <= int(version[1]) <= 36:
        raise RuntimeError('Kubernetes is outside the reviewed CSI lab profiles')
    warnings = []
    if match[1] == 'v3.16.3':
        if not allow_legacy_lab:
            raise RuntimeError('Legacy CSI requires explicit --allow-legacy-csi-lab; this is not production support validation')
        warnings.append('Legacy Ceph CSI v3.16.3 lab; upstream tested Kubernetes 1.32-1.34, actual ' + server)
    elif int(version[1]) < 34:
        raise RuntimeError('Ceph CSI v3.18.1 upstream tested range starts at Kubernetes 1.34')
    return {'image': images[0], 'kubernetes': server, 'warnings': warnings}


def storage_tests(cluster, workers, image, storage_class, provider, record):
    ns, claim = cluster.namespace, provider + '-io'
    mode = 'ReadWriteMany' if provider == 'nfs' else 'ReadWriteOnce'
    sc = cluster.read('storageclass', storage_class)
    if sc['reclaimPolicy'] != 'Retain':
        raise RuntimeError(storage_class + ' must retain test data')
    cluster.create({'apiVersion': 'v1', 'kind': 'PersistentVolumeClaim',
                    'metadata': {'namespace': ns, 'name': claim},
                    'spec': {'accessModes': [mode], 'storageClassName': storage_class,
                             'resources': {'requests': {'storage': '1Gi'}}}})
    writer = provider + '-writer'
    cluster.create(pod(ns, writer, workers[0], image, claim=claim))
    cluster.ready(writer)
    pvc = cluster.read('pvc', claim, namespace=ns)
    if pvc['status']['phase'] != 'Bound':
        raise RuntimeError(claim + ' is not Bound')
    cluster.execute(writer, 'dd if=/dev/urandom of=/data/payload.bin bs=1048576 count=4 2>/dev/null; '
                    'cd /data; sha256sum payload.bin > payload.sha256; sync; sha256sum -c payload.sha256')
    record(provider + '-pvc-write', {'pvc': claim, 'pv': pvc['spec']['volumeName'], 'node': workers[0]})
    if provider == 'nfs':
        reader = 'nfs-reader'
        cluster.create(pod(ns, reader, workers[1], image, claim=claim))
        cluster.ready(reader)
        cluster.execute(reader, 'cd /data; sha256sum -c payload.sha256; printf shared-write > reader-ack; sync')
        if cluster.execute(writer, 'cat /data/reader-ack') != 'shared-write':
            raise RuntimeError('NFS cross-node shared write was not visible')
        record('nfs-rwx-cross-node-read-write', {'nodes': workers[:2]})
    cluster.run('delete', 'pod', writer, '--wait=true', '--timeout=120s', namespace=ns, timeout=150, request_timeout=140)
    reattach = provider + '-reattach'
    target = workers[2] if provider == 'nfs' else workers[1]
    cluster.create(pod(ns, reattach, target, image, claim=claim))
    cluster.ready(reattach)
    cluster.execute(reattach, 'cd /data; sha256sum -c payload.sha256; printf reattached > reattach-ack; sync; '
                    'test "$(cat reattach-ack)" = reattached')
    if cluster.read('pod', reattach, namespace=ns)['spec']['nodeName'] != target:
        raise RuntimeError('Reattachment did not use the requested different worker')
    record(provider + '-pvc-cross-node-reattach-io', {'node': target})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--kubeconfig', default='/etc/kubernetes/admin.conf')
    parser.add_argument('--namespace', default='duststack-e2e-' + uuid.uuid4().hex[:10])
    parser.add_argument('--image', default='docker.io/library/busybox:1.37.0')
    parser.add_argument('--nfs-class', default='nfs-csi')
    parser.add_argument('--rook-class', default='rook-ceph-block')
    parser.add_argument('--rook-namespace', default='rook-ceph')
    parser.add_argument('--cluster-domain', default='cluster.local')
    parser.add_argument('--providers', nargs='+', choices=['nfs', 'rook'], default=['nfs', 'rook'])
    parser.add_argument('--allow-ceph-legacy-client-key-warnings', action='store_true',
                        help='Acknowledge only documented legacy-client warnings; require AES256K service tickets and report warnings')
    parser.add_argument('--allow-legacy-csi-lab', action='store_true',
                        help='Acknowledge Ceph CSI 3.16.3 legacy lab and unsupported Kubernetes combinations; always report warnings')
    parser.add_argument('--confirm-test-workloads', action='store_true')
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    if not args.confirm_test_workloads:
        parser.error('Pass --confirm-test-workloads to create dedicated test Pods and PVCs')
    if not re.fullmatch(r'duststack-e2e-[a-z0-9][a-z0-9-]{0,42}', args.namespace):
        parser.error('Use a fresh duststack-e2e-* namespace')
    cluster = Cluster(args.kubeconfig, args.namespace)
    report = {'status': 'running', 'namespace': args.namespace,
              'started_at': datetime.now(timezone.utc).isoformat(), 'checks': [],
              'requested_providers': list(dict.fromkeys(args.providers)),
              'completed_providers': [],
              'warnings': {},
              'compatibility_warnings': [],
              'ceph_legacy_client_key_warnings_allowed': args.allow_ceph_legacy_client_key_warnings,
              'scope': 'full' if set(args.providers) == {'nfs', 'rook'} else 'partial'}
    source = subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=Path(__file__).resolve().parents[1],
                            capture_output=True, text=True)
    report['source_commit'] = source.stdout.strip() if source.returncode == 0 else 'unknown'
    output = args.output or Path('.tools') / (args.namespace + '.json')
    output.parent.mkdir(parents=True, exist_ok=True)

    def save():
        output.write_text(json.dumps(report, indent=2), encoding='utf-8')

    def record(name, details):
        report['checks'].append({'name': name, 'status': 'passed', **details})
        save()
        print('PASS ' + name + ' ' + json.dumps(details), flush=True)

    try:
        workers = require_ready_workers(cluster.read('nodes')['items'])
        report['workers'] = workers
        ds = cluster.read('daemonset', 'cilium', namespace='kube-system')['status']
        if not ds.get('desiredNumberScheduled') or ds.get('numberReady') != ds['desiredNumberScheduled']:
            raise RuntimeError('Cilium DaemonSet is not fully Ready')
        record('cilium-agents-ready', {'agents': ds['numberReady']})
        # create (not apply) refuses to reuse any existing namespace, even on races.
        cluster.create({'apiVersion': 'v1', 'kind': 'Namespace',
                        'metadata': {'name': args.namespace, 'labels': {
                            'app.kubernetes.io/managed-by': 'duststack-live-validation',
                            'pod-security.kubernetes.io/enforce': 'restricted'}}})
        report['namespace_created'] = True
        network_tests(cluster, workers, args.image, record, args.cluster_domain)
        if 'nfs' in args.providers:
            storage_tests(cluster, workers, args.image, args.nfs_class, 'nfs', record)
            report['completed_providers'].append('nfs')
        if 'rook' in args.providers:
            report['csi_runtime'] = rook_csi_runtime(cluster, args.rook_namespace, args.allow_legacy_csi_lab)
            report['compatibility_warnings'] = report['csi_runtime']['warnings']
            record('rook-csi-runtime', report['csi_runtime'])
            def ceph_healthy():
                ceph = cluster.read('cephcluster', args.rook_namespace, namespace=args.rook_namespace)
                return ceph_health_result(ceph, args.allow_ceph_legacy_client_key_warnings)
            health = eventually(ceph_healthy, 'CephCluster Ready and acceptable explicitly selected health policy', seconds=300)
            if health['warnings']:
                mon = cluster.run('exec', 'deployment/rook-ceph-mon-a', '--', 'ceph', '--admin-daemon',
                                  '/run/ceph/ceph-mon.a.asok', 'mon_status', namespace=args.rook_namespace)
                report['ceph_auth_service_cipher'] = require_secure_service_cipher(json.loads(mon.stdout))
                report['warnings'] = health['warnings']
            pool = cluster.read('cephblockpool', 'replicated-pool', namespace=args.rook_namespace)
            if pool['spec']['replicated']['size'] != 3:
                raise RuntimeError('Ceph block pool must have three replicas')
            record('ceph-health-and-replication', {'ceph_health': health['health'], 'replicas': 3,
                                                'compatibility_warnings': sorted(health['warnings'])})
            storage_tests(cluster, workers, args.image, args.rook_class, 'rook', record)
            report['completed_providers'].append('rook')
        has_warnings = bool(report['warnings'] or report['compatibility_warnings'])
        if report['scope'] == 'full':
            report['status'] = 'passed_with_warnings' if has_warnings else 'passed'
            print('LIVE_CLUSTER_VALIDATION=' + ('PASS_WITH_WARNINGS' if has_warnings else 'PASS'), flush=True)
        else:
            report['status'] = 'partial_passed_with_warnings' if has_warnings else 'partial_passed'
            print('LIVE_CLUSTER_VALIDATION=' + ('PARTIAL_PASS_WITH_WARNINGS' if has_warnings else 'PARTIAL_PASS'), flush=True)
    except Exception as error:
        report['status'] = 'failed'
        report['error'] = str(error)
        if report.get('namespace_created'):
            for resource in ['pods,pvc', 'events']:
                try:
                    diagnostic = cluster.run('get', resource, '-o', 'wide', namespace=args.namespace, required=False)
                    (output.parent / (args.namespace + '-' + resource.replace(',', '-') + '.log')).write_text(
                        (diagnostic.stdout + diagnostic.stderr)[-100000:], encoding='utf-8')
                except Exception:
                    pass
        raise
    finally:
        report['finished_at'] = datetime.now(timezone.utc).isoformat()
        save()
        print('Report: ' + str(output), flush=True)
        if report.get('namespace_created'):
            print('Test namespace and retained PVCs are preserved: ' + args.namespace, flush=True)


if __name__ == '__main__':
    main()
