"""Score que aprende com 👍/👎.

score = sigmoid(Σ peso × característica), entre 0 e 1.

- Sem feedback: pesos iniciais ("prior") que já refletem o objetivo
  (barato em relação ao grupo, com defeito, regras do usuário).
- Com feedback: regressão logística treinada nos seus cliques, mas puxada
  na direção dos pesos iniciais (regularização L2 em torno do prior). Com
  poucos cliques o score muda pouco; quanto mais cliques, mais ele segue
  o seu gosto, inclusive em tipo de defeito, palavras da descrição,
  tamanho, UF e vendedor.

Retreina a cada clique, recalculando as características com os dados atuais
do anúncio (cliques antigos aproveitam correções do leitor da OLX).
"""
from __future__ import annotations

import math

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import (
    Feedback, FeatureWeight, FilterRule, Listing, ListingScore, ModelVersion,
)
from app.scoring.features import extract_features
from app.scraper.service import utcnow

DEFAULT_WEIGHTS: dict[str, float] = {
    "bias": -0.5,
    "preco_vs_grupo": 3.0,             # 20% abaixo da mediana -> +0.6
    "avaliacao:otimo_negocio": 1.0,
    "avaliacao:preco_justo": 0.2,
    "avaliacao:caro": -1.0,
    "estado:defeito": 1.0,             # objetivo: achar TVs com defeito
    "estado:para_pecas": 0.5,
    "estado:usado_com_avaria": 0.2,
    "estado:novo": -0.5,
}
MIN_FEEDBACK = 5        # cliques mínimos (com 👍 e 👎) para treinar
KEEP_VERSIONS = 10      # versões antigas guardadas (para comparar/voltar)
PRIOR_STRENGTH = 0.5    # quanto o modelo resiste a se afastar dos pesos iniciais (simulação: 0.5 aprende mais rápido que 2.0)
EPOCHS, LEARNING_RATE = 400, 0.5


def sigmoid(x: float) -> float:
    return 1 / (1 + math.exp(-max(-30.0, min(30.0, x))))


def prior_weights(db: Session) -> dict[str, float]:
    w = dict(DEFAULT_WEIGHTS)
    for r in db.scalars(select(FilterRule).where(FilterRule.is_active.is_(True))):
        w[f"regra:{r.id}"] = r.weight
    return w


def active_model(db: Session) -> tuple[int, dict[str, float]]:
    """(versão, pesos). Versão 0 = só pesos iniciais, ainda sem aprendizado."""
    prior = prior_weights(db)
    mv = db.scalar(select(ModelVersion).where(ModelVersion.is_active.is_(True)))
    if not mv:
        return 0, prior
    learned = dict(db.execute(select(FeatureWeight.feature, FeatureWeight.weight)
                              .where(FeatureWeight.model_version == mv.version)).all())
    return mv.version, {**prior, **learned}  # regras novas usam o peso inicial


def score_features(weights: dict[str, float], feats: dict[str, float]) -> tuple[float, dict[str, float]]:
    contrib = {k: weights.get(k, 0.0) * v for k, v in feats.items()}
    return sigmoid(sum(contrib.values())), contrib


def explain(contrib: dict[str, float], top: int = 6) -> dict[str, float]:
    items = [(k, v) for k, v in contrib.items() if k != "bias" and abs(v) >= 0.05]
    items.sort(key=lambda kv: abs(kv[1]), reverse=True)
    return {k: round(v, 3) for k, v in items[:top]}


# ------------------------------------------------------------------ treino
def train(db: Session) -> ModelVersion | None:
    rows = db.execute(select(Listing, Feedback.value)
                      .join(Feedback, Feedback.listing_id == Listing.id)).all()
    likes = sum(1 for _, v in rows if v == 1)
    dislikes = len(rows) - likes
    if len(rows) < MIN_FEEDBACK or not likes or not dislikes:
        return None

    prior = prior_weights(db)
    data = [(extract_features(l), 1.0 if v == 1 else 0.0) for l, v in rows]
    names = sorted({k for f, _ in data for k in f} | set(prior))
    w = {k: prior.get(k, 0.0) for k in names}
    n = len(data)

    for _ in range(EPOCHS):  # gradiente em lote: poucos dados, roda em milissegundos
        grad = {k: PRIOR_STRENGTH * (w[k] - prior.get(k, 0.0)) for k in names}
        for feats, y in data:
            err = sigmoid(sum(w[k] * v for k, v in feats.items())) - y
            for k, v in feats.items():
                grad[k] += err * v
        for k in names:
            w[k] -= LEARNING_RATE * grad[k] / n

    preds = [sigmoid(sum(w[k] * v for k, v in f.items())) for f, _ in data]
    eps = 1e-9
    metrics = {
        "likes": likes, "dislikes": dislikes,
        "acuracia_treino": round(sum((p >= 0.5) == (y == 1.0) for p, (_, y) in zip(preds, data)) / n, 3),
        "logloss_treino": round(-sum(y * math.log(p + eps) + (1 - y) * math.log(1 - p + eps)
                                     for p, (_, y) in zip(preds, data)) / n, 4),
    }

    version = (db.scalar(select(func.max(ModelVersion.version))) or 0) + 1
    db.query(ModelVersion).filter(ModelVersion.is_active.is_(True)).update({"is_active": False})
    mv = ModelVersion(version=version, algorithm="logistic_regression", n_samples=n,
                      metrics_json=metrics, is_active=True, trained_at=utcnow())
    db.add(mv)
    db.flush()
    for k, val in w.items():
        if abs(val - prior.get(k, 0.0)) > 1e-4:  # só guarda o que o aprendizado mudou
            db.add(FeatureWeight(model_version=version, feature=k, weight=round(val, 5)))
    # Retreina a cada clique: apaga as versões mais antigas para o banco não crescer à toa
    old = version - KEEP_VERSIONS
    db.query(FeatureWeight).filter(FeatureWeight.model_version <= old).delete()
    db.query(ModelVersion).filter(ModelVersion.version <= old).delete()
    db.flush()
    return mv


def rescore(db: Session, listings: list[Listing] | None = None) -> int:
    """Recalcula o score. Sem lista: todos os anúncios ativos."""
    if listings is None:
        listings = list(db.scalars(select(Listing).where(Listing.is_active.is_(True))))
    version, weights = active_model(db)
    for l in listings:
        s, contrib = score_features(weights, extract_features(l))
        if l.score:
            l.score.score, l.score.model_version = s, version
            l.score.features_json, l.score.computed_at = explain(contrib), utcnow()
        else:
            l.score = ListingScore(listing_id=l.id, score=s, model_version=version,
                                   features_json=explain(contrib), computed_at=utcnow())
    db.flush()
    return len(listings)


def learn_from_feedback(db: Session) -> None:
    """Gancho chamado após cada 👍/👎: retreina (se houver dados) e reordena."""
    train(db)
    rescore(db)
    db.commit()
