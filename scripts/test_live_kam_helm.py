"""Run Helm/TLS/rollback checks in a reviewed disposable, three-control-plane lab.

Requires preloaded images, native admin credentials and an inventory containing
only k8s_master cp01/cp02/cp03. Never run against a production cluster. The test
restores the captured native API manifests and uninstalls its own release.
"""
import argparse
import base64
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import secrets
import subprocess
import tempfile
import time
import yaml

ROOT = Path(__file__).resolve().parents[1]
FILES = ['/etc/kubernetes/manifests/kube-apiserver.yaml'] + [
    '/etc/kubernetes/kiki-kam/' + n for n in ['ca.crt', 'client.crt', 'client.key', 'webhook.yaml']]


def main():
    p = argparse.ArgumentParser(description=__doc__)
    for name in ['kubeconfig', 'kam-source', 'kam-binary', 'helm', 'inventory', 'tls-dir', 'auth-url', 'auth-image', 'output']:
        p.add_argument('--' + name, required=True)
    p.add_argument('--confirm-disposable-lab', action='store_true', required=True)
    a = p.parse_args()
    source = Path(a.kam_source).resolve()
    inventory = yaml.safe_load(Path(a.inventory).read_text())
    hosts = inventory['all']['children']['k8s_master']['hosts']
    if set(hosts) != {'cp01', 'cp02', 'cp03'} or hosts['cp01'].get('ansible_connection') != 'local':
        p.error('Require reviewed cp01(local), cp02 and cp03 inventory')
    if any(h.get('ansible_host', '').startswith(('127.', '0.')) for h in hosts.values()):
        p.error('Use actual private VM addresses')
    ns, release = 'kam-helm-e2e', 'kiki-kam-helm-e2e'
    ctrl = 'kam-' + hashlib.sha256(ns.encode()).hexdigest()[:16]
    report = {'started_at': datetime.now(timezone.utc).isoformat(), 'status': 'failed', 'checks': {},
              'environment': 'Terminal Lab: real kubelet, scheduler, CRI-O and three control planes',
              'impersonation_used': False, 'namespace': ns}
    output = Path(a.output).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    ssh = ['ssh', '-i', inventory['all']['vars']['ansible_ssh_private_key_file'], '-oBatchMode=yes',
           '-oConnectTimeout=8', '-oStrictHostKeyChecking=yes',
           '-oUserKnownHostsFile=/root/.ssh/duststack-ha-known-hosts']
    env = dict(os.environ, KUBECONFIG=a.kubeconfig, ANSIBLE_CONFIG=str(ROOT/'ansible.cfg'))
    env['PATH'] = str(Path(os.sys.executable).parent) + os.pathsep + env['PATH']

    def run(argv, *, body=None, required=True, timeout=360):
        r = subprocess.run([str(x) for x in argv], input=body, text=True, capture_output=True, env=env, timeout=timeout)
        if r.returncode:
            private_log = output.parent/'kam-private-command-error.log'
            private_log.write_text(r.stdout + r.stderr)
            private_log.chmod(0o600)
        if required and r.returncode:
            raise RuntimeError(f'{Path(str(argv[0])).name} exited {r.returncode}; private log retained')
        return r

    def k(*words, body=None, required=True):
        request_timeout = '200s' if 'rollout' in words or 'delete' in words else '10s'
        return run(['kubectl', '--kubeconfig', a.kubeconfig, '--request-timeout=' + request_timeout, *words],
                   body=json.dumps(body) if body is not None else None, required=required)

    def get(*words):
        return json.loads(k('get', *words, '-ojson').stdout)

    def save():
        output.write_text(json.dumps(report, indent=2) + '\n')

    def passed(name, value=True):
        assert value, 'False check cannot be recorded as passed: ' + name
        report['checks'][name] = value
        save()
        print('PASS', name, flush=True)

    def eventually(check, seconds=180):
        until = time.monotonic() + seconds
        while time.monotonic() < until:
            if check():
                return
            time.sleep(2)
        raise RuntimeError('Readiness assertion timed out')

    def peer(host, program, data=None):
        cmd = ['/usr/bin/python3', '-c', program]
        if host == 'cp01':
            return run(cmd, body=data)
        import shlex
        return run(ssh + ['root@' + hosts[host]['ansible_host'], shlex.join(cmd)], body=data)

    def snapshot(host):
        program = ('from pathlib import Path; import json,base64; paths=' + repr(FILES) + '; '
                   'print(json.dumps({n:base64.b64encode(Path(n).read_bytes()).decode() if Path(n).is_file() else None for n in paths}))')
        return json.loads(peer(host, program).stdout)

    def fingerprints(snapshot_value):
        return {n: hashlib.sha256(base64.b64decode(v)).hexdigest() if v is not None else None
                for n, v in snapshot_value.items()}

    def restore(host, snapshot_value):
        program = """from pathlib import Path
import json,base64,sys
data=json.load(sys.stdin)
for name,value in data.items():
 p=Path(name)
 assert not p.is_symlink()
 if value is None:
  p.unlink(missing_ok=True)
 else:
  tmp=p.with_name(p.name+'.kam-lab-restore')
  tmp.write_bytes(base64.b64decode(value)); tmp.chmod(0o600); tmp.replace(p)
"""
        peer(host, program, json.dumps(snapshot_value))

    def api_ready():
        for host in hosts.values():
            r = k('--server=https://' + host['ansible_host'] + ':6443', 'get', '--raw=/readyz', required=False)
            if r.returncode or r.stdout.strip() != 'ok':
                return False
        return True

    def mirrors():
        items = get('pods', '-n', 'kube-system', '-l', 'component=kube-apiserver')['items']
        return {x['spec']['nodeName']: {'uid': x['metadata']['uid'],
                'bundle': x['metadata'].get('annotations', {}).get('access.kam.dustbox.kr/webhook-bundle-sha256'),
                'ready': any(c['type'] == 'Ready' and c['status'] == 'True' for c in x.get('status', {}).get('conditions', []))}
                for x in items}

    def helm(*words, required=True):
        return run([a.helm, '--kubeconfig', a.kubeconfig, '-n', 'kam-system', *words], required=required, timeout=600)

    def operation(fault=False):
        playbook = ROOT/'playbooks/k8s-kam-webhook.yaml'
        temp_playbook = ROOT/'playbooks/.kam-disposable-fault.yaml'
        if fault:
            plays = yaml.safe_load(playbook.read_text())
            tasks = plays[1]['tasks']
            block = next(t['block'] for t in tasks if 'block' in t)
            index = next(i for i, t in enumerate(block) if t['name'] == 'Atomically update the API server static Pod') + 1
            injected = [
                {'name': 'LAB ONLY capture generated API Pod for invalid flag test',
                 'ansible.builtin.set_fact': {'kam_lab_pod': '{{ (kam_api_update.stdout | from_json).manifest | from_yaml }}'}},
                {'name': 'LAB ONLY generate an invalid API command', 'ansible.builtin.set_fact': {
                    'kam_lab_container': "{{ kam_lab_pod.spec.containers[0] | combine({'command': kam_lab_pod.spec.containers[0].command + ['--kam-disposable-invalid-flag=true']}) }}"}},
                {'name': 'LAB ONLY inject real kube-apiserver startup failure on CP02', 'ansible.builtin.copy': {
                    'dest': FILES[0], 'mode': '0600',
                    'content': "{{ kam_lab_pod | combine({'spec': kam_lab_pod.spec | combine({'containers': [kam_lab_container] + kam_lab_pod.spec.containers[1:]})}) | to_nice_json }}"}}]
            for task in injected:
                task['when'] = "inventory_hostname == 'cp02'"
                task['no_log'] = True
            block[index:index] = injected
            for task in block:
                if 'until' in task:
                    task['retries'] = 12
                    task['delay'] = 5
            temp_playbook.write_text(yaml.safe_dump(plays, sort_keys=False))
            playbook = temp_playbook
        values = {'kam_confirm_admin': True, 'kam_auth_url': a.auth_url, 'kam_auth_tls_dir': str(Path(a.tls_dir).resolve())}
        result = run(['ansible-playbook', playbook, '-i', a.inventory, '-e', json.dumps(values)], required=False, timeout=1200)
        log = output.parent / ('kam-webhook-fault.log' if fault else 'kam-webhook-apply.log')
        log.write_text(result.stdout + result.stderr)
        log.chmod(0o600)
        temp_playbook.unlink(missing_ok=True)
        return result

    # Refuse mixed ownership or a previously installed identity service.
    for words in [('namespace', ns), ('deployment', 'kiki-kam-auth', '-n', 'kam-system'),
                  ('secret', 'kiki-kam-identities', '-n', 'kam-system'),
                  ('secret', 'kiki-kam-tls', '-n', 'kam-system'),
                  ('configmap', 'kiki-kam-webhook-ca', '-n', 'kam-system')]:
        assert not k('get', *words, '--ignore-not-found', '-oname').stdout.strip(), 'Existing KAM resources: refuse takeover'
    assert not json.loads(helm('list', '-a', '-ojson').stdout), 'Require no existing Helm releases in kam-system'
    assert api_ready()
    before = {host: snapshot(host) for host in hosts}
    assert all(all(value is None for name, value in snap.items() if name != FILES[0]) for snap in before.values())
    for snap in before.values():
        assert b'authentication-token-webhook' not in base64.b64decode(snap[FILES[0]])
    recovery = output.parent/'kam-native-recovery.json'
    recovery.write_text(json.dumps(before)); recovery.chmod(0o600)
    tls = Path(a.tls_dir).resolve()
    created_namespace, created_external, release_started = False, False, False
    with tempfile.TemporaryDirectory(prefix='kam-live-private-') as private:
        private = Path(private)
        env.update(HOME=str(private), XDG_CONFIG_HOME=str(private/'config'), XDG_CACHE_HOME=str(private/'cache'))
        admin_login, user_login = private/'admin.conf', private/'user.conf'

        def cli(cfg, *words, password=None, required=True):
            return run([a.kam_binary, '--kubeconfig', cfg, *words], body=password, required=required)

        def login(cfg, name, password):
            return cli(cfg, 'login', a.auth_url, '--username', name,
                       '--server', 'https://' + hosts['cp01']['ansible_host'] + ':6443',
                       '--ca-file', tls/'kam-ca.crt', '--api-ca-file', '/etc/kubernetes/pki/ca.crt',
                       '--password-stdin', password=password)

        def real_access():
            return run(['kubectl', '--kubeconfig', user_login, '--request-timeout=10s', '-n', ns, 'get', 'pods'], required=False).returncode == 0

        def access_revoked():
            result = run(['kubectl', '--kubeconfig', user_login, '--request-timeout=10s', '-n', ns, 'get', 'pods'], required=False)
            return result.returncode != 0 and 'forbidden' in result.stderr.lower() and api_ready()

        try:
            run([os.sys.executable, source/'deploy/make_tls.py', '--out', tls, '--hostname', a.auth_url.split('://')[1].split(':')[0]])
            k('create', 'namespace', ns); created_namespace = True
            k('create', '-f', source/'deploy/bootstrap/identity-state.yaml'); created_external = True
            for kind, name, flags in [('secret', 'kiki-kam-tls', ['tls', '--cert=' + str(tls/'kam-server.crt'), '--key=' + str(tls/'kam-server.key')]),
                                      ('configmap', 'kiki-kam-webhook-ca', ['--from-file=ca.crt=' + str(tls/'kam-ca.crt')])]:
                argv = ['create', kind] + (['tls', name] + flags[1:] if kind == 'secret' else [name] + flags)
                k('-n', 'kam-system', *argv)
            password = secrets.token_urlsafe(24)
            cli(a.kubeconfig, 'bootstrap', '--username', 'helm-lab-admin', '--password-stdin', password=password)
            audience = json.loads(run([os.sys.executable, ROOT/'scripts/configure_kam_webhook.py', '--stdin-render'],
                                     body=base64.b64decode(before['cp01'][FILES[0]]).decode()).stdout)['audience']
            values = {'local': {'allowUnpinnedImages': True}, 'auth': {'image': a.auth_image,
                      'audience': audience, 'imagePullPolicy': 'Never', 'service': {'type': 'NodePort', 'nodePort': int(a.auth_url.rsplit(':', 1)[1])}},
                      'controller': {'targets': [{'namespace': ns, 'profiles': ['view']}]}}
            values_file = output.parent/'kam-live-values.yaml'
            values_file.write_text(yaml.safe_dump(values))
            release_started = True
            helm('install', release, source/'charts/kiki-kam', '-f', values_file, '--wait', '--timeout=5m')
            pods = get('pods', '-n', 'kam-system')['items']
            workload = {}
            for app in ['kiki-kam-auth', ctrl]:
                chosen = [x for x in pods if x['metadata'].get('labels', {}).get('app') == app and not x['metadata'].get('deletionTimestamp')]
                assert len(chosen) == 2 and len({x['spec']['nodeName'] for x in chosen}) == 2
                assert all(any(c['type'] == 'Ready' and c['status'] == 'True' for c in x['status'].get('conditions', [])) for x in chosen)
                workload[app] = [{'name': x['metadata']['name'], 'node': x['spec']['nodeName'],
                                  'image_ids': [c['imageID'] for c in x['status']['containerStatuses']]} for x in chosen]
            passed('helm_wait_real_pods_two_workers', workload)
            assert operation().returncode == 0
            passed('initial_webhook_three_control_planes', mirrors())
            login(admin_login, 'helm-lab-admin', password)
            user_password = secrets.token_urlsafe(24)
            cli(admin_login, 'user', 'create', 'helm-lab-user', '--password-stdin', password=user_password)
            cli(admin_login, '-n', ns, 'grant', 'helm-lab-user')
            login(user_login, 'helm-lab-user', user_password)
            eventually(real_access)
            denied = run(['kubectl', '--kubeconfig', user_login, '--request-timeout=10s', '-n', ns, 'get', 'secrets'], required=False)
            assert denied.returncode != 0 and 'forbidden' in denied.stderr.lower()
            passed('password_login_namespace_rbac_without_impersonation')

            first_mirrors = mirrors()
            old_serial = run(['openssl', 'x509', '-in', tls/'kam-server.crt', '-noout', '-serial']).stdout.strip()
            ca_hash = hashlib.sha256((tls/'kam-ca.crt').read_bytes()).hexdigest()
            run([os.sys.executable, source/'deploy/make_tls.py', '--out', tls, '--hostname', a.auth_url.split('://')[1].split(':')[0], '--renew'])
            assert hashlib.sha256((tls/'kam-ca.crt').read_bytes()).hexdigest() == ca_hash
            secret = json.loads(k('-n', 'kam-system', 'create', 'secret', 'tls', 'kiki-kam-tls', '--cert=' + str(tls/'kam-server.crt'),
                                  '--key=' + str(tls/'kam-server.key'), '--dry-run=client', '-ojson').stdout)
            k('apply', '-f', '-', body=secret)
            k('-n', 'kam-system', 'rollout', 'restart', 'deployment/kiki-kam-auth')
            k('-n', 'kam-system', 'rollout', 'status', 'deployment/kiki-kam-auth', '--timeout=3m')
            assert operation().returncode == 0
            renewed_mirrors = mirrors()
            assert len(renewed_mirrors) == 3 and all(renewed_mirrors[n]['uid'] != first_mirrors[n]['uid'] and renewed_mirrors[n]['ready'] for n in first_mirrors)
            assert real_access()
            new_serial = run(['openssl', 'x509', '-in', tls/'kam-server.crt', '-noout', '-serial']).stdout.strip()
            assert old_serial != new_serial
            passed('same_ca_leaf_renewal_real_rollouts_and_login', {'old_server_serial': old_serial, 'new_server_serial': new_serial,
                   'ca_sha256_unchanged': ca_hash, 'api_mirrors': renewed_mirrors})

            installed = {host: snapshot(host) for host in hosts}
            run([os.sys.executable, source/'deploy/make_tls.py', '--out', tls, '--hostname', a.auth_url.split('://')[1].split(':')[0], '--renew'])
            fault = operation(fault=True)
            assert fault.returncode != 0 and 'captured manifest and dedicated TLS/config files were restored' in fault.stdout
            assert fingerprints(snapshot('cp02')) == fingerprints(installed['cp02'])
            assert fingerprints(snapshot('cp03')) == fingerprints(installed['cp03'])
            assert fingerprints(snapshot('cp01')) != fingerprints(installed['cp01'])
            eventually(api_ready)
            assert real_access()
            passed('real_cp02_startup_failure_restores_manifest_tls_bundle_stops_before_cp03', {
                'cp02_before_after_sha256': fingerprints(installed['cp02']), 'cp03_untouched': True,
                'cp01_updated_first': True, 'all_native_apis_ready': True})
            assert operation().returncode == 0
            passed('resume_after_rollback_three_native_apis_and_user_access', api_ready() and real_access())

            state_before = get('secret', 'kiki-kam-identities', '-n', 'kam-system')['data']
            failed_upgrade = helm('upgrade', release, source/'charts/kiki-kam', '-f', values_file, '--set',
                                  'auth.image=localhost/kiki-kam-auth:missing-disposable-test', '--rollback-on-failure', '--timeout=90s', required=False)
            assert failed_upgrade.returncode != 0
            helm_state = json.loads(helm('status', release, '-ojson').stdout)
            assert helm_state['info']['status'] == 'deployed'
            assert get('deployment', 'kiki-kam-auth', '-n', 'kam-system')['spec']['template']['spec']['containers'][0]['image'] == a.auth_image
            assert get('secret', 'kiki-kam-identities', '-n', 'kam-system')['data'] == state_before
            k('-n', 'kam-system', 'rollout', 'status', 'deployment/kiki-kam-auth', '--timeout=3m')
            assert real_access()
            passed('failed_helm_upgrade_rolls_back_ready_pods_and_preserves_accounts', {'revision': helm_state['version'], 'status': helm_state['info']['status']})
            cli(admin_login, '-n', ns, 'revoke', 'helm-lab-user')
            eventually(access_revoked)
            passed('revoke_removes_real_user_pod_access')
            cli(admin_login, 'user', 'delete', 'helm-lab-user')
            cli(admin_login, 'logout')
            report['status'] = 'passed'
        finally:
            restoration = {}
            for host in hosts:
                try:
                    restore(host, before[host])
                    restoration[host] = fingerprints(snapshot(host)) == fingerprints(before[host])
                except Exception:
                    restoration[host] = False
            try:
                eventually(api_ready)
                report['native_api_restored'] = all(restoration.values())
            except Exception:
                report['native_api_restored'] = False
            # Keep auth available if native rollback failed; never strand a live API.
            if report['native_api_restored']:
                if release_started:
                    state_before = get('secret', 'kiki-kam-identities', '-n', 'kam-system')['data']
                    helm('uninstall', release, '--wait', '--timeout=3m')
                    assert get('secret', 'kiki-kam-identities', '-n', 'kam-system')['data'] == state_before
                    passed('helm_uninstall_preserves_external_account_state_and_crd', bool(get('crd', 'kamaccessgrants.access.kam.dustbox.kr')))
                if created_namespace:
                    k('delete', 'namespace', ns, '--wait=true', '--timeout=90s')
                if created_external:
                    k('-n', 'kam-system', 'delete', 'secret', 'kiki-kam-identities', 'kiki-kam-tls', '--ignore-not-found')
                    k('-n', 'kam-system', 'delete', 'configmap', 'kiki-kam-webhook-ca', '--ignore-not-found')
                recovery.unlink(missing_ok=True)
            else:
                report['status'] = 'failed'
            report['finished_at'] = datetime.now(timezone.utc).isoformat()
            save()
            print('KAM_HELM_LIVE_RESULT', report['status'], 'native_api_restored=' + str(report['native_api_restored']), flush=True)
    if report['status'] != 'passed':
        raise SystemExit(1)


if __name__ == '__main__':
    main()
