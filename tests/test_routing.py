"""Dependency-free tests for the routing layer (config load/save + plan_route).

Run: python3 -m unittest tests.test_routing
"""
import pathlib
import sys
import tempfile
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from smart_router.registry import Registry, load_registry
from smart_router.routing import load_routing, plan_route, save_routing


def _reg(tmp):
    return Registry({}, [], [], pathlib.Path(tmp) / "config.json")


def _catalog():
    return [
        {
            "type": "tool", "server": "gh", "name": "create_issue",
            "description": "Create a GitHub issue",
            "input_schema": {"properties": {"title": {}, "body": {}}},
        },
        {
            "type": "tool", "server": "weather", "name": "get_weather",
            "description": "Get the current weather for a city",
            "input_schema": {},
        },
    ]


def _routing(**overrides):
    block = {"mode": "auto", "priority_order": [], "exclude": [], "rules": []}
    block.update(overrides)
    return block


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

    def test_load_validates_stored_block(self):
        # A hand-edited registry with an invalid mode must fail loudly on read.
        with tempfile.TemporaryDirectory() as tmp:
            reg = _reg(tmp)
            reg.routing = {"mode": "weird"}
            with self.assertRaises(ValueError):
                load_routing(reg)

    def test_load_normalizes_stored_extension(self):
        # Stored extensions are normalized on the read path just like on save.
        with tempfile.TemporaryDirectory() as tmp:
            reg = _reg(tmp)
            reg.routing = {"rules": [{"when": {"extension": [".TSX"]}}]}
            loaded = load_routing(reg)
            self.assertEqual(loaded["rules"][0]["when"]["extension"], ["tsx"])


class PlanRouteTests(unittest.TestCase):
    def test_single_option_no_op(self):
        res = plan_route(_catalog(), "weather", None, _routing(), None)
        self.assertTrue(res["single_option"])
        self.assertIsNotNone(res["chosen"])
        self.assertEqual(res["chosen"]["name"], "get_weather")
        self.assertEqual(len(res["candidates"]), 1)

    def test_auto_returns_top_pick(self):
        # priority_order keeps create_issue viable so both candidates survive.
        res = plan_route(
            _catalog(), "weather", None,
            _routing(priority_order=["create_issue"]), "auto",
        )
        self.assertEqual(res["mode"], "auto")
        self.assertFalse(res["single_option"])
        self.assertEqual(res["chosen"]["name"], "get_weather")
        self.assertEqual(len(res["candidates"]), 2)

    def test_ask_returns_ranked_list_with_chosen_none(self):
        res = plan_route(
            _catalog(), "weather", None,
            _routing(priority_order=["create_issue"]), "ask",
        )
        self.assertEqual(res["mode"], "ask")
        self.assertFalse(res["single_option"])
        self.assertIsNone(res["chosen"])
        self.assertEqual([c["name"] for c in res["candidates"]][0], "get_weather")
        self.assertEqual(len(res["candidates"]), 2)

    def test_mode_defaults_to_routing_mode(self):
        res = plan_route(
            _catalog(), "weather", None,
            _routing(mode="ask", priority_order=["create_issue"]), None,
        )
        self.assertEqual(res["mode"], "ask")
        self.assertIsNone(res["chosen"])

    def test_global_exclude_drops_candidate(self):
        res = plan_route(
            _catalog(), "weather", None,
            _routing(exclude=["get_weather"]), "auto",
        )
        names = [c["name"] for c in res["candidates"]]
        self.assertNotIn("get_weather", names)

    def test_priority_order_breaks_score_tie(self):
        # Two zero-text candidates at priority indices 2 and 3: equal boost (1),
        # so total scores tie and the priority position decides the order.
        catalog = [
            {"type": "tool", "name": "zebra", "description": "", "input_schema": {}},
            {"type": "tool", "name": "apple", "description": "", "input_schema": {}},
        ]
        res = plan_route(
            catalog, "no-text-match-here", None,
            _routing(priority_order=["p0", "p1", "zebra", "apple"]), "auto",
        )
        names = [c["name"] for c in res["candidates"]]
        self.assertEqual(res["candidates"][0]["score"], res["candidates"][1]["score"])
        # zebra (index 2) beats apple (index 3) despite sorting later by name.
        self.assertEqual(names, ["zebra", "apple"])

    def test_rule_prefer_boosts_via_extension(self):
        rule = {"when": {"extension": ["tsx"]}, "prefer": ["create_issue"]}
        res = plan_route(
            _catalog(), "", {"extension": "tsx"},
            _routing(rules=[rule]), "auto",
        )
        self.assertEqual(res["chosen"]["name"], "create_issue")
        self.assertTrue(any("prefer" in r for r in res["chosen"]["reasons"]))

    def test_rule_prefer_boosts_via_extension_variants(self):
        # One rule keyed on ["tsx"] must boost create_issue for each of the
        # natural caller inputs: dotless, dotted, wrong-case, and file_path.
        rule = {"when": {"extension": ["tsx"]}, "prefer": ["create_issue"]}
        for context in (
            {"extension": "tsx"},
            {"extension": ".tsx"},
            {"extension": "TSX"},
            {"file_path": "src/App.tsx"},
        ):
            with self.subTest(context=context):
                res = plan_route(
                    _catalog(), "", context,
                    _routing(rules=[rule]), "auto",
                )
                self.assertEqual(res["chosen"]["name"], "create_issue")
                self.assertTrue(any("prefer" in r for r in res["chosen"]["reasons"]))

    def test_context_none_returns_result_without_error(self):
        rule = {"when": {"extension": ["tsx"]}, "prefer": ["create_issue"]}
        res = plan_route(_catalog(), "weather", None, _routing(rules=[rule]), "auto")
        self.assertEqual(res["chosen"]["name"], "get_weather")

    def test_rule_prefer_boosts_via_path_glob(self):
        rule = {"when": {"path_glob": "src/*.tsx"}, "prefer": ["create_issue"]}
        res = plan_route(
            _catalog(), "", {"file_path": "src/App.tsx"},
            _routing(rules=[rule]), "auto",
        )
        self.assertEqual(res["chosen"]["name"], "create_issue")

    def test_rule_exclude_drops_candidate_on_match(self):
        rule = {"when": {"extension": ["tsx"]}, "exclude": ["get_weather"]}
        res = plan_route(
            _catalog(), "weather", {"extension": "tsx"},
            _routing(rules=[rule]), "auto",
        )
        names = [c["name"] for c in res["candidates"]]
        self.assertNotIn("get_weather", names)

    def test_context_none_degrades_to_config_only(self):
        rule = {"when": {"extension": ["tsx"]}, "prefer": ["create_issue"]}
        res = plan_route(
            _catalog(), "no-text-match", None,
            _routing(priority_order=["get_weather"], rules=[rule]), "auto",
        )
        names = [c["name"] for c in res["candidates"]]
        # priority_order still surfaces get_weather; the tsx rule is skipped.
        self.assertIn("get_weather", names)
        self.assertNotIn("create_issue", names)

    def test_empty_candidates_no_crash(self):
        res = plan_route(_catalog(), "zzz-nonexistent", None, _routing(), "auto")
        self.assertEqual(res["candidates"], [])
        self.assertIsNone(res["chosen"])
        self.assertFalse(res["single_option"])

    def test_deterministic(self):
        args = (_catalog(), "weather", {"extension": "tsx"},
                _routing(priority_order=["create_issue"]), "auto")
        self.assertEqual(plan_route(*args), plan_route(*args))

    def test_ask_truncates_to_top_five(self):
        catalog = [
            {"type": "tool", "name": f"t{i}", "description": "", "input_schema": {}}
            for i in range(6)
        ]
        res = plan_route(
            catalog, "no-text-match", None,
            _routing(mode="ask", priority_order=[f"t{i}" for i in range(6)]), None,
        )
        self.assertIsNone(res["chosen"])
        self.assertEqual(len(res["candidates"]), 5)

    def test_server_omitted_when_absent(self):
        catalog = [{"type": "skill", "name": "pdf", "description": "handle pdf", "input_schema": {}}]
        res = plan_route(catalog, "pdf", None, _routing(), "auto")
        self.assertNotIn("server", res["chosen"])


if __name__ == "__main__":
    unittest.main()
