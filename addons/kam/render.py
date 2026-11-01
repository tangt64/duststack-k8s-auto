#!/usr/bin/env python3
"""Render explicit namespace installation; never contacts a cluster."""
import argparse
import hashlib
from pathlib import Path
import re
import yaml

DEFAULT_IMAGE = 'docker.io/library/python:3.12.16-slim-bookworm@sha256:623674a14ef93d052bb9b0de4dbf5f28eb578a35263838941cc8aa43213c1487'


def manifests(namespace, image, profiles):
    if not re.fullmatch(r'[a-z0-9](?:[-a-z0-9]{0,61}[a-z0-9])?', namespace):
        raise ValueError('Invalid namespace')
    if not re.fullmatch(r'[^\s]+@sha256:[0-9a-f]{64}', image):
        raise ValueError('Controller image must use an explicit SHA-256 digest')
    if not set(profiles) <= {'view', 'edit', 'admin'} or not profiles:
        raise ValueError('Invalid profiles')
    meta = lambda name: {'name': name, 'namespace': namespace}
    resource = lambda kind, name, **kw: dict(apiVersion='v1', kind=kind, metadata=meta(name), **kw)
    crd = {'apiVersion': 'apiextensions.k8s.io/v1', 'kind': 'CustomResourceDefinition',
           'metadata': {'name': 'kamaccessgrants.access.kam.dustbox.kr'},
           'spec': {'group': 'access.kam.dustbox.kr', 'scope': 'Namespaced',
                    'names': {'plural': 'kamaccessgrants', 'singular': 'kamaccessgrant',
                              'kind': 'KamAccessGrant', 'shortNames': ['kag']},
                    'versions': [{'name': 'v1alpha1', 'served': True, 'storage': True,
                                  'subresources': {'status': {}},
                                  'additionalPrinterColumns': [
                                      {'name': 'Profile', 'type': 'string', 'jsonPath': '.spec.profile'},
                                      {'name': 'Ready', 'type': 'string', 'jsonPath': '.status.conditions[0].status'}],
                                  'schema': {'openAPIV3Schema': {'type': 'object', 'properties': {
                                      'spec': {'type': 'object', 'required': ['subject', 'profile'],
                                               'properties': {
                                                   'subject': {'type': 'object', 'required': ['kind', 'name'], 'properties': {
                                                       'kind': {'type': 'string', 'enum': ['User', 'Group', 'ServiceAccount']},
                                                       'name': {'type': 'string', 'minLength': 1, 'maxLength': 253,
                                                                'pattern': '^[^\\s]+$'}},
                                                       'x-kubernetes-validations': [{'rule': "!self.name.startsWith('system:')", 'message': 'Reserved subject'}]},
                                                   'profile': {'type': 'string', 'enum': ['view', 'edit', 'admin']},
                                                   'expiresAt': {'type': 'string', 'format': 'date-time'}},
                                               'x-kubernetes-validations': [{'rule': 'self.subject == oldSelf.subject', 'message': 'Subject is immutable; create a new grant'}]},
                                      'status': {'type': 'object', 'x-kubernetes-preserve-unknown-fields': True}}}}}]}}
    role = {'apiVersion': 'rbac.authorization.k8s.io/v1', 'kind': 'Role', 'metadata': meta('kam-controller'),
            'rules': [{'apiGroups': ['access.kam.dustbox.kr'], 'resources': ['kamaccessgrants'], 'verbs': ['get', 'list']},
                      {'apiGroups': ['access.kam.dustbox.kr'], 'resources': ['kamaccessgrants/status'], 'verbs': ['update']},
                      {'apiGroups': ['rbac.authorization.k8s.io'], 'resources': ['rolebindings'], 'verbs': ['get', 'create', 'update', 'delete']},
                      {'apiGroups': ['rbac.authorization.k8s.io'], 'resources': ['clusterroles'], 'resourceNames': profiles, 'verbs': ['bind']},
                      {'apiGroups': ['coordination.k8s.io'], 'resources': ['leases'], 'verbs': ['create']},
                      {'apiGroups': ['coordination.k8s.io'], 'resources': ['leases'], 'resourceNames': ['kam-controller'], 'verbs': ['get', 'update']}]}
    binding = {'apiVersion': 'rbac.authorization.k8s.io/v1', 'kind': 'RoleBinding', 'metadata': meta('kam-controller'),
               'roleRef': {'apiGroup': 'rbac.authorization.k8s.io', 'kind': 'Role', 'name': 'kam-controller'},
               'subjects': [{'kind': 'ServiceAccount', 'name': 'kam-controller', 'namespace': namespace}]}
    deployment = {'apiVersion': 'apps/v1', 'kind': 'Deployment', 'metadata': meta('kam-controller'),
                  'spec': {'replicas': 2, 'selector': {'matchLabels': {'app': 'kam-controller'}},
                           'template': {'metadata': {'labels': {'app': 'kam-controller'}}, 'spec': {
                               'serviceAccountName': 'kam-controller',
                               'securityContext': {'runAsNonRoot': True, 'runAsUser': 1000, 'seccompProfile': {'type': 'RuntimeDefault'}},
                               'topologySpreadConstraints': [{'maxSkew': 1, 'topologyKey': 'kubernetes.io/hostname',
                                   'whenUnsatisfiable': 'DoNotSchedule', 'labelSelector': {'matchLabels': {'app': 'kam-controller'}}}],
                               'containers': [{'name': 'controller', 'image': image,
                                   'command': ['python3', '-B', '/app/controller.py'],
                                   'readinessProbe': {'httpGet': {'path': '/readyz', 'port': 8080}, 'periodSeconds': 10},
                                   'livenessProbe': {'httpGet': {'path': '/healthz', 'port': 8080}, 'initialDelaySeconds': 10, 'periodSeconds': 10},
                                   'env': [{'name': 'KAM_NAMESPACE', 'value': namespace}, {'name': 'KAM_PROFILES', 'value': ','.join(profiles)}],
                                   'resources': {'requests': {'cpu': '20m', 'memory': '32Mi'}, 'limits': {'cpu': '200m', 'memory': '128Mi'}},
                                   'securityContext': {'allowPrivilegeEscalation': False, 'readOnlyRootFilesystem': True, 'capabilities': {'drop': ['ALL']}},
                                   'volumeMounts': [{'name': 'source', 'mountPath': '/app', 'readOnly': True}]}],
                               'volumes': [{'name': 'source', 'configMap': {'name': 'kam-controller-source'}}]}}}}
    # Controller code and credentials must be outside editable tenant namespaces.
    name = 'kam-' + hashlib.sha256(namespace.encode()).hexdigest()[:16]
    secure_meta = {'name': name, 'namespace': 'kam-system'}
    sa = {'apiVersion': 'v1', 'kind': 'ServiceAccount', 'metadata': dict(secure_meta)}
    source = {'apiVersion': 'v1', 'kind': 'ConfigMap', 'metadata': dict(secure_meta),
              'data': {'controller.py': Path(__file__).with_name('controller.py').read_text()}}
    role['rules'] = [r for r in role['rules'] if r['apiGroups'] != ['coordination.k8s.io']]
    binding['subjects'][0].update(name=name, namespace='kam-system')
    lease_role = {'apiVersion': 'rbac.authorization.k8s.io/v1', 'kind': 'Role', 'metadata': dict(secure_meta),
                  'rules': [{'apiGroups': ['coordination.k8s.io'], 'resources': ['leases'], 'verbs': ['create']},
                            {'apiGroups': ['coordination.k8s.io'], 'resources': ['leases'], 'resourceNames': [name], 'verbs': ['get', 'update']}]}
    lease_binding = {'apiVersion': 'rbac.authorization.k8s.io/v1', 'kind': 'RoleBinding', 'metadata': dict(secure_meta),
                     'roleRef': {'apiGroup': 'rbac.authorization.k8s.io', 'kind': 'Role', 'name': name}, 'subjects': binding['subjects']}
    deployment['metadata'] = dict(secure_meta)
    deployment['spec']['strategy'] = {'type': 'RollingUpdate',
                                    'rollingUpdate': {'maxSurge': 0, 'maxUnavailable': 1}}
    pod = deployment['spec']['template']['spec']
    pod['terminationGracePeriodSeconds'] = 45
    pod['serviceAccountName'] = name
    pod['volumes'][0]['configMap']['name'] = name
    pod['containers'][0]['env'] += [{'name': 'KAM_LEASE_NAMESPACE', 'value': 'kam-system'}, {'name': 'KAM_LEASE_NAME', 'value': name},
                                  {'name': 'KAM_POD_NAME', 'valueFrom': {'fieldRef': {'fieldPath': 'metadata.name'}}}]
    deployment['spec']['selector']['matchLabels']['app'] = name
    deployment['spec']['template']['metadata']['labels']['app'] = name
    pod['topologySpreadConstraints'][0]['labelSelector']['matchLabels']['app'] = name
    pdb = {'apiVersion': 'policy/v1', 'kind': 'PodDisruptionBudget', 'metadata': dict(secure_meta),
           'spec': {'minAvailable': 1, 'selector': {'matchLabels': {'app': name}}}}
    return [crd, sa, role, binding, lease_role, lease_binding, source, deployment, pdb]


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('--namespace', required=True)
    p.add_argument('--image', default=DEFAULT_IMAGE, help='Python 3.12+ image pinned by digest; default verified Linux amd64 Python 3.12.16')
    p.add_argument('--profile', action='append', choices=['view', 'edit', 'admin'])
    a = p.parse_args()
    print(yaml.safe_dump_all(manifests(a.namespace, a.image, a.profile or ['view']), sort_keys=False))
