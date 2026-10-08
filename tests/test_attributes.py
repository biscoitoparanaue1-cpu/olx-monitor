import pytest

from app.scraper.attributes import extract_attributes


@pytest.mark.parametrize("title,desc,brand,line,code,size", [
    ("TV LG OLED55C1PSA defeito", "", "LG", "OLED C1", "OLED55C1", 55),
    ("Smart TV LG OLED 65\" C2 tela trincada", "", "LG", "OLED C2", None, 65),
    ("LG OLED evo C3 77 polegadas", "", "LG", "OLED C3", None, 77),
    ("TV OLED LG 48 pol", "", "LG", "OLED", None, 48),
    ("Televisão LG OLED p/ peças", "modelo OLED48A1PSA", "LG", "OLED A1", "OLED48A1", 48),
    ("tv lg oled65cxpsa", "", "LG", "OLED CX", "OLED65CX", 65),
    ("Samsung QLED 55'' Q80T", "", "SAMSUNG", None, None, 55),
    ("Televisão 4K com garantia", "", None, None, None, None),
])
def test_extract(title, desc, brand, line, code, size):
    a = extract_attributes(title, desc)
    assert (a.brand, a.model_line, a.model_code, a.screen_size) == (brand, line, code, size)


def test_listing_properties():
    props = {"tv_video_tvs_brand": "LG", "tv_video_tvs_inches": "55 polegadas",
             "tv_video_tvs_screen_type": "OLED"}
    # Título real da OLX: aspas viraram "?" e a linha vem antes de "OLED"
    a = extract_attributes("TV LG C3 OLED 55? 4K 120hz Dolby Vision", "", props)
    assert (a.brand, a.model_line, a.screen_size) == ("LG", "OLED C3", 55)
    # Ficha diz OLED, mas o texto não: muitas TVs LED vêm marcadas assim
    a = extract_attributes("Smart TV 4K Aceito cartão", "", props)
    assert (a.brand, a.model_line, a.screen_size) == ("LG", None, 55)
    assert extract_attributes("Smart TV 4K", "Tela OLED perfeita", props).model_line == "OLED"
    assert extract_attributes("TV LG C2 55 polegadas", "", props).model_line == "OLED C2"
    assert extract_attributes("Smart tv LG 55 Pol oled gamer C3", "", props).model_line == "OLED C3"
    # Código de TV LED vence a ficha e a palavra OLED solta
    assert extract_attributes("Smart TV LG UHD 55AU801 tipo OLED", "", props).model_line is None
    # Código do modelo vence a ficha
    assert extract_attributes("LG OLED48A1PSA", "", props).screen_size == 48
    # Sem OLED, "LG C1" não é linha OLED
    assert extract_attributes("Celular LG K10", "").model_line is None


def test_category_name():
    assert extract_attributes("LG OLED55C1").category_name == "LG OLED C1 55"
    assert extract_attributes("TV OLED LG 48 pol").category_name == "LG OLED 48"
    assert extract_attributes("TV com garantia").category_name is None
