#!/usr/bin/env python3
"""Generate a self-contained outreach console (one HTML file) from the
status: ready drafts in outreach/featured/ and outreach/studio/.

Open the result (outreach/console.html) in any browser. Fill your name,
sender email and postal address once (saved in the browser). Then click each
email straight into Gmail or your mail app, pre-filled and ready to send.

No server, no accounts, works offline. Re-run this script any time the drafts
change. Stdlib only.
"""
from __future__ import annotations

import html
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "outreach" / "console.html"

# Placeholders in the drafts that the console substitutes live, in-browser.
NAME_PLACEHOLDER = "Greg Morris"
EMAIL_PLACEHOLDER = "hello@commercial-ev-installers.pages.dev"
POSTAL_PLACEHOLDER = "{POSTAL ADDRESS}"


def parse(md: str) -> dict | None:
    """Split a draft into frontmatter dict + body. Return None if not ready."""
    m = re.match(r"^---\n(.*?)\n---\n(.*)$", md, re.S)
    if not m:
        return None
    fm_raw, body = m.group(1), m.group(2).strip("\n")
    fm: dict[str, str] = {}
    for line in fm_raw.splitlines():
        if ":" in line:
            k, _, v = line.partition(":")
            fm[k.strip()] = v.strip()
    if fm.get("status") != "ready":
        return None
    return {
        "to": fm.get("to", ""),
        "subject": fm.get("subject", ""),
        "slug": fm.get("slug", ""),
        "rank": fm.get("prospect_rank", ""),
        "body": body,
    }


def collect(folder: str, kind: str) -> list[dict]:
    items = []
    d = ROOT / "outreach" / folder
    for f in sorted(d.glob("*.md")):
        rec = parse(f.read_text(encoding="utf-8"))
        if rec:
            rec["kind"] = kind
            rec["file"] = f.name
            items.append(rec)
    return items


def main() -> int:
    emails = collect("studio", "Trade body") + collect("featured", "Installer")
    payload = json.dumps(emails, ensure_ascii=False)
    page = HTML.replace("/*DATA*/null/*DATA*/", payload)
    page = page.replace("__NAME_PH__", json.dumps(NAME_PLACEHOLDER))
    page = page.replace("__EMAIL_PH__", json.dumps(EMAIL_PLACEHOLDER))
    page = page.replace("__POSTAL_PH__", json.dumps(POSTAL_PLACEHOLDER))
    OUT.write_text(page, encoding="utf-8")
    studio = sum(1 for e in emails if e["kind"] == "Trade body")
    inst = sum(1 for e in emails if e["kind"] == "Installer")
    print(f"[console] {len(emails)} ready emails "
          f"({studio} trade body, {inst} installer)")
    print(f"[console] written -> {OUT}")
    print(f"[console] open it: start \"\" \"{OUT}\"  (or just double-click)")
    return 0


HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Outreach console</title>
<style>
  :root{
    --bg:#0d0f12; --panel:#15181d; --panel-2:#1b1f26; --bd:#262b33;
    --ink:#e7eaee; --ink-2:#aab2bd; --mut:#727a86;
    --green:#3dd68c; --green-d:#2bb673; --warn:#e8b27a; --warnbg:#2a2418;
    --blue:#6f8fbf;
  }
  *{box-sizing:border-box}
  body{margin:0;background:var(--bg);color:var(--ink);
    font:15px/1.55 -apple-system,BlinkMacSystemFont,"Segoe UI",Inter,system-ui,sans-serif}
  a{color:var(--green)}
  .wrap{max-width:880px;margin:0 auto;padding:28px 20px 80px}
  h1{font-size:24px;font-weight:800;letter-spacing:-.5px;margin:0 0 4px}
  .sub{color:var(--ink-2);margin:0 0 22px;font-size:14px}
  .panel{background:var(--panel);border:1px solid var(--bd);border-radius:12px;
    padding:18px 18px 14px;margin-bottom:18px}
  .panel h2{font-size:12px;text-transform:uppercase;letter-spacing:1.2px;
    color:var(--mut);margin:0 0 12px;font-weight:700}
  .grid3{display:grid;grid-template-columns:1fr 1fr;gap:12px}
  @media(max-width:620px){.grid3{grid-template-columns:1fr}}
  label{display:block;font-size:12px;color:var(--ink-2);margin:0 0 5px}
  input,textarea{width:100%;background:var(--panel-2);border:1px solid var(--bd);
    color:var(--ink);border-radius:8px;padding:9px 11px;font:inherit;font-size:14px}
  textarea{resize:vertical;min-height:54px}
  .full{grid-column:1/-1}
  .warnbar{background:var(--warnbg);border:1px solid #4a3c22;color:var(--warn);
    border-radius:9px;padding:11px 14px;font-size:13.5px;margin-bottom:18px;display:none}
  .warnbar.show{display:block}
  .bar{display:flex;align-items:center;gap:14px;flex-wrap:wrap;margin-bottom:16px}
  .prog{font-size:13px;color:var(--ink-2)}
  .prog b{color:var(--green)}
  .seg{display:inline-flex;border:1px solid var(--bd);border-radius:8px;overflow:hidden}
  .seg button{background:var(--panel);color:var(--ink-2);border:0;padding:7px 13px;
    font:inherit;font-size:13px;cursor:pointer}
  .seg button.on{background:var(--panel-2);color:var(--ink)}
  .pace{margin-left:auto;font-size:12.5px;color:var(--mut)}
  .card{background:var(--panel);border:1px solid var(--bd);border-radius:12px;
    margin-bottom:14px;overflow:hidden;transition:opacity .2s}
  .card.sent{opacity:.5}
  .chead{display:flex;align-items:center;gap:11px;padding:13px 16px;cursor:pointer;
    border-bottom:1px solid transparent}
  .chead:hover{background:var(--panel-2)}
  .card.open .chead{border-bottom-color:var(--bd)}
  .kind{font-size:10.5px;text-transform:uppercase;letter-spacing:.8px;font-weight:700;
    padding:3px 7px;border-radius:5px;white-space:nowrap}
  .kind.tb{background:rgba(111,143,191,.16);color:#9bb6dd}
  .kind.inst{background:rgba(61,214,140,.14);color:var(--green)}
  . to{font-size:13px;color:var(--mut);font-family:ui-monospace,Menlo,Consolas,monospace}
  .subj{flex:1;font-size:14.5px;font-weight:600;min-width:0;
    overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
  .dot{width:9px;height:9px;border-radius:50%;background:var(--bd);flex-shrink:0}
  .card.sent .dot{background:var(--green)}
  .cbody{display:none;padding:16px}
  .card.open .cbody{display:block}
  .preview{background:var(--panel-2);border:1px solid var(--bd);border-radius:8px;
    padding:14px 15px;white-space:pre-wrap;font-size:13.5px;color:var(--ink-2);
    max-height:340px;overflow:auto;margin-bottom:13px}
  .preview .ph{background:rgba(232,84,91,.22);color:#ffb4b4;border-radius:3px;padding:0 3px}
  .actions{display:flex;gap:9px;flex-wrap:wrap;align-items:center}
  .btn{border:0;border-radius:8px;padding:9px 15px;font:inherit;font-size:13.5px;
    font-weight:600;cursor:pointer;text-decoration:none;display:inline-flex;
    align-items:center;gap:7px}
  .btn-g{background:var(--green);color:#04130b}
  .btn-g:hover{background:var(--green-d)}
  .btn-o{background:var(--panel-2);color:var(--ink);border:1px solid var(--bd)}
  .btn-o:hover{border-color:var(--mut)}
  .mark{margin-left:auto;display:flex;align-items:center;gap:7px;font-size:13px;
    color:var(--ink-2);cursor:pointer;user-select:none}
  .mark input{width:auto}
  .sentwhen{font-size:12px;color:var(--green)}
  .empty{color:var(--mut);text-align:center;padding:40px}
  .foot{margin-top:26px;color:var(--mut);font-size:12.5px;line-height:1.7}
  .reset{background:none;border:0;color:var(--mut);text-decoration:underline;
    cursor:pointer;font:inherit;font-size:12px;padding:0}
</style>
</head>
<body>
<div class="wrap">
  <h1>Outreach console</h1>
  <p class="sub">Fill the three fields once. Then open each email straight into
    Gmail or your mail app — pre-filled, ready to review and send. Nothing is
    sent automatically; you press send.</p>

  <div id="warn" class="warnbar"></div>

  <div class="panel">
    <h2>Your details (saved in this browser only)</h2>
    <div class="grid3">
      <div>
        <label>Your name (signoff)</label>
        <input id="f-name" placeholder="e.g. Greg Morris" autocomplete="name">
      </div>
      <div>
        <label>Send-from / reply email</label>
        <input id="f-email" placeholder="you@yourdomain.co.uk" autocomplete="email">
      </div>
      <div class="full">
        <label>Postal address (PECR requires an identifiable sender)</label>
        <textarea id="f-postal" placeholder="e.g. 12 Example Street, Town, AB1 2CD, United Kingdom"></textarea>
      </div>
    </div>
  </div>

  <div class="bar">
    <div class="prog">Sent <b id="n-sent">0</b> / <span id="n-total">0</span></div>
    <div class="seg" id="filter">
      <button data-f="all" class="on">All</button>
      <button data-f="Trade body">Trade bodies</button>
      <button data-f="Installer">Installers</button>
      <button data-f="unsent">Unsent</button>
    </div>
    <div class="pace" id="pace"></div>
  </div>

  <div id="list"></div>

  <div class="foot">
    <p><strong>Pacing matters.</strong> Don't blast all 45 in one sitting —
    spam filters and PECR both prefer a steady trickle. A handful a day,
    spread across the morning, is the sweet spot. Trade-body pitches first
    (highest value), installers second.</p>
    <p>Sent-status is remembered in this browser. <button class="reset" id="reset">Reset all sent marks</button></p>
  </div>
</div>

<script>
const EMAILS = /*DATA*/null/*DATA*/;
const NAME_PH = __NAME_PH__, EMAIL_PH = __EMAIL_PH__, POSTAL_PH = __POSTAL_PH__;
const LS = "outreach-console-v1";

function loadState(){ try{ return JSON.parse(localStorage.getItem(LS))||{}; }catch(e){ return {}; } }
function saveState(s){ localStorage.setItem(LS, JSON.stringify(s)); }
let state = loadState();
state.fields = state.fields || {};
state.sent = state.sent || {};

const $ = id => document.getElementById(id);
const fName=$("f-name"), fEmail=$("f-email"), fPostal=$("f-postal");
fName.value = state.fields.name || "";
fEmail.value = state.fields.email || "";
fPostal.value = state.fields.postal || "";

function esc(s){ return s.replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;"); }

// Substitute placeholders with the user's details. Returns {text, missing[]}.
function fill(raw){
  const missing = [];
  let t = raw;
  const name = fName.value.trim();
  const email = fEmail.value.trim();
  const postal = fPostal.value.trim();
  if(name) t = t.split(NAME_PH).join(name); else missing.push("name");
  if(email) t = t.split(EMAIL_PH).join(email); else missing.push("email");
  if(postal) t = t.split(POSTAL_PH).join(postal); else missing.push("postal address");
  return {text:t, missing};
}

// Preview HTML: highlight any still-unfilled placeholder.
function previewHTML(filled){
  let h = esc(filled);
  [NAME_PH, EMAIL_PH, POSTAL_PH].forEach(ph=>{
    h = h.split(esc(ph)).join('<span class="ph">'+esc(ph)+'</span>');
  });
  return h;
}

let filter = "all";

function render(){
  const list = $("list");
  list.innerHTML = "";
  let shown = 0;
  EMAILS.forEach((e, i)=>{
    if(filter==="Trade body" && e.kind!=="Trade body") return;
    if(filter==="Installer" && e.kind!=="Installer") return;
    if(filter==="unsent" && state.sent[e.file]) return;
    shown++;
    const filled = fill(e.body);
    const isSent = !!state.sent[e.file];
    const card = document.createElement("div");
    card.className = "card" + (isSent?" sent":"");
    card.innerHTML = `
      <div class="chead">
        <span class="dot"></span>
        <span class="kind ${e.kind==="Trade body"?"tb":"inst"}">${e.kind==="Trade body"?"Trade body":"Installer"}</span>
        <span class="subj">${esc(e.subject)}</span>
        <span class="to">${esc(e.to)}</span>
      </div>
      <div class="cbody">
        <div class="preview">${previewHTML(filled.text)}</div>
        <div class="actions">
          <a class="btn btn-g gmail" target="_blank" rel="noopener">Open in Gmail</a>
          <a class="btn btn-o mailto">Open in mail app</a>
          <button class="btn btn-o copy">Copy text</button>
          <label class="mark"><input type="checkbox" class="sentbox" ${isSent?"checked":""}> Sent
            ${isSent?`<span class="sentwhen">${state.sent[e.file]}</span>`:""}</label>
        </div>
      </div>`;
    const head = card.querySelector(".chead");
    head.addEventListener("click", ev=>{
      if(ev.target.closest(".actions")) return;
      card.classList.toggle("open");
    });
    const subj = encodeURIComponent(e.subject);
    const body = encodeURIComponent(filled.text);
    const to = encodeURIComponent(e.to);
    const gmail = card.querySelector(".gmail");
    gmail.href = `https://mail.google.com/mail/?view=cm&fs=1&to=${to}&su=${subj}&body=${body}`;
    const mailto = card.querySelector(".mailto");
    mailto.href = `mailto:${e.to}?subject=${subj}&body=${body}`;
    card.querySelector(".copy").addEventListener("click", async ()=>{
      try{ await navigator.clipboard.writeText(filled.text);
        card.querySelector(".copy").textContent="Copied ✓";
        setTimeout(()=>card.querySelector(".copy").textContent="Copy text",1400);
      }catch(err){ alert("Copy failed — select the preview text manually."); }
    });
    // Opening either send button auto-marks as sent (you can untick if you didn't).
    [gmail, mailto].forEach(b=> b.addEventListener("click", ()=>{
      if(!state.sent[e.file]){ markSent(e.file, true); }
    }));
    card.querySelector(".sentbox").addEventListener("change", ev=>{
      markSent(e.file, ev.target.checked);
    });
    list.appendChild(card);
  });
  if(shown===0) list.innerHTML = '<div class="empty">Nothing here. Switch filter, or you\'ve sent them all 🎉</div>';
  updateProgress();
}

function markSent(file, on){
  if(on){ state.sent[file] = new Date().toISOString().slice(0,10); }
  else { delete state.sent[file]; }
  saveState(state);
  render();
}

function updateProgress(){
  const n = Object.keys(state.sent).length;
  $("n-sent").textContent = n;
  $("n-total").textContent = EMAILS.length;
  // today's count
  const today = new Date().toISOString().slice(0,10);
  const todayN = Object.values(state.sent).filter(d=>d===today).length;
  $("pace").textContent = todayN ? `${todayN} opened today` : "";
}

function checkWarn(){
  const w = $("warn");
  const miss = [];
  if(!fName.value.trim()) miss.push("name");
  if(!fEmail.value.trim()) miss.push("reply email");
  if(!fPostal.value.trim()) miss.push("postal address");
  if(miss.length){
    w.className = "warnbar show";
    w.textContent = "⚠ Fill your " + miss.join(", ") + " above — emails will go out with placeholder text until you do.";
  } else { w.className = "warnbar"; }
}

[fName, fEmail, fPostal].forEach(el=> el.addEventListener("input", ()=>{
  state.fields = {name:fName.value, email:fEmail.value, postal:fPostal.value};
  saveState(state);
  checkWarn(); render();
}));

document.querySelectorAll("#filter button").forEach(b=>{
  b.addEventListener("click", ()=>{
    document.querySelectorAll("#filter button").forEach(x=>x.classList.remove("on"));
    b.classList.add("on"); filter = b.dataset.f; render();
  });
});

$("reset").addEventListener("click", ()=>{
  if(confirm("Clear all sent marks?")){ state.sent={}; saveState(state); render(); }
});

checkWarn();
render();
</script>
</body>
</html>"""


if __name__ == "__main__":
    raise SystemExit(main())
