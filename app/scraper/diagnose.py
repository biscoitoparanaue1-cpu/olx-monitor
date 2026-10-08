"""Mostra como a OLX está estruturando as páginas hoje (para ajustar o parser).

Uso:  python -m app.scraper.diagnose ["TV LG OLED"]
Imprime um resumo e grava diagnostico.txt (e as páginas em diagnostico/).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from app.scraper.fetcher import describe_page, make_fetcher
from app.scraper.parser import _initial_data, _next_data, _walk, parse_ad_page, parse_search_page

OUT = Path("diagnostico")
lines: list[str] = []


def out(*parts) -> None:
    text = " ".join(str(p) for p in parts)
    print(text, flush=True)
    lines.append(text)


def shape(obj, depth: int = 0, max_depth: int = 3, prefix: str = "") -> None:
    """Árvore de chaves (sem valores longos) para entender o JSON."""
    if depth > max_depth:
        return
    if isinstance(obj, dict):
        for k, v in list(obj.items())[:40]:
            kind = type(v).__name__
            extra = f" len={len(v)}" if isinstance(v, (list, dict, str)) else f" = {v!r}"[:60]
            out(f"{prefix}{k}: {kind}{extra}")
            if isinstance(v, (dict, list)):
                shape(v, depth + 1, max_depth, prefix + "  ")
    elif isinstance(obj, list) and obj:
        out(f"{prefix}[0]: {type(obj[0]).__name__}")
        shape(obj[0], depth + 1, max_depth, prefix + "  ")


def ad_like(data) -> list[dict]:
    return [d for d in _walk(data) if isinstance(d, dict) and
            any(k in d for k in ("listId", "list_id", "adId")) and
            any(k in d for k in ("subject", "title"))]


def main(query: str = "TV LG OLED") -> None:
    OUT.mkdir(exist_ok=True)
    fetcher = make_fetcher()
    try:
        url = f"https://www.olx.com.br/brasil?q={query.replace(' ', '+')}&sf=1"
        html = fetcher.get(url)
        (OUT / "busca.html").write_text(html, encoding="utf-8")
        out("=== BUSCA", url, "modo:", fetcher.mode)
        out(describe_page(html)[:400])
        data = _next_data(html)
        out("__NEXT_DATA__:", bool(data))
        if data:
            pp = data.get("props", {}).get("pageProps", {})
            out("pageProps keys:", list(pp)[:40])
            ads = ad_like(data)
            out("objetos com cara de anúncio:", len(ads))
            if ads:
                out("--- chaves do 1º anúncio:", sorted(ads[0]))
                out("--- 1º anúncio (JSON):")
                out(json.dumps(ads[0], ensure_ascii=False, default=str)[:5000])
                out("--- 2º anúncio (JSON):")
                out(json.dumps(ads[1] if len(ads) > 1 else {}, ensure_ascii=False, default=str)[:2500])
            out("--- árvore do pageProps:")
            shape(pp, max_depth=2)
        # Estruturas alternativas ao __NEXT_DATA__ (Next.js app router, JSON-LD, DOM)
        import re as _re
        for m in _re.finditer(r'<script[^>]+application/ld\+json[^>]*>(.*?)</script>', html, _re.S):
            out("--- JSON-LD (início):", m.group(1)[:3000])
        pushes = _re.findall(r'self\.__next_f\.push\(\[1,\s*"(.*?)"\]\)', html, _re.S)
        out("__next_f.push:", len(pushes), "tamanhos:", [len(p) for p in pushes][:30])
        for key in ("priceValue", "listId", '\\"subject', "subject"):
            i = html.find(key)
            out(f"--- 1ª ocorrência de {key!r} em {i}:", html[max(0, i - 600):i + 1400] if i >= 0 else "-")
        first_link = _re.search(r'<a[^>]+href="https://[a-z]{2}\.olx\.com\.br/[^"]+-\d{8,}"', html)
        if first_link:
            j = first_link.start()
            out("--- HTML em volta do 1º link de anúncio:", html[max(0, j - 1500):j + 3500])
        parsed = parse_search_page(html)
        out(f"parse_search_page: {len(parsed)} anúncios")
        for a in parsed[:5]:
            out(f"  {a.olx_id} | {a.title[:120]!r} | preço={a.price} | img={bool(a.image_url)} | {a.url[:90]}")

        if parsed and "--com-detalhe" in sys.argv:
            for n, item in enumerate(parsed[:3], 1):
                detail_url = item.url
                dhtml = fetcher.get(detail_url)
                (OUT / f"anuncio-{n}.html").write_text(dhtml, encoding="utf-8")
                out("\n=== ANÚNCIO", detail_url)
                out(describe_page(dhtml)[:400])
                for name, d in (("__NEXT_DATA__", _next_data(dhtml)), ("initial-data", _initial_data(dhtml))):
                    out(f"{name}:", bool(d))
                    if d and n == 1:
                        pp = d.get("props", {}).get("pageProps", {}) if "props" in d else d
                        out("  chaves:", list(pp)[:40])
                        cands = ad_like(d)
                        out("  objetos com cara de anúncio:", len(cands),
                            [(c.get("listId") or c.get("adId"), (c.get("subject") or c.get("title") or "")[:40])
                             for c in cands[:5]])
                        if cands:
                            out("  1º objeto (JSON):", json.dumps(cands[0], ensure_ascii=False, default=str)[:5000])
                ad = parse_ad_page(dhtml)
                if ad:
                    out(f"parse_ad_page: {ad.olx_id} | {ad.title[:60]!r} | preço={ad.price} | "
                        f"img={bool(ad.image_url)} | desc={(ad.description or '')[:200]!r}")
                else:
                    out("parse_ad_page: None")
    finally:
        fetcher.close()
        Path("diagnostico.txt").write_text("\n".join(lines), encoding="utf-8")


if __name__ == "__main__":
    main(*(sys.argv[1:2] or ["TV LG OLED"]))
