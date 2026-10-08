"""Pós-captura: estado do item -> avaliação de preço -> score."""
from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Listing
from app.nlp.categorizer import apply_categorization
from app.pricing.evaluator import evaluate_many
from app.scoring.model import rescore

log = logging.getLogger(__name__)


def process(db: Session, listings: list[Listing]) -> int:
    if not listings:
        return 0
    apply_categorization(db, listings)
    evaluate_many(db, listings)
    rescore(db, listings)
    db.commit()
    return len(listings)


def reprocess_all(db: Session) -> int:
    """Reaplica regras, preço e score em todos os anúncios ativos (ex.: após mudar regras)."""
    listings = list(db.scalars(select(Listing).where(Listing.is_active.is_(True))
                               .order_by(Listing.first_seen_at)))
    return process(db, listings)
