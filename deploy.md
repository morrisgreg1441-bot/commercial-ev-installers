# Deploy — the one credential-gated step

Everything else is autonomous. Hosting is account-bound: a site can't be "live"
without **your** login on a host. This is that step, made as short as possible.
Pick **one** path. Recommended: **A (Cloudflare Pages)** — serves at a domain
root (the site uses root-absolute paths), free, auto-deploys on every push.

The autonomous weekly refresh (`.github/workflows/refresh.yml`) already re-scrapes,
validates, rebuilds and commits. Any host wired to the repo redeploys on that
commit automatically. So after this one-time setup, it self-updates forever.

---

## Path A — Cloudflare Pages (recommended)

1. Push this repo to GitHub (one-time):
   ```
   gh repo create commercial-ev-installers --public --source=. --push
   ```
   (or create the repo in the GitHub UI and `git push`).
2. Cloudflare dashboard → **Workers & Pages → Create → Pages → Connect to Git** →
   pick the repo.
3. Build settings: **Framework preset: None**. **Build command:**
   `pip install -r requirements.txt && python site/generate.py`.
   **Build output directory:** `site/dist`.
   **Environment variable:** `SITE_BASE_URL = https://<your-project>.pages.dev`
   (set it to your final URL/custom domain so canonical tags + sitemap are right).
4. Deploy. Every future push (including the weekly auto-refresh commit) redeploys
   with zero further action.

## Path B — GitHub Pages (no Cloudflare account)

1. Push to GitHub (as above).
2. Repo → **Settings → Pages → Source: GitHub Actions**.
3. The included workflow already builds and deploys via `actions/deploy-pages`.
   **Important:** GitHub *project* Pages serve under `/<repo>/`, which breaks the
   site's root-absolute links. So either:
   - use a **custom domain** (Settings → Pages → Custom domain), or
   - use a **user/org site** repo named `<you>.github.io`.
   Set repo Actions variable `SITE_BASE_URL` to the final URL either way.

## Path C — instant manual (no auto-deploy, for a quick look)

```
npx --yes wrangler pages deploy site/dist --project-name commercial-ev-installers
```
First run does an interactive Cloudflare login. Re-run after each rebuild
(no auto-refresh wiring — Path A/B are better for the passive goal).

---

## After deploy — 3 small edits (see MONETIZATION.md for detail)

1. Set `SITE_BASE_URL` to the real URL (above) so SEO canonicals are correct.
2. Replace the contact email: set `SITE_CONTACT_EMAIL` env var (or edit the
   `/contact/` placeholder) — a free forwarding address is fine.
3. Submit the live URL + `/sitemap.xml` to **Google Search Console**. This starts
   the SEO clock (Gate 1). Nothing earns until pages index — expect weeks.

## Local fallback refresh (only if NOT using GitHub Actions)

Windows Task Scheduler → weekly task → action:
`powershell -ExecutionPolicy Bypass -File C:\Users\greg\Desktop\ev-directory\refresh.ps1`
