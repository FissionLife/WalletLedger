"""The project map (scripts/build_map.py) knows every file. Offline, reads files only."""

import os

os.environ["WALLETLEDGER_TESTING"] = "1"
os.environ["LITELLM_MODE"] = "PRODUCTION"
import importlib.util  # noqa: E402
import json  # noqa: E402
import unittest  # noqa: E402
from pathlib import Path  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("build_map", ROOT / "scripts" / "build_map.py")
build_map = importlib.util.module_from_spec(spec)
spec.loader.exec_module(build_map)


class ProjectMapTests(unittest.TestCase):
    def test_every_file_has_a_plain_language_note(self):
        _, missing = build_map.build()
        self.assertEqual(
            missing,
            [],
            "Add a line to NOTES in scripts/build_map.py, then run it to refresh the map.",
        )

    def test_map_is_consistent(self):
        data, _ = build_map.build()
        paths = {f["path"] for f in data["files"]}
        layers = {layer["id"] for layer in data["layers"]}
        for f in data["files"]:
            self.assertIn(f["layer"], layers)
            self.assertTrue(f["note"].strip())
            for other in f["uses"] + f["used_by"]:
                self.assertIn(other, paths)
        for tour in data["tours"]:
            self.assertGreaterEqual(len(tour["steps"]), 4, tour["title"])
        self.assertIn("/stats", {c["command"] for c in data["commands"]})

    def test_committed_outputs_exist_and_are_valid(self):
        self.assertTrue(build_map.JSON_OUT.exists(), "run: uv run python scripts/build_map.py")
        committed = json.loads(build_map.JSON_OUT.read_text(encoding="utf-8"))
        self.assertGreater(len(committed["files"]), 40)
        html = build_map.HTML_OUT.read_text(encoding="utf-8")
        self.assertNotIn("/*__DATA__*/", html)
        self.assertNotIn("__SCRIPT__", html)
        self.assertIn("WalletLedger", html)

    def test_no_secrets_in_the_map(self):
        text = build_map.JSON_OUT.read_text(encoding="utf-8")
        for needle in ("AIzaSy", "AQ.Ab", "sk-ant-api", "gsk_" + "a", "SECRET_KEY="):
            self.assertNotIn(needle, text)


if __name__ == "__main__":
    unittest.main()
