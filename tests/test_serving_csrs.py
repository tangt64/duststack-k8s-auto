"""Exercise real PKCS#10 signatures and hostile SAN/identity approval boundaries."""
import base64
import copy
import importlib.util
import ipaddress
from pathlib import Path
import unittest

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('serving_csrs', ROOT / 'scripts/check_kubelet_serving_csrs.py')
serving = importlib.util.module_from_spec(spec)
spec.loader.exec_module(serving)


class ServingCSRTests(unittest.TestCase):
    def payload(self, sans=None, subject=None, extra=None, corrupt=False):
        key = ec.generate_private_key(ec.SECP256R1())
        subject = subject or x509.Name([
            x509.NameAttribute(NameOID.COMMON_NAME, 'system:node:worker1'),
            x509.NameAttribute(NameOID.ORGANIZATION_NAME, 'system:nodes')])
        builder = x509.CertificateSigningRequestBuilder().subject_name(subject).add_extension(
            x509.SubjectAlternativeName(sans if sans is not None else [
                x509.DNSName('worker1'), x509.IPAddress(ipaddress.ip_address('172.30.61.77'))]), critical=False)
        if extra is not None:
            builder = builder.add_extension(extra, critical=True)
        request = builder.sign(key, hashes.SHA256())
        if corrupt:
            der = bytearray(request.public_bytes(serialization.Encoding.DER))
            der[-1] ^= 1
            request = x509.load_der_x509_csr(bytes(der))
        csr = {'metadata': {'name': 'csr-test', 'uid': 'fixed-uid', 'resourceVersion': '123'},
               'spec': {'username': 'system:node:worker1', 'groups': ['system:nodes', 'system:authenticated'],
                        'signerName': 'kubernetes.io/kubelet-serving',
                        'usages': ['digital signature', 'key encipherment', 'server auth'],
                        'request': base64.b64encode(request.public_bytes(serialization.Encoding.PEM)).decode()}}
        return {'expected_nodes': {'worker1': '172.30.61.77'},
                'nodes': [{'metadata': {'name': 'worker1'}, 'status': {'addresses': [
                    {'type': 'InternalIP', 'address': '172.30.61.77'}]}}], 'csrs': [csr]}

    def test_valid_request_preserves_uid_and_resource_version_for_approval(self):
        data = self.payload()
        before = copy.deepcopy(data)
        result = serving.select_requests(data)
        self.assertEqual(result['eligible'], data['csrs'])
        self.assertEqual(data, before)
        self.assertEqual(result['eligible'][0]['metadata']['resourceVersion'], '123')

    def test_foreign_ip_dns_email_uri_and_ca_requests_are_rejected(self):
        valid_ip = x509.IPAddress(ipaddress.ip_address('172.30.61.77'))
        for sans in [[valid_ip, x509.IPAddress(ipaddress.ip_address('172.30.61.180'))],
                     [valid_ip, x509.DNSName('cp1')], [valid_ip, x509.DNSName('*.example.com')],
                     [valid_ip, x509.RFC822Name('admin@example.com')],
                     [valid_ip, x509.UniformResourceIdentifier('spiffe://cluster/admin')],
                     [x509.DNSName('worker1')]]:
            with self.subTest(sans=sans), self.assertRaises(ValueError):
                serving.select_requests(self.payload(sans=sans))
        with self.assertRaises(ValueError):
            serving.select_requests(self.payload(extra=x509.BasicConstraints(ca=True, path_length=None)))

    def test_requester_subject_usage_signature_and_node_binding_are_enforced(self):
        for field, value in [('username', 'system:node:cp1'), ('groups', ['system:masters']),
                             ('usages', ['server auth', 'client auth'])]:
            data = self.payload()
            data['csrs'][0]['spec'][field] = value
            if field == 'username':
                self.assertEqual(serving.select_requests(data)['eligible'], [])
            else:
                with self.subTest(field=field), self.assertRaises(ValueError):
                    serving.select_requests(data)
        for payload in [self.payload(corrupt=True), self.payload(subject=x509.Name([
                x509.NameAttribute(NameOID.COMMON_NAME, 'system:node:worker1'),
                x509.NameAttribute(NameOID.ORGANIZATION_NAME, 'system:masters')]))]:
            with self.assertRaises(ValueError):
                serving.select_requests(payload)
        data = self.payload()
        data['nodes'][0]['status']['addresses'][0]['address'] = '172.30.61.180'
        with self.assertRaises(ValueError):
            serving.select_requests(data)

    def test_other_signers_and_already_processed_requests_are_not_approved(self):
        for change in ['other-signer', 'Approved', 'Denied', 'Failed']:
            data = self.payload()
            if change == 'other-signer':
                data['csrs'][0]['spec']['signerName'] = 'kubernetes.io/kube-apiserver-client-kubelet'
            else:
                data['csrs'][0]['status'] = {'conditions': [{'type': change, 'status': 'True'}]}
            self.assertEqual(serving.select_requests(data)['eligible'], [])
        data = self.payload()
        del data['csrs'][0]['metadata']['resourceVersion']
        with self.assertRaises(ValueError):
            serving.select_requests(data)


if __name__ == '__main__':
    unittest.main()
