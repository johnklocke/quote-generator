"""Reads free-text job notes and picks services and quantities from the catalog.

Uses Claude when ANTHROPIC_API_KEY is set. Otherwise a keyword-and-number
fallback runs, so the app works offline (and in tests) with no API key.
"""
import os
import re

from .catalog import Catalog

CLAUDE_MODEL = os.getenv("CLAUDE_MODEL", "claude-haiku-5-5")

SYSTEM = """You are the estimator for {company}. A salesperson pasted notes from a
site visit or phone call. Choose services ONLY from this price list (code: name, unit):

{services}

Rules:
- Use only the codes above. Never invent a service or a price.
- Take quantities from the notes. If one is missing, make a sensible estimate and
  say so in assumptions, or ask about it in questions.
- Flat-rate services always have quantity 1.
- scope_summary: 2-4 friendly sentences to the customer describing the work. No prices.
"""

TOOL = {
    "name": "build_quote",
    "description": "Record the services, quantities and scope for this quote.",
    "input_schema": {
        "type": "object",
        "properties": {
            "items": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "code": {"type": "string"},
                        "quantity": {"type": "number"},
                        "note": {"type": "string", "description": "Short detail shown under the line, e.g. 'garage and kitchen'"},
                    },
                    "required": ["code", "quantity"],
                },
            },
            "scope_summary": {"type": "string"},
            "assumptions": {"type": "array", "items": {"type": "string"}},
            "questions": {"type": "array", "items": {"type": "string"},
                          "description": "Anything to confirm with the customer before work starts"},
        },
        "required": ["items", "scope_summary", "assumptions", "questions"],
    },
}

NUMBER = r"(\d[\d,]*(?:\.\d+)?)"


def _positions(text: str, words: list[str]) -> list[int]:
    out = []
    for w in words:
        out += [m.start() for m in re.finditer(rf"\b{re.escape(w)}\b", text)]
    return out


def _unit_pattern(phrase: str) -> str:
    """'entry point' -> matches 'entry point', 'entry points', 'entry-points'."""
    parts = [re.escape(p) for p in phrase.lower().split()]
    return r"[\s-]*".join(parts) + r"(?:e?s)?"


def _quantity(text: str, qty_words: list[str], near: list[int]) -> float | None:
    """Find 'N <unit word>' closest to where the service was mentioned."""
    best, best_dist = None, None
    for word in qty_words:
        for m in re.finditer(rf"{NUMBER}\s*-?\s*{_unit_pattern(word)}\b", text):
            dist = min((abs(m.start() - p) for p in near), default=0)
            if best_dist is None or dist < best_dist:
                best, best_dist = float(m.group(1).replace(",", "")), dist
    return best


def parse_rules(notes: str, catalog: Catalog) -> dict:
    text = notes.lower()
    items, assumptions, questions = [], [], []
    for s in catalog.services.values():
        hits = _positions(text, [k.lower() for k in s.keywords])
        if not hits:
            continue
        qty = 1.0
        if s.unit != "flat" and s.qty_words:
            found = _quantity(text, s.qty_words, hits)
            if found:
                qty = found
            else:
                questions.append(f"How many {s.unit}s for {s.name.lower()}? Quoted 1 for now.")
        items.append({"code": s.code, "quantity": qty, "note": ""})

    names = [catalog.services[i["code"]].name.lower() for i in items]
    if names:
        listed = names[0] if len(names) == 1 else ", ".join(names[:-1]) + " and " + names[-1]
        summary = f"Thanks for having us out. Based on what we discussed, this quote covers {listed}."
    else:
        summary = "We couldn't match these notes to our services. Please add more detail."
        questions.append("What problem is the customer seeing, and where?")
    if items:
        assumptions.append("Quantities are taken from the notes and will be confirmed on site.")
    return {"items": items, "scope_summary": summary, "assumptions": assumptions,
            "questions": questions, "source": "rules"}


def parse_claude(notes: str, catalog: Catalog, client=None) -> dict:
    import anthropic

    client = client or anthropic.Anthropic()
    services = "\n".join(f"{s.code}: {s.name} (per {s.unit})" for s in catalog.services.values())
    response = client.messages.create(
        model=CLAUDE_MODEL,
        max_tokens=1024,
        system=SYSTEM.format(company=catalog.company["name"], services=services),
        tools=[TOOL],
        tool_choice={"type": "tool", "name": "build_quote"},
        messages=[{"role": "user", "content": f"Job notes:\n{notes}"}],
    )
    data = next(block.input for block in response.content if block.type == "tool_use")
    # Keep only codes that exist in the price list.
    data["items"] = [i for i in data.get("items", []) if i.get("code") in catalog.services]
    data.setdefault("assumptions", [])
    data.setdefault("questions", [])
    data["source"] = "claude"
    return data


def parse_notes(notes: str, catalog: Catalog) -> dict:
    if os.getenv("ANTHROPIC_API_KEY"):
        try:
            return parse_claude(notes, catalog)
        except Exception as exc:  # network error, bad response, etc.
            result = parse_rules(notes, catalog)
            result["assumptions"].append(f"AI parsing unavailable ({type(exc).__name__}); used keyword rules.")
            return result
    return parse_rules(notes, catalog)
