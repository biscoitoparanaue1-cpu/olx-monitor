"""Transforma um anúncio em características numéricas para o score.

Nomes legíveis de propósito: viram a explicação "por que esse anúncio subiu".
"""
from __future__ import annotations

import math
import re

from app.models import Listing
from app.nlp.categorizer import normalize, strip_negations
from app.scraper.service import utcnow

STOPWORDS = set("""
a o e de da do das dos em no na nos nas um uma uns umas para pra por com sem que se
ao aos as os ou mais muito ja so tv smart televisao lg oled polegadas pol hdmi vendo
esta estao tem bem bom boa estado ela ele isso este essa esse aqui apenas valor preco
""".split())
TOKEN = re.compile(r"[a-z]{4,}")


def text_tokens(l: Listing) -> set[str]:
    """Palavras e pares de palavras relevantes do título e da descrição."""
    words = [w for w in TOKEN.findall(strip_negations(normalize(f"{l.title} {l.description or ''}")))
             if w not in STOPWORDS]
    return set(words) | {f"{a} {b}" for a, b in zip(words, words[1:])}


def extract_features(l: Listing) -> dict[str, float]:
    f: dict[str, float] = {"bias": 1.0}
    ev = l.latest_evaluation
    price = float(l.current_price) if l.current_price is not None else None

    if ev and ev.group_median and price:
        # >0 = mais barato que o grupo (0.3 = 30% abaixo da mediana); limitado a ±1
        f["preco_vs_grupo"] = max(-1.0, min(1.0, (float(ev.group_median) - price) / float(ev.group_median)))
    if ev:
        f[f"avaliacao:{ev.price_label}"] = 1.0
    if price:
        f["preco_log"] = math.log1p(price) / math.log1p(10_000)
    if l.condition:
        f[f"estado:{l.condition}"] = 1.0
    for m in l.rule_matches:
        f[f"regra:{m.rule_id}"] = 1.0
    if l.screen_size:
        f[f"tamanho:{l.screen_size}"] = 1.0
    if l.model_line:
        f[f"linha:{l.model_line}"] = 1.0
    if l.seller and l.seller.is_professional is not None:
        f["vendedor_profissional"] = 1.0 if l.seller.is_professional else 0.0
    if l.state:
        f[f"uf:{l.state}"] = 1.0
    if l.posted_at:
        f["dias_no_ar"] = min((utcnow() - l.posted_at).days, 30) / 30
    for tok in text_tokens(l):
        f[f"palavra:{tok}"] = 1.0
    return f
