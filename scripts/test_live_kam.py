"""Exercise an installed KAM controller in an explicitly disposable lab namespace."""
import argparse
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import subprocess
import time
import uuid


def eventually(check, description, seconds=150):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        value = check()
        if value:
            return value
        time.sleep(2)
    raise RuntimeError('Timed out: ' + description)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--kubeconfig', required=True)
    parser.add_argument('--namespace', required=True)
    parser.add_argument('--confirm-disposable-lab', action='store_true', required=True)
    parser.add_argument('--output', default='.tools/live-kam-result.json')
    parser.add_argument('--leader-trials', type=int, choices=range(1, 6), default=1)
    parser.add_argument('--max-handover-seconds', type=float, default=150)
    args = parser.parse_args()
    if args.max_handover_seconds <= 0 or args.max_handover_seconds > 150:
        parser.error('handover limit must be in (0, 150]')
    if args.namespace in {'default', 'kam-system'} or args.namespace.startswith('kube-'):
        parser.error('Use a dedicated, disposable target namespace')
    base = ['kubectl', '--kubeconfig', args.kubeconfig, '--request-timeout=15s']
    target = args.namespace
    name = 'kam-' + hashlib.sha256(target.encode()).hexdigest()[:16]
    suffix = uuid.uuid4().hex[:12]
    subject = 'kam-e2e-' + suffix
    grants = []
    evidence = {'started_at': datetime.now(timezone.utc).isoformat(), 'namespace': target,
                'subject': subject, 'status': 'failed', 'checks': {}}

    def run(*words, ns=None, body=None, required=True):
        result = subprocess.run(base + (['-n', ns] if ns else []) + list(words),
                                input=json.dumps(body) if body else None,
                                text=True, capture_output=True, timeout=45)
        if required and result.returncode:
            raise RuntimeError(result.stderr[-2500:])
        return result

    def read(kind, item=None, ns=target, selector=None):
        words = ['get', kind] + ([item] if item else []) + ['-o', 'json']
        if selector:
            words += ['-l', selector]
        return json.loads(run(*words, ns=ns).stdout)

    def allowed(verb='get', resource='pods', ns=target):
        result = run('auth', 'can-i', verb, resource, '--as=' + subject,
                     ns=ns, required=False)
        answer = result.stdout.strip()
        if answer not in {'yes', 'no'} or result.returncode not in {0, 1}:
            raise RuntimeError('Authorization query failed: ' + result.stderr[-1500:])
        return answer == 'yes'

    def grant(label, expires=None):
        grant_name = 'e2e-' + suffix + '-' + label
        obj = {'apiVersion': 'access.kam.dustbox.kr/v1alpha1', 'kind': 'KamAccessGrant',
               'metadata': {'name': grant_name, 'namespace': target},
               'spec': {'subject': {'kind': 'User', 'name': subject}, 'profile': 'view'}}
        if expires:
            obj['spec']['expiresAt'] = expires
        run('create', '-f', '-', body=obj)
        grants.append(grant_name)
        def ready():
            obj = read('kag', grant_name)
            conditions = obj.get('status', {}).get('conditions', [])
            return obj if any(c.get('type') == 'Ready' and c.get('status') == 'True' for c in conditions) else None
        obj = eventually(ready, 'Grant Ready')
        return grant_name, 'kam-' + hashlib.sha256(obj['metadata']['uid'].encode()).hexdigest()[:32]

    def missing(kind, item):
        result = run('get', kind, item, '--ignore-not-found', '-o', 'name', ns=target)
        return not result.stdout.strip()

    try:
        # Readiness plus two distinct nodeNames proves real scheduling, beyond API/envtest.
        run('rollout', 'status', 'deployment/' + name, '--timeout=30s', ns='kam-system')
        pods = read('pods', ns='kam-system', selector='app=' + name)['items']
        ready = [p for p in pods if not p['metadata'].get('deletionTimestamp') and
                 any(c.get('type') == 'Ready' and c.get('status') == 'True' for c in p.get('status', {}).get('conditions', []))]
        nodes = {p['spec'].get('nodeName') for p in ready}
        assert len(ready) == 2 and len(nodes) == 2 and None not in nodes, 'Two ready replicas must occupy distinct nodes'
        evidence['pods_before'] = [{'name': p['metadata']['name'], 'node': p['spec']['nodeName']} for p in ready]
        evidence['checks']['distinct_node_placement'] = True
        assert not allowed(), 'Fresh subject unexpectedly has access'
        grant_name, binding = grant('initial')
        eventually(allowed, 'view access granted')
        assert not allowed('get', 'secrets') and not allowed('create', 'rolebindings'), 'Unexpected escalation'
        assert not allowed(ns='default'), 'Grant escaped its namespace'
        evidence['checks']['namespace_view_and_escalation_denied'] = True

        evidence['leader_failovers'] = []
        for _ in range(args.leader_trials):
            pods = read('pods', ns='kam-system', selector='app=' + name)['items']
            ready = [p for p in pods if not p['metadata'].get('deletionTimestamp') and
                     any(c.get('type') == 'Ready' and c.get('status') == 'True' for c in p.get('status', {}).get('conditions', []))]
            assert len(ready) == 2 and len({p['spec']['nodeName'] for p in ready}) == 2
            lease = read('lease', name, ns='kam-system')
            holder = lease['spec']['holderIdentity']
            leader = next((p for p in ready if holder.split(':', 1)[0] == p['metadata']['name']), None)
            assert leader, 'Lease holder must match a running controller Pod'
            started = time.monotonic()
            run('delete', 'pod', leader['metadata']['name'], '--wait=false', ns='kam-system')
            def new_leader():
                obj = read('lease', name, ns='kam-system')
                value = obj['spec'].get('holderIdentity')
                return value if value and value != holder else None
            replacement = eventually(new_leader, 'leader failover')
            evidence['leader_failover'] = {'from': holder, 'to': replacement, 'seconds': round(time.monotonic() - started, 2)}
            assert allowed(), 'Existing view permission disappeared during controller failover'
            trial = evidence['leader_failover'].copy()
            evidence['leader_failovers'].append(trial)
            assert trial['seconds'] <= args.max_handover_seconds, 'Leader handover exceeded requested limit'
            run('rollout', 'status', 'deployment/' + name, '--timeout=60s', ns='kam-system')
        run('delete', 'kag', grant_name, ns=target)
        eventually(lambda: missing('rolebinding', binding), 'native garbage collection of owned binding')
        eventually(lambda: not allowed(), 'permission revoked after CR deletion')
        evidence['checks']['leader_failover_and_native_gc'] = True

        expiry = (datetime.now(timezone.utc) + timedelta(seconds=75)).isoformat().replace('+00:00', 'Z')
        _, binding = grant('expiry', expiry)
        eventually(allowed, 'expiring view access granted')
        eventually(lambda: missing('rolebinding', binding) and not allowed(), 'expiry revokes binding and access', seconds=150)
        evidence['checks']['expiry_revocation'] = True
        run('rollout', 'status', 'deployment/' + name, '--timeout=30s', ns='kam-system')
        restored = read('pods', ns='kam-system', selector='app=' + name)['items']
        evidence['pods_after'] = [{'name': p['metadata']['name'], 'node': p['spec'].get('nodeName')}
                                  for p in restored if not p['metadata'].get('deletionTimestamp')]
        evidence['status'] = 'passed'
        print('KAM_LIVE_CLUSTER=PASS')
    except Exception as error:
        evidence['error'] = str(error)
        raise
    finally:
        for item in grants:
            run('delete', 'kag', item, '--ignore-not-found', ns=target, required=False)
        evidence['finished_at'] = datetime.now(timezone.utc).isoformat()
        output = Path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(evidence, indent=2) + '\n')
        print(json.dumps(evidence, ensure_ascii=False))


if __name__ == '__main__':
    main()
