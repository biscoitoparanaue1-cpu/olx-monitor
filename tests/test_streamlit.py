from pathlib import Path

from streamlit.testing.v1 import AppTest

from app.db import Base, SessionLocal, engine
from app.models import Feedback
from tests.test_api import add_listing

APP = str(Path(__file__).resolve().parent.parent / "streamlit_app.py")


def test_dashboard_renders_and_records_feedback():
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    with SessionLocal() as db:
        l = add_listing(db, "1", "TV LG OLED C1 55 desliga sozinha", 1800, score=0.9, z=-1.0,
                        image_url="https://img.olx.com.br/images/53/535616082996697.jpg")
        add_listing(db, "2", "TV LG OLED C2 65 tela trincada", 1500, score=0.5)
        db.commit()
        lid = l.id

    at = AppTest.from_file(APP, default_timeout=30).run()
    assert not at.exception
    assert [b.label for b in at.button][:2] == ["👍 Gostei", "👎 Não gostei"]
    # Foto sem Referer: a OLX recusa (403) quando o pedido vem de outro site
    photos = [m.value for m in at.markdown if "<img" in m.value]
    assert photos and 'referrerpolicy="no-referrer"' in photos[0] and "535616082996697" in photos[0]
    assert any("Liga e desliga" in m.value for m in at.markdown)  # tipo de defeito no cartão

    # Filtro por tipo de defeito
    at.sidebar.multiselect[0].set_value(["tela"]).run()
    assert [b.key for b in at.button if b.key and b.key.startswith("up")] == [f"up{lid + 1}"]
    at.sidebar.multiselect[0].set_value([]).run()

    at.button(key=f"up{lid}").click().run()
    with SessionLocal() as db:
        assert db.query(Feedback).one().value == 1
    at.button(key=f"up{lid}").click().run()  # clicar de novo desfaz
    with SessionLocal() as db:
        assert db.query(Feedback).count() == 0
