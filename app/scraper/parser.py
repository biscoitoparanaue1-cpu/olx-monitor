"""Parser das páginas da OLX.

A OLX (Next.js) embute os dados da página num JSON em
<script id="__NEXT_DATA__">. Ler esse JSON é bem mais estável do que
depender de classes CSS, que mudam com frequência. Se o caminho principal
mudar, o parser procura recursivamente por objetos com cara de anúncio
(têm "listId"), e por último cai para o HTML/JSON-LD.
"""
from __future__ import annotations

import html as html_lib
import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
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


def _ad_from_dict(ad: dict) -> RawAd | None:
    olx_id = _first(ad, "listId", "list_id", "adId", "id")
    title = _first(ad, "subject", "title")
    url = _first(ad, "url", "friendlyUrl")
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
        description=_first(ad, "body", "description"),
        posted_at=parse_date(_first(ad, "date", "origListTime", "listTime")),
        location=location,
        state=state,
        image_url=_image(ad),
        is_professional=ad.get("professionalAd"),
        seller_id=str(seller_id) if seller_id else None,
        seller_name=_first(user, "name"),
        raw=ad,
    )


# ------------------------------------------------------------ página de busca
def parse_search_page(html: str) -> list[RawAd]:
    if looks_blocked(html):
        raise BlockedError("Página de bloqueio/captcha na busca")

    data = _next_data(html)
    if data:
        ads = (data.get("props", {}).get("pageProps", {}) or {}).get("ads")
        if not isinstance(ads, list):
            # Plano B: qualquer lista de dicts com "listId"
            ads = [d for d in _walk(data) if "listId" in d and "subject" in d]
        parsed = [a for a in (_ad_from_dict(d) for d in ads if isinstance(d, dict)) if a]
        # Remove banners/ads patrocinados repetidos
        seen, unique = set(), []
        for a in parsed:
            if a.olx_id not in seen:
                seen.add(a.olx_id)
                unique.append(a)
        return unique

    return _parse_search_html_fallback(html)


def _parse_search_html_fallback(html: str) -> list[RawAd]:
    """Último recurso: links de anúncio no HTML (sem preço/descrição confiáveis)."""
    soup = BeautifulSoup(html, "html.parser")
    ads: dict[str, RawAd] = {}
    for a in soup.select('a[href*="olx.com.br"]'):
        href = a.get("href", "")
        m = re.search(r"-(\d{8,})(?:\?|$)", href)
        title = (a.get("title") or a.get_text(" ", strip=True))[:300]
        if m and title and m.group(1) not in ads:
            price_el = a.find(string=re.compile(r"R\$\s?[\d\.]+"))
            ads[m.group(1)] = RawAd(
                olx_id=m.group(1), title=title, url=href,
                price=parse_price(price_el) if price_el else None,
            )
    return list(ads.values())


# --------------------------------------------------------- página do anúncio
def parse_ad_page(html: str) -> RawAd | None:
    """Extrai descrição completa, vendedor e data da página do anúncio."""
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
                    description=d.get("description"),
                )
    return None
