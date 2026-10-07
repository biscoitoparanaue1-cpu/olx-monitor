"""Extrai marca, linha/modelo e tamanho de tela do título (e descrição).

Usado para montar o grupo de comparação de preço ("LG OLED C1 55").
"""
import re
import unicodedata
from dataclasses import dataclass

BRANDS = ["LG", "SAMSUNG", "SONY", "PHILIPS", "TCL", "PANASONIC", "AOC", "HISENSE", "XIAOMI"]

# Código de modelo LG: OLED55C1PSA, OLED65CXPSA, OLED77G2, OLED48A1...
_LG_CODE = re.compile(r"\bOLED\s?(\d{2})\s?([ABCEGMWZ])([1-9X])(?:[A-Z]{2,4})?\b")
# Linha citada sem código: "LG OLED C1 55", "OLED evo C3", "OLED 65 C2"
_LG_LINE = re.compile(
    r"\bOLED(?:\s+EVO)?\s+(?:\d{2}\s*(?:\"|POL\w*|'')?\s+)?([ABCEGMWZ][1-9X])\b"
)
# Tamanho: 55", 55'', 55 pol, 55 polegadas, 55 in, 55pol.
_SIZE = re.compile(r"\b(\d{2,3})\s*(?:\"|”|''|POLEGADAS?|POLS?\b|POL\.?|IN\b|INCH)")
_VALID_SIZES = range(24, 101)


def normalize(text: str) -> str:
    text = unicodedata.normalize("NFKD", text or "")
    text = "".join(c for c in text if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", text).upper().strip()


@dataclass
class TvAttributes:
    brand: str | None = None
    model_line: str | None = None   # ex.: "OLED C1"
    model_code: str | None = None   # ex.: "OLED55C1"
    screen_size: int | None = None  # polegadas

    @property
    def category_name(self) -> str | None:
        """Nome do grupo de preço. None se não houver o mínimo (marca ou tamanho)."""
        if not (self.brand or self.screen_size):
            return None
        parts = [self.brand or "?", self.model_line or "", str(self.screen_size or "?")]
        return " ".join(p for p in parts if p)


def extract_attributes(title: str, description: str = "") -> TvAttributes:
    t = normalize(title)
    d = normalize(description)
    attrs = TvAttributes()

    for text in (t, d):  # título tem prioridade sobre a descrição
        if not attrs.brand:
            attrs.brand = next((b for b in BRANDS if re.search(rf"\b{b}\b", text)), None)

        if not attrs.model_code and (m := _LG_CODE.search(text)):
            size, series, gen = m.groups()
            attrs.model_code = f"OLED{size}{series}{gen}"
            attrs.model_line = f"OLED {series}{gen}"
            attrs.screen_size = attrs.screen_size or int(size)
            attrs.brand = attrs.brand or "LG"

        if not attrs.model_line and (m := _LG_LINE.search(text)):
            attrs.model_line = f"OLED {m.group(1)}"

        if not attrs.screen_size:
            for m in _SIZE.finditer(text):
                if int(m.group(1)) in _VALID_SIZES:
                    attrs.screen_size = int(m.group(1))
                    break

    if attrs.model_line is None and "OLED" in t:
        attrs.model_line = "OLED"  # sabemos a tecnologia, não a geração
    return attrs
