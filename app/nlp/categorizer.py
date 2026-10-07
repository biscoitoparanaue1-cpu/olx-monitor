"""Lê título + descrição, define o estado do item e aplica as regras do usuário.

Sem modelo pesado: texto normalizado (minúsculas, sem acento), regex com
tratamento de negação ("sem defeito" não conta como defeito) e regras
configuráveis (regex, palavras-chave ou aproximado).
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from difflib import SequenceMatcher

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.models import FilterRule, Listing, ListingRuleMatch

# Do mais grave para o menos grave: quando várias pistas aparecem, vale a mais grave
SEVERITY = ["para_pecas", "defeito", "usado_com_avaria", "usado_bom", "novo"]

BUILTIN_SIGNALS: dict[str, list[str]] = {
    "para_pecas": [
        r"\b(para|pra|p/)\s*(retirada\s+de\s+)?pecas\b", r"\bsucata\b", r"\bretirar\s+pecas\b",
        r"\bvendo\s+(as\s+)?pecas\b",
    ],
    "defeito": [
        r"\bdefeit\w*", r"\bnao\s+(liga|funciona|da\s+imagem|acende)\b", r"\bdeslig\w*\s+sozinh\w*",
        r"\bdeslig\w*\s+(apos|depois\s+de|a\s+cada|com)\s+\d+\s*(min|minutos|h|horas)\b",
        r"\btela\s+(trincad\w*|quebrad\w*|rachad\w*|danificad\w*|estourad\w*)",
        r"\b(trincad\w*|quebrad\w*)\b", r"\blistras?\b", r"\bmanchas?\s+(na|em)\s+tela\b",
        r"\bsem\s+(imagem|som|video)\b", r"\bqueimad\w*", r"\breinicia\w*\b", r"\bfica\s+reiniciando\b",
        r"\btravad\w*", r"\bbacklight\b", r"\bled\s+queimad\w*", r"\bimagem\s+(escura|piscando)\b",
        r"\bpisca\w*\b", r"\bliga\s+e\s+deslig\w*", r"\bburn\s*-?in\b", r"\btela\s+(preta|escura)\b",
    ],
    "usado_com_avaria": [
        r"\bris(co|cos|cada|cado)\b", r"\barranh\w*", r"\bpixels?\s+(morto|queimado)s?\b",
        r"\bsem\s+(controle|pe|pes|base|suporte)\b", r"\bdetalhes?\s+(na|no)\b", r"\bamassad\w*",
        r"\bmarcas?\s+de\s+uso\b",
    ],
    "novo": [r"\blacrad\w*", r"\bnunca\s+usad\w*", r"\bnov[ao]\s+na\s+caixa\b", r"\bzero\s+km\b"],
}

# Remove trechos negados antes de procurar sinais ("sem nenhum defeito", "nao tem riscos")
_NEGATION = re.compile(
    r"\b(sem|nenhum|nenhuma|zero|nao\s+tem|nao\s+possui|nao\s+apresenta|livre\s+de|isent[ao]\s+de)"
    r"\s+(\w+\s+){0,2}?(defeitos?|riscos?|avarias?|trincas?|arranh\w*|marcas?|detalhes?|problemas?)\b"
)
_NEGATION_ADJ = re.compile(
    r"\bnao\s+(esta|estao|tem|possui|e)?\s*(\w+\s+)?(trincad|quebrad|riscad|arranhad|amassad|queimad)\w*"
)
_COMPILED = {cond: [re.compile(p) for p in pats] for cond, pats in BUILTIN_SIGNALS.items()}


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


def detect_condition(text_norm: str) -> tuple[str, dict[str, list[str]]]:
    clean = strip_negations(text_norm)
    signals: dict[str, list[str]] = {}
    for cond, regexes in _COMPILED.items():
        hits = [m.group(0) for r in regexes for m in [r.search(clean)] if m]
        if hits:
            signals[cond] = hits
    for cond in SEVERITY:
        if cond in signals:
            return cond, signals
    return "usado_bom", signals


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
    condition, signals = detect_condition(text)
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
