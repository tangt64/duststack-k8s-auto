"""Namespace-local KAM reconciler. Uses projected credentials and verified TLS."""
import copy
from datetime import datetime, timezone
import hashlib
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
import os
from pathlib import Path
import ssl
import time
import threading
import uuid
from urllib.error import HTTPError
from urllib.request import Request, urlopen

GROUP = 'access.kam.dustbox.kr'
VERSION = GROUP + '/v1alpha1'
LAST_API_SUCCESS = 0.0


class Health(BaseHTTPRequestHandler):
    def do_GET(self):
        healthy = self.path == '/healthz' or (self.path == '/readyz' and time.monotonic() - LAST_API_SUCCESS < 30)
        self.send_response(200 if healthy else 503)
        self.end_headers()

    def log_message(self, *args):
        pass


def now():
    return datetime.now(timezone.utc)


def stamp(value):
    return value.isoformat().replace('+00:00', 'Z')


def desired_binding(grant, namespace, profiles, at=None):
    """Validate before mutation. A grant owns one deterministic RoleBinding."""
    meta, spec = grant['metadata'], grant['spec']
    if meta['namespace'] != namespace:
        raise ValueError('Namespace mismatch')
    if spec['profile'] not in profiles:
        raise ValueError('Profile is not allowed by this controller')
    subject = spec['subject']
    if subject['kind'] not in ('User', 'Group', 'ServiceAccount') or not subject['name']:
        raise ValueError('Invalid subject')
    if subject['name'].startswith('system:'):
        raise ValueError('Reserved subject')
    if spec.get('expiresAt'):
        expiry = datetime.fromisoformat(spec['expiresAt'].replace('Z', '+00:00'))
        if expiry.tzinfo is None:
            raise ValueError('Expiry needs a timezone')
        if expiry <= (at or now()):
            return None
    s = {'kind': subject['kind'], 'name': subject['name']}
    if s['kind'] == 'ServiceAccount':
        s['namespace'] = namespace
    else:
        s['apiGroup'] = 'rbac.authorization.k8s.io'
    return {'apiVersion': 'rbac.authorization.k8s.io/v1', 'kind': 'RoleBinding',
            'metadata': {'name': 'kam-' + hashlib.sha256(meta['uid'].encode()).hexdigest()[:32],
                         'namespace': namespace,
                         'labels': {'app.kubernetes.io/managed-by': 'kam'},
                         'ownerReferences': [{'apiVersion': VERSION, 'kind': 'KamAccessGrant',
                                              'name': meta['name'], 'uid': meta['uid'],
                                              'controller': True}]},
            'roleRef': {'apiGroup': 'rbac.authorization.k8s.io', 'kind': 'ClusterRole',
                        'name': spec['profile']}, 'subjects': [s]}


def owned(binding, grant):
    return any(o.get('uid') == grant['metadata']['uid'] and o.get('controller') is True
               and o.get('apiVersion') == VERSION and o.get('kind') == 'KamAccessGrant'
               for o in binding.get('metadata', {}).get('ownerReferences', []))


class API:
    def __init__(self):
        self.base = 'https://' + os.environ['KUBERNETES_SERVICE_HOST'] + ':' + os.environ.get('KUBERNETES_SERVICE_PORT', '443')
        self.credentials = Path('/var/run/secrets/kubernetes.io/serviceaccount')
        self.tls = ssl.create_default_context(cafile=str(self.credentials / 'ca.crt'))

    def call(self, method, path, body=None):
        headers = {'Authorization': 'Bearer ' + (self.credentials / 'token').read_text().strip(),
                   'Content-Type': 'application/json'}
        req = Request(self.base + path, headers=headers, method=method,
                      data=json.dumps(body).encode() if body is not None else None)
        try:
            with urlopen(req, context=self.tls, timeout=5) as response:
                return json.load(response)
        except HTTPError as error:
            if error.code == 404 and method == 'GET':
                return None
            raise RuntimeError('API request failed: HTTP ' + str(error.code)) from None


def reconcile(api, grant, namespace, profiles):
    base = '/apis/rbac.authorization.k8s.io/v1/namespaces/' + namespace + '/rolebindings'
    expected = desired_binding(grant, namespace, profiles)
    name = 'kam-' + hashlib.sha256(grant['metadata']['uid'].encode()).hexdigest()[:32]
    path = base + '/' + name
    current = api.call('GET', path)
    if current and not owned(current, grant):
        raise ValueError('Refusing to adopt an existing binding')
    if expected is None:
        if current:
            api.call('DELETE', path, {'preconditions': {'uid': current['metadata']['uid'],
                                                       'resourceVersion': current['metadata']['resourceVersion']}})
        return 'Expired'
    if not current:
        api.call('POST', base, expected)
    elif current['roleRef'] != expected['roleRef']:
        # roleRef is immutable. Retrying safely converges after a failed replacement.
        api.call('DELETE', path, {'preconditions': {'uid': current['metadata']['uid'],
                                                   'resourceVersion': current['metadata']['resourceVersion']}})
        api.call('POST', base, expected)
    elif current['subjects'] != expected['subjects']:
        updated = copy.deepcopy(current)
        updated['subjects'] = expected['subjects']
        api.call('PUT', path, updated)
    return 'Applied'


def acquire(api, namespace, identity, at=None):
    at = at or now()
    base = '/apis/coordination.k8s.io/v1/namespaces/' + namespace + '/leases'
    lease_name = os.environ.get('KAM_LEASE_NAME', 'kam-controller')
    lease = api.call('GET', base + '/' + lease_name)
    if lease:
        spec = lease['spec']
        renew = datetime.fromisoformat(spec['renewTime'].replace('Z', '+00:00'))
        if spec.get('holderIdentity') != identity and (at - renew).total_seconds() < spec['leaseDurationSeconds']:
            return False
    else:
        lease = {'apiVersion': 'coordination.k8s.io/v1', 'kind': 'Lease',
                 'metadata': {'name': lease_name, 'namespace': namespace}}
    lease['spec'] = {'holderIdentity': identity, 'leaseDurationSeconds': 60, 'renewTime': stamp(at)}
    api.call('PUT' if lease['metadata'].get('resourceVersion') else 'POST',
             base + '/' + lease_name if lease['metadata'].get('resourceVersion') else base, lease)
    return True


def run():
    global LAST_API_SUCCESS
    namespace = os.environ['KAM_NAMESPACE']
    lease_namespace = os.environ.get('KAM_LEASE_NAMESPACE', 'kam-system')
    profiles = set(os.environ.get('KAM_PROFILES', 'view').split(','))
    if not profiles or not profiles <= {'view', 'edit', 'admin'}:
        raise ValueError('Only reviewed built-in profiles are supported')
    api = API()
    health_server = HTTPServer(('0.0.0.0', 8080), Health)
    threading.Thread(target=health_server.serve_forever, daemon=True).start()
    identity = str(uuid.uuid4())
    path = '/apis/' + VERSION + '/namespaces/' + namespace + '/kamaccessgrants'
    while True:
        try:
            leader = acquire(api, lease_namespace, identity)
            LAST_API_SUCCESS = time.monotonic()
            if not leader:
                time.sleep(10)
                continue
            grants = api.call('GET', path)['items']
            for grant in grants:
                if not acquire(api, lease_namespace, identity):
                    break
                if grant['metadata'].get('deletionTimestamp'):
                    continue  # Native garbage collection removes owned bindings.
                try:
                    reason = reconcile(api, grant, namespace, profiles)
                    ready = reason == 'Applied'
                    message = reason
                except Exception as error:
                    reason, ready, message = 'ReconcileFailed', False, str(error)
                previous = grant.get('status', {}).get('conditions', [])
                condition = {'type': 'Ready', 'status': str(ready), 'reason': reason,
                             'message': message, 'observedGeneration': grant['metadata']['generation'],
                             'lastTransitionTime': stamp(now())}
                if previous and all(previous[0].get(k) == condition[k] for k in ('status', 'reason', 'message')):
                    condition['lastTransitionTime'] = previous[0]['lastTransitionTime']
                status = {'observedGeneration': grant['metadata']['generation'], 'conditions': [condition]}
                if status != grant.get('status'):
                    body = copy.deepcopy(grant)
                    body['status'] = status
                    api.call('PUT', path + '/' + grant['metadata']['name'] + '/status', body)
        except Exception as error:
            print('KAM reconciliation failed: ' + str(error), flush=True)
        time.sleep(10)


if __name__ == '__main__':
    run()
