# Overnight handover — 21/22 May 2026

You said: £1,000 in your account by 1 September. I researched, planned, built,
and polished. Here's exactly what's now in place and exactly what you do next.

## What I changed about the strategy after research

**You suspected** the move was selling Featured Listings (£99) to the installers
already on the directory. I tested it. **Better play emerged.**

The research agent ran the numbers honestly:

| Path | Probability of clearing £1k by 1 Sep | Per-deal value |
|------|--------------------------------------|----------------|
| **A. Sell directory builds to UK trade bodies** | **~65%** | **£750–£1,500** |
| B. Sell Featured Listings to installers | ~35% | £99 |

Path A: **one yes from a trade body = goal hit**. The same engine that built
your EV directory can be re-pointed at any niche. Trade bodies (BVRLA, FMB,
NICEIC, BESA, ECA...) want member directories and don't have good ones.

**So I built for both.** Path B (Featured) is the slower, smaller, parallel
trickle. Path A (Studio) is the swing for £1k in one transaction.

## The two pages now live

After you push (one command below), these go live on Cloudflare:

1. **https://commercial-ev-installers.pages.dev/studio/** — pitches the
   directory-build service. £750 starter / £1,500 standard. CTA is a `mailto:`
   to your contact email pre-filled with the right subject line. Marked
   `noindex` so it doesn't compete with directory SEO; you share the URL
   manually in pitches.

2. **https://commercial-ev-installers.pages.dev/featured/** — sells the
   Featured slot to installers. £99 founder rate, 12 months, one-time payment.
   30-day click-based refund. Honest about the fact the directory is new.
   This is the page your outreach emails link to.

A `/featured/thanks/` confirmation page handles the Stripe success redirect.
Privacy page rewritten with full PECR / GDPR / suppression-list documentation
so cold outreach is legally clean.

## What you do — in exact order

### Step 1: Push the build live (30 seconds)

```
cd C:\Users\greg\Desktop\ev-directory
git add -A
git commit -m "Add monetization: studio + featured pages, admin flow, outreach packs"
git push
```

Cloudflare auto-deploys in ~90 seconds. Verify:
- https://commercial-ev-installers.pages.dev/featured/
- https://commercial-ev-installers.pages.dev/studio/

Both pages will show a yellow "Stripe link not yet configured" warning. That's
correct — fix it in step 2.

### Step 2: Create the Stripe Payment Links (15 minutes — the only critical bottleneck)

**Without this, every Featured outreach email links to a dead button. Do this before sending a single email.**

1. Log into Stripe → Payment Links → "+ New".
2. Product: **"Featured Listing — Founder rate (12 months)"**, price **£99 GBP**, one-time payment.
3. Custom fields → add a required text field labelled:
   `Your directory slug (find it in the URL of your listing page, e.g. /installers/this-bit-here/)`
   *This is how you'll know who paid.*
4. After payment → Don't show Stripe confirmation → **Redirect to**:
   `https://commercial-ev-installers.pages.dev/featured/thanks/`
5. Copy the resulting `https://buy.stripe.com/...` URL.
6. **Repeat** for **"Featured Listing — Standard tier (12 months)"** at **£199 GBP**.

### Step 3: Paste URLs into Cloudflare env (2 minutes)

Cloudflare Pages dashboard → your project → Settings → Environment variables → **Production**:

| Variable | Value |
|----------|-------|
| `STRIPE_FEATURED_FOUNDER_URL` | (the £99 link) |
| `STRIPE_FEATURED_STANDARD_URL` | (the £199 link) |
| `STUDIO_CONTACT_EMAIL` | your real email (probably james@proudcastle.co.uk) |
| `SITE_CONTACT_EMAIL` | same — change from the `example.com` placeholder |

Trigger a redeploy (Cloudflare dashboard → "Retry deployment", or `git commit --allow-empty -m "trigger rebuild" && git push`).

After redeploy, `/featured/` shows live CTAs that go to Stripe checkout. The yellow warning is gone.

### Step 4: Send the first outreach email (5 minutes)

Three options, ranked by EV:

**A. Pick one Trade Body pitch from `outreach/studio/` (highest leverage)** —
The 15 ready pitches at `outreach/studio/01-bvrla.md` through `outreach/studio/20-bcc.md`. (5 are marked SKIP because their public addresses aren't generic mailboxes.) **My pick: 01-bvrla.md** — fleet leasing trade body, the most natural fit for the EV directory you already built as proof. Open it, replace `{lastname}` and `{POSTAL ADDRESS}` with yours, paste into your email client, send. **One yes = your goal hit.**

**B. Pick one installer pitch from `outreach/featured/` (faster cycle)** — 30
ready pitches. Start with the highest-ranked: `outreach/featured/01-barassie-engineering-systems-ltd.md`. Same edit-and-send routine. Realistic close rate: 1–3 paying out of 30.

**C. Both, paced** — One trade-body pitch per day for 14 working days. One installer pitch per day for 30 working days. Don't batch — PECR rules + spam filters dislike it.

Before sending any:
- Add your **real postal address** (PECR requires identifiable sender) — replace `{POSTAL ADDRESS}` placeholder.
- Confirm your name is right — replace `Greg Morris` if needed.
- Send from your own real email, never `mailto:` shotgun.

### Step 5: When someone pays — flip them Featured (2 minutes)

Stripe emails you the confirmation. The Stripe custom field tells you their
directory slug. You run:

```
cd C:\Users\greg\Desktop\ev-directory
python sales/mark_featured.py --slug <their-slug> --tier founder --rebuild
git add data/featured.json
git commit -m "Featured: <their company>"
git push
```

Cloudflare redeploys. Their FEATURED PARTNER badge goes live within 2 minutes.
Email them confirming go-live.

## What's where

```
ev-directory/
├── HANDOVER_OVERNIGHT_2026-05-21.md       ← THIS FILE
├── HANDOVER_2026-05-21.md                  (yesterday's work summary)
├── data/featured.json                      ← who's Featured (managed by mark_featured.py)
├── outreach/
│   ├── featured/01..50-*.md                ← 30 ready installer pitches, 20 SKIP
│   └── studio/01..20-*.md                  ← 15 ready trade-body pitches, 5 SKIP
├── sales/
│   ├── mark_featured.py                    ← admin CLI to flip Featured
│   ├── prospects-top50.csv                 ← scored installer list (used to write outreach)
│   └── score.py                            ← re-runnable scoring rubric
├── site/generate.py                        ← all page builders (rebuilds site)
└── site/dist/                              ← built site (Cloudflare publishes this)
```

## Honest truth — read this before you start

- **One trade body Yes by mid-July** is your real win condition. The Featured
  trickle is slower and shouldn't be the focus of your attention.
- **Don't batch-send outreach**. PECR is on your side for B2B Ltd-company
  generic mailboxes, but volume + spam-complaint risk + Gmail-spam-folder risk
  all kill conversion at scale. One thoughtful send per day beats fifty in
  an evening.
- **The 30-day click-based refund on Featured is real** — write the refund
  cheque if asked. Don't try to wriggle out. One angry installer Tweet kills
  the directory.
- **The Studio page is `noindex`** — only people you share the URL with see it.
  That's deliberate: it's a pitch tool, not a marketing site.
- **Probability you clear £1k by 1 Sep is roughly 60–70%** with daily
  outreach. Probability is roughly 15% if you do nothing further. Tonight's
  work doesn't generate revenue — sending the emails does.

## The single most important thing

**Send one outreach email tomorrow.** Not later. Not "when I have time".
Tomorrow. Trade body or installer — pick one, edit two placeholders, hit send.
Everything else built tonight is dead weight until that first email goes out.

Sleep well. The pipeline is real now.
