#!/usr/bin/env python3
"""Run WalletLedger behind a Cloudflare Tunnel: one command, and /dashboard opens inside Telegram.

    uv run python scripts/tunnel.py                 # quick tunnel: free, no account, random https address
    uv run python scripts/tunnel.py --webhook       # also let Telegram push messages through the tunnel
    uv run python scripts/tunnel.py --port 8001
    uv run python scripts/tunnel.py --named         # your own tunnel and domain (see docs/CLOUDFLARE.md)

What it does: starts `cloudflared`, waits for the public https address it prints, then starts the server
with PUBLIC_URL set to that address (an environment variable beats `.env`, so `.env` is never edited).
Press Ctrl+C once to stop both.

Needs the `cloudflared` program (not a Python package):
    Windows: winget install Cloudflare.cloudflared      macOS: brew install cloudflared
    Linux:   https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/downloads/

A quick tunnel gets a NEW address every run, so dashboard links from an earlier run stop working.
That is fine for demos. For an address that never changes, use --named.
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
# "api." is cloudflared talking to Cloudflare, not your tunnel's address
QUICK_URL = re.compile(r"https://(?!api\.)[a-z0-9-]+\.trycloudflare\.com")
WAIT_SECONDS = 45

INSTALL_HINT = (
    "cloudflared is not installed (it is a separate program).\n"
    "  Windows: winget install Cloudflare.cloudflared\n"
    "  macOS:   brew install cloudflared\n"
    "  Linux:   https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/downloads/"
)


def find_cloudflared() -> str | None:
    return shutil.which("cloudflared")


def parse_tunnel_url(line: str) -> str | None:
    """The https address in a line of cloudflared output, or None."""
    match = QUICK_URL.search(line or "")
    return match.group(0) if match else None


def quick_command(binary: str, port: int) -> list[str]:
    return [binary, "tunnel", "--no-autoupdate", "--url", f"http://localhost:{port}"]


def named_command(binary: str) -> list[str]:
    # the token goes in the TUNNEL_TOKEN environment variable, not on the command line (any program can read that)
    return [binary, "tunnel", "--no-autoupdate", "run"]


def server_env(
    public_url: str, *, webhook: bool, base: dict[str, str] | None = None
) -> dict[str, str]:
    """Environment for the server: PUBLIC_URL, and optionally webhook mode through the same address."""
    env = dict(os.environ if base is None else base)
    env["PUBLIC_URL"] = public_url.rstrip("/")
    if webhook:
        env["USE_WEBHOOK"] = "true"
        env["WEBHOOK_URL"] = env["PUBLIC_URL"] + "/bot/webhook"
    return env


def _dotenv_value(name: str) -> str:
    """One value from .env, read with the project's own parser (never printed)."""
    sys.path.insert(0, str(ROOT))
    from app.envfile import read_env

    path = ROOT / ".env"
    return read_env(path).get(name, "") if path.exists() else ""


def _watch(process: subprocess.Popen, found: list[str], done: threading.Event) -> None:
    """Read cloudflared's log; remember the first address; keep draining so the pipe never fills."""
    assert process.stderr is not None
    for line in process.stderr:
        if not found:
            url = parse_tunnel_url(line)
            if url:
                found.append(url)
                done.set()
    done.set()


def _stop(*processes: subprocess.Popen | None) -> None:
    for p in processes:
        if p and p.poll() is None:
            p.terminate()
    deadline = time.time() + 8
    for p in processes:
        if p:
            try:
                p.wait(timeout=max(0.1, deadline - time.time()))
            except subprocess.TimeoutExpired:
                p.kill()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument("--port", type=int, default=8000, help="port for the server (default 8000)")
    parser.add_argument(
        "--webhook", action="store_true", help="Telegram pushes messages through the tunnel"
    )
    parser.add_argument(
        "--named",
        action="store_true",
        help="use your own tunnel (CLOUDFLARE_TUNNEL_TOKEN + PUBLIC_URL)",
    )
    args = parser.parse_args(argv)

    token = ""
    binary = find_cloudflared()
    if not binary:
        print(INSTALL_HINT)
        return 1

    if args.named:
        token = os.environ.get("CLOUDFLARE_TUNNEL_TOKEN") or _dotenv_value(
            "CLOUDFLARE_TUNNEL_TOKEN"
        )
        public_url = os.environ.get("PUBLIC_URL") or _dotenv_value("PUBLIC_URL")
        if not token or not public_url.startswith("https://"):
            print(
                "--named needs CLOUDFLARE_TUNNEL_TOKEN and an https PUBLIC_URL (in .env or the environment)."
            )
            print("How to get them: docs/CLOUDFLARE.md, 'Your own tunnel'.")
            return 1
        command = named_command(binary)
    else:
        public_url = ""
        command = quick_command(binary, args.port)

    found: list[str] = []
    done = threading.Event()
    tunnel_env = {**os.environ, "TUNNEL_TOKEN": token} if args.named else None
    tunnel = subprocess.Popen(
        command, stderr=subprocess.PIPE, stdout=subprocess.DEVNULL, text=True, env=tunnel_env
    )
    server: subprocess.Popen | None = None
    try:
        if args.named:
            time.sleep(3)  # nothing to parse: the address is the one you configured
        else:
            threading.Thread(target=_watch, args=(tunnel, found, done), daemon=True).start()
            print("Starting the tunnel ...")
            if not done.wait(WAIT_SECONDS) or not found:
                print(
                    f"No tunnel address after {WAIT_SECONDS}s. Is this computer online? Try again."
                )
                return 1
            public_url = found[0]
        if tunnel.poll() is not None:
            print(
                "cloudflared stopped right away; run it by hand to see why: "
                + " ".join(command[:3])
            )
            return 1

        print(f"\nPublic address: {public_url}")
        print("In Telegram, send /dashboard: it now opens inside the app.")
        if args.webhook:
            print("Webhook mode: Telegram delivers messages through this address.")
        print("Press Ctrl+C to stop.\n")

        env = server_env(public_url, webhook=args.webhook)
        server = subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "main:app", "--port", str(args.port)],
            cwd=ROOT,
            env=env,
        )
        while server.poll() is None and tunnel.poll() is None:
            time.sleep(0.5)
        if (
            server.poll() is None
        ):  # the tunnel died but the server is still running: say so and stop
            print(
                "\nThe tunnel stopped, so the public address no longer works. Stopping the server too."
            )
            return 1
        return server.returncode or 0
    except KeyboardInterrupt:
        print("\nStopping ...")
        return 0
    finally:
        _stop(server, tunnel)


if __name__ == "__main__":
    sys.exit(main())
