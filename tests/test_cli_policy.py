"""Regression checks for release locks and narrowly scoped documentation images."""
import copy
import importlib.util
from pathlib import Path
import tempfile
import unittest

from ansible.template import trust_as_template
from test_configuration import ROOT, read_yaml, templar, variables

spec = importlib.util.spec_from_file_location('source_policy', ROOT / 'scripts/check_source_tree.py')
policy = importlib.util.module_from_spec(spec)
spec.loader.exec_module(policy)


class CliPolicyTests(unittest.TestCase):
    def tool_variables(self, name='clusteradm', arch='amd64', **overrides):
        values = read_yaml('roles/common/cli-tool/defaults/main.yaml')
        values.update(read_yaml('roles/common/cli-tool/vars/main.yaml'))
        values.update(cli_tool_name=name, cli_tool_arch=arch)
        values.update(overrides)
        return variables(**values)

    def test_default_release_locks_resolve_for_both_architectures(self):
        assertions = read_yaml('roles/common/cli-tool/tasks/main.yaml')[1]['ansible.builtin.assert']['that']
        for name in ('clusteradm', 'virtctl', 'helm'):
            for arch in ('amd64', 'arm64'):
                with self.subTest(name=name, arch=arch):
                    engine = templar(self.tool_variables(name, arch))
                    self.assertTrue(all(engine.evaluate_conditional(trust_as_template(x)) for x in assertions))
                    release = engine.evaluate_expression(trust_as_template('_cli_spec'))
                    self.assertIn(release['version'], release['url'])
                    self.assertIn(arch, release['asset'])

    def test_metadata_rejects_unpinned_or_unsafe_artifacts(self):
        assertions = read_yaml('roles/common/cli-tool/tasks/main.yaml')[1]['ansible.builtin.assert']['that']
        catalog = read_yaml('roles/common/cli-tool/defaults/main.yaml')['cli_tool_catalog']
        for field, value in [('version', 'latest'), ('url', 'http://example.com/cli'),
                             ('asset', '..'), ('archive_member', '../cli'),
                             ('sha256', {'amd64': 'invalid'})]:
            with self.subTest(field=field):
                changed = copy.deepcopy(catalog)
                changed['clusteradm'][field] = value
                engine = templar(self.tool_variables(cli_tool_catalog=changed))
                self.assertFalse(all(engine.evaluate_conditional(trust_as_template(x)) for x in assertions))

    def test_source_tree_contains_no_unapproved_binary_or_broken_markdown_links(self):
        errors, _ = policy.check()
        self.assertEqual(errors, [])

    def test_only_named_bounded_jpeg_frames_are_allowed_as_documentation(self):
        # A small format fixture checks framing metadata; real captures are also reviewed visually.
        frame = b'\xff\xd8\xff\xc0\x00\x0b\x08\x01\x90\x03\x20\x01\x01\x11\x00\xff\xd9'
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            screenshot = root / 'docs/screenshots/01-lab-vms.jpg'
            screenshot.parent.mkdir(parents=True)
            screenshot.write_bytes(frame)
            self.assertEqual(policy.check(root)[0], [])
            screenshot.write_bytes(b'\x7fELF\x00masquerading-as-a-screenshot')
            self.assertIn('Invalid or oversized documentation screenshot', policy.check(root)[0][0])
            screenshot.write_bytes(frame)
            (root / 'unexpected.jpg').write_bytes(frame)
            self.assertTrue(any('Binary payload' in item for item in policy.check(root)[0]))
            self.assertFalse(policy.valid_documentation_jpeg(frame + b'\x00'))
            self.assertFalse(policy.valid_documentation_jpeg(b'\xff\xd8\xff' + b'\x00' * (2 * 1024 * 1024) + b'\xff\xd9'))

    def test_policy_detects_binary_payload_and_empty_legacy_executable(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'new-tool').write_bytes(b'\x7fELF\x00test')
            old = root / policy.REMOVED_EXECUTABLES[1]
            old.parent.mkdir(parents=True)
            old.write_bytes(b'')
            errors, _ = policy.check(root)
            self.assertTrue(any('Binary payload' in error for error in errors))
            self.assertTrue(any('Removed bundled executable' in error for error in errors))

    def test_policy_allows_manual_artifacts_and_detects_bad_links(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'artifacts').mkdir()
            (root / 'artifacts/cli').write_bytes(b'\x7fELF\x00test')
            (root / 'README.md').write_text('[bad](missing.md)\n', encoding='utf-8')
            errors, _ = policy.check(root)
            self.assertEqual(len(errors), 1)
            self.assertIn('Broken Markdown link', errors[0])


if __name__ == '__main__':
    unittest.main()
