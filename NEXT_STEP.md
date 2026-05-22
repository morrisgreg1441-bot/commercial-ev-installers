# The next step — converting tomorrow's emails into money

You send 364 emails tomorrow. This is what happens *after*: how to convert
replies, how to deliver if someone says yes, and the legal/payment plumbing so
you get paid safely. Researched deep across three angles + a check of your own
code. Today: 2026-05-22.

---

## 0. One thing I fixed before you send (important)

Your emails and the `/featured/` page promised: *"if you don't get 5+ outbound
clicks in 30 days, full refund — we track clicks."* **Your site does not track
outbound clicks** — it uses Cloudflare Web Analytics (pageviews only), the
"Visit website" links are plain links, and there's no backend. So that promise
was unmeasurable and unfair to make.

**Fixed.** I reworded it everywhere (319 emails + the /featured/ page) to a
clean **"30-day money-back guarantee, no questions asked."** That's honest,
needs no tracking, is more credible, and lowers chargeback risk. Rebuilt and
ready.

*(If you ever want a performance-based promise back, I can build real
click-tracking — a counted redirect or a Cloudflare Pages Function — but you
don't need it, and "no-questions money-back" converts better anyway.)*

---

## 1. When a reply lands — the cheat sheet

1. **Reply same day.** Speed-to-reply is the biggest lever a solo operator has.
2. **Trade body = chase a 15–20 min call.** Four-figure builds close on a call.
3. **Installer = stay async, zero friction.** Send the link, reassure, done. Never push a call (it's a £99 decision).
4. **"Remove me" = action immediately, log it, one-line reply.** Never sell. (PECR duty — add to `data/suppress.txt`.)
5. **No reply = follow up.** Trade body: nudge day 4, break-up day 10. Installer: one nudge day 4, stop.
6. **Track every reply in one sheet** (company / path / status / next action / date). 364 emails won't fit in your head.

**All the actual reply wording is in [`outreach/reply-templates.md`](outreach/reply-templates.md) — keep it open while you work the inbox.**

---

## 2. Where the £1,000 actually is

Realistic UK B2B cold-email math on these two batches:

| | Trade body (45 sends, £750–£1,500) | Installer (319 sends, £99) |
|---|---|---|
| Replies | ~2–7 | ~10–16 (some "remove me") |
| Real conversations | ~2–4 | — (mostly self-serve) |
| Closes | **1–2** | ~3–6 |
| Revenue | **£750–£3,000** | ~£300–£600 |

**One trade-body yes hits your goal. The installer batch alone probably won't.**
So: handle installer replies fast and templated (2 min each, no calls). Pour
your real attention into the 45 trade-body replies — same-day, personal, always
pushing to a call. **That's where the £1,000 lives.** Full reasoning and the
discovery-call structure are in §3 and the templates file.

---

## 3. The discovery call (trade-body path only)

20 minutes, loosely SPIN-style:
- **0–2 min** — Set agenda: "15 min understanding your members' needs, then I'll show you the example, then we'll see if it fits."
- **2–6 min** — Situation: how do members find each other / find [service] now? Do they have any directory? Where's their member value?
- **6–13 min** — Problem + cost: is [members not findable] a real issue? What does it cost them (churn, fewer renewals)? *Let them say the pain in their words — reuse it.* Talk less than 40% here.
- **13–17 min** — Show the example. Scope live: "For you it'd be [seeded listings + filtering + your branding]." Their answer picks the tier.
- **17–20 min** — Land the price + ask for the deposit: *"Based on that, it's the £[X] version. 50% to start, 50% on delivery, live in [2–3 weeks]. Shall I send the deposit invoice and we get going?"* **Then stop talking.** Silence is the close.

Anchor price on the value they described, not on hours. Don't pre-discount.

---

## 4. If someone says yes to a build — delivery playbook

You've built the engine once. Here's how to deliver a *new* niche without
tripping. (Full version with hour estimates was researched; key points below.)

**a) Scope it before you quote.** One call + one form. Lock down: data source,
record count, facets (default: location × one category), number of editorial
pages, domain/hosting. **Write the EXCLUSIONS into the agreement** — this is
what protects the fixed price:
- No CMS / logins / user accounts / database / payments (it's a static site by design)
- Missing data shows as "N/A", never invented
- A fixed number of guide pages + facets + **one** revision round
- No SEO ranking guarantee; no ongoing data refreshes unless separately paid

**b) Go/no-go on the data (under 1 hour).** Cleanest → riskiest:
1. **Client's own member CSV** (best — they own it, they consent to publish; get one line in writing confirming that)
2. **Public register under OGL v3.0** (like the OZEV source — free with attribution)
3. **Companies House / ONS** open data
4. **Scraping a third party — usually decline** (robots.txt + ToS + no personal data; not worth a dispute)

   **Decline the build** if the only source is a paid lead DB, a login-walled
   site, a ToS that forbids reuse, or substantially personal data with no lawful
   basis. A £750 build you can't deliver legally is not worth it.

**c) Build (you own the engine).** Realistic hands-on hours: **Starter (≤500
records, location + 1 facet, ~2 guides) = 12–18h; Standard (≤2,000 records,
multi-facet, 4–6 guides) = 30–45h.** ~80% of the engine is reusable; the fiddly
20% is the record schema, the facet logic, the editorial copy, and branding.

**d) Hand over cleanly (no open-ended support).** Transfer the GitHub repo to
them; they create their own Cloudflare Pages project + domain (do it together on
a screen-share, never take custody of their logins); send a one-page refresh
doc; get a sign-off email. **"Delivered" = live on their domain + repo theirs +
sign-off received.** Offer paid refreshes as a separate retainer rather than
free-forever support.

**e) Timeline truth.** "2 weeks / 3–4 weeks" is achievable — *from the day you
have their data and domain*, not from "yes". Delays come almost entirely from
the client being slow with data and sign-off. Make data delivery Milestone 0;
the clock starts there. Quote "two weeks from the day we have your data."

---

## 5. Getting paid (UK sole trader) — do these in order

**Before you can take installer money (£99):**
- [ ] **Set up Stripe** (individual/sole-trader account): needs your legal name, DOB, home address, UK bank sort code + account number, photo ID. No fees to open.
- [ ] **Create the £99 Payment Link**: one-time, GBP, with a **custom text field** "Business name / which listing is this for?" (so you know who paid), and a **success redirect** to `https://commercial-ev-installers.pages.dev/featured/thanks/`.
- [ ] **Paste the link** into Cloudflare Pages → Settings → Environment variables (Production): `STRIPE_FEATURED_FOUNDER_URL`, plus `STRIPE_FEATURED_STANDARD_URL` (£199) and `SITE_CONTACT_EMAIL` (must not be the `example.com` placeholder). Redeploy.
- Fee on £99 ≈ £1.69. Refunds: the processing fee isn't returned, so a refunded £99 costs you ~£1.69 — fine.

**For the builds (£750–£1,500):** **invoice + bank transfer beats Stripe** — £0
fees and no chargeback risk on four-figure B2B. A compliant UK invoice needs: a
unique sequential number, your name/trading name + a service address, the
client's name/address, description, dates, total, and (since you're not VAT
registered) no VAT. Take **50% deposit, non-refundable once work starts; balance
on delivery; IP transfers only on final payment.** A simple one-page
Statement of Work is enough at this size — you don't need a lawyer.

**Required-ish admin (don't skip):**
- [ ] **ICO data-protection fee (~£40/year).** You hold a prospect list and do cold outreach using business-contact data — that very likely takes you outside the "own marketing" exemption, so the fee applies. Run the 2-min self-assessment at ico.org.uk and pay if it says so. **This is the compliance item people in your spot most often miss.**
- [ ] **HMRC Self Assessment** once self-employed income exceeds **£1,000** in the tax year (register by 5 Oct after that tax year). Below £1,000, nothing to do.
- VAT threshold is **£90,000** — nowhere near; ignore until/unless you scale massively.
- Keep records 5 years: invoices, Stripe payouts, expenses, refund confirmations. A dedicated account + one spreadsheet is enough.

*(I'm not a lawyer/accountant. One 30-min call with an accountant before your
first tax return is cheap insurance — confirm expenses and timing.)*

---

## 6. Two honest flags on the outreach itself

1. **PECR / recipient type.** The corporate-subscriber exemption (cold email
   without consent) covers **Ltd companies and LLPs**. Some installers on the
   319 list are **sole traders / ordinary partnerships**, which are "individual
   subscribers" and technically need consent. Mitigations already in place:
   you're emailing **generic mailboxes** (info@/sales@/office@), every email
   has a one-click opt-out, and you action removals immediately. Risk is low at
   this volume, but it's why the **trade-body batch (all incorporated bodies) is
   cleaner** as well as higher-value. Don't mass-blast the installers; trickle
   them.

2. **Deliverability.** Those installer `info@` addresses are partly inferred
   from domains — some will bounce. Send in batches of ~20–30 and watch
   bounce-backs. If more than a couple bounce, slow down: a high bounce rate
   pushes the rest into spam.

---

## The actual order of operations

1. **Tomorrow:** open the console, send 5–10 **trade-body** emails (no setup needed). Keep `reply-templates.md` open.
2. **This week:** pay the ICO fee (~£40, 5 min). Set up Stripe + Cloudflare env vars (~15 min).
3. **Once Stripe is live:** start trickling installer emails, 20–30/day.
4. **When a trade body replies:** chase the call. That's your £1,000.
5. **When you close a build:** use §4. Take 50% upfront by bank transfer.
