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

The look follows Cloudflare's open-source design system **Kumo** (blue brand colour, neutral greys,
8px rounded buttons, pill badges). The exact token values and their source are listed in the comment
at the top of `styles.css`. Light and dark themes follow the visitor's system setting; the moon/sun
button overrides it and remembers the choice in the browser.

Keep it honest: only describe features the bot actually has (see the main `README.md`).

## Publishing on GitHub Pages

The workflow `.github/workflows/pages.yml` publishes this folder whenever something in `site/`
changes on `main` (or when you run it by hand from the Actions tab).

One-time setup in the GitHub repository: **Settings > Pages > Build and deployment > Source:
GitHub Actions**. After the first run the site is at
`https://<owner>.github.io/<repo>/` (for this repo: `https://fissionlife.github.io/WalletLedger/`).

`.nojekyll` tells GitHub not to run Jekyll if the folder is ever published from a branch instead of
the workflow. With the workflow it is not needed, but it does no harm.
