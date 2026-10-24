import os
from datetime import date
from types import SimpleNamespace

os.environ["ANTHROPIC_API_KEY"] = ""  # tests use the offline rules

from fastapi.testclient import TestClient  # noqa: E402

from app.catalog import load_catalog  # noqa: E402
from app.main import SAMPLES, app  # noqa: E402
from app.parser import parse_claude, parse_rules  # noqa: E402
from app.pricing import price_items  # noqa: E402
from app.quotes import Customer, build_quote  # noqa: E402

CAT = load_catalog()


def codes(result):
    return {i["code"]: i["quantity"] for i in result["items"]}


def test_rules_parser_finds_services_and_quantities():
    got = codes(parse_rules(SAMPLES[0], CAT))
    assert got == {"INSP": 1, "PLAN": 1, "RX": 12, "RT": 1, "BS": 40}
    got = codes(parse_rules(SAMPLES[1], CAT))
    assert got == {"WR": 2, "AC": 600, "BN": 150}


def test_missing_quantity_becomes_a_question():
    result = parse_rules("Pigeons everywhere, they want netting on the loading dock.", CAT)
    assert codes(result) == {"BN": 1}
    assert result["questions"]


def test_pricing_math():
    q = price_items([{"code": "RX", "quantity": 10}, {"code": "INSP", "quantity": 5}, {"code": "PLAN", "quantity": 1}], CAT)
    # RX 650 + INSP 95 (flat, qty forced to 1) + PLAN 420
    assert q.subtotal == 1165.00
    # bundle: 10% off one-time services only (650 + 95), not the plan
    assert q.discount == 74.50
    assert q.tax == round((1165.00 - 74.50) * 0.07, 2)
    assert q.total == round(1165.00 - 74.50 + q.tax, 2)


def test_minimum_job_charge():
    q = price_items([{"code": "INSP", "quantity": 1}], CAT)
    assert q.minimum_adjustment == 55.00
    assert q.total == round(150 * 1.07, 2)


def test_unknown_codes_are_ignored():
    q = price_items([{"code": "FAKE", "quantity": 3}, {"code": "GEN", "quantity": 2}], CAT)
    assert [l.code for l in q.lines] == ["GEN"]


def test_claude_parser_keeps_only_catalog_codes():
    tool_input = {"items": [{"code": "WR", "quantity": 1}, {"code": "MADE-UP", "quantity": 9}],
                  "scope_summary": "We will remove the squirrel.", "assumptions": [], "questions": []}

    class FakeClient:
        class messages:  # noqa: N801
            @staticmethod
            def create(**kwargs):
                assert kwargs["tool_choice"]["name"] == "build_quote"
                return SimpleNamespace(content=[SimpleNamespace(type="tool_use", input=dict(tool_input))])

    result = parse_claude("squirrel in the attic", CAT, client=FakeClient())
    assert codes(result) == {"WR": 1}
    assert result["source"] == "claude"


def test_build_quote_dates():
    q = build_quote(Customer("Test Co"), SAMPLES[1], CAT, today=date(2026, 10, 24))
    assert q.issued == "2026-10-24" and q.valid_until == "2026-11-23"
    assert q.number.startswith("Q-20261024-")


def test_web_and_api_flow():
    client = TestClient(app)
    assert client.get("/").status_code == 200
    r = client.post("/quote", data={"customer_name": "Main St Bakery", "notes": SAMPLES[0]})
    assert r.status_code == 200 and "Download PDF" in r.text

    data = client.post("/api/quotes", json={"customer": {"name": "Jordan Lee"}, "notes": SAMPLES[1]}).json()
    assert data["priced"]["total"] > 0
    pdf = client.get(data["pdf_url"])
    assert pdf.headers["content-type"] == "application/pdf"
    assert pdf.content[:4] == b"%PDF"
    assert client.get("/quotes/NOPE.pdf").status_code == 404
