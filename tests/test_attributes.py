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


def test_category_name():
    assert extract_attributes("LG OLED55C1").category_name == "LG OLED C1 55"
    assert extract_attributes("TV OLED LG 48 pol").category_name == "LG OLED 48"
    assert extract_attributes("TV com garantia").category_name is None
