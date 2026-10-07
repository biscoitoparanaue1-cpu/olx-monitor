"""Job diário: roda todos os termos de busca ativos.

GitHub Actions:  python -m app.jobs.daily --skip-if-done-today   (várias tentativas por dia)
Sua máquina:     python -m app.jobs.daily   (ou scripts/rodar_scraper.bat no Agendador de Tarefas)
"""
import argparse
import logging
import os
import sys

from sqlalchemy import select

from app.db import SessionLocal, init_db
from app.models import ScrapeRun, SearchTerm
from app.scraper.fetcher import make_fetcher
from app.scraper.service import run_search
from app.services import day_start_utc

# Termos criados automaticamente na primeira execução (separados por ";")
DEFAULT_TERMS = os.getenv("DEFAULT_SEARCH_TERMS", "TV LG OLED")


def seed_terms(db) -> None:
    if db.scalar(select(SearchTerm.id).limit(1)) is None:
        for q in filter(None, (t.strip() for t in DEFAULT_TERMS.split(";"))):
            db.add(SearchTerm(query=q, region="brasil", max_pages=3))
        db.commit()


def done_today(db, term: SearchTerm) -> bool:
    """Já houve hoje uma execução completa (busca + descrições) para este termo?"""
    return db.scalar(select(ScrapeRun.id).where(
        ScrapeRun.search_term_id == term.id, ScrapeRun.status == "ok",
        ScrapeRun.error_message.is_(None), ScrapeRun.started_at >= day_start_utc()).limit(1)) is not None


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--skip-if-done-today", action="store_true",
                    help="Pula termos que já rodaram completos hoje")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    init_db()
    statuses = []
    with SessionLocal() as db:
        seed_terms(db)
        terms = list(db.scalars(select(SearchTerm).where(SearchTerm.is_active.is_(True))))
        if args.skip_if_done_today:
            skipped = [t.query for t in terms if done_today(db, t)]
            terms = [t for t in terms if t.query not in skipped]
            if skipped:
                logging.info("Já concluídos hoje: %s", ", ".join(skipped))
            if not terms:
                return 0
        fetcher = make_fetcher()
        try:
            for term in terms:
                run = run_search(db, term, fetcher)
                statuses.append(run.status)
                logging.info("[%s] '%s': %s anúncios, %s novos (%s) %s", run.status, term.query,
                             run.ads_found, run.ads_new, run.fetch_mode, run.error_message or "")
        finally:
            fetcher.close()
    # Falha o job (fica vermelho no GitHub) se nenhuma busca funcionou
    return 0 if "ok" in statuses else 1


if __name__ == "__main__":
    sys.exit(main())
