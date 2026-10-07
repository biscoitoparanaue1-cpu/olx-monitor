from datetime import timedelta

from sqlalchemy import func, select

from app.models import Listing, PriceHistory, ProductCategory, SearchTerm
from app.scraper.parser import BlockedError
from app.scraper.service import build_search_url, run_search, utcnow
from tests.conftest import SEARCH_ADS, next_data_page


class FakeFetcher:
    mode = "fake"

    def __init__(self, pages: dict[str, str], detail: str = "", blocked=False):
        self.pages, self.detail, self.blocked, self.calls = pages, detail, blocked, []

    def get(self, url):
        self.calls.append(url)
        if self.blocked:
            raise BlockedError("captcha")
        if "o=" not in url and "olx.com.br/brasil" in url:
            return self.pages["1"]
        if "olx.com.br/brasil" in url:
            return self.pages.get("2", next_data_page({"ads": []}))
        return self.detail

    def close(self): ...


def make_term(db, pages=2):
    t = SearchTerm(query="TV LG OLED", region="brasil", max_pages=pages)
    db.add(t)
    db.commit()
    return t


def test_build_url():
    t = SearchTerm(query="TV LG OLED", region="brasil", max_pages=1, min_price=500)
    assert build_search_url(t, 2) == "https://www.olx.com.br/brasil?q=TV+LG+OLED&sf=1&ps=500&o=2"


def test_run_saves_listings_and_details(db, search_html, ad_html):
    term = make_term(db)
    run = run_search(db, term, FakeFetcher({"1": search_html}, detail=ad_html))
    assert run.status == "ok" and run.ads_found == 3 and run.ads_new == 3
    assert db.scalar(select(func.count(Listing.id))) == 3
    assert db.scalar(select(func.count(PriceHistory.id))) == 3

    peças = db.scalar(select(Listing).where(Listing.olx_id == "1300000003"))
    assert "40 min" in peças.description              # veio da página de detalhe
    assert peças.category.name == "LG OLED A1 48"     # modelo descoberto na descrição
    assert peças.seller.name == "João"
    names = set(db.scalars(select(ProductCategory.name)))
    assert {"LG OLED C1 55", "LG OLED C2 65", "LG OLED A1 48"} <= names


def test_second_run_tracks_price_change(db, search_html):
    term = make_term(db)
    run_search(db, term, FakeFetcher({"1": search_html}), fetch_details=False)
    changed = [dict(a) for a in SEARCH_ADS]
    changed[0]["price"] = "R$ 1.500"
    run = run_search(db, term, FakeFetcher({"1": next_data_page({"ads": changed})}),
                     fetch_details=False)
    assert run.ads_new == 0
    tv = db.scalar(select(Listing).where(Listing.olx_id == "1300000001"))
    assert float(tv.current_price) == 1500.0
    assert [float(p.price) for p in tv.prices] == [1800.0, 1500.0]


def test_inactivates_after_7_days_missing(db, search_html):
    term = make_term(db)
    run_search(db, term, FakeFetcher({"1": search_html}), fetch_details=False)
    old = db.scalar(select(Listing).where(Listing.olx_id == "1300000003"))
    old.last_seen_at = utcnow() - timedelta(days=8)
    db.commit()
    only_two = next_data_page({"ads": SEARCH_ADS[:2]})
    run_search(db, term, FakeFetcher({"1": only_two}), fetch_details=False)
    db.refresh(old)
    assert old.is_active is False


def test_blocked_run_is_recorded(db):
    term = make_term(db)
    run = run_search(db, term, FakeFetcher({}, blocked=True))
    assert run.status == "blocked" and "captcha" in run.error_message


def test_blocked_details_keep_search_results(db, search_html):
    class DetailsBlocked(FakeFetcher):
        def get(self, url):
            if "olx.com.br/brasil" in url:
                return super().get(url)
            raise BlockedError("captcha no anúncio")

    term = make_term(db, pages=1)
    run = run_search(db, term, DetailsBlocked({"1": search_html}))
    assert run.status == "ok" and run.ads_new == 3
    assert "Detalhes bloqueados após 0 de 3" in run.error_message
    assert all(l.score is not None for l in db.scalars(select(Listing)))


def test_later_run_fetches_missing_descriptions(db, search_html, ad_html):
    class DetailsBlocked(FakeFetcher):
        def get(self, url):
            if "olx.com.br/brasil" in url:
                return super().get(url)
            raise BlockedError("captcha no anúncio")

    term = make_term(db, pages=1)
    run_search(db, term, DetailsBlocked({"1": search_html}))
    assert db.scalar(select(func.count(Listing.id)).where(Listing.description.is_(None))) == 3
    # Segunda tentativa no mesmo dia: nada novo, mas completa as descrições que faltaram
    fetcher = FakeFetcher({"1": search_html}, detail=ad_html)
    run = run_search(db, term, fetcher)
    assert run.ads_new == 0 and run.error_message is None
    assert sum("olx.com.br/brasil" not in u for u in fetcher.calls) == 3


def test_skip_if_done_today(db, monkeypatch, search_html):
    import app.jobs.daily as daily
    term = make_term(db, pages=1)
    assert not daily.done_today(db, term)
    run_search(db, term, FakeFetcher({"1": search_html}), fetch_details=False)
    assert daily.done_today(db, term)
