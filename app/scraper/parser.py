"""Parser das páginas da OLX.

A OLX embute os dados da página em JSON, o que é bem mais estável do que
depender de classes CSS. Formatos conhecidos (do mais novo ao mais antigo):
- busca: payload do Next.js em self.__next_f.push([1,"..."]) com "ads":[...]
- anúncio: <script id="initial-data" data-json="..."> com "ad"
- ambos (antigo): <script id="__NEXT_DATA__">
Se nada disso existir, o parser lê os cartões do HTML e o JSON-LD.
"""
from __future__ import annotations

import html as html_lib
import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Iterator

from bs4 import BeautifulSoup

# "challenge-platform" ficou de fora: o Cloudflare injeta esse script em páginas normais
BLOCK_MARKERS = (
    "cf-chl", "Just a moment", "px-captcha", "Access Denied", "captcha-delivery",
    "Attention Required",
)
# Se a página traz os dados do anúncio, não é bloqueio, mesmo com scripts anti-bot no HTML
DATA_MARKERS = ("__NEXT_DATA__", 'id="initial-data"', "application/ld+json")


@dataclass
class RawAd:
    olx_id: str
    title: str
    url: str
    price: float | None = None
    description: str | None = None
    posted_at: datetime | None = None
    location: str | None = None
    state: str | None = None
    image_url: str | None = None
    is_professional: bool | None = None
    seller_id: str | None = None
    seller_name: str | None = None
    # Ficha do anúncio: {"tv_video_tvs_condition": "Usado - Excelente", "tv_video_tvs_inches": "55 polegadas"...}
    properties: dict[str, str] = field(default_factory=dict)
    raw: dict = field(default_factory=dict, repr=False)


class BlockedError(Exception):
    """A OLX devolveu captcha/página de bloqueio em vez do conteúdo."""


def looks_blocked(html: str) -> bool:
    if any(m in html for m in DATA_MARKERS):
        return False
    head = html[:30000]
    return any(m in head for m in BLOCK_MARKERS)


# ---------------------------------------------------------------- utilidades
def parse_price(value: Any) -> float | None:
    """'R$ 2.499' -> 2499.0 ; 'R$ 1.234,56' -> 1234.56 ; 2499 -> 2499.0"""
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)):
        return float(value)
    digits = re.sub(r"[^\d,\.]", "", str(value))
    if not digits:
        return None
    digits = digits.replace(".", "").replace(",", ".")
    try:
        return float(digits)
    except ValueError:
        return None


def parse_date(value: Any) -> datetime | None:
    if value in (None, ""):
        return None
    if isinstance(value, (int, float)):
        ts = value / 1000 if value > 1e12 else value
        return datetime.fromtimestamp(ts, tz=timezone.utc).replace(tzinfo=None)
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return dt.astimezone(timezone.utc).replace(tzinfo=None) if dt.tzinfo else dt
    except ValueError:
        return None


def _next_data(html: str) -> dict | None:
    m = re.search(
        r'<script[^>]+id="__NEXT_DATA__"[^>]*>(.*?)</script>', html, re.S)
    if not m:
        return None
    try:
        return json.loads(m.group(1))
    except json.JSONDecodeError:
        return None


def _initial_data(html: str) -> dict | None:
    """Formato antigo da página de anúncio: <script id="initial-data" data-json="...">"""
    m = re.search(r'id="initial-data"[^>]*data-json="([^"]*)"', html)
    if not m:
        return None
    try:
        return json.loads(html_lib.unescape(m.group(1)))
    except json.JSONDecodeError:
        return None


def _walk(obj: Any) -> Iterator[dict]:
    if isinstance(obj, dict):
        yield obj
        for v in obj.values():
            yield from _walk(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from _walk(v)


def _first(d: dict, *keys: str) -> Any:
    for k in keys:
        if d.get(k) not in (None, ""):
            return d[k]
    return None


def _uf_from_url(url: str | None) -> str | None:
    """https://rr.olx.com.br/... -> "RR" """
    m = re.match(r"https?://([a-z]{2})\.olx\.com\.br/", url or "")
    return m.group(1).upper() if m else None


def _location(ad: dict) -> tuple[str | None, str | None]:
    det = ad.get("locationDetails") or ad.get("location") or {}
    if isinstance(det, dict):
        city = _first(det, "municipality", "city")
        uf = _first(det, "uf", "state")
        nb = _first(det, "neighbourhood", "neighborhood")
        parts = [p for p in (nb, city, uf) if p]
        return (", ".join(parts) or None), (uf.upper() if isinstance(uf, str) else None)
    if isinstance(det, str):
        m = re.search(r"\b([A-Z]{2})\s*$", det)
        return det, (m.group(1) if m else None)
    return None, None


def _image(ad: dict) -> str | None:
    imgs = ad.get("images")
    if isinstance(imgs, list) and imgs:
        first = imgs[0]
        if isinstance(first, dict):
            return _first(first, "original", "originalWebp", "url", "thumbnail")
        if isinstance(first, str):
            return first
    return _first(ad, "thumbnail", "image")


def _properties(ad: dict) -> dict[str, str]:
    props = ad.get("properties")
    if isinstance(props, dict):
        return {str(k): str(v) for k, v in props.items() if v not in (None, "")}
    out: dict[str, str] = {}
    for p in props if isinstance(props, list) else []:
        if isinstance(p, dict) and p.get("name") and p.get("value") not in (None, ""):
            out[str(p["name"])] = str(p["value"])
    return out


def clean_text(value: Any) -> str | None:
    """Descrição da OLX vem com <br> e entidades HTML."""
    if not isinstance(value, str) or not value.strip():
        return None
    text = re.sub(r"<br\s*/?>", "\n", value, flags=re.I)
    text = html_lib.unescape(re.sub(r"<[^>]+>", " ", text))
    return re.sub(r"[ \t]+", " ", text).strip()


def _posted_at(ad: dict) -> datetime | None:
    dt = parse_date(_first(ad, "date", "origListTime", "listTime"))
    if dt:
        return dt
    age = ad.get("lastBumpAgeSecs")  # a busca nova só traz "há quantos segundos"
    try:
        return datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(seconds=int(age))
    except (TypeError, ValueError):
        return None


# Campos guardados em raw_json (o anúncio completo tem dezenas de chaves que não usamos)
RAW_KEYS = ("listId", "subject", "priceValue", "price", "oldPrice", "professionalAd", "date",
            "origListTime", "location", "locationDetails", "url", "friendlyUrl", "categoryName")


def compact_raw(ad: dict) -> dict:
    raw = {k: ad[k] for k in RAW_KEYS if ad.get(k) not in (None, "")}
    props = _properties(ad)
    if props:
        raw["properties"] = props
    imgs = [_first(i, "original", "originalWebp") if isinstance(i, dict) else i
            for i in (ad.get("images") or [])[:6]]
    if any(imgs):
        raw["images"] = [i for i in imgs if i]
    return raw


def _ad_from_dict(ad: dict, url: str | None = None) -> RawAd | None:
    olx_id = _first(ad, "listId", "list_id", "adId", "id")
    title = _first(ad, "subject", "title")
    url = _first(ad, "url", "friendlyUrl", "canonicalUrl") or url
    if not (olx_id and title and url):
        return None
    location, state = _location(ad)
    user = ad.get("user") or ad.get("seller") or {}
    if not isinstance(user, dict):
        user = {}
    seller_id = _first(user, "userId", "accountId", "id")
    return RawAd(
        olx_id=str(olx_id),
        title=str(title).strip(),
        url=str(url),
        price=parse_price(_first(ad, "priceValue", "price")),
        description=clean_text(_first(ad, "body", "description")),
        posted_at=_posted_at(ad),
        location=location,
        state=state or _uf_from_url(str(url)),
        image_url=_image(ad),
        is_professional=ad.get("professionalAd"),
        seller_id=str(seller_id) if seller_id else None,
        seller_name=_first(user, "name"),
        properties=_properties(ad),
        raw=compact_raw(ad),
    )


# ------------------------------------------------- payload do Next.js (app router)
_FLIGHT_RE = re.compile(r'self\.__next_f\.push\(\[1,\s*"((?:[^"\\]|\\.)*)"\]\)', re.S)


def flight_payload(html: str) -> str:
    """Junta os pedaços de self.__next_f.push([1,"..."]) já decodificados."""
    chunks = []
    for m in _FLIGHT_RE.finditer(html):
        s = m.group(1)
        for attempt in (s, re.sub(r"\\x([0-9a-fA-F]{2})", r"\\u00\1", s)):
            try:
                chunks.append(json.loads(f'"{attempt}"'))
                break
            except json.JSONDecodeError:
                continue
    return "".join(chunks)


def _json_values(payload: str, key: str) -> Iterator[Any]:
    """Todos os valores JSON que vêm depois de "key": no payload."""
    decoder = json.JSONDecoder()
    for m in re.finditer(rf'"{re.escape(key)}"\s*:\s*', payload):
        try:
            yield decoder.raw_decode(payload, m.end())[0]
        except json.JSONDecodeError:
            continue


def _rsc_clean(obj: Any) -> Any:
    """O payload usa "$undefined" no lugar de valores ausentes."""
    if isinstance(obj, dict):
        return {k: _rsc_clean(v) for k, v in obj.items() if v != "$undefined"}
    if isinstance(obj, list):
        return [_rsc_clean(v) for v in obj]
    return obj


def _flight_ads(html: str) -> list[dict]:
    payload = flight_payload(html)
    ads: list[dict] = []
    for value in _json_values(payload, "ads"):
        if isinstance(value, list):
            ads += [_rsc_clean(d) for d in value if isinstance(d, dict) and "listId" in d]
    return ads


# ------------------------------------------------------------ cartões do HTML
@dataclass
class _Card:
    olx_id: str
    url: str
    title: str
    price: float | None = None
    image_url: str | None = None
    location: str | None = None


def _img_src(img) -> str | None:
    if img is None:
        return None
    for attr in ("src", "data-src"):
        v = img.get(attr)
        if v and v.startswith("http"):
            return v
    srcset = img.get("srcset") or img.get("data-srcset") or ""
    first = srcset.split(",")[0].strip().split(" ")[0]
    return first if first.startswith("http") else None


def _html_cards(html: str) -> dict[str, _Card]:
    """Cartões da lista (<section class="olx-adcard">): link, título, preço, foto e local."""
    soup = BeautifulSoup(html, "html.parser")
    cards: dict[str, _Card] = {}
    for sec in soup.select("section.olx-adcard, [data-testid='adcard']"):
        link = sec.select_one("a[data-testid='adcard-link']") or sec.select_one("a[href*='olx.com.br']")
        if not link:
            continue
        href = link.get("href", "")
        m = re.search(r"-(\d{8,})(?:[?#]|$)", href)
        if not m or m.group(1) in cards:
            continue
        heading = link.select_one("h2") or sec.select_one("h2")
        title = (link.get("title") or (heading.get_text(" ", strip=True) if heading else "")).strip()
        price_el = sec.select_one(".olx-adcard__price, h3")
        loc_el = sec.select_one(".olx-adcard__location")
        cards[m.group(1)] = _Card(
            olx_id=m.group(1), url=href, title=title[:300],
            price=parse_price(price_el.get_text(" ", strip=True)) if price_el else None,
            image_url=_img_src(sec.select_one(".olx-adcard__media img, img")),
            location=loc_el.get_text(" ", strip=True) if loc_el else None,
        )
    return cards


# ------------------------------------------------------------ página de busca
def parse_search_page(html: str) -> list[RawAd]:
    if looks_blocked(html):
        raise BlockedError("Página de bloqueio/captcha na busca")

    dicts: list[dict] = []
    data = _next_data(html)
    if data:
        dicts = (data.get("props", {}).get("pageProps", {}) or {}).get("ads") or []
        if not isinstance(dicts, list):
            dicts = []
        if not dicts:
            # Plano B: qualquer dict com "listId" e "subject"
            dicts = [d for d in _walk(data) if "listId" in d and "subject" in d]
    if not dicts:
        dicts = _flight_ads(html)

    cards = _html_cards(html) if "olx-adcard" in html or not dicts else {}
    parsed: list[RawAd] = []
    seen: set[str] = set()
    for d in dicts:
        if not isinstance(d, dict):
            continue
        card = cards.get(str(d.get("listId") or ""))
        ad = _ad_from_dict(d, url=card.url if card else None)
        if not ad or ad.olx_id in seen:  # banners/patrocinados repetem anúncios
            continue
        if card:
            ad.image_url = ad.image_url or card.image_url
            ad.price = ad.price if ad.price is not None else card.price
        seen.add(ad.olx_id)
        parsed.append(ad)
    if parsed:
        return parsed

    if cards:
        return [RawAd(olx_id=c.olx_id, title=c.title, url=c.url, price=c.price,
                      image_url=c.image_url, location=c.location, state=_uf_from_url(c.url))
                for c in cards.values() if c.title]
    return _parse_search_html_fallback(html)


def _parse_search_html_fallback(html: str) -> list[RawAd]:
    """Último recurso: links de anúncio no HTML (sem preço/descrição confiáveis)."""
    soup = BeautifulSoup(html, "html.parser")
    ads: dict[str, RawAd] = {}
    for a in soup.select('a[href*="olx.com.br"]'):
        href = a.get("href", "")
        m = re.search(r"-(\d{8,})(?:\?|$)", href)
        heading = a.find(["h2", "h3"])
        title = (a.get("title") or (heading.get_text(" ", strip=True) if heading else "")
                 or a.get_text(" ", strip=True))[:300]
        if m and title and m.group(1) not in ads:
            price_el = a.find(string=re.compile(r"R\$\s?[\d\.]+"))
            ads[m.group(1)] = RawAd(
                olx_id=m.group(1), title=title, url=href,
                price=parse_price(price_el) if price_el else None, state=_uf_from_url(href),
            )
    return list(ads.values())


# --------------------------------------------------------- página do anúncio
def parse_ad_page(html: str) -> RawAd | None:
    """Extrai descrição completa, ficha, vendedor e data da página do anúncio."""
    if looks_blocked(html):
        raise BlockedError("Página de bloqueio/captcha no anúncio")

    for data in (_next_data(html), _initial_data(html)):
        if not data:
            continue
        page_ad = (data.get("props", {}).get("pageProps", {}) or {}).get("ad") or data.get("ad")
        candidates = [page_ad] if isinstance(page_ad, dict) else []
        candidates += [d for d in _walk(data) if "listId" in d and ("body" in d or "description" in d)]
        for cand in candidates:
            ad = _ad_from_dict(cand)
            if ad:
                return ad

    # Next.js app router: "ad":{...} no payload
    for value in _json_values(flight_payload(html), "ad"):
        if isinstance(value, dict) and "listId" in value:
            ad = _ad_from_dict(_rsc_clean(value))
            if ad:
                return ad

    # JSON-LD (schema.org Product) como último recurso
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup.find_all("script", type="application/ld+json"):
        try:
            ld = json.loads(tag.string or "")
        except json.JSONDecodeError:
            continue
        for d in _walk(ld):
            if d.get("@type") == "Product" and d.get("name"):
                offers = d.get("offers") or {}
                return RawAd(
                    olx_id=str(d.get("sku") or d.get("productID") or ""),
                    title=d["name"], url=str(offers.get("url") or ""),
                    price=parse_price(offers.get("price")),
                    description=clean_text(d.get("description")),
                )
    return None
