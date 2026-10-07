from datetime import timedelta

import pytest
from sqlalchemy import select

from app.models import (
    Feedback, FeatureWeight, FilterRule, Listing, ModelVersion, PriceHistory, ProductCategory,
)
from app.nlp.categorizer import apply_categorization, categorize, detect_condition, normalize
from app.pipeline import process
from app.pricing.evaluator import evaluate
from app.scoring.model import DEFAULT_WEIGHTS, active_model, rescore, train
from app.scraper.service import utcnow
from app.services import set_feedback


def mk(db, oid, title, price, desc="", size=55, line="OLED C1", state="SP", cat=None,
       condition=None, days_ago=0):
    l = Listing(olx_id=str(oid), title=title, description=desc, url=f"https://olx/{oid}",
                current_price=price, brand="LG", model_line=line, screen_size=size, state=state,
                category=cat, condition=condition,
                first_seen_at=utcnow() - timedelta(days=days_ago), last_seen_at=utcnow())
    db.add(l)
    db.flush()
    db.add(PriceHistory(listing_id=l.id, price=price, observed_at=l.first_seen_at))
    db.flush()
    return l


# ------------------------------------------------------------- categorizador
@pytest.mark.parametrize("text,expected", [
    ("TV LG OLED desliga a cada 40min", "defeito"),
    ("Tela trincada no canto inferior", "defeito"),
    ("Perfeita, sem nenhum defeito, a tela não está trincada", "usado_bom"),
    ("Vendo para retirada de peças, não liga", "para_pecas"),
    ("Lacrada, nunca usada", "novo"),
    ("Pequeno risco na borda e sem controle", "usado_com_avaria"),
])
def test_detect_condition(text, expected):
    assert detect_condition(normalize(text))[0] == expected


def test_user_rules(db):
    regex = FilterRule(id=1, name="Desliga", pattern=r"deslig\w* a cada \d+ ?min", pattern_type="regex",
                       action="include", weight=1.5)
    kw = FilterRule(id=2, name="Placa", pattern="placa principal; placa fonte", pattern_type="keywords",
                    action="tag", weight=0.5)
    fuzzy = FilterRule(id=3, name="Linhas", pattern="listras na tela", pattern_type="fuzzy",
                       action="tag", sets_condition="para_pecas", weight=0.0)
    l = Listing(title="TV LG OLED 55", description="Ela DESLIGA a cada 40 minutos, já troquei a "
                "placa fonte. Tem listra na tela.", url="u", olx_id="x")
    res = categorize(l, [regex, kw, fuzzy])
    assert {r.id: hit for r, hit in res.rule_matches} == {
        1: "desliga a cada 40 min", 2: "placa fonte", 3: "listra na tela"}
    assert res.condition == "para_pecas"  # regra mais grave vence
    assert categorize(Listing(title="TV sem placa fonte com defeito", url="u", olx_id="y"), [kw]).rule_matches


def test_apply_categorization_replaces_matches(db):
    r = FilterRule(name="Trincada", pattern=r"trincad", action="tag")
    db.add(r)
    l = mk(db, 1, "TV tela trincada", 1000)
    apply_categorization(db, [l])
    apply_categorization(db, [l])
    db.commit()
    db.refresh(l)
    assert l.condition == "defeito" and len(l.rule_matches) == 1


# ---------------------------------------------------------------- preço
def test_price_labels_and_fallback(db):
    c1 = ProductCategory(name="LG OLED C1 55", brand="LG", model_line="OLED C1", screen_size=55)
    db.add(c1)
    for i, p in enumerate([2000, 2100, 2200, 2300, 2400, 99999, 1]):  # outliers não atrapalham
        mk(db, i, f"TV {i}", p, cat=c1, condition="defeito")
    cheap = mk(db, 100, "barata", 1600, cat=c1, condition="defeito")
    pricey = mk(db, 101, "cara", 3000, cat=c1, condition="defeito")
    fair = mk(db, 102, "justa", 2250, cat=c1, condition="defeito")
    assert evaluate(db, cheap).price_label == "otimo_negocio"
    ev = evaluate(db, pricey)
    assert ev.price_label == "caro" and ev.group_level == "modelo+tamanho" and ev.z_score > 0
    assert evaluate(db, fair).price_label == "preco_justo"

    # C2 55 sem amostra própria: sobe para marca+tamanho
    c2 = ProductCategory(name="LG OLED C2 55", brand="LG", model_line="OLED C2", screen_size=55)
    db.add(c2)
    other = mk(db, 200, "c2", 1500, cat=c2, line="OLED C2", condition="defeito")
    assert evaluate(db, other).group_level == "marca+tamanho"
    # Estado diferente não mistura
    new = mk(db, 201, "nova", 1500, cat=c1, condition="novo")
    assert evaluate(db, new).price_label == "sem_base"


# ---------------------------------------------------------------- score
def test_prior_scores_follow_goal(db):
    l_def = mk(db, 1, "TV desliga sozinha", 1500, condition="defeito")
    l_ok = mk(db, 2, "TV perfeita", 1500, condition="usado_bom")
    rescore(db)
    assert l_def.score.score > l_ok.score.score
    assert l_def.score.model_version == 0
    assert "estado:defeito" in l_def.score.features_json


def test_learns_preferences_from_feedback(db):
    # Você gosta das TVs de SP com "placa" na descrição e não gosta das de AM com "riscos"
    liked = [mk(db, i, f"TV {i}", 1500, desc="defeito na placa principal", state="SP") for i in range(4)]
    disliked = [mk(db, 10 + i, f"TV {i}", 1500, desc="defeito, com riscos", state="AM") for i in range(4)]
    process(db, liked + disliked)
    assert train(db) is None  # sem feedback ainda

    for l in liked:
        set_feedback(db, l, 1)
    for l in disliked:
        set_feedback(db, l, -1)

    version, weights = active_model(db)
    mv = db.get(ModelVersion, version)
    assert version >= 1 and mv.metrics_json["acuracia_treino"] == 1.0
    assert weights["uf:SP"] > 0 > weights["uf:AM"]
    assert weights["palavra:placa"] > 0
    assert weights["estado:defeito"] == pytest.approx(DEFAULT_WEIGHTS["estado:defeito"], abs=0.6)

    # Anúncios novos parecidos herdam a preferência
    a = mk(db, 50, "TV nova SP", 1500, desc="defeito na placa", state="SP")
    b = mk(db, 51, "TV nova AM", 1500, desc="defeito na placa", state="AM")
    process(db, [a, b])
    assert a.score.score > b.score.score
    assert db.scalar(select(FeatureWeight).limit(1)) is not None


def test_new_rule_weight_applies_without_retraining(db):
    l = mk(db, 1, "TV com tela trincada", 1500)
    process(db, [l])
    before = l.score.score
    r = FilterRule(name="Trincada", pattern="trincad", action="tag", weight=2.0)
    db.add(r)
    db.commit()
    process(db, [l])
    assert l.score.score > before
    assert f"regra:{r.id}" in l.score.features_json
