"""Uso:
    python -m app.scraper.cli "TV LG OLED" --pages 2
    python -m app.scraper.cli "TV LG OLED" --mode playwright --no-details
    python -m app.scraper.cli --all          # todos os termos ativos do banco
"""
import argparse
import logging

from sqlalchemy import select

from app.db import SessionLocal, init_db
from app.models import Listing, ScrapeRun, SearchTerm
from app.scraper.fetcher import make_fetcher
from app.scraper.service import run_search


def get_or_create_term(db, query: str, pages: int, region: str) -> SearchTerm:
    term = db.scalar(select(SearchTerm).where(SearchTerm.query == query))
    if not term:
        term = SearchTerm(query=query, max_pages=pages, region=region)
        db.add(term)
        db.commit()
    term.max_pages = pages
    return term


def main() -> None:
    ap = argparse.ArgumentParser(description="Scraper OLX")
    ap.add_argument("query", nargs="?", help='Termo de busca, ex.: "TV LG OLED"')
    ap.add_argument("--all", action="store_true", help="Roda todos os termos ativos")
    ap.add_argument("--pages", type=int, default=3)
    ap.add_argument("--region", default="brasil")
    ap.add_argument("--mode", choices=["auto", "httpx", "playwright"], default="auto")
    ap.add_argument("--no-details", action="store_true", help="Não abre a página de cada anúncio")
    args = ap.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    init_db()

    with SessionLocal() as db:
        if args.all:
            terms = list(db.scalars(select(SearchTerm).where(SearchTerm.is_active.is_(True))))
        elif args.query:
            terms = [get_or_create_term(db, args.query, args.pages, args.region)]
        else:
            ap.error("informe um termo ou --all")

        fetcher = make_fetcher(args.mode)
        try:
            for term in terms:
                run: ScrapeRun = run_search(db, term, fetcher, fetch_details=not args.no_details)
                print(f"[{run.status}] '{term.query}': {run.pages_fetched} páginas, "
                      f"{run.ads_found} anúncios, {run.ads_new} novos ({run.fetch_mode})"
                      + (f" — {run.error_message}" if run.error_message else ""))
        finally:
            fetcher.close()

        print("\nÚltimos anúncios salvos:")
        for l in db.scalars(select(Listing).order_by(Listing.first_seen_at.desc()).limit(10)):
            cat = l.category.name if l.category else "sem grupo"
            print(f"  R$ {l.current_price or '?':>8} | {cat:<22} | {l.title[:60]}")


if __name__ == "__main__":
    main()
