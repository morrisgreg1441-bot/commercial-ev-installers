#!/usr/bin/env python3
"""Turn outreach/reply-templates.md into a click-to-copy HTML console.

Parses the markdown (## sections, ### template titles, > blockquote bodies,
*(italic notes)*) and emits outreach/reply-console.html: a searchable page of
reply cards, each with a Copy button. Set your name once (saved in the browser)
and it substitutes the 'Greg' signoff. Recipient-specific bits like [Name] stay
as placeholders for you to fill per reply. Stdlib only; no server, no accounts.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "outreach" / "reply-templates.md"
OUT = ROOT / "outreach" / "reply-console.html"


def parse(md: str) -> list[dict]:
    """-> [{section, title, body, note, intro}] flattened in document order."""
    items: list[dict] = []
    section = ""
    section_intro: list[str] = []
    title = None
    body: list[str] = []
    note_lines: list[str] = []
    pending_intro: list[str] = []

    def flush():
        nonlocal title, body, note_lines
        if title is not None:
            items.append({
                "section": section,
                "title": title,
                "body": "\n".join(body).strip("\n"),
                "note": " ".join(note_lines).strip(),
            })
        title, body, note_lines = None, [], []

    for raw in md.splitlines():
        line = raw.rstrip()
        if line.startswith("# ") and not line.startswith("## "):
            continue  # page H1
        if line.startswith("## "):
            flush()
            section = line[3:].strip()
            section_intro = []
            pending_intro = []
            continue
        if line.startswith("### "):
            flush()
            title = line[4:].strip()
            continue
        if line.strip() == "---":
            flush()
            continue
        if title is None:
            # section-level intro paragraph (plain text under a ##)
            if line.strip() and not line.startswith(">"):
                pending_intro.append(line.strip())
            continue
        # within a template
        m = re.match(r"^\*\((.*)\)\*$", line.strip())
        if m:
            note_lines.append(m.group(1).strip())
        elif line.startswith(">"):
            body.append(line[1:].lstrip())
        elif line.strip() == "":
            if body:
                body.append("")
    flush()
    return items


def md_inline(s: str) -> str:
    """Minimal inline markdown -> HTML for titles/notes (bold, links)."""
    s = (s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))
    s = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", s)
    s = re.sub(r"\[(.+?)\]\((https?://[^)]+)\)",
               r'<a href="\2" target="_blank" rel="noopener">\1</a>', s)
    return s


def main() -> int:
    items = parse(SRC.read_text(encoding="utf-8"))
    payload = json.dumps(items, ensure_ascii=False)
    page = HTML.replace("/*DATA*/null/*DATA*/", payload)
    OUT.write_text(page, encoding="utf-8")
    secs = sorted({i["section"] for i in items})
    print(f"[reply-console] {len(items)} templates across {len(secs)} sections")
    print(f"[reply-console] written -> {OUT}")
    return 0


HTML = r"""<!DOCTYPE html>
<html lang="en"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Reply templates</title>
<style>
  :root{--bg:#0d0f12;--panel:#15181d;--panel2:#1b1f26;--bd:#262b33;--ink:#e7eaee;
    --ink2:#aab2bd;--mut:#727a86;--green:#3dd68c;--green-d:#2bb673;--blue:#6f8fbf;}
  *{box-sizing:border-box}
  body{margin:0;background:var(--bg);color:var(--ink);
    font:15px/1.55 -apple-system,BlinkMacSystemFont,"Segoe UI",Inter,system-ui,sans-serif}
  a{color:var(--green)}
  .wrap{max-width:860px;margin:0 auto;padding:26px 20px 80px}
  h1{font-size:23px;font-weight:800;letter-spacing:-.5px;margin:0 0 4px}
  .sub{color:var(--ink2);margin:0 0 20px;font-size:14px}
  .controls{position:sticky;top:0;background:var(--bg);padding:12px 0 14px;
    border-bottom:1px solid var(--bd);margin-bottom:18px;z-index:5}
  .row{display:flex;gap:10px;flex-wrap:wrap;align-items:center}
  input[type=text]{flex:1;min-width:180px;background:var(--panel2);
    border:1px solid var(--bd);color:var(--ink);border-radius:8px;
    padding:9px 12px;font:inherit;font-size:14px}
  .namebox{max-width:230px}
  .seg{display:inline-flex;border:1px solid var(--bd);border-radius:8px;overflow:hidden;flex-wrap:wrap}
  .seg button{background:var(--panel);color:var(--ink2);border:0;padding:7px 12px;
    font:inherit;font-size:12.5px;cursor:pointer;white-space:nowrap}
  .seg button.on{background:var(--panel2);color:var(--ink)}
  .sechead{font-size:12px;text-transform:uppercase;letter-spacing:1.2px;
    color:var(--mut);font-weight:700;margin:24px 0 4px}
  .secintro{color:var(--ink2);font-size:13px;margin:0 0 10px}
  .card{background:var(--panel);border:1px solid var(--bd);border-radius:11px;
    padding:14px 16px;margin-bottom:12px}
  .ct{font-size:14.5px;font-weight:700;margin:0 0 9px;color:var(--ink)}
  .ct strong{color:var(--green)}
  .msg{background:var(--panel2);border:1px solid var(--bd);border-radius:8px;
    padding:12px 13px;white-space:pre-wrap;font-size:13.5px;color:var(--ink2);
    margin-bottom:10px}
  .msg .ph{background:rgba(232,84,91,.20);color:#ffb4b4;border-radius:3px;padding:0 3px}
  .note{font-size:12.5px;color:var(--mut);font-style:italic;margin:0 0 10px}
  .btn{border:0;border-radius:8px;padding:8px 15px;font:inherit;font-size:13px;
    font-weight:600;cursor:pointer;background:var(--green);color:#04130b}
  .btn:hover{background:var(--green-d)}
  .empty{color:var(--mut);text-align:center;padding:40px}
  .hint{color:var(--mut);font-size:12px;margin-top:6px}
</style></head><body>
<div class="wrap">
  <h1>Reply templates</h1>
  <p class="sub">When a reply lands: find the right one, hit Copy, paste into your
    reply, fill the <span style="color:#ffb4b4">[highlighted]</span> bits, send.</p>

  <div class="controls">
    <div class="row">
      <input type="text" id="q" placeholder="Search templates… (e.g. traffic, scam, scope, remove)">
      <input type="text" id="name" class="namebox" placeholder="Your name (signoff)">
    </div>
    <div class="row" id="filter" style="margin-top:10px"></div>
    <div class="hint">Recipient-specific bits like [Name]/[Org] stay as placeholders — fill them per reply.</div>
  </div>

  <div id="list"></div>
</div>
<script>
const T = /*DATA*/null/*DATA*/;
const LS="reply-console-name";
const $=id=>document.getElementById(id);
const nameEl=$("name"); nameEl.value=localStorage.getItem(LS)||"";
let section="all", query="";

const sections=[...new Set(T.map(t=>t.section))];
const fbar=$("filter");
function mkBtn(label,val){const b=document.createElement("button");b.textContent=label;
  b.dataset.f=val;if(val==="all")b.classList.add("on");
  b.onclick=()=>{section=val;[...fbar.children].forEach(x=>x.classList.remove("on"));
    b.classList.add("on");render();};return b;}
const seg=document.createElement("div");seg.className="seg";
seg.appendChild(mkBtn("All","all"));
sections.forEach(s=>seg.appendChild(mkBtn(s.replace(/ replies.*| \(.*/,""),s)));
fbar.appendChild(seg);

function esc(s){return s.replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;");}
function sub(s){const n=nameEl.value.trim();return n?s.split("Greg").join(n):s;}
function inlineMd(s){s=esc(s);s=s.replace(/\*\*(.+?)\*\*/g,"<strong>$1</strong>");
  return s;}
function hl(s){let h=esc(sub(s));
  h=h.replace(/\[(.+?)\]/g,'<span class="ph">[$1]</span>');return h;}

function render(){
  const list=$("list");list.innerHTML="";
  let lastSec=null,shown=0;
  T.forEach((t,i)=>{
    if(section!=="all"&&t.section!==section)return;
    const hay=(t.title+" "+t.body+" "+t.section).toLowerCase();
    if(query&&!hay.includes(query))return;
    shown++;
    if(t.section!==lastSec){const h=document.createElement("div");
      h.className="sechead";h.textContent=t.section;list.appendChild(h);lastSec=t.section;}
    const card=document.createElement("div");card.className="card";
    card.innerHTML=`<p class="ct">${inlineMd(t.title)}</p>
      <div class="msg">${hl(t.body)}</div>
      ${t.note?`<p class="note">${inlineMd(t.note)}</p>`:""}
      <button class="btn">Copy</button>`;
    card.querySelector(".btn").onclick=async ev=>{
      try{await navigator.clipboard.writeText(sub(t.body));
        ev.target.textContent="Copied ✓";setTimeout(()=>ev.target.textContent="Copy",1300);
      }catch(e){alert("Copy failed — select the text manually.");}
    };
    list.appendChild(card);
  });
  if(!shown)list.innerHTML='<div class="empty">No template matches that search.</div>';
}
$("q").addEventListener("input",e=>{query=e.target.value.trim().toLowerCase();render();});
nameEl.addEventListener("input",()=>{localStorage.setItem(LS,nameEl.value);render();});
render();
</script></body></html>"""


if __name__ == "__main__":
    raise SystemExit(main())
