"""Compara o preço de um anúncio com o histórico de anúncios parecidos.

Grupo = mesmo estado (defeito, para peças...) e, do mais específico ao mais
amplo: modelo + tamanho ("LG OLED C1 55") -> marca + tamanho -> só tamanho.
OLED só é comparada com OLED (e LED com LED): misturar faria uma TV LED
comum parecer "ótimo negócio".
Usa o primeiro preço pedido de cada anúncio dos últimos 90 dias, mediana e
desvio robusto (MAD), que não se deixam levar por preços absurdos.
"""
from __future__ import annotations

import statistics
from dataclasses import dataclass
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Listing, PriceEvaluation, PriceHistory
from app.scraper.service import utcnow

WINDOW_DAYS = 90
MIN_SAMPLE = 5
GREAT_DEAL_RATIO = 0.80   # até 80% da mediana = Ótimo negócio
EXPENSIVE_RATIO = 1.15    # a partir de 115% da mediana = Caro
MIN_VALID_PRICE = 50      # "R$ 1", "R$ 10" são iscas, não preço


@dataclass
class GroupStats:
    level: str
    prices: list[float]

    @property
    def median(self) -> float:
        return statistics.median(self.prices)

    @property
    def mean(self) -> float:
        return statistics.fmean(self.prices)

    @property
    def robust_std(self) -> float:
        med = self.median
        mad = statistics.median(abs(p - med) for p in self.prices)
        return 1.4826 * mad or (statistics.pstdev(self.prices) or 0.15 * med)


def label_for(price: float, median: float) -> str:
    ratio = price / median
    if ratio <= GREAT_DEAL_RATIO:
        return "otimo_negocio"
    if ratio >= EXPENSIVE_RATIO:
        return "caro"
    return "preco_justo"


def _first_prices(db: Session, listing_ids: list[int]) -> dict[int, float]:
    first: dict[int, float] = {}
    rows = db.execute(select(PriceHistory.listing_id, PriceHistory.price)
                      .where(PriceHistory.listing_id.in_(listing_ids))
                      .order_by(PriceHistory.listing_id, PriceHistory.observed_at)).all()
    for lid, price in rows:
        first.setdefault(lid, float(price))
    return first


def _candidate_levels(l: Listing) -> list[tuple[str, list]]:
    levels = []
    if l.category_id and l.model_line and l.model_line != "OLED":
        levels.append(("modelo+tamanho", [Listing.category_id == l.category_id]))
    oled = bool(l.model_line and l.model_line.startswith("OLED"))
    tech = Listing.model_line.like("OLED%") if oled else Listing.model_line.is_(None)
    if l.brand and l.screen_size:
        levels.append(("marca+tamanho", [tech, Listing.brand == l.brand, Listing.screen_size == l.screen_size]))
    if l.screen_size:
        levels.append(("tamanho", [tech, Listing.screen_size == l.screen_size]))
    return levels


def group_stats(db: Session, l: Listing) -> GroupStats | None:
    since = utcnow() - timedelta(days=WINDOW_DAYS)
    for level, filters in _candidate_levels(l):
        ids = list(db.scalars(select(Listing.id).where(
            *filters, Listing.condition == l.condition, Listing.id != l.id,
            Listing.first_seen_at >= since)))
        if len(ids) < MIN_SAMPLE:
            continue
        prices = [p for p in _first_prices(db, ids).values() if p >= MIN_VALID_PRICE]
        if len(prices) >= MIN_SAMPLE:
            return GroupStats(level, prices)
    return None


def evaluate(db: Session, l: Listing) -> PriceEvaluation | None:
    if l.current_price is None:
        return None
    price = float(l.current_price)
    stats = group_stats(db, l) if price >= MIN_VALID_PRICE else None
    if not stats:
        ev = PriceEvaluation(listing_id=l.id, price=price, price_label="sem_base",
                             sample_size=0, evaluated_at=utcnow())
    else:
        med, std = stats.median, stats.robust_std
        ev = PriceEvaluation(
            listing_id=l.id, price=price, group_level=stats.level,
            group_median=round(med, 2), group_mean=round(stats.mean, 2),
            group_stddev=round(std, 2), sample_size=len(stats.prices),
            z_score=round((price - med) / std, 3), price_label=label_for(price, med),
            evaluated_at=utcnow(),
        )
    l.evaluations.append(ev)
    return ev


def evaluate_many(db: Session, listings: list[Listing]) -> None:
    for l in listings:
        evaluate(db, l)
    db.flush()
