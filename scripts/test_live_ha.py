"""Stop the active lab HAProxy, verify VIP migration/API recovery, then restore it."""
import argparse
from datetime import datetime, timezone
import ipaddress
import json
from pathlib import Path
import re
import socket
import subprocess
import threading
import time
from urllib.parse import urlsplit


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--kubeconfig', required=True)
    parser.add_argument('--vip', required=True)
    parser.add_argument('--lb', action='append', required=True, help='SSH user@literal-IP; supply twice')
    parser.add_argument('--identity-file', required=True)
    parser.add_argument('--known-hosts', required=True)
    parser.add_argument('--interface', required=True)
    parser.add_argument('--confirm-disposable-lab', action='store_true', required=True)
    parser.add_argument('--output', default='.tools/live-ha-result.json')
    args = parser.parse_args()
    vip = str(ipaddress.IPv4Address(args.vip))
    if len(args.lb) != 2 or len(set(args.lb)) != 2:
        parser.error('Supply exactly two distinct LB SSH targets')
    if not re.fullmatch(r'[A-Za-z0-9_.:-]+', args.interface):
        parser.error('Invalid network interface')
    for host in args.lb:
        if not re.fullmatch(r'[a-z_][a-z0-9_-]*@[0-9.]+', host):
            parser.error('LB target must be user@literal-IPv4')
        ipaddress.IPv4Address(host.split('@')[1])
    ssh = ['ssh', '-i', args.identity_file, '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=5',
           '-o', 'StrictHostKeyChecking=yes', '-o', 'UserKnownHostsFile=' + str(Path(args.known_hosts).resolve())]
    base = ['kubectl', '--kubeconfig', args.kubeconfig, '--request-timeout=3s']
    cluster = json.loads(subprocess.check_output(base + ['config', 'view', '--minify', '-o', 'json'], text=True))
    server = cluster['clusters'][0]['cluster']['server']
    hostname = urlsplit(server).hostname
    if vip not in {address[4][0] for address in socket.getaddrinfo(hostname, None, socket.AF_INET)}:
        parser.error('The selected kubeconfig API endpoint must resolve to the tested VIP')
    report = {'started_at': datetime.now(timezone.utc).isoformat(), 'vip': vip,
              'api_server': server, 'status': 'failed', 'probes': []}
    stop = threading.Event()
    stopped = None
    thread = None

    def remote(host, *words):
        # The only commands sent are fixed service operations or a validated interface name.
        result = subprocess.run(ssh + [host, *words], text=True, capture_output=True, timeout=20)
        if result.returncode:
            raise RuntimeError(host + ': ' + result.stderr[-1500:])
        return result.stdout

    def owners():
        found = []
        for host in args.lb:
            addresses = json.loads(remote(host, 'ip', '-j', '-4', 'addr', 'show', 'dev', args.interface))
            if any(a.get('local') == vip for interface in addresses for a in interface.get('addr_info', [])):
                found.append(host)
        return found

    def probe():
        while not stop.is_set():
            started = time.monotonic()
            try:
                result = subprocess.run(base + ['get', '--raw=/readyz'], text=True,
                                        capture_output=True, timeout=10)
                ok = result.returncode == 0 and result.stdout.strip() == 'ok'
            except subprocess.TimeoutExpired:
                ok = False
            report['probes'].append({'at': datetime.now(timezone.utc).isoformat(),
                                     'ok': ok,
                                     'seconds': round(time.monotonic() - started, 3)})
            stop.wait(1)

    try:
        initial = owners()
        assert len(initial) == 1, 'VIP must have exactly one owner before fault injection'
        report['owner_before'] = initial[0]
        thread = threading.Thread(target=probe, daemon=True)
        thread.start()
        time.sleep(5)
        assert report['probes'] and all(p['ok'] for p in report['probes']), 'API baseline failed'
        started = time.monotonic()
        stopped = initial[0]
        remote(stopped, 'sudo', '-n', 'systemctl', 'stop', 'haproxy')
        observed = []
        deadline = time.monotonic() + 45
        while time.monotonic() < deadline:
            current = owners()
            observed.append({'seconds': round(time.monotonic() - started, 2), 'owners': current})
            assert len(current) <= 1, 'Duplicate VIP ownership observed'
            if len(current) == 1 and current != initial:
                break
            time.sleep(1)
        else:
            raise RuntimeError('VIP failed to migrate within 45 seconds')
        report['owner_after'] = current[0]
        report['vip_migration_seconds'] = round(time.monotonic() - started, 2)
        report['ownership_samples'] = observed
        time.sleep(10)
        assert len(report['probes']) >= 3 and all(p['ok'] for p in report['probes'][-3:]), 'API did not recover through VIP'
        report['status'] = 'passed'
    except Exception as error:
        report['error'] = str(error)
        raise
    finally:
        stop.set()
        if thread:
            thread.join(timeout=12)
        if stopped:
            try:
                remote(stopped, 'sudo', '-n', 'systemctl', 'start', 'haproxy')
                remote(stopped, 'sudo', '-n', 'systemctl', 'is-active', 'haproxy')
                report['haproxy_restored'] = True
            except Exception as error:
                report['status'] = 'failed'
                report['restore_error'] = str(error)
        report['finished_at'] = datetime.now(timezone.utc).isoformat()
        output = Path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(report, indent=2) + '\n')
        print(json.dumps(report, ensure_ascii=False))
        if report['status'] == 'passed':
            print('HA_VIP_LIVE_CLUSTER=PASS')
        elif report.get('restore_error'):
            raise RuntimeError('HAProxy restoration failed; inspect the lab immediately')


if __name__ == '__main__':
    main()
