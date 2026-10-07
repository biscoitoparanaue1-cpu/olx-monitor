"""Orquestra uma busca: baixa páginas, salva/atualiza anúncios e histórico."""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from urllib.parse import urlencode

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import config
from app.models import Listing, PriceHistory, ProductCategory, ScrapeRun, SearchTerm, Seller
from app.scraper.attributes import TvAttributes, extract_attributes
from app.scraper.fetcher import Fetcher
from app.scraper.parser import BlockedError, RawAd, parse_ad_page, parse_search_page

log = logging.getLogger(__name__)


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def build_search_url(term: SearchTerm, page: int = 1) -> str:
    params: dict[str, str | int] = {"q": term.query, "sf": 1}  # sf=1: mais recentes primeiro
    if term.min_price:
        params["ps"] = int(term.min_price)
    if term.max_price:
        params["pe"] = int(term.max_price)
    if page > 1:
        params["o"] = page
    region = term.region or config.OLX_REGION
    return f"{config.OLX_BASE_URL}/{region}?{urlencode(params)}"


def get_or_create_category(db: Session, brand, model_line, size) -> ProductCategory | None:
    name = TvAttributes(brand=brand, model_line=model_line, screen_size=size).category_name
    if not name:
        return None
    cat = db.scalar(select(ProductCategory).where(ProductCategory.name == name))
    if not cat:
        cat = ProductCategory(name=name, brand=brand, model_line=model_line, screen_size=size)
        db.add(cat)
        db.flush()
    return cat


def _get_or_create_seller(db: Session, ad: RawAd) -> Seller | None:
    if not ad.seller_id:
        return None
    seller = db.scalar(select(Seller).where(Seller.olx_seller_id == ad.seller_id))
    if not seller:
        seller = Seller(olx_seller_id=ad.seller_id, name=ad.seller_name,
                        is_professional=ad.is_professional, location=ad.location)
        db.add(seller)
        db.flush()
    return seller


def upsert_listing(db: Session, ad: RawAd, term: SearchTerm, run: ScrapeRun) -> tuple[Listing, bool]:
    """Cria ou atualiza o anúncio. Retorna (listing, é_novo)."""
    now = utcnow()
    listing = db.scalar(select(Listing).where(Listing.olx_id == ad.olx_id))
    is_new = listing is None

    if is_new:
        attrs = extract_attributes(ad.title, ad.description or "")
        cat = get_or_create_category(db, attrs.brand, attrs.model_line, attrs.screen_size)
        listing = Listing(
            olx_id=ad.olx_id, search_term_id=term.id, title=ad.title, url=ad.url,
            description=ad.description, current_price=ad.price, location=ad.location,
            state=ad.state, image_url=ad.image_url, posted_at=ad.posted_at,
            brand=attrs.brand, model_line=attrs.model_line, model_code=attrs.model_code,
            screen_size=attrs.screen_size, category=cat,
            seller=_get_or_create_seller(db, ad), raw_json=ad.raw or None,
            first_seen_at=now, last_seen_at=now, is_active=True,
        )
        db.add(listing)
        db.flush()
    else:
        listing.last_seen_at = now
        listing.is_active = True
        listing.title = ad.title or listing.title
        if ad.description and not listing.description:
            listing.description = ad.description

    price_changed = ad.price is not None and (
        is_new or listing.current_price is None or float(listing.current_price) != ad.price)
    if price_changed:
        listing.current_price = ad.price
        db.add(PriceHistory(listing_id=listing.id, price=ad.price,
                            observed_at=now, scrape_run_id=run.id))
    return listing, is_new


def enrich_with_details(db: Session, fetcher: Fetcher, listing: Listing) -> None:
    """Abre a página do anúncio para pegar descrição completa e vendedor."""
    detail = parse_ad_page(fetcher.get(listing.url))
    if not detail:
        return
    listing.description = detail.description or listing.description
    listing.posted_at = listing.posted_at or detail.posted_at
    if not listing.seller:
        listing.seller = _get_or_create_seller(db, detail)
    if detail.description:
        # A descrição pode revelar o modelo/tamanho que o título omitiu
        attrs = extract_attributes(listing.title, detail.description)
        listing.model_code = listing.model_code or attrs.model_code
        listing.screen_size = listing.screen_size or attrs.screen_size
        if attrs.model_line and listing.model_line in (None, "OLED"):
            listing.model_line = attrs.model_line
        listing.brand = listing.brand or attrs.brand


def run_search(db: Session, term: SearchTerm, fetcher: Fetcher,
               fetch_details: bool = config.FETCH_DETAILS_FOR_NEW) -> ScrapeRun:
    run = ScrapeRun(search_term_id=term.id, status="running", fetch_mode=fetcher.mode)
    db.add(run)
    db.commit()
    seen_ids: set[str] = set()
    new_listings: list[Listing] = []
    touched: list[Listing] = []

    try:
        for page in range(1, term.max_pages + 1):
            url = build_search_url(term, page)
            log.info("Buscando %s", url)
            ads = parse_search_page(fetcher.get(url))
            run.pages_fetched += 1
            run.fetch_mode = fetcher.mode
            if not ads:
                break
            for ad in ads:
                if ad.olx_id in seen_ids:
                    continue
                seen_ids.add(ad.olx_id)
                listing, is_new = upsert_listing(db, ad, term, run)
                touched.append(listing)
                if is_new:
                    new_listings.append(listing)
            db.commit()

        detail_note = None
        if fetch_details:
            # Novos e os que ficaram sem descrição em execuções anteriores (ex.: bloqueio)
            pending = [l for l in touched if not l.description][:config.MAX_DETAILS_PER_RUN]
            for i, listing in enumerate(pending):
                try:
                    enrich_with_details(db, fetcher, listing)
                    # Atualiza o grupo de preço com o que a descrição revelou
                    listing.category = get_or_create_category(
                        db, listing.brand, listing.model_line, listing.screen_size)
                    db.commit()
                except BlockedError as exc:
                    # A busca já foi salva; só para de abrir anúncios por hoje
                    db.rollback()
                    detail_note = (f"Detalhes bloqueados após {i} de {len(pending)} "
                                   f"anúncios sem descrição: {exc}")
                    log.warning(detail_note)
                    break
                except Exception as exc:  # um anúncio ruim não derruba a execução
                    log.warning("Falha no detalhe de %s: %s", listing.olx_id, exc)
                    db.rollback()

        run.status, run.error_message = "ok", detail_note
    except BlockedError as exc:
        db.rollback()
        run.status, run.error_message = "blocked", str(exc)
    except Exception as exc:
        db.rollback()
        run.status, run.error_message = "error", repr(exc)
        log.exception("Erro na busca '%s'", term.query)

    # Só marca como inativo (vendido/removido) se a busca rodou completa
    if run.status == "ok" and seen_ids:
        for listing in db.scalars(select(Listing).where(
                Listing.search_term_id == term.id, Listing.is_active.is_(True))):
            # Pode só ter saído das primeiras N páginas; só inativa após 7 dias sem ver
            if listing.olx_id not in seen_ids and (utcnow() - listing.last_seen_at).days >= 7:
                listing.is_active = False

    # Estado do item, avaliação de preço e score (mesmo se a busca parou no meio)
    try:
        from app.pipeline import needs_processing, process
        process(db, [l for l in touched if needs_processing(l)])
    except Exception:
        db.rollback()
        log.exception("Falha no pós-processamento")

    run.fetch_mode = fetcher.mode  # pode ter trocado para Playwright no meio
    run.ads_found = len(seen_ids)
    run.ads_new = len(new_listings)
    run.finished_at = utcnow()
    db.add(run)
    db.commit()
    return run
