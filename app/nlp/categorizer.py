"""Lê título + descrição, define o estado do item e aplica as regras do usuário.

Sem modelo pesado: texto normalizado (minúsculas, sem acento), regex com
tratamento de negação ("sem defeito" não conta como defeito) e regras
configuráveis (regex, palavras-chave ou aproximado). A condição marcada pelo
vendedor na ficha da OLX ("Com defeito ou avarias", "Novo"...) também conta;
vale a mais grave entre ela e o que o texto revela.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from difflib import SequenceMatcher

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.models import FilterRule, Listing, ListingRuleMatch
from app.scraper.attributes import PROP_CONDITION

# Do mais grave para o menos grave: quando várias pistas aparecem, vale a mais grave
SEVERITY = ["para_pecas", "defeito", "usado_com_avaria", "usado_bom", "novo"]

# Tipos de defeito: (rótulo, estado que indicam, padrões no texto normalizado).
# Definem o estado do item, viram filtro no painel e entram no score, para o modelo
# aprender quais tipos você prefere (ex.: backlight costuma ser conserto barato;
# tela quebrada, caro).
DEFECT_TYPES: dict[str, tuple[str, str, list[str]]] = {
    "pecas": ("Para peças", "para_pecas", [
        r"\b(para|pra|p/)\s*(retirada\s+de\s+)?pecas\b", r"\bsucata\b", r"\bretirar\s+pecas\b",
        r"\bvendo\s+(as\s+)?pecas\b",
    ]),
    "tela": ("Tela quebrada", "defeito", [
        r"\b(tela|display|painel|vidro)\s+(\w+\s+){0,2}?(trincad|quebrad|rachad|danificad|estourad|partid)\w*",
        r"\bquebr\w*\s+(a\s+|o\s+)?(tela|display|painel)\b", r"\b(trincad|rachad|estourad)\w*", r"\btrincas?\b",
    ]),
    "imagem": ("Sem imagem / backlight", "defeito", [
        r"\bsem\s+(imagem|video)\b", r"\bnao\s+(da|aparece|tem|mostra)\s+imagem\b", r"\bback\s*light\b",
        r"\bleds?\s+(queimad\w*|da\s+tela)", r"\bbarras?\s+de\s+leds?\b", r"\bimagem\s+(escura|apagada)\b",
        r"\btela\s+(preta|escura|apagada)\b", r"\b(so|apenas)\s+(o\s+)?(som|audio)\b",
    ]),
    "liga_desliga": ("Liga e desliga / reinicia", "defeito", [
        r"\bdeslig\w*\s+sozinh\w*", r"\bliga\s+e\s+deslig\w*", r"\breinicia\w*", r"\breiniciando\b",
        r"\bdeslig\w*\s+(apos|depois\s+de|a\s+cada|com)\s+(uns\s+|umas\s+|cerca\s+de\s+)?\d+\s*"
        r"(min|minutos|h|horas|seg\w*)\b",
    ]),
    "nao_liga": ("Não liga", "defeito", [r"\bnao\s+(liga|acende|esta\s+ligando)\b"]),
    "listras": ("Listras / manchas", "defeito", [
        r"\blistras?\b", r"\b(faixas?|linhas?)\s+(na\s+tela|na\s+imagem|verticais|horizontais|coloridas)\b",
        r"\bmanchas?\s+(na|em)\s+(tela|imagem)\b", r"\bburn\s*-?\s*in\b",
        r"\b(imagem|tela)\s+(piscando|tremendo)\b", r"\bretencao\s+de\s+imagem\b",
    ]),
    "placa": ("Placa / fonte", "defeito", [
        r"\bplaca\s+(principal|mae|da\s+fonte|fonte|t-?con|logica|queimad\w*|com\s+defeito|ruim)\b",
        r"\bfonte\s+(queimad\w*|com\s+defeito|ruim)", r"\bt-?con\b", r"\bem\s+curto\b",
    ]),
    "som": ("Sem som", "defeito", [r"\bsem\s+(som|audio)\b", r"\bsom\s+(nao\s+funciona|chiando|falhando)\b"]),
    # Só aparece quando o texto fala em defeito sem dizer qual
    "outro": ("Defeito não especificado", "defeito", [
        r"\bdefeit\w*", r"\bdanificad\w*", r"\bqueimad\w*", r"\btravad\w*", r"\bquebrad\w*",
        r"\bpisca\w*", r"\bnao\s+funciona\b",
    ]),
    "estetico": ("Avarias leves (riscos, pixels)", "usado_com_avaria", [
        r"\bris(co|cos|cada|cado)\b", r"\barranh\w*", r"\bpixels?\s+(morto|queimado)s?\b",
        r"\bsem\s+(controle|pe|pes|base|suporte)\b", r"\bdetalhes?\s+(na|no)\b", r"\bamassad\w*",
        r"\bmarcas?\s+de\s+uso\b",
    ]),
}
NEW_SIGNALS = [r"\blacrad\w*", r"\bnunca\s+usad\w*", r"\bnov[ao]\s+na\s+caixa\b", r"\bzero\s+km\b"]

# Remove trechos negados antes de procurar sinais ("sem nenhum defeito", "nao tem riscos")
_NEGATION = re.compile(
    r"\b(sem|nenhum|nenhuma|zero|nem|nao\s+tem|nao\s+possui|nao\s+apresenta|livre\s+de|isent[ao]\s+de)"
    r"\s+(\w+\s+){0,2}?(defeitos?|riscos?|avarias?|trincas?|arranh\w*|marcas?|detalhes?|problemas?)\b"
)
_NEGATION_ADJ = re.compile(
    r"\bnao\s+(esta|estao|tem|possui|e)?\s*(\w+\s+)?(trincad|quebrad|riscad|arranhad|amassad|queimad)\w*"
)
_DEFECT_RE = {k: [re.compile(p) for p in pats] for k, (_, _, pats) in DEFECT_TYPES.items()}
_NEW_RE = [re.compile(p) for p in NEW_SIGNALS]


def strip_accents(text: str | None) -> str:
    text = unicodedata.normalize("NFKD", text or "")
    return "".join(c for c in text if not unicodedata.combining(c))


def normalize(text: str | None) -> str:
    text = strip_accents(text).lower()
    text = re.sub(r"(\d)\s*(min|minutos)\b", r"\1 min", text)  # "40min" == "40 min"
    return re.sub(r"\s+", " ", text).strip()


def strip_negations(text: str) -> str:
    return _NEGATION_ADJ.sub(" ", _NEGATION.sub(" ", text))


@dataclass
class CategorizeResult:
    condition: str
    signals: dict[str, list[str]] = field(default_factory=dict)   # estado -> trechos
    rule_matches: list[tuple[FilterRule, str]] = field(default_factory=list)


def declared_condition(value: str | None) -> str | None:
    """Condição da ficha da OLX: "Novo", "Usado - Excelente", "Usado - Bom", "Com defeito ou avarias"."""
    v = normalize(value)
    if not v:
        return None
    if "peca" in v:
        return "para_pecas"
    if any(w in v for w in ("defeito", "avaria", "reparo", "conserto")):
        return "defeito"
    if v.startswith("novo"):
        return "novo"
    return "usado_bom" if "usado" in v else None


def listing_properties(listing: Listing) -> dict[str, str]:
    props = (listing.raw_json or {}).get("properties")
    return props if isinstance(props, dict) else {}


def text_defects(text_norm: str) -> dict[str, list[str]]:
    """Tipos de defeito citados no texto (já sem os trechos negados) -> trechos encontrados."""
    clean = strip_negations(text_norm)
    found = {}
    for key, regexes in _DEFECT_RE.items():
        hits = [m.group(0) for r in regexes if (m := r.search(clean))]
        if hits:
            found[key] = hits
    if "outro" in found and any(DEFECT_TYPES[k][1] == "defeito" for k in found if k != "outro"):
        del found["outro"]  # "defeito na tela trincada" já é "Tela quebrada"
    return found


def detect_condition(text_norm: str, declared: str | None = None) -> tuple[str, dict[str, list[str]]]:
    signals: dict[str, list[str]] = {}
    for key, hits in text_defects(text_norm).items():
        signals.setdefault(DEFECT_TYPES[key][1], []).extend(hits)
    clean = strip_negations(text_norm)
    if new := [m.group(0) for r in _NEW_RE if (m := r.search(clean))]:
        signals["novo"] = new
    for cond in SEVERITY:
        if cond in signals or cond == declared:
            return cond, signals
    return "usado_bom", signals


def defect_types(listing: Listing) -> list[str]:
    """Tipos de defeito do anúncio, na ordem de DEFECT_TYPES. Se o estado é "com defeito"
    (ex.: pela ficha da OLX) mas o texto não diz qual, entra "outro"."""
    found = text_defects(normalize(f"{listing.title}\n{listing.description or ''}"))
    types = [k for k in DEFECT_TYPES if k in found]
    if listing.condition == "defeito" and not any(DEFECT_TYPES[k][1] == "defeito" for k in types):
        types.append("outro")
    if listing.condition == "para_pecas" and "pecas" not in types:
        types.append("pecas")
    return types


# ----------------------------------------------------------------- regras
def _fuzzy_find(phrase: str, text: str, threshold: float = 0.85) -> str | None:
    words, target = re.findall(r"\w+", text), phrase.split()
    n = len(target)
    for i in range(max(1, len(words) - n + 1)):
        window = " ".join(words[i:i + n])
        if SequenceMatcher(None, window, phrase).ratio() >= threshold:
            return window
    return None


def match_rule(rule: FilterRule, text_norm: str) -> str | None:
    """Retorna o trecho que casou, ou None."""
    clean = strip_negations(text_norm)
    if rule.pattern_type == "keywords":
        for kw in filter(None, (normalize(k) for k in re.split(r"[;,\n]", rule.pattern))):
            if re.search(rf"\b{re.escape(kw)}\b", clean):
                return kw
        return None
    if rule.pattern_type == "fuzzy":
        for phrase in filter(None, (normalize(k) for k in re.split(r"[;\n]", rule.pattern))):
            if hit := _fuzzy_find(phrase, clean):
                return hit
        return None
    try:
        # Só tira acentos do padrão: minúsculas mudariam \S, \W, \D da regex
        m = re.search(strip_accents(rule.pattern), clean, re.I)
    except re.error:
        return None
    return m.group(0) if m else None


def categorize(listing: Listing, rules: list[FilterRule]) -> CategorizeResult:
    text = normalize(f"{listing.title}\n{listing.description or ''}")
    declared = declared_condition(listing_properties(listing).get(PROP_CONDITION))
    condition, signals = detect_condition(text, declared)
    result = CategorizeResult(condition=condition, signals=signals)
    for rule in rules:
        if (hit := match_rule(rule, text)) is not None:
            result.rule_matches.append((rule, hit))
            if rule.sets_condition and (
                    SEVERITY.index(rule.sets_condition) < SEVERITY.index(result.condition)):
                result.condition = rule.sets_condition
    return result


def apply_categorization(db: Session, listings: list[Listing],
                         rules: list[FilterRule] | None = None) -> None:
    """Grava estado e regras casadas (substitui as anteriores)."""
    if rules is None:
        rules = list(db.scalars(select(FilterRule).where(FilterRule.is_active.is_(True))))
    for listing in listings:
        res = categorize(listing, rules)
        listing.condition = res.condition
        db.execute(delete(ListingRuleMatch).where(ListingRuleMatch.listing_id == listing.id))
        db.expire(listing, ["rule_matches"])
        for rule, hit in res.rule_matches:
            db.add(ListingRuleMatch(listing_id=listing.id, rule_id=rule.id, matched_text=hit[:300]))
    db.flush()
