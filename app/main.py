"""AI Quote Generator: FastAPI app.

Run:   uvicorn app.main:app --reload
Open:  http://localhost:8000      (web form)
       http://localhost:8000/docs (API docs)
"""
import html
import json
import os

from dotenv import load_dotenv

load_dotenv()  # reads ANTHROPIC_API_KEY etc. from a .env file if present

from fastapi import FastAPI, Form, HTTPException  # noqa: E402
from fastapi.responses import HTMLResponse, Response
from pydantic import BaseModel

from .catalog import load_catalog
from .pdf import render_pdf
from .quotes import Customer, Quote, build_quote

app = FastAPI(
    title="AI Quote Generator",
    description="Turns job notes into a priced, branded PDF quote from a company price list.",
    version="1.0.0",
)

QUOTES: dict[str, Quote] = {}  # in-memory store; swap for a database in production

SAMPLES = [
    "Met with Dana at the Main St bakery. Mice in the back storage room, found about 12 gaps "
    "along the foundation and around pipes. Pigeons nesting on the front sign, roughly 40 feet "
    "of ledge. They also want ongoing quarterly service going forward. Please include the inspection.",
    "Homeowner hears scratching in the attic at night, likely 2 raccoons. Droppings over about "
    "600 sq ft of attic insulation. Birds nesting under the deck too, maybe 150 square feet of netting.",
]


class CustomerIn(BaseModel):
    name: str
    email: str = ""
    address: str = ""


class QuoteRequest(BaseModel):
    customer: CustomerIn
    notes: str


def mode() -> str:
    return "Claude AI" if os.getenv("ANTHROPIC_API_KEY") else "Offline keyword rules"


def _store(quote: Quote) -> Quote:
    QUOTES[quote.number] = quote
    return quote


@app.get("/health")
def health():
    return {"status": "ok", "mode": mode()}


@app.get("/catalog")
def catalog():
    c = load_catalog()
    return {"company": c.company, "pricing": c.pricing,
            "services": [vars(s) for s in c.services.values()]}


@app.post("/api/quotes")
def create_quote(req: QuoteRequest):
    if not req.notes.strip():
        raise HTTPException(400, "Notes are empty.")
    quote = _store(build_quote(Customer(**req.customer.model_dump()), req.notes, load_catalog()))
    return {**quote.to_dict(), "pdf_url": f"/quotes/{quote.number}.pdf"}


@app.get("/api/quotes/{number}")
def get_quote(number: str):
    if number not in QUOTES:
        raise HTTPException(404, "Quote not found.")
    return QUOTES[number].to_dict()


@app.get("/quotes/{number}.pdf")
def quote_pdf(number: str):
    if number not in QUOTES:
        raise HTTPException(404, "Quote not found.")
    pdf = render_pdf(QUOTES[number], load_catalog())
    return Response(pdf, media_type="application/pdf",
                    headers={"Content-Disposition": f'inline; filename="{number}.pdf"'})


# ---------- Web pages ----------

STYLE = """
:root{--brand:#1f4e79;--ink:#1b1f24;--muted:#5b6470;--bg:#f6f7f9;--card:#fff;--line:#e6e9ee}
*{box-sizing:border-box} body{margin:0;font-family:system-ui,-apple-system,Segoe UI,sans-serif;color:var(--ink);background:var(--bg)}
header{background:var(--brand);color:#fff;padding:18px 24px} header h1{margin:0;font-size:22px}
header p{margin:4px 0 0;opacity:.85;font-size:14px}
main{max-width:860px;margin:24px auto;padding:0 16px}
.card{background:var(--card);border-radius:12px;box-shadow:0 1px 3px #0001;padding:20px;margin-bottom:16px}
label{display:block;font-weight:600;font-size:14px;margin:12px 0 4px}
input,textarea{width:100%;padding:10px;border:1px solid var(--line);border-radius:8px;font:inherit}
textarea{min-height:150px;resize:vertical}
.row{display:grid;grid-template-columns:1fr 1fr;gap:12px} @media(max-width:640px){.row{grid-template-columns:1fr}}
button,.btn{background:var(--brand);color:#fff;border:0;border-radius:8px;padding:10px 16px;font:inherit;font-weight:600;cursor:pointer;text-decoration:none;display:inline-block}
.ghost{background:#e8f0f8;color:var(--brand)} .badge{font-size:12px;background:#e8f0f8;color:var(--brand);padding:3px 8px;border-radius:10px}
table{width:100%;border-collapse:collapse;font-size:14px} th,td{padding:8px;border-bottom:1px solid var(--line);text-align:left}
th{color:var(--muted);font-weight:600} td.n,th.n{text-align:right} tr.total td{font-weight:700;font-size:16px;border-bottom:0}
.muted{color:var(--muted);font-size:14px} ul{margin:6px 0 0;padding-left:20px} .warn{color:#8a5a00}
"""


def page(body: str) -> str:
    c = load_catalog().company
    return f"""<!doctype html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>AI Quote Generator</title>
<style>{STYLE}</style></head><body>
<header><h1>AI Quote Generator</h1><p>{html.escape(c['name'])} &middot; <span class="badge" style="background:#fff3;color:#fff">{mode()}</span></p></header>
<main>{body}</main></body></html>"""


@app.get("/", response_class=HTMLResponse)
def form():
    samples = json.dumps(SAMPLES)
    return page(f"""
<form class="card" method="post" action="/quote">
  <div class="row">
    <div><label for="n">Customer name</label><input id="n" name="customer_name" required placeholder="Main St Bakery"></div>
    <div><label for="em">Email (optional)</label><input id="em" name="customer_email" type="email"></div>
  </div>
  <label for="ad">Address (optional)</label><input id="ad" name="customer_address">
  <label for="notes">Job notes</label>
  <textarea id="notes" name="notes" required placeholder="Paste notes from the site visit or call..."></textarea>
  <p class="muted">Write it the way you'd text it to the office. The AI picks services and quantities from your
  price list; prices always come from the list, never from the AI.</p>
  <button type="submit">Generate quote</button>
  <button type="button" class="ghost" onclick="fill(0)">Try sample 1</button>
  <button type="button" class="ghost" onclick="fill(1)">Try sample 2</button>
</form>
<script>const S={samples};function fill(i){{document.getElementById('notes').value=S[i];
const n=document.getElementById('n');if(!n.value)n.value=i?'Jordan Lee (homeowner)':'Main St Bakery';}}</script>""")


@app.post("/quote", response_class=HTMLResponse)
def quote_page(customer_name: str = Form(...), customer_email: str = Form(""),
               customer_address: str = Form(""), notes: str = Form(...)):
    q = _store(build_quote(Customer(customer_name, customer_email, customer_address), notes, load_catalog()))
    e, p = html.escape, q.priced
    rows = "".join(
        f"<tr><td>{e(l.name)}{' <span class=badge>annual</span>' if l.recurring else ''}</td>"
        f"<td class=n>{l.quantity:g}</td><td>{e(l.unit)}</td><td class=n>${l.unit_price:,.2f}</td>"
        f"<td class=n>${l.amount:,.2f}</td></tr>" for l in p.lines)
    extra = ""
    if p.discount:
        extra += f"<tr><td colspan=4 class=n>{e(p.discount_label)}</td><td class=n>-${p.discount:,.2f}</td></tr>"
    if p.minimum_adjustment:
        extra += f"<tr><td colspan=4 class=n>Minimum job adjustment</td><td class=n>${p.minimum_adjustment:,.2f}</td></tr>"
    lists = ""
    if q.questions:
        lists += "<p class=warn><b>Confirm with the customer:</b></p><ul>" + "".join(f"<li>{e(x)}</li>" for x in q.questions) + "</ul>"
    if q.assumptions:
        lists += "<p><b>Assumptions on the quote:</b></p><ul>" + "".join(f"<li>{e(x)}</li>" for x in q.assumptions) + "</ul>"
    return page(f"""
<div class="card"><p class="muted">Quote {e(q.number)} for <b>{e(q.customer.name)}</b> &middot; valid until {e(q.valid_until)}</p>
<p>{e(q.scope_summary)}</p>
<table><tr><th>Service</th><th class=n>Qty</th><th>Unit</th><th class=n>Unit price</th><th class=n>Amount</th></tr>
{rows}<tr><td colspan=4 class=n>Subtotal</td><td class=n>${p.subtotal:,.2f}</td></tr>{extra}
<tr><td colspan=4 class=n>Tax</td><td class=n>${p.tax:,.2f}</td></tr>
<tr class=total><td colspan=4 class=n>Total</td><td class=n>${p.total:,.2f}</td></tr></table>
{lists}</div>
<a class="btn" href="/quotes/{e(q.number)}.pdf" target="_blank">Download PDF</a>
<a class="btn ghost" href="/">New quote</a>""")
