from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.api.deps import get_db, require_api_key
from app.models import Listing, ScrapeRun, SearchTerm
from app.scraper.parser import RawAd
from app.scraper.service import upsert_listing, utcnow
from app.pipeline import process
from app.services import rank_key, top_listings
from app.schemas import (
    IngestIn, IngestOut, ListingDetail, ListingOut, ListingPage, PriceEvalOut, PricePoint,
    RuleMatchOut,
)

router = APIRouter(prefix="/api/listings", tags=["anúncios"])


def to_out(l: Listing, detail: bool = False) -> ListingOut | ListingDetail:
    ev = l.latest_evaluation
    data = dict(
        id=l.id, olx_id=l.olx_id, title=l.title, url=l.url,
        current_price=float(l.current_price) if l.current_price is not None else None,
        location=l.location, state=l.state, image_url=l.image_url, brand=l.brand,
        model_line=l.model_line, model_code=l.model_code, screen_size=l.screen_size,
        category=l.category.name if l.category else None, condition=l.condition,
        posted_at=l.posted_at, first_seen_at=l.first_seen_at, is_active=l.is_active,
        score=l.score.score if l.score else None,
        price_evaluation=PriceEvalOut.model_validate(ev) if ev else None,
        feedback=l.feedback.value if l.feedback else None,
        rule_matches=[RuleMatchOut(rule_id=m.rule_id, name=m.rule.name, matched_text=m.matched_text)
                      for m in l.rule_matches],
    )
    if not detail:
        return ListingOut(**data)
    return ListingDetail(
        **data, description=l.description,
        seller_name=l.seller.name if l.seller else None,
        seller_is_professional=l.seller.is_professional if l.seller else None,
        price_history=[PricePoint(price=float(p.price), observed_at=p.observed_at) for p in l.prices],
        score_features=l.score.features_json if l.score else None,
    )


@router.get("/top", response_model=list[ListingOut], summary="Melhores anúncios do dia")
def top(days: int = Query(1, ge=1, le=30, description="1 = só hoje"),
        limit: int = Query(20, ge=1, le=100), db: Session = Depends(get_db)):
    return [to_out(l) for l in top_listings(db, days, limit)]


@router.get("", response_model=ListingPage, summary="Buscar e filtrar anúncios")
def list_listings(
    q: str | None = Query(None, description="Texto no título ou descrição"),
    category_id: int | None = None, condition: str | None = None,
    price_label: str | None = Query(None, description="otimo_negocio | preco_justo | caro"),
    screen_size: int | None = None, state: str | None = None,
    min_price: float | None = None, max_price: float | None = None,
    feedback: int | None = Query(None, description="1, -1 ou 0 (sem feedback)"),
    active: bool | None = True,
    order: str = Query("recent", pattern="^(recent|price|score)$"),
    offset: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
):
    stmt = select(Listing)
    if q:
        like = f"%{q}%"
        stmt = stmt.where(or_(Listing.title.ilike(like), Listing.description.ilike(like)))
    if category_id:
        stmt = stmt.where(Listing.category_id == category_id)
    if condition:
        stmt = stmt.where(Listing.condition == condition)
    if screen_size:
        stmt = stmt.where(Listing.screen_size == screen_size)
    if state:
        stmt = stmt.where(Listing.state == state.upper())
    if min_price is not None:
        stmt = stmt.where(Listing.current_price >= min_price)
    if max_price is not None:
        stmt = stmt.where(Listing.current_price <= max_price)
    if active is not None:
        stmt = stmt.where(Listing.is_active.is_(active))

    rows = db.scalars(stmt).all()
    # Filtros que dependem de relações (poucos milhares de linhas: Python resolve bem)
    if price_label:
        rows = [l for l in rows if l.latest_evaluation and l.latest_evaluation.price_label == price_label]
    if feedback is not None:
        rows = [l for l in rows if (l.feedback.value if l.feedback else 0) == feedback]

    if order == "price":
        rows.sort(key=lambda l: (l.current_price is None, l.current_price or 0))
    elif order == "score":
        rows.sort(key=rank_key)
    else:
        rows.sort(key=lambda l: l.first_seen_at, reverse=True)
    return ListingPage(total=len(rows), items=[to_out(l) for l in rows[offset:offset + limit]])


@router.get("/{listing_id}", response_model=ListingDetail, summary="Detalhe com histórico de preço")
def get_listing(listing_id: int, db: Session = Depends(get_db)):
    l = db.get(Listing, listing_id)
    if not l:
        raise HTTPException(404, "Anúncio não encontrado")
    return to_out(l, detail=True)


@router.post("/ingest", response_model=IngestOut, dependencies=[Depends(require_api_key)],
             summary="Receber anúncios de um scraper externo")
def ingest(payload: IngestIn, db: Session = Depends(get_db)):
    term = db.scalar(select(SearchTerm).where(SearchTerm.query == payload.search_query))
    if not term:
        term = SearchTerm(query=payload.search_query)
        db.add(term)
        db.flush()
    run = ScrapeRun(search_term_id=term.id, status="running", fetch_mode="external")
    db.add(run)
    db.flush()
    new, touched = 0, []
    for ad in payload.ads:
        listing, is_new = upsert_listing(db, RawAd(**ad.model_dump()), term, run)
        new += is_new
        touched.append(listing)
    run.status, run.ads_found, run.ads_new, run.finished_at = "ok", len(payload.ads), new, utcnow()
    db.commit()
    process(db, touched)
    return IngestOut(received=len(payload.ads), new=new, scrape_run_id=run.id)
