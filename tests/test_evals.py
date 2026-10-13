"""The agent evaluation: scoring rules and a small rules-tier run of the real router (no AI)."""

import os

os.environ["WALLETLEDGER_TESTING"] = "1"  # never read the real .env in tests
os.environ["LITELLM_MODE"] = "PRODUCTION"  # litellm would otherwise load .env (real keys!)
import json  # noqa: E402
import subprocess  # noqa: E402
import sys  # noqa: E402
import tempfile  # noqa: E402
import unittest  # noqa: E402
from datetime import date  # noqa: E402
from pathlib import Path  # noqa: E402

from evals import scoring  # noqa: E402
from evals.run_eval import scrub  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
TODAY = date(2026, 10, 12)


class ScoringTests(unittest.TestCase):
    def test_compare_value_rules(self):
        cv = scoring.compare_value
        self.assertTrue(cv(200, 200.004))
        self.assertFalse(cv(200, 201))
        self.assertTrue(cv("food & dining", " Food & Dining "))
        self.assertTrue(cv(["Cash", "Bank"], "bank"))
        self.assertTrue(cv("$TODAY-1", "2026-10-11T09:00:00", TODAY))
        self.assertTrue(cv(None, None))
        self.assertFalse(cv(None, "x"))

    def test_score_turn_flags_wrong_tool_arg_and_ledger(self):
        expect = {
            "calls": [
                {"tool": "log_expense", "args": {"amount": 200, "category": "Food & Dining"}}
            ],
            "needs_confirmation": False,
            "ledger_after": {"balances": {"Cash": 800}, "new_transactions": 1},
            "reply": {"must_not_include": ["Traceback"]},
        }
        good = {
            "calls": [
                {"tool": "log_expense", "args": {"amount": 200, "category": "Food & Dining"}}
            ],
            "needs_confirmation": False,
            "balances": {"Cash": 800.0},
            "new_transactions": 1,
            "reply_text": "ok",
        }
        self.assertTrue(all(c["ok"] for c in scoring.score_turn(expect, good)))
        bad = {**good, "calls": [{"tool": "log_income", "args": {"amount": 200}}], "balances": {}}
        failed = {c["check"] for c in scoring.score_turn(expect, bad) if not c["ok"]}
        self.assertIn("calls", failed)
        self.assertIn("balance:Cash", failed)

    def test_numbers_must_come_from_tools(self):
        expect = {"reply": {"numbers_from_tools": True}}
        observed = {"reply_text": "You spent ₹4,500 of ₹6,000.", "calls": [{"result": {"spent": 4500}}],
                    "balances": {"Bank": 6000}}  # fmt: skip
        self.assertTrue(all(c["ok"] for c in scoring.score_turn(expect, observed)))
        observed["reply_text"] = "You spent ₹9,999."
        self.assertFalse(all(c["ok"] for c in scoring.score_turn(expect, observed)))

    def test_sums_of_real_figures_are_grounded_but_guesses_are_not(self):
        observed = {"calls": [{"result": {"food": 920, "fun": 649, "rent": 15000}}],
                    "reply_text": "Food and fun cost ₹1,569; cut ~₹400."}  # fmt: skip
        self.assertEqual(scoring.unsupported_figures(observed), [400.0])

    def test_metrics_and_not_run(self):
        case = {"id": "X", "tier": "llm", "group": "llm_goal", "max_provider_requests": 2,
                "turns": [{"user": "q", "expect": {"ledger_after": {"new_transactions": 0}}}]}  # fmt: skip
        run = scoring.score_case(case, [{"new_transactions": 0, "provider_requests": 3}])
        self.assertFalse(run["passed"])  # over the request budget
        results = [scoring.case_result(case, [run]), scoring.case_result({**case, "id": "Y"}, None)]
        m = scoring.metrics(results)
        self.assertEqual((m["cases_run"], m["not_run"]), (1, 1))
        self.assertEqual(m["question_never_logged"], 1.0)
        self.assertIn("Not run", scoring.render_markdown(m, results, {"tier": "llm"}))

    def test_scrub_removes_keys(self):
        key = "AIza" + "x" * 35
        self.assertEqual(scrub({"a": f"key {key}", "api_key": key}), {"a": "key [KEY]"})


class GoldenFileTests(unittest.TestCase):
    def test_golden_dataset_shape(self):
        cases = [
            json.loads(line) for line in (ROOT / "evals" / "golden.jsonl").open(encoding="utf-8")
        ]
        self.assertEqual(len(cases), 50)
        self.assertEqual(len({c["id"] for c in cases}), 50)
        self.assertEqual(sum(c["tier"] == "rules" for c in cases), 34)
        for c in cases:
            self.assertTrue(c["turns"], c["id"])


class RulesRunTests(unittest.TestCase):
    def test_runner_end_to_end_on_three_cases(self):
        work = Path(tempfile.mkdtemp(prefix="walletledger-evaltest-"))
        golden = work / "g.jsonl"
        cases = [
            {"id": "T-1", "tier": "rules", "group": "expense", "seed": {"accounts": {"Cash": 1000}},
             "turns": [{"user": "spent 200 on chai from cash", "expect": {
                 "path": "rules", "calls": [{"tool": "log_expense", "args": {"amount": 200}}],
                 "ledger_after": {"balances": {"Cash": 800}, "new_transactions": 1}}}]},
            {"id": "T-2", "tier": "rules", "group": "transfer",
             "seed": {"accounts": {"Bank": 20000, "Cash": 0}},
             "turns": [{"user": "transfer 6000 from bank to cash",
                        "expect": {"needs_confirmation": True, "calls": [],
                                   "ledger_after": {"new_transactions": 0}}},
                       {"user": "yes", "expect": {"path": "confirmation",
                        "ledger_after": {"balances": {"Bank": 14000, "Cash": 6000}}}}]},
            {"id": "T-3", "tier": "rules", "group": "question", "seed": {},
             "turns": [{"user": "did I spend 500 on food?",
                        "expect": {"ledger_after": {"new_transactions": 0}}}]},
        ]  # fmt: skip
        golden.write_text("\n".join(json.dumps(c) for c in cases), encoding="utf-8")
        env = {k: v for k, v in os.environ.items() if k != "DATABASE_URL"}
        out = subprocess.run(
            [sys.executable, "-W", "ignore", "-m", "evals.run_eval", "--tier", "rules",
             "--golden", str(golden), "--out", str(work / "out")],
            cwd=ROOT, env=env, capture_output=True, text=True, encoding="utf-8", timeout=300,
        )  # fmt: skip
        self.assertEqual(out.returncode, 0, out.stdout + out.stderr)
        report = json.loads((work / "out" / "latest-rules-direct.json").read_text(encoding="utf-8"))
        self.assertEqual(report["metrics"]["cases_passed"], 3, out.stdout)
        self.assertEqual(report["meta"]["real_provider_requests"], 0)


if __name__ == "__main__":
    unittest.main()
