import html
import json
import os
import tempfile

# Banco de teste isolado (antes de importar app.*)
os.environ["DATABASE_URL"] = f"sqlite:///{tempfile.mkdtemp()}/test.db"
os.environ.pop("API_KEY", None)

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db import Base, init_db


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    init_db(engine)
    with sessionmaker(bind=engine, expire_on_commit=False)() as s:
        yield s


def next_data_page(page_props: dict) -> str:
    """HTML no formato que a OLX usa (Next.js com __NEXT_DATA__).
    Estrutura sintética: a OLX não é acessível deste ambiente de teste."""
    payload = json.dumps({"props": {"pageProps": page_props}})
    return f'<html><head></head><body><div id="__next"></div>' \
           f'<script id="__NEXT_DATA__" type="application/json">{payload}</script></body></html>'


SEARCH_ADS = [
    {"listId": 1300000001, "subject": "TV LG OLED55C1PSA 55 polegadas - desliga sozinha",
     "price": "R$ 1.800", "url": "https://sp.olx.com.br/sao-paulo/tv/tv-lg-oled-1300000001",
     "date": 1759800000, "professionalAd": False,
     "locationDetails": {"municipality": "São Paulo", "uf": "SP", "neighbourhood": "Moema"},
     "images": [{"original": "https://img.olx.com.br/1.jpg"}]},
    {"listId": 1300000002, "subject": "Smart TV LG OLED 65\" C2 tela trincada",
     "price": "R$ 2.300", "url": "https://rj.olx.com.br/rio/tv/tv-lg-oled-1300000002",
     "date": 1759810000, "professionalAd": True, "location": "Rio de Janeiro - RJ"},
    {"listId": 1300000003, "subject": "Televisão LG OLED para retirada de peças",
     "price": "R$ 900", "url": "https://mg.olx.com.br/bh/tv/tv-lg-oled-1300000003",
     "date": 1759820000},
    {"listId": 1300000001, "subject": "duplicado (banner)", "price": "R$ 1",
     "url": "https://x"},
]


@pytest.fixture
def search_html():
    return next_data_page({"ads": SEARCH_ADS, "totalOfAds": 3})


@pytest.fixture
def ad_html():
    return next_data_page({"ad": {
        "listId": 1300000003, "subject": "Televisão LG OLED para retirada de peças",
        "body": "TV LG OLED 48 polegadas modelo OLED48A1PSA. Liga mas desliga a cada 40 min.",
        "price": "R$ 900", "url": "https://mg.olx.com.br/bh/tv/tv-lg-oled-1300000003",
        "user": {"userId": "u-77", "name": "João"}, "origListTime": 1759820000}})


# ------------------------------------------------ formato atual da OLX (out/2026)
# Mesma estrutura das páginas reais capturadas pelo diagnóstico; dados fictícios.
def _props(condition: str | None, inches: str | None = "55 polegadas") -> list[dict]:
    props = [{"name": "category", "value": "TVs", "label": "Categoria"},
             {"name": "tv_video_tvs_brand", "value": "LG", "label": "Marca"},
             {"name": "tv_video_tvs_screen_type", "value": "OLED", "label": "Tipo de Tela"}]
    if condition:
        props.append({"name": "tv_video_tvs_condition", "value": condition, "label": "Condição"})
    if inches:
        props.append({"name": "tv_video_tvs_inches", "value": inches, "label": "Tamanho da TV"})
    return props


FLIGHT_ADS = [
    {"subject": "TV LG C3 OLED 55? 4K 120hz Dolby Vision", "priceValue": "R$ 4.500",
     "oldPrice": "R$ 4.700", "professionalAd": False, "listId": 1500000001,
     "lastBumpAgeSecs": "2890", "categoryName": "TVs", "date": 1791416684,
     "images": [{"original": "https://img.olx.com.br/images/11/111.jpg",
                 "originalWebp": "https://img.olx.com.br/images/11/111.webp"}],
     "location": "Boa Vista, União",
     "locationDetails": {"municipality": "Boa Vista", "ddd": "95", "neighbourhood": "União", "uf": "RR"},
     "properties": _props("Usado - Excelente"),
     "url": "https://rr.olx.com.br/roraima/tvs-e-video/tvs/tv-lg-c3-oled-55-1500000001",
     "olxPay": {"enabled": True}, "view360": {"url": None}, "zapDetails": "$undefined"},
    # Sem "url" no JSON: vem do cartão do HTML
    {"subject": "TV LG OLED C1 55 POLEGADAS - DANIFICADA", "priceValue": "R$ 1.000",
     "listId": 1500000002, "categoryName": "TVs", "date": 1791400000, "images": [],
     "location": "Porto Alegre, Teresópolis",
     "locationDetails": {"municipality": "Porto Alegre", "neighbourhood": "Teresópolis", "uf": "RS"},
     "properties": _props("Com defeito ou avarias")},
    {"subject": "Base pedestal TV OLED 48/55 LG OLED C9, CX e C1", "priceValue": "R$ 100",
     "listId": 1500000003, "categoryName": "Peças e Acessórios para TV", "date": 1791300000,
     "url": "https://df.olx.com.br/distrito-federal/tvs-e-video/base-pedestal-1500000003",
     "properties": [{"name": "category", "value": "Peças e Acessórios para TV", "label": "Categoria"}]},
]

CARD_TV2 = (
    '<section class="olx-adcard olx-adcard__horizontal"><div class="olx-adcard__content">'
    '<a data-testid="adcard-link" class="olx-adcard__link" title="TV LG OLED C1 55 POLEGADAS - DANIFICADA" '
    'href="https://rs.olx.com.br/regioes-de-porto-alegre/tvs-e-video/tvs/tv-lg-oled-c1-55-1500000002">'
    '<h2 class="olx-adcard__title">TV LG OLED C1 55 POLEGADAS - DANIFICADA</h2></a>'
    '<h3 class="typo-body-large olx-adcard__price">R$ 1.000</h3>'
    '<p class="olx-adcard__location">Porto Alegre, Teresópolis</p>'
    '<p class="olx-adcard__date">Hoje, 20:44</p></div>'
    '<div class="olx-adcard__media"><img src="https://img.olx.com.br/images/22/222.jpg" alt=""></div>'
    '</section>'
)


def flight_page(ads: list[dict], cards_html: str = "") -> str:
    """Busca no formato do Next.js app router: os dados vêm em pedaços de
    self.__next_f.push([1,"..."]), com a lista em "ads":[...]."""
    payload = '1d:["$","$L24",null,' + json.dumps({"ads": ads, "totalOfAds": len(ads)}, separators=(",", ":")) + "]\n"
    mid = len(payload) // 2
    pushes = "".join(f"<script>self.__next_f.push([1,{json.dumps(part)}])</script>"
                     for part in ("0:[\"$\",\"html\"]\n", payload[:mid], payload[mid:]))
    return (f"<html><head><title>TV LG OLED no Brasil</title>"
            f'<script type="application/ld+json">{{"@type":"WebSite"}}</script></head>'
            f"<body>{cards_html}<script>(self.__next_f=self.__next_f||[]).push([0])</script>"
            f"{pushes}</body></html>")


def initial_data_page(ad: dict) -> str:
    """Página do anúncio: JSON escapado em <script id="initial-data" data-json="...">."""
    data = html.escape(json.dumps({"ad": ad, "urls": {}, "deviceType": "desktop"}), quote=True)
    return ('<html><head><script src="/cdn-cgi/challenge-platform/scripts/jsd/main.js"></script></head>'
            f'<body><script id="initial-data" type="text/plain" data-json="{data}"></script></body></html>')


def detail_ad(list_id: int, body: str, condition: str = "Usado - Excelente", **extra) -> dict:
    ad = {"adId": 1800000000 + list_id % 1000, "listId": list_id, "body": body,
          "subject": extra.pop("subject", "TV LG OLED"), "priceValue": extra.pop("priceValue", "R$ 4.500"),
          "professionalAd": False, "origListTime": 1788624998,
          "friendlyUrl": f"https://rr.olx.com.br/roraima/tvs-e-video/tvs/tv-{list_id}",
          "user": {"userId": 31500000 + list_id % 1000, "name": "vendedor teste"},
          "images": [{"original": f"https://img.olx.com.br/images/00/{list_id}.jpg"}],
          "location": {"neighbourhood": "Centro", "municipality": "Boa Vista", "uf": "RR"},
          "properties": _props(condition)}
    ad.update(extra)
    return ad
