import pathlib, sys, tempfile, unittest
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from smart_router.registry import (Registry, load_registry, save_registry,
    add_mcp_server, add_skill_dir, remove, summary)

class RegistryTests(unittest.TestCase):
    def _reg(self, tmp):
        return Registry({}, [], [], pathlib.Path(tmp) / "config.json")

    def test_add_mcp_is_idempotent(self):
        with tempfile.TemporaryDirectory() as tmp:
            reg = self._reg(tmp)
            self.assertTrue(add_mcp_server(reg, "gh", "npx", ["-y", "x"]))
            self.assertFalse(add_mcp_server(reg, "gh", "npx", ["-y", "x"]))
            self.assertEqual(reg.mcp_servers["gh"]["command"], "npx")

    def test_add_skill_dir_idempotent_by_abspath(self):
        with tempfile.TemporaryDirectory() as tmp:
            reg = self._reg(tmp)
            self.assertTrue(add_skill_dir(reg, tmp))
            self.assertFalse(add_skill_dir(reg, tmp))

    def test_remove(self):
        with tempfile.TemporaryDirectory() as tmp:
            reg = self._reg(tmp)
            add_mcp_server(reg, "gh", "npx")
            self.assertTrue(remove(reg, "mcp", "gh"))
            self.assertFalse(remove(reg, "mcp", "gh"))

    def test_save_load_roundtrip(self):
        with tempfile.TemporaryDirectory() as tmp:
            reg = self._reg(tmp)
            add_mcp_server(reg, "gh", "npx", ["-y"])
            save_registry(reg)
            reg2 = load_registry(reg.path)
            self.assertEqual(reg2.mcp_servers, reg.mcp_servers)

    def test_load_missing_returns_empty(self):
        with tempfile.TemporaryDirectory() as tmp:
            reg = load_registry(pathlib.Path(tmp) / "nope.json")
            self.assertEqual(reg.mcp_servers, {})
