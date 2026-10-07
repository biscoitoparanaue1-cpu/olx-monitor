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
