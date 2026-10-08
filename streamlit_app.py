"""Painel do OLX Monitor (Streamlit).

Local:   streamlit run streamlit_app.py
Nuvem:   Streamlit Community Cloud, com DATABASE_URL (Neon) nos Secrets do app.
"""
import html
import os
import re

import streamlit as st

# Secrets do Streamlit Cloud -> variáveis de ambiente (antes de importar app.*)
try:
    for _k in ("DATABASE_URL", "APP_PASSWORD"):
        if _k in st.secrets:
            os.environ[_k] = str(st.secrets[_k])
except Exception:  # sem secrets.toml (rodando local com SQLite)
    pass

from sqlalchemy import func, select  # noqa: E402

from app.db import SessionLocal, init_db  # noqa: E402
from app.nlp.categorizer import DEFECT_TYPES, defect_types  # noqa: E402
from app.models import (  # noqa: E402
    FeatureWeight, Feedback, FilterRule, Listing, ModelVersion, ProductCategory, ScrapeRun,
    SearchTerm,
)
from app.pipeline import reprocess_all  # noqa: E402
from app.scoring.model import DEFAULT_WEIGHTS, MIN_FEEDBACK, learn_from_feedback, note_word_weights, prior_weights  # noqa: E402
from app.services import TZ, day_start_utc, save_note, set_feedback, clear_feedback, top_listings  # noqa: E402

st.set_page_config(page_title="OLX Monitor", page_icon="📺", layout="wide")

PRICE_LABELS = {
    "otimo_negocio": ("Ótimo negócio", "green"),
    "preco_justo": ("Preço justo", "blue"),
    "caro": ("Caro", "red"),
    "sem_base": ("Sem histórico", "gray"),
}
CONDITIONS = {
    "novo": "Novo", "usado_bom": "Usado (bom)", "usado_com_avaria": "Usado com avaria",
    "defeito": "Com defeito", "para_pecas": "Para peças",
}


@st.cache_resource
def _init():
    init_db()
    return True


def check_password() -> bool:
    pwd = os.getenv("APP_PASSWORD")
    if not pwd or st.session_state.get("auth_ok"):
        return True
    st.title("📺 OLX Monitor")
    typed = st.text_input("Senha", type="password")
    if typed:
        if typed == pwd:
            st.session_state.auth_ok = True
            st.rerun()
        st.error("Senha incorreta")
    return False


def brl(v) -> str:
    if v is None:
        return "Preço não informado"
    return "R$ " + f"{float(v):,.0f}".replace(",", ".")


def local_dt(dt) -> str:
    if not dt:
        return "?"
    from datetime import timezone
    return dt.replace(tzinfo=timezone.utc).astimezone(TZ).strftime("%d/%m %H:%M")


def humanize(feature: str, rule_names: dict[int, str]) -> str:
    kind, _, value = feature.partition(":")
    if kind == "regra":
        return f"regra “{rule_names.get(int(value), value)}”"
    if kind == "estado":
        return CONDITIONS.get(value, value).lower()
    if kind == "avaliacao":
        return PRICE_LABELS.get(value, (value,))[0].lower()
    if kind == "palavra":
        return f"“{value}”"
    if kind == "tamanho":
        return f'{value}"'
    if kind == "defeito":
        return DEFECT_TYPES[value][0].lower() if value in DEFECT_TYPES else value
    if kind in ("uf", "linha"):
        return value
    return {"preco_vs_grupo": "preço vs. grupo", "vendedor_profissional": "vendedor profissional",
            "dias_no_ar": "tempo no ar", "preco_log": "faixa de preço"}.get(feature, feature)


def rule_names(db) -> dict[int, str]:
    return dict(db.execute(select(FilterRule.id, FilterRule.name)).all())


# ----------------------------------------------------------------- cartões
def photo_html(l: Listing) -> str:
    """A OLX recusa (HTTP 403) fotos pedidas a partir de outro site, pelo cabeçalho Referer;
    sem Referer elas abrem. Por isso <img referrerpolicy="no-referrer"> em vez de st.image."""
    return (f'<a href="{html.escape(l.url)}" target="_blank">'
            f'<img src="{html.escape(l.image_url)}" referrerpolicy="no-referrer" loading="lazy" '
            f'alt="foto do anúncio" style="width:100%;aspect-ratio:4/3;object-fit:cover;'
            f'border-radius:8px"></a>')


def render_card(db, l: Listing, names: dict[int, str]) -> None:
    with st.container(border=True):
        img, body = st.columns([1, 3], gap="medium")
        with img:
            if l.image_url:
                st.markdown(photo_html(l), unsafe_allow_html=True)
            else:
                st.markdown("### 📺")
        with body:
            st.markdown(f"**[{l.title}]({l.url})**")
            ev = l.latest_evaluation
            badges = []
            if ev and ev.price_label in PRICE_LABELS:
                txt, color = PRICE_LABELS[ev.price_label]
                badges.append(f":{color}-badge[{txt}]")
            if l.condition:
                badges.append(f":orange-badge[{CONDITIONS.get(l.condition, l.condition)}]")
            for t in defect_types(l):
                badges.append(f":red-badge[🔧 {DEFECT_TYPES[t][0]}]")
            if l.category:
                badges.append(f":gray-badge[{l.category.name}]")
            st.markdown(f"### {brl(l.current_price)} " + " ".join(badges))

            info = [f"📍 {l.location or '?'}"]
            if l.posted_at:
                info.append(f"🗓️ postado {local_dt(l.posted_at)}")
            if ev and ev.group_median:
                info.append(f"mediana do grupo {brl(ev.group_median)} ({ev.sample_size} anúncios)")
            if l.score:
                info.append(f"score {l.score.score:.2f}")
            st.caption(" · ".join(info))

            if l.score and l.score.features_json:
                why = " · ".join(f"{'▲' if v > 0 else '▼'} {humanize(k, names)}"
                                 for k, v in l.score.features_json.items())
                st.caption(f"Por que: {why}")
            if l.rule_matches:
                st.markdown(" ".join(
                    f":violet-badge[{m.rule.name}: “{(m.matched_text or '')[:40]}”]"
                    for m in l.rule_matches))
            if l.description:
                with st.expander("Descrição"):
                    st.write(l.description)

            current = l.feedback.value if l.feedback else 0
            b1, b2, _ = st.columns([1, 1.4, 3])
            if b1.button("👍 Gostei", key=f"up{l.id}",
                         type="primary" if current == 1 else "secondary"):
                clear_feedback(db, l.id) if current == 1 else set_feedback(db, l, 1)
                st.rerun()
            if b2.button("👎 Não gostei", key=f"down{l.id}",
                         type="primary" if current == -1 else "secondary"):
                clear_feedback(db, l.id) if current == -1 else set_feedback(db, l, -1)
                st.rerun()
            note = l.note
            with st.expander("✍️ Comentar o que gostei / não gostei" + (" (salvo)" if note else "")):
                with st.form(f"note{l.id}", border=False):
                    liked = st.text_area("O que gostei", value=(note.liked or "") if note else "",
                                         key=f"liked{l.id}", height=68,
                                         placeholder="ex.: backlight, preço baixo, perto de SP")
                    disliked = st.text_area("O que não gostei", value=(note.disliked or "") if note else "",
                                            key=f"disliked{l.id}", height=68,
                                            placeholder="ex.: tela quebrada, só retirada")
                    if st.form_submit_button("Salvar comentário"):
                        save_note(db, l, liked, disliked)
                        st.rerun()


# ------------------------------------------------------------------- abas
def tab_top(db, days: int, limit: int, show_disliked: bool, types: set[str]) -> None:
    items = top_listings(db, days=days, limit=limit, hide_disliked=not show_disliked,
                         defect_filter=types or None)
    if not items:
        st.info("Nenhum anúncio nesse período" + (" com esse tipo de defeito" if types else "")
                + ". Aumente o período na barra lateral ou confira a aba **Execuções** "
                "para ver se o scraper rodou.")
        return
    names = rule_names(db)
    for l in items:
        render_card(db, l, names)


def tab_all(db, types: set[str]) -> None:
    c1, c2, c3, c4 = st.columns(4)
    q = c1.text_input("Buscar no título/descrição")
    sizes = sorted({s for s in db.scalars(select(Listing.screen_size).distinct()) if s})
    size = c2.selectbox("Tamanho", ["Todos"] + sizes)
    cats = db.scalars(select(ProductCategory).order_by(ProductCategory.name)).all()
    cat = c3.selectbox("Grupo", ["Todos"] + [c.name for c in cats])
    fb = c4.selectbox("Feedback", ["Todos", "👍", "👎", "Sem feedback"])

    stmt = select(Listing).order_by(Listing.first_seen_at.desc())
    if q:
        stmt = stmt.where(Listing.title.ilike(f"%{q}%") | Listing.description.ilike(f"%{q}%"))
    if size != "Todos":
        stmt = stmt.where(Listing.screen_size == size)
    if cat != "Todos":
        stmt = stmt.where(Listing.category_id == next(c.id for c in cats if c.name == cat))
    rows = db.scalars(stmt.limit(1000)).all()
    want = {"👍": 1, "👎": -1, "Sem feedback": 0}.get(fb)
    if want is not None:
        rows = [l for l in rows if (l.feedback.value if l.feedback else 0) == want]
    kinds = {l.id: defect_types(l) for l in rows}
    if types:
        rows = [l for l in rows if types & set(kinds[l.id])]

    st.caption(f"{len(rows)} anúncios")
    st.dataframe(
        [{
            "Título": l.title, "Preço": float(l.current_price) if l.current_price else None,
            "Grupo": l.category.name if l.category else None,
            "Estado": CONDITIONS.get(l.condition, l.condition),
            "Defeitos": ", ".join(DEFECT_TYPES[t][0] for t in kinds[l.id]),
            "Avaliação": PRICE_LABELS.get(getattr(l.latest_evaluation, "price_label", ""), ("",))[0],
            "Local": l.location, "Visto em": local_dt(l.first_seen_at),
            "Ativo": l.is_active, "Link": l.url,
        } for l in rows],
        width="stretch", hide_index=True,
        column_config={
            "Preço": st.column_config.NumberColumn(format="R$ %.0f"),
            "Link": st.column_config.LinkColumn(display_text="abrir"),
        },
    )


def tab_rules(db) -> None:
    st.caption("Os tipos de defeito mais comuns já são reconhecidos sozinhos (filtro **Tipo de "
               "defeito** na barra lateral). Aqui você cria os seus, aplicados ao título e à "
               "descrição. Ex.: *desliga a cada 40min*, *tela trincada*. **include** = só mostra "
               "quem casar; **exclude** = esconde; **tag** = só marca e pesa no score.")
    with st.form("new_rule", clear_on_submit=True):
        c1, c2 = st.columns([1, 2])
        name = c1.text_input("Nome", placeholder="Desliga sozinha")
        pattern = c2.text_input("Padrão (regex)", placeholder=r"deslig\w*\s+(sozinh\w*|a cada \d+\s*min)")
        c3, c4, c5 = st.columns(3)
        action = c3.selectbox("Ação", ["tag", "include", "exclude"])
        cond = c4.selectbox("Define o estado", ["(não muda)"] + list(CONDITIONS))
        weight = c5.number_input("Peso no score", value=1.0, step=0.5)
        if st.form_submit_button("Adicionar regra"):
            try:
                re.compile(pattern, re.I)
            except re.error as exc:
                st.error(f"Regex inválida: {exc}")
            else:
                if name and pattern:
                    db.add(FilterRule(name=name, pattern=pattern, action=action, weight=weight,
                                      sets_condition=None if cond == "(não muda)" else cond))
                    db.commit()
                    with st.spinner("Reaplicando regras nos anúncios..."):
                        reprocess_all(db)
                    st.rerun()

    for r in db.scalars(select(FilterRule).order_by(FilterRule.id)):
        c1, c2, c3 = st.columns([3, 4, 1])
        c1.markdown(f"**{r.name}** · {r.action} · peso {r.weight:g}"
                    + (f" · → {CONDITIONS.get(r.sets_condition)}" if r.sets_condition else ""))
        c2.code(r.pattern, language=None)
        active = c3.toggle("Ativa", value=r.is_active, key=f"rule{r.id}")
        if active != r.is_active:
            r.is_active = active
            db.commit()
            with st.spinner("Reaplicando regras nos anúncios..."):
                reprocess_all(db)
            st.rerun()


def tab_terms(db) -> None:
    st.caption("O que o scraper procura todo dia (Brasil todo).")
    with st.form("new_term", clear_on_submit=True):
        c1, c2, c3 = st.columns([3, 1, 1])
        query = c1.text_input("Termo", placeholder="TV LG OLED")
        pages = c2.number_input("Páginas", 1, 20, 3)
        max_price = c3.number_input("Preço máx. (0 = sem)", 0, 100000, 0, step=100)
        if st.form_submit_button("Adicionar termo") and query:
            db.add(SearchTerm(query=query, max_pages=pages, region="brasil",
                              max_price=max_price or None))
            db.commit()
            st.rerun()
    for t in db.scalars(select(SearchTerm).order_by(SearchTerm.id)):
        c1, c2 = st.columns([5, 1])
        c1.markdown(f"**{t.query}** · {t.max_pages} páginas"
                    + (f" · até {brl(t.max_price)}" if t.max_price else ""))
        active = c2.toggle("Ativo", value=t.is_active, key=f"term{t.id}")
        if active != t.is_active:
            t.is_active = active
            db.commit()
            st.rerun()


def tab_learning(db) -> None:
    likes = db.scalar(select(func.count()).where(Feedback.value == 1))
    dislikes = db.scalar(select(func.count()).where(Feedback.value == -1))
    mv = db.scalar(select(ModelVersion).where(ModelVersion.is_active.is_(True)))
    c1, c2, c3 = st.columns(3)
    c1.metric("Cliques 👍", likes)
    c2.metric("Cliques 👎", dislikes)
    c3.metric("Versão do modelo", mv.version if mv else "inicial")
    if not mv:
        st.info(f"O score ainda usa só os pesos iniciais (barato em relação ao grupo, com defeito, "
                f"suas regras). O aprendizado começa com {MIN_FEEDBACK} cliques, tendo pelo menos "
                f"um 👍 e um 👎.")
    else:
        m = mv.metrics_json or {}
        st.caption(f"Treinado em {local_dt(mv.trained_at)} com {mv.n_samples} cliques · "
                   f"acerto no treino {m.get('acuracia_treino', 0):.0%}")
        prior = prior_weights(db)
        learned = db.execute(select(FeatureWeight.feature, FeatureWeight.weight)
                             .where(FeatureWeight.model_version == mv.version)).all()
        deltas = sorted(((f, w - prior.get(f, 0.0)) for f, w in learned), key=lambda x: x[1])
        names = rule_names(db)
        up, down = st.columns(2)
        up.markdown("**O que você mais gosta**")
        for f, d in reversed(deltas[-8:]):
            if d > 0:
                up.markdown(f"▲ {humanize(f, names)} `+{d:.2f}`")
        down.markdown("**O que você evita**")
        for f, d in deltas[:8]:
            if d < 0:
                down.markdown(f"▼ {humanize(f, names)} `{d:.2f}`")

    b1, b2, _ = st.columns([1, 1, 2])
    if b1.button("Retreinar agora"):
        learn_from_feedback(db)
        st.rerun()
    if b2.button("Reprocessar anúncios"):
        with st.spinner("Recalculando estado, preço e score..."):
            n = reprocess_all(db)
        st.success(f"{n} anúncios atualizados")
    notes = note_word_weights(db)
    if notes:
        st.markdown("**Palavras dos seus comentários** (valem na hora, antes mesmo dos cliques)")
        st.caption(" · ".join(f"{'▲' if v > 0 else '▼'} {k.split(':', 1)[1]}"
                              for k, v in sorted(notes.items(), key=lambda kv: -abs(kv[1]))[:30]))
    with st.expander("Pesos iniciais"):
        st.json(DEFAULT_WEIGHTS)


def tab_runs(db) -> None:
    runs = db.scalars(select(ScrapeRun).order_by(ScrapeRun.id.desc()).limit(30)).all()
    if not runs:
        st.info("O scraper ainda não rodou. Ele roda todo dia às 07:00 no seu computador "
                "(e o GitHub Actions tenta como reserva).")
        return
    icon = {"ok": "✅", "blocked": "⛔", "error": "❌", "running": "⏳"}
    st.dataframe([{
        "": icon.get(r.status, ""), "Início": local_dt(r.started_at), "Status": r.status,
        "Modo": r.fetch_mode, "Anúncios": r.ads_found, "Novos": r.ads_new,
        "Erro": (r.error_message or "")[:200],
    } for r in runs], width="stretch", hide_index=True)


# ------------------------------------------------------------------ página
def main() -> None:
    if not check_password():
        return
    _init()
    with SessionLocal() as db:
        with st.sidebar:
            st.title("📺 OLX Monitor")
            period = st.radio("Período", ["Hoje", "3 dias", "7 dias", "30 dias"], horizontal=True)
            days = {"Hoje": 1, "3 dias": 3, "7 dias": 7, "30 dias": 30}[period]
            limit = st.slider("Quantos anúncios", 5, 100, 20, step=5)
            show_disliked = st.toggle("Mostrar os que marquei 👎", value=False)
            types = set(st.multiselect(
                "Tipo de defeito", list(DEFECT_TYPES), format_func=lambda k: DEFECT_TYPES[k][0],
                placeholder="Todos", help="Mostra só anúncios com pelo menos um dos tipos escolhidos "
                "(vale para Melhores do dia e Todos)."))
            st.divider()
            total = db.scalar(select(func.count(Listing.id)))
            today = db.scalar(select(func.count(Listing.id)).where(
                Listing.first_seen_at >= day_start_utc()))
            fb = dict(db.execute(select(Feedback.value, func.count()).group_by(Feedback.value)).all())
            m1, m2 = st.columns(2)
            m1.metric("Anúncios", total)
            m2.metric("Novos hoje", today)
            m1.metric("👍", fb.get(1, 0))
            m2.metric("👎", fb.get(-1, 0))
            if not os.getenv("DATABASE_URL"):
                st.warning("Sem DATABASE_URL: usando banco local temporário. "
                           "Na nuvem, configure o Neon nos Secrets do app.")
            last = db.scalar(select(ScrapeRun).order_by(ScrapeRun.id.desc()).limit(1))
            if last:
                st.caption(f"Última execução: {local_dt(last.started_at)} · {last.status}")

        tabs = st.tabs(["🏆 Melhores do dia", "📋 Todos", "🔎 Regras de filtro",
                        "🗂️ Termos de busca", "🧠 Aprendizado", "⚙️ Execuções"])
        with tabs[0]:
            tab_top(db, days, limit, show_disliked, types)
        with tabs[1]:
            tab_all(db, types)
        with tabs[2]:
            tab_rules(db)
        with tabs[3]:
            tab_terms(db)
        with tabs[4]:
            tab_learning(db)
        with tabs[5]:
            tab_runs(db)


main()
