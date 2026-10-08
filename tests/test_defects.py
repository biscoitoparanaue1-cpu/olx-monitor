"""Tipos de defeito: estado do item, filtro do painel e características do score."""
import pytest

from app.models import Listing
from app.nlp.categorizer import defect_types
from app.pipeline import process
from app.scoring.features import extract_features
from app.services import top_listings
from tests.test_scoring import mk


@pytest.mark.parametrize("text,expected", [
    ("TV LG OLED com tela trincada no canto", ["tela"]),
    ("Liga, tem som mas não dá imagem. Acho que é o backlight", ["imagem"]),
    ("Desliga sozinha depois de uns 40 minutos", ["liga_desliga"]),
    ("Fica reiniciando no logo da LG", ["liga_desliga"]),
    ("Não liga, led vermelho piscando", ["nao_liga"]),
    ("Apareceram listras verticais na tela", ["listras"]),
    ("Defeito na placa principal", ["placa"]),
    ("Vendo para retirada de peças", ["pecas"]),
    ("TV com defeito, vendo no estado", ["outro"]),            # defeito sem dizer qual
    ("Pequeno risco na borda", ["estetico"]),
    ("Perfeita, sem nenhum defeito, sem riscos nem trincas", []),
    ("Tela quebrada e não liga", ["tela", "nao_liga"]),
])
def test_defect_types_from_text(text, expected):
    assert defect_types(Listing(title="TV LG OLED 55", description=text, url="u", olx_id="x")) == expected


def test_declared_defect_without_details_is_outro():
    l = Listing(title="TV LG OLED 55", description="Vendo no estado", url="u", olx_id="x",
                condition="defeito")
    assert defect_types(l) == ["outro"]


def test_defect_types_are_score_features(db):
    l = mk(db, 1, "TV LG OLED 55", 1500, desc="tela trincada")
    process(db, [l])
    assert extract_features(l)["defeito:tela"] == 1.0


def test_top_listings_filters_by_defect_type(db):
    tela = mk(db, 1, "TV tela trincada", 1500)
    backlight = mk(db, 2, "TV sem imagem, backlight", 1500)
    process(db, [tela, backlight])
    assert top_listings(db, defect_filter={"imagem"}) == [backlight]
    assert set(top_listings(db, defect_filter={"imagem", "tela"})) == {tela, backlight}
    assert len(top_listings(db)) == 2
