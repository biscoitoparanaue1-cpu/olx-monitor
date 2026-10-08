"""Regras de negócio compartilhadas pela API (FastAPI) e pelo painel (Streamlit)."""
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Feedback, FeedbackNote, FilterRule, Listing
from app.nlp.categorizer import defect_types
from app.scoring.model import learn_from_feedback
from app.scraper.service import utcnow

TZ = ZoneInfo("America/Sao_Paulo")

def day_start_utc(days_back: int = 0) -> datetime:
    """Meia-noite de Brasília (hoje - days_back), em UTC sem fuso, como no banco."""
    today = datetime.now(TZ).replace(hour=0, minute=0, second=0, microsecond=0)
    return (today - timedelta(days=days_back)).astimezone(timezone.utc).replace(tzinfo=None)


def passes_rules(l: Listing, include_ids: set[int], exclude_ids: set[int]) -> bool:
    matched = {m.rule_id for m in l.rule_matches}
    if matched & exclude_ids:
        return False
    return not include_ids or bool(matched & include_ids)


def rank_key(l: Listing):
    # Score primeiro; sem score ainda, o mais barato em relação ao grupo
    ev = l.latest_evaluation
    z = ev.z_score if ev and ev.z_score is not None else 0.0
    return (-(l.score.score if l.score else float("-inf")), z)


def top_listings(db: Session, days: int = 1, limit: int = 20, hide_disliked: bool = True,
                 defect_filter: set[str] | None = None) -> list[Listing]:
    """Melhores anúncios vistos pela primeira vez nos últimos `days` dias (1 = só hoje).
    defect_filter: só os que têm pelo menos um desses tipos de defeito (chaves de DEFECT_TYPES)."""
    listings = db.scalars(select(Listing).where(
        Listing.first_seen_at >= day_start_utc(days - 1), Listing.is_active.is_(True))).all()
    rules = db.scalars(select(FilterRule).where(FilterRule.is_active.is_(True))).all()
    include = {r.id for r in rules if r.action == "include"}
    exclude = {r.id for r in rules if r.action == "exclude"}
    kept = [l for l in listings if passes_rules(l, include, exclude) and
            not (hide_disliked and l.feedback and l.feedback.value == -1) and
            (not defect_filter or defect_filter & set(defect_types(l)))]
    kept.sort(key=rank_key)
    return kept[:limit]


def set_feedback(db: Session, listing: Listing, value: int) -> Feedback:
    """Grava 👍 (1) ou 👎 (-1). Clicar de novo troca a opinião."""
    if value not in (-1, 1):
        raise ValueError("value deve ser 1 ou -1")
    fb = db.scalar(select(Feedback).where(Feedback.listing_id == listing.id))
    if fb:
        fb.value, fb.created_at = value, utcnow()
    else:
        fb = Feedback(listing_id=listing.id, value=value, created_at=utcnow())
        db.add(fb)
    fb.score_at_time = listing.score.score if listing.score else None
    db.commit()
    learn_from_feedback(db)
    return fb


def save_note(db: Session, listing: Listing, liked: str, disliked: str) -> FeedbackNote | None:
    """Grava o que você gostou / não gostou no anúncio e reaprende. Tudo vazio apaga."""
    liked, disliked = (liked or "").strip() or None, (disliked or "").strip() or None
    note = db.scalar(select(FeedbackNote).where(FeedbackNote.listing_id == listing.id))
    if not liked and not disliked:
        if note:
            db.delete(note)
        note = None
    elif note:
        note.liked, note.disliked, note.updated_at = liked, disliked, utcnow()
    else:
        note = FeedbackNote(listing_id=listing.id, liked=liked, disliked=disliked, updated_at=utcnow())
        db.add(note)
    db.commit()
    learn_from_feedback(db)
    return note


def clear_feedback(db: Session, listing_id: int) -> None:
    fb = db.scalar(select(Feedback).where(Feedback.listing_id == listing_id))
    if fb:
        db.delete(fb)
        db.commit()
        learn_from_feedback(db)
