# Monetization — what Greg actually has to do (the non-autonomous bits)

The site, data pipeline and refresh are autonomous. **Money cannot be, because
money rails legally require *your* identity and bank details.** This file is the
exact, pre-filled action pack so each step takes minutes, not research.

Honest expectation: this asset earns **inbound** (organic search → outbound
referral clicks + paid listings). That means **near-zero revenue until it ranks**
— realistically months of Google indexing first. Nothing here is a guaranteed
payout; it is a real, low-cost, compounding asset. Don't spend ahead of signal.

---

## Revenue path A — hardware/charging affiliate & referral (most passive)

Once a guide page ranks and gets clicks, disclosed partner links on the guide
pages earn referral fees with **zero per-sale work from you**. The site already
renders the disclosed slots (`/guides/*` → "Hardware & partner options") and an
`/about/` disclosure page (UK ASA/CAP compliant). They currently say
"pending affiliate approval" — that is deliberate; **I will not fabricate
affiliate links.** You replace them after approval.

### Programs to apply to (verified to exist in the EV niche)

| Partner | Why | Apply |
|---|---|---|
| **waEV-charge** | Pays a referral commission per charger referred (commercial-friendly) | Search "waEV-charge installer/partner referral", apply with business details |
| **Andersen EV** | Premium hardware, partner/affiliate programme | Andersen EV website → Partners |
| **ChargePoint** | Global network, partner programme | chargepoint.com → Partners |
| **Parkable** | Workplace/fleet charging SaaS, partner referrals | parkable.com → Partners |
| **Awin / Webgains networks** | Aggregators that often carry EV charging brands | Apply to network, then search "EV charging" merchants |

**What you need to apply (have ready):** business/sole-trader name, the live site
URL, a contact email on the domain, and your payout bank details. Rates are not
published publicly — you must apply to see them; treat any that pay < a few £/lead
as not worth the slot.

### After approval (5 minutes, no code knowledge needed)
1. Open `site/generate.py`, find the `aff` block inside `page_guide()`.
2. Replace each `<span>Partner slot — pending affiliate approval…</span>` with
   `<a href="YOUR_AFFILIATE_LINK" target="_blank" rel="nofollow sponsored noopener">Partner name — short value line</a>`.
3. Re-run the build (`python site/generate.py`) and redeploy (see `deploy.md`).
   The scheduled refresh then keeps them live automatically.

---

## Revenue path B — featured listings (recurring, light setup)

Installers pay to be highlighted + sorted to the top. The site already supports
this: set `"featured": true` on any record and it renders a green **FEATURED**
card, ordered first. No code change needed to sell it — only a payment link.

### Setup (one-off, ~30 min, needs your Stripe)
1. Create/loginto **Stripe** → Payment Links → new link, e.g.
   *"Featured listing — 12 months — £180"* (price your call; £150–£300/yr is sane
   for a lead-gen listing).
2. Put that link on the `/contact/` page (replace the placeholder email block) and
   add a one-line "Featured listing — get priority placement" CTA.
3. When someone pays, Stripe emails you. You add `"featured": true` to their record
   in `data/installers.json` (or a `data/featured.txt` allowlist — ask Claude to
   wire the allowlist so you never touch JSON). Rebuild + redeploy.
4. Optional, gated to Gate 2: a semi-automated, *opt-out-respecting* email to
   installers already in the index offering the featured tier. Only do this once
   there is real traffic; keep it low-volume and CAN-SPAM/PECR-compliant. This is
   the one mildly non-passive lever and is entirely optional.

---

## Revenue path C — replicate (pure leverage, later)

The whole engine is niche-agnostic. Once EV proves the model, point the same
pipeline at the **farm/agricultural solar** fallback (research file in
`~/.claude/plans/…agent-af867287092979113.md`): best verified referral economics
(£250–£500/lead). Near-zero marginal effort — it's the same code with a new source
and template tokens.

---

## The gate rule (re-stated, because it's the whole point)

- **Gate 0 (done at build):** site live, data real, £0 spent.
- **Gate 1:** submit to Google Search Console; watch impressions for ~8–12 weeks.
  Apply to affiliate programs now (above) — free, and approval takes time anyway.
- **Gate 2:** *only if impressions are rising* — paste affiliate links, launch the
  Stripe featured link. Consider a custom domain (~£8/yr) for trust/SEO.
- **Gate 3:** *only if Gate 2 earns* — replicate to farm solar.

Never pre-spend. Signal first, money second. That is the honest answer to
"depends on the guaranteed output": there is none — so we risk ~£0 to find out.
