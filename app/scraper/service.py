"""Orquestra uma busca: baixa páginas, salva/atualiza anúncios e histórico."""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from urllib.parse import urlencode

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import config
from app.models import Listing, PriceHistory, ProductCategory, ScrapeRun, SearchTerm, Seller
from app.scraper.attributes import TvAttributes, extract_attributes, normalize
from app.scraper.fetcher import Fetcher
from app.scraper.parser import BlockedError, RawAd, parse_ad_page, parse_search_page

log = logging.getLogger(__name__)

# Sobe quando a leitura da página do anúncio muda: os anúncios já salvos são relidos
DETAIL_VERSION = 2


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


def is_tv_ad(ad: RawAd) -> bool:
    """A busca "TV LG OLED" também traz bases, controles e capas ("Peças e Acessórios para TV")."""
    return "ACESSORIO" not in normalize(ad.raw.get("categoryName") or "")


def _merge_raw(listing: Listing, ad: RawAd) -> None:
    raw = dict(listing.raw_json or {})
    raw.update(ad.raw)
    if ad.properties:
        raw["properties"] = {**(raw.get("properties") or {}), **ad.properties}
    listing.raw_json = raw  # objeto novo: o SQLAlchemy só percebe a mudança assim


def refresh_attributes(db: Session, listing: Listing) -> None:
    """Recalcula marca/linha/tamanho e o grupo de preço com tudo o que se sabe do anúncio."""
    props = (listing.raw_json or {}).get("properties") or {}
    a = extract_attributes(listing.title, listing.description or "", props)
    listing.brand, listing.model_line, listing.model_code, listing.screen_size = (
        a.brand, a.model_line, a.model_code, a.screen_size)
    listing.category = get_or_create_category(db, a.brand, a.model_line, a.screen_size)


def _record_price(db: Session, listing: Listing, price: float | None, run_id: int | None) -> None:
    if price is None:
        return
    if listing.current_price is None or float(listing.current_price) != price:
        listing.current_price = price
        db.add(PriceHistory(listing_id=listing.id, price=price, observed_at=utcnow(),
                            scrape_run_id=run_id))


def upsert_listing(db: Session, ad: RawAd, term: SearchTerm, run: ScrapeRun) -> tuple[Listing, bool]:
    """Cria ou atualiza o anúncio. Retorna (listing, é_novo)."""
    now = utcnow()
    listing = db.scalar(select(Listing).where(Listing.olx_id == ad.olx_id))
    is_new = listing is None

    if is_new:
        listing = Listing(
            olx_id=ad.olx_id, search_term_id=term.id, title=ad.title, url=ad.url,
            description=ad.description, location=ad.location, state=ad.state,
            image_url=ad.image_url, posted_at=ad.posted_at,
            seller=_get_or_create_seller(db, ad), first_seen_at=now, last_seen_at=now, is_active=True,
        )
        db.add(listing)
        db.flush()
    else:
        listing.last_seen_at = now
        listing.is_active = True
        listing.title = ad.title or listing.title
        listing.url = ad.url or listing.url
        listing.image_url = ad.image_url or listing.image_url
        listing.location = ad.location or listing.location
        listing.state = ad.state or listing.state
        listing.posted_at = listing.posted_at or ad.posted_at
        if ad.description and not listing.description:
            listing.description = ad.description

    _merge_raw(listing, ad)
    refresh_attributes(db, listing)
    _record_price(db, listing, ad.price, run.id)
    return listing, is_new


def needs_details(listing: Listing) -> bool:
    """Página do anúncio ainda não lida (ex.: bloqueio) ou lida por uma versão antiga do parser."""
    return (listing.raw_json or {}).get("_detail_v") != DETAIL_VERSION


def enrich_with_details(db: Session, fetcher: Fetcher, listing: Listing,
                        run_id: int | None = None) -> None:
    """Abre a página do anúncio: descrição completa, ficha, vendedor e data original."""
    detail = parse_ad_page(fetcher.get(listing.url))
    if detail and detail.olx_id and detail.olx_id != listing.olx_id:
        log.warning("A página de %s trouxe o anúncio %s; ignorando", listing.olx_id, detail.olx_id)
        if needs_details(listing):  # descrição de antes da checagem pode ter vindo da página errada
            listing.description = None
        detail = None
    if detail:
        listing.title = detail.title or listing.title
        if detail.description:
            listing.description = detail.description
        listing.posted_at = detail.posted_at or listing.posted_at
        listing.image_url = detail.image_url or listing.image_url
        listing.location = detail.location or listing.location
        listing.state = detail.state or listing.state
        if detail.seller_id:
            listing.seller = _get_or_create_seller(db, detail)
        _record_price(db, listing, detail.price, run_id)
        _merge_raw(listing, detail)
    raw = dict(listing.raw_json or {})
    raw["_detail_v"] = DETAIL_VERSION  # mesmo sem dados (anúncio removido): não tenta de novo
    listing.raw_json = raw
    # A descrição e a ficha podem revelar o modelo/tamanho que o título omitiu
    refresh_attributes(db, listing)


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
                if not is_tv_ad(ad):
                    # Acessório: não entra (e sai do painel, se tiver entrado antes)
                    old = db.scalar(select(Listing).where(Listing.olx_id == ad.olx_id))
                    if old:
                        old.is_active = False
                    continue
                listing, is_new = upsert_listing(db, ad, term, run)
                touched.append(listing)
                if is_new:
                    new_listings.append(listing)
            db.commit()

        detail_note = None
        if fetch_details:
            # Os sem descrição primeiro; depois os lidos por uma versão antiga do parser
            pending = sorted((l for l in touched if needs_details(l)),
                             key=lambda l: l.description is not None)[:config.MAX_DETAILS_PER_RUN]
            for i, listing in enumerate(pending):
                try:
                    enrich_with_details(db, fetcher, listing, run.id)
                    db.commit()
                except BlockedError as exc:
                    # A busca já foi salva; só para de abrir anúncios por hoje
                    db.rollback()
                    detail_note = (f"Detalhes bloqueados após {i} de {len(pending)} "
                                   f"anúncios a abrir: {exc}")
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

    # Estado do item, avaliação de preço e score de tudo o que foi visto hoje (mesmo se a
    # busca parou no meio): a ficha, a descrição e o grupo de comparação podem ter mudado
    try:
        from app.pipeline import process
        process(db, [l for l in touched if l.is_active])
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
