import importlib.util
import json
from pathlib import Path
import tempfile
import tomllib
import unittest

spec=importlib.util.spec_from_file_location('configure_codex',Path(__file__).parents[1]/'configure_codex.py')
module=importlib.util.module_from_spec(spec); spec.loader.exec_module(module)

class ConfigTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='rwc-config-')
        self.path=Path(self.temp.name)/'config.toml'
        self.before='# User notes\nmodel = "existing-model"\n[mcp_servers.existing]\ncommand = "keep-me"\nenv = { PRIVATE_SETTING = "synthetic-fixture" }\n'
        self.path.write_text(self.before,encoding='utf-8')
        self.pair={'hostName':'rwc-123456789abc','mcpToken':'a'*64}
    def tearDown(self): self.temp.cleanup()
    def test_preserves_unrelated_values_and_comments(self):
        module.update_config(self.path,self.pair,'http://100.100.1.2:8765/mcp',False)
        raw=self.path.read_text(encoding='utf-8')
        self.assertTrue(raw.startswith(self.before))
        parsed=tomllib.loads(raw)
        self.assertEqual(parsed['mcp_servers']['existing']['command'],'keep-me')
        self.assertFalse(parsed['mcp_servers']['rwc_123456789abc']['enabled'])
    def test_idempotence_and_enable(self):
        module.update_config(self.path,self.pair,'http://example.invalid:8765/mcp',False)
        once=self.path.read_bytes()
        module.update_config(self.path,self.pair,'http://example.invalid:8765/mcp',False)
        self.assertEqual(once,self.path.read_bytes())
        module.update_config(self.path,self.pair,'http://100.100.1.2:8765/mcp',True)
        parsed=tomllib.loads(self.path.read_text(encoding='utf-8'))
        self.assertTrue(parsed['mcp_servers']['rwc_123456789abc']['enabled'])
        self.assertEqual(parsed['mcp_servers']['rwc_123456789abc']['url'],'http://100.100.1.2:8765/mcp')
    def test_rejects_unmanaged_name_collision(self):
        self.path.write_text(self.before+'[mcp_servers.rwc_123456789abc]\ncommand="custom"\n',encoding='utf-8')
        before=self.path.read_bytes()
        with self.assertRaises(ValueError): module.update_config(self.path,self.pair,'http://100.100.1.2:8765/mcp',False)
        self.assertEqual(before,self.path.read_bytes())
    def test_rejects_invalid_identity_before_writing(self):
        self.pair['hostName']='../../invalid'
        with self.assertRaises(ValueError): module.update_config(self.path,self.pair,'http://localhost',False)
        self.assertEqual(self.before,self.path.read_text(encoding='utf-8'))

if __name__=='__main__': unittest.main()
