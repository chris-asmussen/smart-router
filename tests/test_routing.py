"""Dependency-free tests for the routing layer (config load/save + plan_route).

Run: python3 -m unittest tests.test_routing
"""
import pathlib
import sys
import tempfile
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from smart_router.registry import Registry, load_registry
from smart_router.routing import load_routing, save_routing


def _reg(tmp):
    return Registry({}, [], [], pathlib.Path(tmp) / "config.json")


class RoutingConfigTests(unittest.TestCase):
    def test_defaults_fill_when_absent(self):
        with tempfile.TemporaryDirectory() as tmp:
            reg = _reg(tmp)
            routing = load_routing(reg)
            self.assertEqual(
                routing,
                {"mode": "auto", "priority_order": [], "exclude": [], "rules": []},
            )

    def test_loaded_block_does_not_alias_registry(self):
        with tempfile.TemporaryDirectory() as tmp:
            reg = _reg(tmp)
            reg.routing = {"priority_order": ["a"]}
            routing = load_routing(reg)
            routing["priority_order"].append("b")
            self.assertEqual(reg.routing["priority_order"], ["a"])

    def test_save_load_roundtrip(self):
        with tempfile.TemporaryDirectory() as tmp:
            reg = _reg(tmp)
            block = {
                "mode": "ask",
                "priority_order": ["gh.create_issue"],
                "exclude": ["weather.get_weather"],
                "rules": [
                    {
                        "when": {"extension": ["tsx"], "path_glob": "src/*.tsx"},
                        "prefer": ["gh.create_issue"],
                        "exclude": ["weather.get_weather"],
                    }
                ],
            }
            save_routing(reg, block)
            reg2 = load_registry(reg.path)
            self.assertEqual(load_routing(reg2), block)

    def test_save_persists_into_registry_object(self):
        with tempfile.TemporaryDirectory() as tmp:
            reg = _reg(tmp)
            save_routing(reg, {"mode": "ask"})
            self.assertEqual(reg.routing["mode"], "ask")

    def test_malformed_mode_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            reg = _reg(tmp)
            with self.assertRaises(ValueError):
                save_routing(reg, {"mode": "sometimes"})

    def test_malformed_priority_order_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            reg = _reg(tmp)
            with self.assertRaises(ValueError):
                save_routing(reg, {"priority_order": [1, 2]})

    def test_malformed_exclude_not_a_list_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            reg = _reg(tmp)
            with self.assertRaises(ValueError):
                save_routing(reg, {"exclude": "not-a-list"})

    def test_malformed_rule_when_type_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            reg = _reg(tmp)
            with self.assertRaises(ValueError):
                save_routing(reg, {"rules": [{"when": {"extension": "tsx"}}]})

    def test_malformed_rule_not_dict_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            reg = _reg(tmp)
            with self.assertRaises(ValueError):
                save_routing(reg, {"rules": ["nope"]})

    def test_malformed_block_not_dict_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            reg = _reg(tmp)
            with self.assertRaises(ValueError):
                save_routing(reg, ["not", "a", "dict"])


if __name__ == "__main__":
    unittest.main()
