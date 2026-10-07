"""Job diário: roda todos os termos de busca ativos.

Na nuvem é executado pelo Cloud Run Job, disparado pelo Cloud Scheduler.
Local: python -m app.jobs.daily
"""
import logging
import os
import sys

from sqlalchemy import select

from app.db import SessionLocal, init_db
from app.models import SearchTerm
from app.scraper.fetcher import make_fetcher
from app.scraper.service import run_search

# Termos criados automaticamente na primeira execução (separados por ";")
DEFAULT_TERMS = os.getenv("DEFAULT_SEARCH_TERMS", "TV LG OLED")


def seed_terms(db) -> None:
    if db.scalar(select(SearchTerm.id).limit(1)) is None:
        for q in filter(None, (t.strip() for t in DEFAULT_TERMS.split(";"))):
            db.add(SearchTerm(query=q, region="brasil", max_pages=3))
        db.commit()


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    init_db()
    statuses = []
    with SessionLocal() as db:
        seed_terms(db)
        terms = list(db.scalars(select(SearchTerm).where(SearchTerm.is_active.is_(True))))
        fetcher = make_fetcher()
        try:
            for term in terms:
                run = run_search(db, term, fetcher)
                statuses.append(run.status)
                logging.info("[%s] '%s': %s anúncios, %s novos (%s) %s", run.status, term.query,
                             run.ads_found, run.ads_new, run.fetch_mode, run.error_message or "")
        finally:
            fetcher.close()
    # Falha o job (aparece vermelho no Cloud Run) se nenhuma busca funcionou
    return 0 if "ok" in statuses else 1


if __name__ == "__main__":
    sys.exit(main())
