"""Formato atual da OLX: busca com payload do Next.js e anúncio com initial-data."""
from sqlalchemy import func, select

from app.models import Listing, PriceHistory, ProductCategory
from app.nlp.categorizer import declared_condition
from app.scraper.parser import parse_ad_page, parse_search_page
from app.scraper.service import DETAIL_VERSION, run_search
from tests.conftest import CARD_TV2, FLIGHT_ADS, detail_ad, flight_page, initial_data_page
from tests.test_service import make_term

TV1, TV2 = "1500000001", "1500000002"


class SiteFetcher:
    """Busca na página 1; anúncios pelo id no fim da URL."""
    mode = "fake"

    def __init__(self, search: str, details: dict[str, str]):
        self.search, self.details, self.calls = search, details, []

    def get(self, url):
        self.calls.append(url)
        if "olx.com.br/brasil" in url:
            return self.search if "o=" not in url else flight_page([])
        return self.details[url.rsplit("-", 1)[-1]]

    def close(self): ...


def details() -> dict[str, str]:
    return {
        TV1: initial_data_page(detail_ad(int(TV1), "Linda TV LG C3 OLED de 55 polegadas, sem nenhum risco.",
                                         subject=FLIGHT_ADS[0]["subject"])),
        TV2: initial_data_page(detail_ad(int(TV2), "Liga mas desliga a cada 40min. Tela ok.",
                                         condition="Com defeito ou avarias", priceValue="R$ 1.000",
                                         subject=FLIGHT_ADS[1]["subject"])),
    }


def test_search_page_reads_next_payload():
    ads = parse_search_page(flight_page(FLIGHT_ADS, CARD_TV2))
    assert [a.olx_id for a in ads] == [TV1, TV2, "1500000003"]
    a = ads[0]
    assert a.price == 4500.0 and a.image_url.endswith("111.jpg")
    assert a.state == "RR" and a.location == "União, Boa Vista, RR"
    assert a.properties["tv_video_tvs_condition"] == "Usado - Excelente"
    assert a.posted_at is not None and "zapDetails" not in a.raw
    # Link e foto que faltavam no JSON vêm do cartão do HTML
    assert ads[1].url.endswith("-1500000002") and ads[1].image_url.endswith("222.jpg")


def test_search_page_from_cards_only():
    ads = parse_search_page(f"<html><body>{CARD_TV2}</body></html>")
    assert len(ads) == 1
    assert (ads[0].price, ads[0].state) == (1000.0, "RS")
    assert ads[0].title == "TV LG OLED C1 55 POLEGADAS - DANIFICADA"
    assert ads[0].image_url.endswith("222.jpg")


def test_ad_page_initial_data():
    ad = parse_ad_page(details()[TV2])
    assert ad.olx_id == TV2 and ad.price == 1000.0 and "40min" in ad.description
    assert ad.properties["tv_video_tvs_condition"] == "Com defeito ou avarias"
    assert ad.seller_name == "vendedor teste" and ad.state == "RR"


def test_declared_condition():
    assert declared_condition("Com defeito ou avarias") == "defeito"
    assert declared_condition("Usado - Excelente") == "usado_bom"
    assert declared_condition("Novo") == "novo"
    assert declared_condition(None) is None


def test_run_with_current_format(db):
    term = make_term(db, pages=1)
    run = run_search(db, term, SiteFetcher(flight_page(FLIGHT_ADS, CARD_TV2), details()))
    assert run.status == "ok" and run.error_message is None
    # A base de TV (acessório) fica de fora
    assert set(db.scalars(select(Listing.olx_id))) == {TV1, TV2}

    tv1 = db.scalar(select(Listing).where(Listing.olx_id == TV1))
    assert float(tv1.current_price) == 4500.0 and tv1.image_url and tv1.state == "RR"
    assert tv1.category.name == "LG OLED C3 55"
    assert tv1.condition == "usado_bom"           # "sem nenhum risco" não é avaria
    assert tv1.seller.name == "vendedor teste"
    assert tv1.raw_json["_detail_v"] == DETAIL_VERSION

    tv2 = db.scalar(select(Listing).where(Listing.olx_id == TV2))
    assert tv2.category.name == "LG OLED C1 55"
    assert tv2.condition == "defeito" and "40min" in tv2.description
    assert tv2.latest_evaluation is not None and tv2.score is not None


def test_repairs_listings_saved_by_old_parser(db):
    """Anúncios salvos antes da correção: sem preço/foto e com dados trocados."""
    term = make_term(db, pages=1)
    wrong = db.scalar(select(ProductCategory).where(ProductCategory.name == "LG OLED C4 55"))
    wrong = wrong or ProductCategory(name="LG OLED C4 55", brand="LG", model_line="OLED C4", screen_size=55)
    for olx_id, title in ((TV1, FLIGHT_ADS[0]["subject"]), (TV2, FLIGHT_ADS[1]["subject"])):
        db.add(Listing(olx_id=olx_id, search_term_id=term.id, title=title, url=f"https://x/{olx_id}",
                       description="TV LG OLED C4 55 com riscos", model_line="OLED C4",
                       screen_size=55, brand="LG", category=wrong, condition="usado_com_avaria"))
    db.commit()

    fetcher = SiteFetcher(flight_page(FLIGHT_ADS, CARD_TV2), details())
    run_search(db, term, fetcher)
    assert sum("olx.com.br/brasil" not in u for u in fetcher.calls) == 2  # releu as duas páginas

    tv1 = db.scalar(select(Listing).where(Listing.olx_id == TV1))
    assert float(tv1.current_price) == 4500.0 and tv1.image_url
    assert tv1.url.endswith("-1500000001") and "C4" not in tv1.description
    assert (tv1.category.name, tv1.condition) == ("LG OLED C3 55", "usado_bom")
    tv2 = db.scalar(select(Listing).where(Listing.olx_id == TV2))
    assert (tv2.category.name, tv2.condition) == ("LG OLED C1 55", "defeito")
    assert db.scalar(select(func.count(PriceHistory.id))) == 2

    # Na próxima execução não relê as páginas dos anúncios
    again = SiteFetcher(flight_page(FLIGHT_ADS, CARD_TV2), details())
    run_search(db, term, again)
    assert all("olx.com.br/brasil" in u for u in again.calls)


def test_detail_page_of_another_ad_is_ignored(db):
    term = make_term(db, pages=1)
    pages = details()
    pages[TV2] = pages[TV1]  # a OLX devolveu outro anúncio
    run_search(db, term, SiteFetcher(flight_page(FLIGHT_ADS[:2], CARD_TV2), pages))
    tv2 = db.scalar(select(Listing).where(Listing.olx_id == TV2))
    assert tv2.description is None and tv2.condition == "defeito"  # ficha da busca ainda vale
