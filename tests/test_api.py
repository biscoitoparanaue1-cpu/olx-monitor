from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from app.db import Base, SessionLocal, engine
from app.main import app
from app.models import (
    FilterRule, Listing, ListingRuleMatch, ListingScore, PriceEvaluation, SearchTerm,
)
from app.scraper.service import utcnow


@pytest.fixture
def client():
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    with TestClient(app) as c:
        yield c


def add_listing(db, olx_id, title, price, score=None, z=None, days_ago=0, **kw):
    l = Listing(olx_id=olx_id, title=title, url=f"https://olx/{olx_id}", current_price=price,
                first_seen_at=utcnow() - timedelta(days=days_ago), last_seen_at=utcnow(), **kw)
    db.add(l)
    db.flush()
    if score is not None:
        db.add(ListingScore(listing_id=l.id, score=score, model_version=1))
    if z is not None:
        db.add(PriceEvaluation(listing_id=l.id, price=price, z_score=z, price_label="otimo_negocio"))
    return l


@pytest.fixture
def seeded(client):
    with SessionLocal() as db:
        a = add_listing(db, "1", "TV LG OLED C1 55 desliga sozinha", 1800, score=0.9, z=-1.5)
        b = add_listing(db, "2", "TV LG OLED C2 65 tela trincada", 2300, score=0.4)
        c = add_listing(db, "3", "TV LG OLED assistência técnica", 900, score=0.99)
        add_listing(db, "4", "TV antiga de semana passada", 500, score=1.0, days_ago=8)
        excl = FilterRule(name="Lojas de conserto", pattern="assistencia", action="exclude")
        db.add(excl)
        db.flush()
        db.add(ListingRuleMatch(listing_id=c.id, rule_id=excl.id, matched_text="assistência"))
        db.commit()
        return {"a": a.id, "b": b.id, "c": c.id}


def test_health(client):
    assert client.get("/api/health").json() == {"ok": True}


def test_top_orders_by_score_and_applies_exclude(client, seeded):
    items = client.get("/api/listings/top").json()
    assert [i["olx_id"] for i in items] == ["1", "2"]  # 3 excluído, 4 é antigo
    assert items[0]["price_evaluation"]["price_label"] == "otimo_negocio"
    assert len(client.get("/api/listings/top?days=10").json()) == 3


def test_feedback_flow(client, seeded):
    r = client.post("/api/feedback", json={"listing_id": seeded["a"], "value": 1})
    assert r.status_code == 200 and r.json()["value"] == 1
    client.post("/api/feedback", json={"listing_id": seeded["a"], "value": -1})  # troca opinião
    detail = client.get(f"/api/listings/{seeded['a']}").json()
    assert detail["feedback"] == -1
    # "Não gostei" some do topo do dia
    assert [i["olx_id"] for i in client.get("/api/listings/top").json()] == ["2"]
    assert client.delete(f"/api/feedback/{seeded['a']}").status_code == 204
    assert client.get(f"/api/listings/{seeded['a']}").json()["feedback"] is None
    assert client.post("/api/feedback", json={"listing_id": 999, "value": 1}).status_code == 404
    assert client.post("/api/feedback", json={"listing_id": seeded["a"], "value": 5}).status_code == 422


def test_list_filters(client, seeded):
    assert client.get("/api/listings?q=trincada").json()["total"] == 1
    page = client.get("/api/listings?order=price&max_price=2000").json()
    assert [i["olx_id"] for i in page["items"]] == ["4", "3", "1"]
    assert client.get("/api/listings?price_label=otimo_negocio").json()["total"] == 1


def test_rules_crud_and_regex_validation(client):
    bad = client.post("/api/rules", json={"name": "x", "pattern": "(abc"})
    assert bad.status_code == 422
    r = client.post("/api/rules", json={"name": "Desliga", "pattern": r"deslig\w* a cada \d+ ?min",
                                        "action": "include", "sets_condition": "defeito", "weight": 1.5})
    assert r.status_code == 201
    rid = r.json()["id"]
    assert client.get("/api/rules").json()[0]["name"] == "Desliga"
    client.delete(f"/api/rules/{rid}")
    assert client.get("/api/rules").json()[0]["is_active"] is False


def test_search_terms_and_ingest(client):
    client.post("/api/search-terms", json={"query": "TV LG OLED"})
    payload = {"search_query": "TV LG OLED", "ads": [
        {"olx_id": "77", "title": "TV LG OLED55C1 tela trincada", "url": "https://olx/77", "price": 1500},
        {"olx_id": "78", "title": "TV LG OLED 65 pol", "url": "https://olx/78", "price": 2500},
    ]}
    r = client.post("/api/listings/ingest", json=payload).json()
    assert r["received"] == 2 and r["new"] == 2
    assert client.post("/api/listings/ingest", json=payload).json()["new"] == 0
    cats = {c["name"]: c["listings"] for c in client.get("/api/categories").json()}
    assert cats == {"LG OLED C1 55": 1, "LG OLED 65": 1}
    stats = client.get("/api/stats").json()
    assert stats["listings_total"] == 2 and stats["last_runs"][0]["fetch_mode"] == "external"
    assert len(client.get("/api/search-terms").json()) == 1


def test_api_key_protects_writes(client, monkeypatch, seeded):
    import app.api.deps as deps
    monkeypatch.setattr(deps, "API_KEY", "segredo")
    body = {"listing_id": seeded["a"], "value": 1}
    assert client.post("/api/feedback", json=body).status_code == 401
    assert client.post("/api/feedback", json=body, headers={"X-API-Key": "segredo"}).status_code == 200
    assert client.get("/api/listings/top").status_code == 200  # leitura continua aberta


def test_rule_change_reprocesses_and_model_endpoint(client):
    payload = {"search_query": "TV LG OLED", "ads": [
        {"olx_id": str(i), "title": f"TV LG OLED55C1 {d}", "url": f"https://olx/{i}", "price": 1500 + i}
        for i, d in enumerate(["tela trincada", "tela trincada", "perfeita", "perfeita", "perfeita"])]}
    client.post("/api/listings/ingest", json=payload)
    top = client.get("/api/listings/top").json()
    assert top[0]["condition"] == "defeito" and top[0]["score"] is not None

    client.post("/api/rules", json={"name": "Só trincadas", "pattern": "trincad", "action": "include"})
    assert {i["olx_id"] for i in client.get("/api/listings/top").json()} == {"0", "1"}

    for lid, v in [(1, 1), (2, 1), (3, -1), (4, -1), (5, -1)]:
        client.post("/api/feedback", json={"listing_id": lid, "value": v})
    info = client.get("/api/model").json()
    assert info["version"] >= 1 and info["metrics"]["likes"] == 2
    assert client.post("/api/listings/reprocess").json()["processed"] == 5
