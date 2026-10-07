import pytest

from app.scraper.parser import BlockedError, parse_ad_page, parse_price, parse_search_page


def test_parse_price():
    assert parse_price("R$ 2.499") == 2499.0
    assert parse_price("R$ 1.234,56") == 1234.56
    assert parse_price(800) == 800.0
    assert parse_price("") is None


def test_search_page(search_html):
    ads = parse_search_page(search_html)
    assert [a.olx_id for a in ads] == ["1300000001", "1300000002", "1300000003"]  # sem duplicado
    a = ads[0]
    assert a.price == 1800.0 and a.state == "SP" and a.location == "Moema, São Paulo, SP"
    assert a.posted_at.year == 2025 and a.image_url.endswith("1.jpg")
    assert ads[1].state == "RJ" and ads[1].is_professional is True


def test_ad_page(ad_html):
    ad = parse_ad_page(ad_html)
    assert "desliga a cada 40 min" in ad.description
    assert ad.seller_id == "u-77" and ad.seller_name == "João"


def test_blocked_page():
    with pytest.raises(BlockedError):
        parse_search_page("<html><title>Just a moment...</title><div class='cf-chl'></div></html>")


def test_html_fallback():
    html = '<a href="https://sp.olx.com.br/tv/tv-lg-oled-c1-1311112222" title="TV LG OLED C1">' \
           '<span>R$ 2.000</span></a>'
    ads = parse_search_page(html)
    assert ads[0].olx_id == "1311112222" and ads[0].price == 2000.0


def test_empty_database_url_falls_back_to_sqlite(monkeypatch):
    import importlib

    import app.config as config
    monkeypatch.setenv("DATABASE_URL", "")
    assert importlib.reload(config).DATABASE_URL.startswith("sqlite:///")
    monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@host/db?sslmode=require")
    assert importlib.reload(config).DATABASE_URL.startswith("postgresql+psycopg://")
    monkeypatch.undo()
    importlib.reload(config)


def test_cloudflare_script_on_normal_page_is_not_a_block(ad_html):
    page = ad_html.replace("<head></head>",
                           '<head><script src="/cdn-cgi/challenge-platform/scripts/jsd/main.js"></script></head>')
    assert parse_ad_page(page).olx_id == "1300000003"
