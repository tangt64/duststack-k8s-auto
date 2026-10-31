"""Select only signed, inventory-bound kubelet serving requests; never approve here."""
import base64
import ipaddress
import json
import sys

from cryptography import x509
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID


def select_requests(payload):
    expected = payload['expected_nodes']
    nodes = {node['metadata']['name']: node for node in payload['nodes']}
    eligible, ignored = [], []
    for item in payload['csrs']:
        spec = item['spec']
        if spec.get('signerName') != 'kubernetes.io/kubelet-serving':
            continue
        if any(c['type'] in ['Approved', 'Denied', 'Failed'] for c in item.get('status', {}).get('conditions', [])):
            continue
        username = spec.get('username', '')
        name = username.removeprefix('system:node:')
        if username != 'system:node:' + name or name not in expected:
            ignored.append(item['metadata']['name'])
            continue
        address = ipaddress.ip_address(expected[name])
        if name not in nodes or str(address) not in [a['address'] for a in nodes[name]['status']['addresses'] if a['type'] == 'InternalIP']:
            raise ValueError(name + ': Node InternalIP does not match the inventory')
        if set(spec.get('groups', [])) != {'system:nodes', 'system:authenticated'}:
            raise ValueError(name + ': unexpected requester groups')
        usages = set(spec.get('usages', []))
        if 'server auth' not in usages or usages - {'server auth', 'digital signature', 'key encipherment'}:
            raise ValueError(name + ': unexpected certificate usages')
        request = x509.load_pem_x509_csr(base64.b64decode(spec['request'], validate=True))
        if not request.is_signature_valid:
            raise ValueError(name + ': invalid CSR signature')
        subject = request.subject
        if len(subject) != 2 or [a.value for a in subject.get_attributes_for_oid(NameOID.COMMON_NAME)] != [username] or [a.value for a in subject.get_attributes_for_oid(NameOID.ORGANIZATION_NAME)] != ['system:nodes']:
            raise ValueError(name + ': unexpected certificate subject')
        for extension in request.extensions:
            value = extension.value
            if isinstance(value, x509.SubjectAlternativeName):
                continue
            if isinstance(value, x509.ExtendedKeyUsage) and list(value) == [ExtendedKeyUsageOID.SERVER_AUTH]:
                continue
            if isinstance(value, x509.KeyUsage) and not any([value.content_commitment, value.data_encipherment, value.key_agreement, value.key_cert_sign, value.crl_sign]):
                continue
            raise ValueError(name + ': unexpected CSR extension')
        san = request.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
        if any(not isinstance(value, (x509.DNSName, x509.IPAddress)) for value in san):
            raise ValueError(name + ': URI/email/other SANs are forbidden')
        ips = san.get_values_for_type(x509.IPAddress)
        dns = san.get_values_for_type(x509.DNSName)
        if set(ips) != {address} or set(dns) - {name}:
            raise ValueError(name + ': SANs do not match the inventory node')
        if not item['metadata'].get('uid') or not item['metadata'].get('resourceVersion'):
            raise ValueError(name + ': missing immutable object identity/version')
        eligible.append(item)
    return {'eligible': eligible, 'ignored': ignored}


if __name__ == '__main__':
    print(json.dumps(select_requests(json.load(sys.stdin))))
