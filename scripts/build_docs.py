#!/usr/bin/env python3
"""Turn the Markdown docs into pages of the website, so the site and the docs are one place.

    uv run python scripts/build_docs.py              # writes site/docs/  (not committed; CI builds it)

The landing page (site/), the code explorer (site/explore/) and these pages share one header, one set of
colours and one light/dark setting. Diagrams (```mermaid blocks) are drawn in the browser.
Needs the `markdown` package (a dev dependency: `uv sync`).
"""

from __future__ import annotations

import html
import re
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DOCS = ROOT / "docs"
OUT = ROOT / "site" / "docs"
TEMPLATE = Path(__file__).with_name("docs_template.html")
REPO = "https://github.com/FissionLife/WalletLedger"

# (file stem, slug, title, one line). The order here is the order in the menu.
PAGES = [
    (
        "PROJECT_GUIDE",
        "guide",
        "Project guide",
        "What is where, and how each part works. Start here.",
    ),
    ("HOW_IT_WORKS", "how-it-works", "How it works", "The five-minute story, in plain words."),
    (
        "ARCHITECTURE",
        "architecture",
        "Architecture",
        "Diagrams: the system, a message, the agent, the data, the dashboard.",
    ),
    (
        "SECURITY",
        "security",
        "Security and data",
        "What is stored where, who can read it, how encryption works.",
    ),
    (
        "DEPLOYMENT",
        "deployment",
        "Deployment",
        "Run it on your computer, a server, Docker or a serverless host.",
    ),
    (
        "CLOUDFLARE",
        "cloudflare",
        "Cloudflare",
        "Tunnel for the dashboard, Containers for hosting, and why not plain Workers.",
    ),
    ("DEMO", "demo", "Demo script", "An eight-minute live demo, step by step."),
    (
        "EVALUATION",
        "evaluation",
        "Evaluation",
        "How well the AI agent works: method, the 50-case dataset, metrics and results.",
    ),
    (
        "TOOL_MODE",
        "tool-mode",
        "Tool mode",
        "Calling ledger tools directly or through the MCP server.",
    ),
    ("DOCUMENTATION", "code-map", "Code map", "A table of every file and the endpoints."),
]
BY_STEM = {stem: slug for stem, slug, _, _ in PAGES}

_LINK = re.compile(r'href="([^"]+)"')
_MERMAID = re.compile(r'<pre><code class="language-mermaid">(.*?)</code></pre>', re.S)


def rewrite_link(href: str, doc_dir: str = "docs") -> str:
    """Links between docs become site links; links to source files become GitHub links."""
    site = "https://fissionlife.github.io/WalletLedger/"
    if href.startswith(site):  # our own site: link relatively so it works on any host
        return "../../" + href[len(site) :]
    if re.match(r"^(https?:|mailto:|#)", href):
        return href
    path, _, frag = href.partition("#")
    suffix = f"#{frag}" if frag else ""
    name = Path(path).name
    stem = name[:-3] if name.endswith(".md") else None
    if stem in BY_STEM and (path == name or path.startswith("./")):
        return f"../{BY_STEM[stem]}/{suffix}"
    # anything else in the repo: show it on GitHub (resolve ../ from docs/)
    parts: list[str] = [doc_dir] if doc_dir else []
    for piece in path.split("/"):
        if piece in ("", "."):
            continue
        if piece == "..":
            if parts:
                parts.pop()
        else:
            parts.append(piece)
    target = "/".join(parts)
    kind = "tree" if not Path(target).suffix else "blob"
    return f"{REPO}/{kind}/main/{target}{suffix}"


def render_markdown(text: str) -> tuple[str, bool]:
    import markdown

    body = markdown.markdown(
        text, extensions=["fenced_code", "tables", "toc", "sane_lists"], output_format="html"
    )
    has_diagram = bool(_MERMAID.search(body))
    body = _MERMAID.sub(lambda m: f'<pre class="mermaid">{m.group(1)}</pre>', body)
    body = _LINK.sub(
        lambda m: f'href="{html.escape(rewrite_link(html.unescape(m.group(1))), quote=True)}"', body
    )
    # tables scroll sideways on phones instead of breaking the page
    body = body.replace("<table>", '<div class="table-wrap"><table>').replace(
        "</table>", "</table></div>"
    )
    return body, has_diagram


def page(
    template: str, *, root: str, title: str, body: str, nav: str, diagram: bool, source: str
) -> str:
    script = ""
    if diagram:
        script = (
            '<script type="module">\n'
            'import mermaid from "https://cdn.jsdelivr.net/npm/mermaid@11.4.0/dist/mermaid.esm.min.mjs";\n'
            "const dark = (document.documentElement.dataset.theme || "
            '(matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light")) === "dark";\n'
            'mermaid.initialize({ startOnLoad: true, theme: dark ? "dark" : "neutral", securityLevel: "strict" });\n'
            "</script>"
        )
    return (
        template.replace("{{ROOT}}", root)
        .replace("{{TITLE}}", html.escape(title))
        .replace("{{NAV}}", nav)
        .replace("{{BODY}}", body)
        .replace("{{SCRIPT}}", script)
        .replace("{{SOURCE}}", source)
        .replace("{{HAS_DIAGRAM}}", "true" if diagram else "false")
    )


def nav_html(current: str | None, root: str) -> str:
    items = []
    for _, slug, title, _ in PAGES:
        cls = ' aria-current="page"' if slug == current else ""
        items.append(f'<li><a href="{root}{slug}/"{cls}>{html.escape(title)}</a></li>')
    return "\n".join(items)


def build(out: Path = OUT) -> list[str]:
    template = TEMPLATE.read_text(encoding="utf-8").replace("\r\n", "\n")
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)
    written = []
    for stem, slug, title, _ in PAGES:
        src = DOCS / f"{stem}.md"
        if not src.exists():
            continue
        body, diagram = render_markdown(src.read_text(encoding="utf-8").replace("\r\n", "\n"))
        target = out / slug / "index.html"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            page(
                template,
                root="../../",
                title=title,
                body=body,
                nav=nav_html(slug, "../"),
                diagram=diagram,
                source=f"{REPO}/blob/main/docs/{stem}.md",
            ),
            encoding="utf-8",
            newline="\n",
        )
        written.append(slug)
    cards = "\n".join(
        f'<a class="doc-card" href="{slug}/"><b>{html.escape(title)}</b><span>{html.escape(line)}</span></a>'
        for _, slug, title, line in PAGES
        if slug in written
    )
    index_body = (
        "<h1>Documentation</h1>"
        "<p>Everything about WalletLedger in one place. New here? Start with the "
        '<a href="guide/">project guide</a>, or <a href="../explore/">explore the code</a> interactively.</p>'
        f'<div class="doc-cards">{cards}</div>'
    )
    (out / "index.html").write_text(
        page(
            template,
            root="../",
            title="Documentation",
            body=index_body,
            nav=nav_html(None, ""),
            diagram=False,
            source=f"{REPO}/tree/main/docs",
        ),
        encoding="utf-8",
        newline="\n",
    )
    return written


def main() -> int:
    try:
        written = build()
    except ModuleNotFoundError:
        print(
            "The `markdown` package is missing. Run: uv sync   (or: uv run --with markdown python scripts/build_docs.py)"
        )
        return 1
    print(f"Wrote {len(written)} doc pages and an index to {OUT.relative_to(ROOT)}/")
    return 0


if __name__ == "__main__":
    sys.exit(main())
