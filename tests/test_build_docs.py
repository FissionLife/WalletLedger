"""The docs become website pages: links, diagrams and the shared header. Offline."""

import os

os.environ["WALLETLEDGER_TESTING"] = "1"
os.environ["LITELLM_MODE"] = "PRODUCTION"
import importlib.util  # noqa: E402
import re  # noqa: E402
import tempfile  # noqa: E402
import unittest  # noqa: E402
from pathlib import Path  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("build_docs", ROOT / "scripts" / "build_docs.py")
build_docs = importlib.util.module_from_spec(spec)
spec.loader.exec_module(build_docs)

HAS_MARKDOWN = importlib.util.find_spec("markdown") is not None


class LinkTests(unittest.TestCase):
    def test_links_between_docs_stay_on_the_site(self):
        self.assertEqual(build_docs.rewrite_link("SECURITY.md"), "../security/")
        self.assertEqual(build_docs.rewrite_link("SECURITY.md#4-how"), "../security/#4-how")
        self.assertEqual(build_docs.rewrite_link("./DEMO.md"), "../demo/")

    def test_source_files_open_on_github(self):
        self.assertEqual(
            build_docs.rewrite_link("../app/crypto.py"),
            f"{build_docs.REPO}/blob/main/app/crypto.py",
        )
        self.assertEqual(
            build_docs.rewrite_link("../README.md"), f"{build_docs.REPO}/blob/main/README.md"
        )
        self.assertEqual(
            build_docs.rewrite_link("../cloudflare/"), f"{build_docs.REPO}/tree/main/cloudflare"
        )

    def test_outside_links_and_anchors_are_untouched(self):
        for href in ("https://example.com/x", "#section", "mailto:a@b.c"):
            self.assertEqual(build_docs.rewrite_link(href), href)

    def test_the_sites_own_address_becomes_relative(self):
        self.assertEqual(
            build_docs.rewrite_link("https://fissionlife.github.io/WalletLedger/explore/"),
            "../../explore/",
        )


@unittest.skipUnless(HAS_MARKDOWN, "the markdown package is a dev dependency: run uv sync")
class BuildTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.out = Path(tempfile.mkdtemp(prefix="walletledger-docs-test-"))
        cls.written = build_docs.build(cls.out)

    def read(self, slug):
        return (self.out / slug / "index.html").read_text(encoding="utf-8")

    def test_every_listed_doc_became_a_page_and_there_is_an_index(self):
        self.assertEqual(set(self.written), {slug for _, slug, _, _ in build_docs.PAGES})
        index = (self.out / "index.html").read_text(encoding="utf-8")
        for _, slug, title, _ in build_docs.PAGES:
            self.assertIn(f'href="{slug}/"', index)
            self.assertIn(title, index)

    def test_diagrams_are_drawn_in_the_browser(self):
        page = self.read("architecture")
        self.assertIn('<pre class="mermaid">', page)
        self.assertNotIn("language-mermaid", page)
        self.assertIn("mermaid.esm.min.mjs", page)
        self.assertNotIn("mermaid.esm.min.mjs", self.read("deployment"))  # only where needed

    def test_no_link_points_at_a_raw_markdown_file_on_the_site(self):
        for slug in self.written:
            for href in re.findall(r'href="([^"]+)"', self.read(slug)):
                if href.startswith(("http", "#", "../")):
                    self.assertFalse(
                        re.search(r"\.md(#|$)", href) and not href.startswith("http"), (slug, href)
                    )

    def test_shared_header_and_theme_setting(self):
        page = self.read("guide")
        for needle in ('href="../../"', 'href="../../explore/"', 'href="../../docs/"', "wl-theme"):
            self.assertIn(needle, page)
        self.assertIn('aria-current="page"', page)

    def test_tables_scroll_on_phones(self):
        self.assertIn('<div class="table-wrap"><table>', self.read("code-map"))


class SiteIntegrationTests(unittest.TestCase):
    def test_landing_and_explorer_link_to_each_other_and_the_docs(self):
        landing = (ROOT / "site" / "index.html").read_text(encoding="utf-8")
        explorer = (ROOT / "site" / "explore" / "index.html").read_text(encoding="utf-8")
        self.assertIn('href="explore/"', landing)
        self.assertIn('href="docs/"', landing)
        self.assertIn('href="../docs/"', explorer)
        self.assertIn('href="../"', explorer)

    def test_the_pages_workflow_builds_the_docs(self):
        text = (ROOT / ".github" / "workflows" / "pages.yml").read_text(encoding="utf-8")
        self.assertIn("scripts/build_docs.py", text)
        self.assertIn('"docs/**"', text)


if __name__ == "__main__":
    unittest.main()
