"""The Cloudflare Tunnel runner: pure helpers only. Nothing is started and nothing touches the network."""

import os

os.environ["WALLETLEDGER_TESTING"] = "1"
os.environ["LITELLM_MODE"] = "PRODUCTION"
import importlib.util  # noqa: E402
import json  # noqa: E402
import unittest  # noqa: E402
from pathlib import Path  # noqa: E402
from unittest.mock import patch  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("tunnel", ROOT / "scripts" / "tunnel.py")
tunnel = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tunnel)


class TunnelHelperTests(unittest.TestCase):
    def test_address_is_found_in_cloudflared_output(self):
        log = (
            "2026-10-12T07:00:00Z INF Thank you for trying Cloudflare Tunnel.\n"
            "2026-10-12T07:00:01Z INF |  https://quiet-river-1234.trycloudflare.com  |\n"
        )
        found = [tunnel.parse_tunnel_url(line) for line in log.splitlines()]
        self.assertEqual(found, [None, "https://quiet-river-1234.trycloudflare.com"])

    def test_other_urls_are_not_mistaken_for_the_tunnel(self):
        for line in (
            "",
            "see https://www.cloudflare.com/docs",
            "https://api.trycloudflare.com/tunnel",
        ):
            self.assertIsNone(tunnel.parse_tunnel_url(line), line)

    def test_commands(self):
        self.assertEqual(
            tunnel.quick_command("cloudflared", 8000),
            ["cloudflared", "tunnel", "--no-autoupdate", "--url", "http://localhost:8000"],
        )
        self.assertEqual(
            tunnel.named_command("cloudflared"),
            ["cloudflared", "tunnel", "--no-autoupdate", "run"],
        )

    def test_server_environment(self):
        env = tunnel.server_env("https://a.trycloudflare.com/", webhook=False, base={"KEEP": "1"})
        self.assertEqual(env["PUBLIC_URL"], "https://a.trycloudflare.com")
        self.assertEqual(env["KEEP"], "1")
        self.assertNotIn("USE_WEBHOOK", env)

        hook = tunnel.server_env("https://a.trycloudflare.com", webhook=True, base={})
        self.assertEqual(hook["USE_WEBHOOK"], "true")
        self.assertEqual(hook["WEBHOOK_URL"], "https://a.trycloudflare.com/bot/webhook")

    def test_missing_cloudflared_gives_install_help_and_starts_nothing(self):
        with (
            patch.object(tunnel, "find_cloudflared", return_value=None),
            patch.object(tunnel.subprocess, "Popen") as popen,
        ):
            self.assertEqual(tunnel.main([]), 1)
        popen.assert_not_called()

    def test_named_mode_needs_a_token_and_an_https_address(self):
        with (
            patch.object(tunnel, "find_cloudflared", return_value="cloudflared"),
            patch.object(tunnel, "_dotenv_value", return_value=""),
            patch.dict(os.environ, {"CLOUDFLARE_TUNNEL_TOKEN": "", "PUBLIC_URL": ""}),
            patch.object(tunnel.subprocess, "Popen") as popen,
        ):
            self.assertEqual(tunnel.main(["--named"]), 1)
        popen.assert_not_called()


class CloudflareFilesTests(unittest.TestCase):
    def test_compose_has_optional_profiles_and_no_required_secret(self):
        text = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
        self.assertIn('profiles: ["app"]', text)
        self.assertIn('profiles: ["tunnel"]', text)
        self.assertNotIn(":?", text)  # a required variable would break plain `docker compose up`

    def test_worker_passes_secrets_through_and_never_embeds_them(self):
        js = (ROOT / "cloudflare" / "src" / "index.js").read_text(encoding="utf-8")
        for name in ("TELEGRAM_BOT_TOKEN", "SECRET_KEY", "DATABASE_URL"):
            self.assertIn(f'"{name}"', js)
        self.assertIn('USE_WEBHOOK: "true"', js)
        self.assertNotIn("AIza", js)

    def test_wrangler_config_points_at_the_dockerfile(self):
        text = (ROOT / "cloudflare" / "wrangler.jsonc").read_text(encoding="utf-8")
        body = "\n".join(line for line in text.splitlines() if not line.strip().startswith("//"))
        config = json.loads(body)
        self.assertEqual(config["containers"][0]["image"], "../Dockerfile")
        self.assertEqual(config["durable_objects"]["bindings"][0]["name"], "WALLETLEDGER")
        self.assertTrue((ROOT / "Dockerfile").exists())


if __name__ == "__main__":
    unittest.main()
