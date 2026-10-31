"""Regression checks for release locks and binary-free project sources."""
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

    def test_source_tree_contains_no_binary_or_broken_markdown_links(self):
        errors, _ = policy.check()
        self.assertEqual(errors, [])

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
