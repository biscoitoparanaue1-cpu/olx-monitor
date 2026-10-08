"""Extrai marca, linha/modelo e tamanho de tela do título, da descrição e da
ficha do anúncio (os campos "Marca", "Tamanho da TV" e "Tipo de Tela" da OLX).

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
# "TV LG C3 OLED", "LG B4 OLED 65": linha antes da palavra OLED
_LG_LINE_BEFORE = re.compile(r"\bLG\s+(?:OLED\s+)?(?:EVO\s+)?([ABCEGMWZ][1-9X])\b")
# Linha solta no título ("Smart tv LG 55 oled gamer C3"), só se já se sabe que é OLED
_LINE_TOKEN = re.compile(r"\b([ABCEGMWZ][1-9X])\b")
# Códigos de TVs LG que NÃO são OLED: 55UN7100, 50UQ8050, 55AU801, 55NANO75, 65QNED80, 43LM6300
_NON_OLED_CODE = re.compile(r"\b\d{2}\s?(?:U[A-Z]\d|AU\d|NANO|QNED|L[A-Z]\d{3}|SM\d|SK\d)")
# Tamanho: 55", 55'', 55 pol, 55 polegadas, 55 in, 55pol.
_SIZE = re.compile(r"\b(\d{2,3})\s*(?:\"|”|''|POLEGADAS?|POLS?\b|POL\.?|IN\b|INCH)")
_VALID_SIZES = range(24, 101)

# Campos da ficha da OLX (categoria TVs)
PROP_BRAND = "tv_video_tvs_brand"
PROP_INCHES = "tv_video_tvs_inches"
PROP_SCREEN = "tv_video_tvs_screen_type"
PROP_CONDITION = "tv_video_tvs_condition"


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


def _prop_size(value: str | None) -> tuple[int | None, bool]:
    """("55 polegadas") -> (55, True); ("50 a 54 polegadas") -> (50, False): faixa, menos confiável."""
    nums = [int(n) for n in re.findall(r"\d{2,3}", value or "") if int(n) in _VALID_SIZES]
    return (nums[0], len(nums) == 1) if nums else (None, False)


def extract_attributes(title: str, description: str = "",
                       properties: dict[str, str] | None = None) -> TvAttributes:
    props = properties or {}
    t = normalize(title)
    d = normalize(description)
    attrs = TvAttributes()
    # Muitos vendedores marcam "OLED" na ficha de TVs LED: a ficha sozinha não basta para
    # chamar de OLED (senão uma TV LED barata parece "ótimo negócio" perto das OLED)
    led_code = bool(_NON_OLED_CODE.search(t))
    is_oled = ("OLED" in t or "OLED" in d) and not led_code
    maybe_oled = is_oled or ("OLED" in normalize(props.get(PROP_SCREEN, "")) and not led_code)

    brand = normalize(props.get(PROP_BRAND, ""))
    if brand and not brand.startswith("OUTR"):
        attrs.brand = brand[:40]
    prop_size, prop_size_exact = _prop_size(props.get(PROP_INCHES))
    code_size = text_size = None

    for i, text in enumerate((t, d)):  # título tem prioridade sobre a descrição
        if not attrs.brand:
            attrs.brand = next((b for b in BRANDS if re.search(rf"\b{b}\b", text)), None)

        if not attrs.model_code and (m := _LG_CODE.search(text)):
            size, series, gen = m.groups()
            attrs.model_code = f"OLED{size}{series}{gen}"
            attrs.model_line = f"OLED {series}{gen}"
            code_size = int(size)
            attrs.brand = attrs.brand or "LG"

        if not attrs.model_line and (m := _LG_LINE.search(text)):
            attrs.model_line = f"OLED {m.group(1)}"
        if not attrs.model_line and maybe_oled and (m := _LG_LINE_BEFORE.search(text)):
            attrs.model_line = f"OLED {m.group(1)}"
        if not attrs.model_line and maybe_oled and i == 0 and (m := _LINE_TOKEN.search(text)):
            attrs.model_line = f"OLED {m.group(1)}"

        if not text_size and not (i == 1 and prop_size):
            for m in _SIZE.finditer(text):
                if int(m.group(1)) in _VALID_SIZES:
                    text_size = int(m.group(1))
                    break

    # Código do modelo > ficha (tamanho exato) > título > ficha (faixa) > descrição
    attrs.screen_size = code_size or (prop_size if prop_size_exact else None) or text_size or prop_size
    if attrs.model_line is None and is_oled:
        attrs.model_line = "OLED"  # sabemos a tecnologia, não a geração
    return attrs
