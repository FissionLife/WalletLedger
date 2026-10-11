# WalletLedger landing page

A plain static site: `index.html`, `styles.css`, `app.js` and `favicon.svg`. There is no build step,
no framework and no npm. Open `index.html` in a browser, or serve the folder:

```bash
cd site
python -m http.server 8080      # then open http://localhost:8080
```

## How to edit

| What | Where |
|---|---|
| Telegram bot link, GitHub repo link | the `SITE` object at the top of `app.js` (one place) |
| Text and sections | `index.html` (each section has a comment header) |
| Colours, spacing, fonts | the variables at the top of `styles.css` |

The links in `index.html` also have the URLs written in their `href`, only as a fallback for visitors
with JavaScript turned off. If you change a URL, a find-and-replace in `index.html` keeps the fallback
in step.

The look is Material Design 3 (neutral white/grey surfaces, soft shadows, rounded cards, pill
buttons, chips, a segmented button) with Cloudflare Kumo's blue as the only accent. The colour
tokens (light and dark) are listed at the very top of `styles.css`; reuse them verbatim in the
dashboard and charts. The page opens in light mode; the moon/sun button switches to a neutral dark
grey theme and remembers the choice in the browser. Never use navy or blue-tinted backgrounds:
blue is only for buttons, links, icons and small highlights.

Keep it honest: only describe features the bot actually has (see the main `README.md`).

## Publishing on GitHub Pages

The workflow `.github/workflows/pages.yml` publishes this folder whenever something in `site/`
changes on `main` (or when you run it by hand from the Actions tab).

One-time setup in the GitHub repository: **Settings > Pages > Build and deployment > Source:
GitHub Actions**. After the first run the site is at
`https://<owner>.github.io/<repo>/` (for this repo: `https://fissionlife.github.io/WalletLedger/`).

`.nojekyll` tells GitHub not to run Jekyll if the folder is ever published from a branch instead of
the workflow. With the workflow it is not needed, but it does no harm.
