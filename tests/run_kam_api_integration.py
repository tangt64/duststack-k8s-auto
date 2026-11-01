"""Real, loopback-only envtest API/RBAC integration. No existing kubeconfig used.

Requires official controller-tools envtest-v1.37.0 bundle cached under .tools/envtest.
Does not install kubelet/controller-manager or create paid VMs.
"""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import socket
import ssl
import subprocess
import sys
import tempfile
import time
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
EXPECTED = '1d1c453633b72c161a5d5a886cde7ac850be1a2ac796a9e1d4ffacacc64868295bdd2d57aa66cd0c158f5ce510f5dfe3fbc61ac21bd3dcfb875bd70658aa663a'


def load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / 'addons/kam' / (name + '.py'))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def port():
    with socket.socket() as s:
        s.bind(('127.0.0.1', 0))
        return s.getsockname()[1]


def main():
    cache = ROOT / '.tools/envtest'
    assert hashlib.sha512((cache / 'envtest.tar.gz').read_bytes()).hexdigest() == EXPECTED, 'Official bundle hash mismatch'
    binaries = cache / 'controller-tools/envtest'
    kam, renderer = load('controller'), load('render')
    processes, logs = [], []
    with tempfile.TemporaryDirectory(prefix='kam-api-') as directory:
        root = Path(directory)
        def command(*args, **kwargs):
            return subprocess.run(args, cwd=root, check=True, capture_output=True, text=True, **kwargs).stdout
        try:
            command('openssl', 'req', '-x509', '-newkey', 'rsa:2048', '-nodes', '-keyout', 'ca.key', '-out', 'ca.crt', '-days', '1', '-subj', '/CN=kam-test-ca')
            for name, subject in [('server', '/CN=localhost'), ('admin', '/CN=kam-test-admin/O=system:masters')]:
                command('openssl', 'req', '-newkey', 'rsa:2048', '-nodes', '-keyout', name + '.key', '-out', name + '.csr', '-subj', subject)
                (root / 'extensions').write_text('subjectAltName=IP:127.0.0.1,DNS:localhost\nextendedKeyUsage=serverAuth,clientAuth\n')
                command('openssl', 'x509', '-req', '-in', name + '.csr', '-CA', 'ca.crt', '-CAkey', 'ca.key', '-CAcreateserial', '-out', name + '.crt', '-days', '1', '-extfile', 'extensions')
            command('openssl', 'genrsa', '-out', 'sa.key', '2048')
            etcd_port, peer_port, api_port = port(), port(), port()
            def start(name, args):
                log = open(root / (name + '.log'), 'w+')
                logs.append(log)
                processes.append(subprocess.Popen([str(binaries / name), *args], cwd=root, stdout=log, stderr=log))
            start('etcd', ['--data-dir=' + str(root / 'data'), '--listen-client-urls=http://127.0.0.1:' + str(etcd_port),
                           '--advertise-client-urls=http://127.0.0.1:' + str(etcd_port),
                           '--listen-peer-urls=http://127.0.0.1:' + str(peer_port),
                           '--initial-advertise-peer-urls=http://127.0.0.1:' + str(peer_port),
                           '--initial-cluster=default=http://127.0.0.1:' + str(peer_port)])
            start('kube-apiserver', ['--etcd-servers=http://127.0.0.1:' + str(etcd_port), '--bind-address=127.0.0.1',
                                    '--advertise-address=127.0.0.1', '--endpoint-reconciler-type=none', '--secure-port=' + str(api_port),
                                    '--tls-cert-file=' + str(root / 'server.crt'), '--tls-private-key-file=' + str(root / 'server.key'),
                                    '--client-ca-file=' + str(root / 'ca.crt'), '--authorization-mode=RBAC',
                                    '--service-account-issuer=https://kubernetes.default.svc',
                                    '--service-account-signing-key-file=' + str(root / 'sa.key'),
                                    '--service-account-key-file=' + str(root / 'sa.key'), '--service-cluster-ip-range=10.254.0.0/24'])
            base = 'https://127.0.0.1:' + str(api_port)
            tls = ssl.create_default_context(cafile=str(root / 'ca.crt'))
            tls.load_cert_chain(str(root / 'admin.crt'), str(root / 'admin.key'))
            for _ in range(90):
                try:
                    with urllib.request.urlopen(base + '/readyz', context=tls, timeout=1):
                        break
                except Exception:
                    if any(p.poll() is not None for p in processes):
                        raise RuntimeError('envtest process exited')
                    time.sleep(1)
            else:
                raise RuntimeError('API readiness timeout')
            def kubectl(*args, body=None):
                return command(str(binaries / 'kubectl'), '--server=' + base, '--certificate-authority=' + str(root / 'ca.crt'),
                               '--client-certificate=' + str(root / 'admin.crt'), '--client-key=' + str(root / 'admin.key'),
                               *args, input=json.dumps(body) if body else None)
            kubectl('create', 'namespace', 'dev')
            kubectl('create', 'namespace', 'kam-system')
            docs = renderer.manifests('dev', 'python@sha256:' + 'a' * 64, ['view'])
            for doc in docs:
                kubectl('apply', '--server-side', '-f', '-', body=doc)
                kubectl('diff', '--server-side', '-f', '-', body=doc)
            kubectl('wait', '--for=condition=Established', 'crd/kamaccessgrants.access.kam.dustbox.kr', '--timeout=30s')
            config = {'apiVersion': 'v1', 'kind': 'Config', 'current-context': 'test',
                      'clusters': [{'name': 'test', 'cluster': {'server': base, 'certificate-authority': str(root / 'ca.crt')}}],
                      'users': [{'name': 'admin', 'user': {'client-certificate': str(root / 'admin.crt'), 'client-key': str(root / 'admin.key')}}],
                      'contexts': [{'name': 'test', 'context': {'cluster': 'test', 'user': 'admin'}}]}
            (root / 'kubeconfig').write_text(json.dumps(config))
            (root / 'kubeconfig').chmod(0o600)
            env = dict(os.environ, PATH=str(binaries) + ':' + os.environ['PATH'], KUBECONFIG=str(root / 'kubeconfig'))
            for action in ('grant', 'get', 'revoke'):
                args = [sys.executable, str(ROOT / 'addons/kam/kubectl-kam'), action, '-n', 'dev']
                if action != 'get':
                    args.append('plugin@example.com')
                subprocess.run(args, env=env, check=True, capture_output=True, text=True)
            # No aggregation controller in envtest: seed only this isolated role's rules.
            kubectl('patch', 'clusterrole', 'view', '--type=merge', '-p', json.dumps({
                'rules': [{'apiGroups': [''], 'resources': ['pods'], 'verbs': ['get', 'list']}]}))
            sa_name = next(d['metadata']['name'] for d in docs if d['kind'] == 'ServiceAccount')
            os.environ['KAM_LEASE_NAME'] = sa_name
            token = kubectl('create', 'token', sa_name, '-n', 'kam-system', '--duration=10m').strip()
            (root / 'token').write_text(token)
            (root / 'token').chmod(0o600)
            api = kam.API.__new__(kam.API)
            api.base, api.credentials = base, root
            api.tls = ssl.create_default_context(cafile=str(root / 'ca.crt'))
            assert kam.acquire(api, 'kam-system', 'leader-one')
            assert not kam.acquire(api, 'kam-system', 'leader-two')
            g = {'apiVersion': kam.VERSION, 'kind': 'KamAccessGrant', 'metadata': {'name': 'alice', 'namespace': 'dev'},
                 'spec': {'subject': {'kind': 'User', 'name': 'alice@example.com'}, 'profile': 'view'}}
            kubectl('apply', '-f', '-', body=g)
            rejected = json.loads(json.dumps(g))
            rejected['metadata']['name'] = 'reserved'
            rejected['spec']['subject']['name'] = 'system:masters'
            try:
                kubectl('apply', '-f', '-', body=rejected)
                raise AssertionError('CRD accepted a reserved subject')
            except subprocess.CalledProcessError as error:
                assert 'Reserved subject' in error.stderr
            g = json.loads(kubectl('get', 'kag', 'alice', '-n', 'dev', '-o', 'json'))
            assert kam.reconcile(api, g, 'dev', {'view'}) == 'Applied'
            assert kam.reconcile(api, g, 'dev', {'view'}) == 'Applied'
            g['status'] = {'observedGeneration': g['metadata']['generation'], 'conditions': [
                {'type': 'Ready', 'status': 'True', 'reason': 'Applied', 'lastTransitionTime': kam.stamp(kam.now())}]}
            api.call('PUT', '/apis/' + kam.VERSION + '/namespaces/dev/kamaccessgrants/alice/status', g)
            assert kubectl('auth', 'can-i', 'list', 'pods', '-n', 'dev', '--as=alice@example.com').strip() == 'yes'
            # SA itself cannot create arbitrary elevated role bindings.
            forbidden = kam.desired_binding(g, 'dev', {'view'})
            forbidden['metadata']['name'] = 'forbidden-admin'
            forbidden['roleRef']['name'] = 'cluster-admin'
            try:
                api.call('POST', '/apis/rbac.authorization.k8s.io/v1/namespaces/dev/rolebindings', forbidden)
                raise AssertionError('Privilege escalation was allowed')
            except RuntimeError as error:
                assert '403' in str(error), str(error)
            g['spec']['expiresAt'] = '2020-01-01T00:00:00Z'
            assert kam.reconcile(api, g, 'dev', {'view'}) == 'Expired'
            result = subprocess.run([str(binaries / 'kubectl'), '--server=' + base, '--certificate-authority=' + str(root / 'ca.crt'),
                                    '--client-certificate=' + str(root / 'admin.crt'), '--client-key=' + str(root / 'admin.key'),
                                    'auth', 'can-i', 'list', 'pods', '-n', 'dev', '--as=alice@example.com'], capture_output=True, text=True)
            assert result.stdout.strip() == 'no'
            print('KAM_REAL_API_PASS: CRD admission/CEL, kubectl plugin via KUBECONFIG, namespace Role bind, status update, repeated reconciliation, Lease exclusion, RBAC allow, escalation denial, expiry revocation')
            print('Not tested: kubelet scheduling, native garbage collection, multi-VM HA failover')
        except Exception:
            for log in logs:
                log.flush()
                log.seek(0)
                print(log.read()[-8000:])
            raise
        finally:
            for p in reversed(processes):
                p.terminate()
                try:
                    p.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    p.kill()
                    p.wait()
            for log in logs:
                log.close()


if __name__ == '__main__':
    main()
