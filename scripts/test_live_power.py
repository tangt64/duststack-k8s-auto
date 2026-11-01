"""Observe externally injected VM power faults in an explicitly disposable HA lab.

This observer never calls a cloud API or removes an etcd member. Start it before
an operator injects the fault; retain the cloud action receipt separately.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import ipaddress
import json
from pathlib import Path
import socket
import subprocess
import time
import uuid


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--kubeconfig', required=True)
    p.add_argument('--etcdctl', required=True, help='Official etcdctl executable available locally')
    p.add_argument('--peer', action='append', required=True)
    p.add_argument('--lb', action='append', required=True)
    p.add_argument('--identity-file', required=True)
    p.add_argument('--known-hosts', required=True)
    p.add_argument('--phase', choices=['lb', 'cp-single', 'cp-quorum'], required=True)
    p.add_argument('--seconds', type=int, default=180)
    p.add_argument('--output', required=True)
    p.add_argument('--confirm-disposable-lab', action='store_true', required=True)
    a = p.parse_args()
    if len(set(a.peer)) != 2 or len(set(a.lb)) != 2 or not 60 <= a.seconds <= 600:
        p.error('Supply two distinct peer and LB IPs, duration 60..600 seconds')
    for ip in a.peer + a.lb:
        ipaddress.IPv4Address(ip)
    kubectl = ['kubectl', '--kubeconfig', a.kubeconfig, '--request-timeout=2s']
    ssh = ['ssh', '-i', a.identity_file, '-oBatchMode=yes', '-oConnectTimeout=2',
           '-oStrictHostKeyChecking=yes', '-oUserKnownHostsFile=' + str(Path(a.known_hosts).resolve())]
    ns = 'power-e2e-' + uuid.uuid4().hex[:10]
    nonce = uuid.uuid4().hex
    report = {'started_at': datetime.now(timezone.utc).isoformat(), 'phase': a.phase,
              'namespace': ns, 'status': 'failed', 'samples': []}

    def call(cmd, timeout=8):
        try:
            r = subprocess.run(cmd, text=True, capture_output=True, timeout=timeout)
            return {'ok': r.returncode == 0, 'output': (r.stdout or r.stderr).strip()[-1500:]}
        except subprocess.TimeoutExpired:
            return {'ok': False, 'output': 'command timeout'}

    def remote(ip, *cmd):
        return call(ssh + ['root@' + ip, *cmd])

    def boot_ids():
        return {ip: remote(ip, 'cat', '/proc/sys/kernel/random/boot_id') for ip in a.peer + a.lb}

    def tcp(ip):
        try:
            with socket.create_connection((ip, 2379), timeout=.4):
                return True
        except OSError:
            return False

    def owners():
        result = {}
        for ip in a.lb:
            r = remote(ip, 'ip', '-j', '-4', 'addr', 'show')
            result[ip] = (any(x.get('local') == '172.30.62.250' for dev in json.loads(r['output'])
                              for x in dev.get('addr_info', [])) if r['ok'] else None)
        return result

    def etcd(action):
        return call([a.etcdctl, '--endpoints=https://127.0.0.1:2379',
                     '--cacert=/etc/kubernetes/pki/etcd/ca.crt',
                     '--cert=/etc/kubernetes/pki/etcd/healthcheck-client.crt',
                     '--key=/etc/kubernetes/pki/etcd/healthcheck-client.key',
                     '--dial-timeout=1s', '--command-timeout=2s', 'endpoint', action, '-w', 'json'])

    created = False
    try:
        assert Path(a.etcdctl).is_file(), 'Local official etcdctl executable required'
        assert etcd('health')['ok'], 'Local etcd baseline failed'
        report['boot_before'] = boot_ids()
        assert all(v['ok'] for v in report['boot_before'].values())
        report['owners_before'] = owners()
        assert list(report['owners_before'].values()).count(True) == 1
        subprocess.run(kubectl + ['create', 'namespace', ns], check=True, capture_output=True)
        created = True
        subprocess.run(kubectl + ['-n', ns, 'create', 'configmap', 'sentinel', '--from-literal=value=' + nonce],
                       check=True, capture_output=True)
        subprocess.run(kubectl + ['-n', ns, 'create', 'configmap', 'write-probe', '--from-literal=value=0'],
                       check=True, capture_output=True)
        print('POWER_PROBE_READY phase=' + a.phase, flush=True)
        start = time.monotonic()
        with ThreadPoolExecutor(max_workers=6) as pool:
            while time.monotonic() - start < a.seconds:
                n = len(report['samples'])
                jobs = {'api_ready': pool.submit(call, kubectl + ['get', '--raw=/readyz']),
                        'api_write': pool.submit(call, kubectl + ['-n', ns, 'patch', 'configmap', 'write-probe',
                            '--type=merge', '-p', json.dumps({'data': {'value': str(n)}})]),
                        'etcd_health': pool.submit(etcd, 'health'),
                        'etcd_status': pool.submit(etcd, 'status')}
                sample = {'seconds': round(time.monotonic() - start, 2),
                          'at': datetime.now(timezone.utc).isoformat(),
                          'peer_etcd_tcp': {ip: tcp(ip) for ip in a.peer}}
                if a.phase == 'lb':
                    sample['vip_owners'] = owners()
                sample.update({key: job.result() for key, job in jobs.items()})
                report['samples'].append(sample)
                print('PROBE', sample['seconds'], 'etcd=' + str(sample['etcd_health']['ok']),
                      'write=' + str(sample['api_write']['ok']), 'peers=' + str(sample['peer_etcd_tcp']), flush=True)
                time.sleep(1)
        report['boot_after'] = boot_ids()
        changed = [ip for ip, v in report['boot_after'].items()
                   if v['ok'] and v['output'] != report['boot_before'][ip]['output']]
        report['rebooted_ips'] = changed
        expected = a.lb if a.phase == 'lb' else a.peer
        assert any(ip in changed for ip in expected), 'No target boot ID changed: no fault proven'
        if a.phase == 'cp-quorum':
            assert all(ip in changed for ip in a.peer), 'Both control planes must reboot'
            assert any(not any(s['peer_etcd_tcp'].values()) and s['etcd_status']['ok']
                       and not s['etcd_health']['ok'] and not s['api_write']['ok']
                       for s in report['samples']), 'No observed quorum-loss window'
        if a.phase == 'cp-single':
            assert a.peer[0] in changed and a.peer[1] not in changed
            assert any(not s['peer_etcd_tcp'][a.peer[0]] and s['peer_etcd_tcp'][a.peer[1]]
                       and s['etcd_health']['ok'] and s['api_write']['ok']
                       for s in report['samples']), 'No observed successful write with one member down'
        if a.phase == 'lb':
            original = next(ip for ip, own in report['owners_before'].items() if own)
            assert original in changed, 'The active LB must reboot'
            assert any(s['vip_owners'].get(original) is not True and
                       any(v is True for ip, v in s['vip_owners'].items() if ip != original)
                       and s['api_ready']['ok'] for s in report['samples']), 'No observed VIP failover'
        assert all(s['etcd_health']['ok'] and s['api_write']['ok'] for s in report['samples'][-3:])
        sentinel = call(kubectl + ['-n', ns, 'get', 'configmap', 'sentinel', '-ojson'])
        assert sentinel['ok'] and json.loads(sentinel['output'])['data']['value'] == nonce
        assert all(tcp(ip) for ip in a.peer) and etcd('health')['ok']
        report['peer_api_after'] = {ip: call(kubectl + ['--server=https://' + ip + ':6443',
                                                      'get', '--raw=/readyz']) for ip in a.peer}
        assert all(v['ok'] for v in report['peer_api_after'].values())
        members = call([a.etcdctl, '--endpoints=https://127.0.0.1:2379',
                        '--cacert=/etc/kubernetes/pki/etcd/ca.crt',
                        '--cert=/etc/kubernetes/pki/etcd/healthcheck-client.crt',
                        '--key=/etc/kubernetes/pki/etcd/healthcheck-client.key',
                        '--command-timeout=2s', 'member', 'list', '-w', 'json'])
        assert members['ok'] and len(json.loads(members['output'])['members']) == 3
        report['etcd_members_after'] = 3
        report['owners_after'] = owners()
        assert all(v is not None for v in report['owners_after'].values())
        assert list(report['owners_after'].values()).count(True) == 1
        report['sentinel_preserved'] = True
        report['status'] = 'passed'
    except Exception as e:
        report['error'] = str(e)
        raise
    finally:
        if created:
            report['test_namespace_cleanup'] = call(kubectl + ['delete', 'namespace', ns, '--wait=false'])
        report['finished_at'] = datetime.now(timezone.utc).isoformat()
        path = Path(a.output)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(report, indent=2) + '\n')
        print('POWER_RESULT', report['status'], a.output, flush=True)


if __name__ == '__main__':
    main()
