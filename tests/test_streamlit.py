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
        l = add_listing(db, "1", "TV LG OLED C1 55 desliga sozinha", 1800, score=0.9, z=-1.0)
        db.commit()
        lid = l.id

    at = AppTest.from_file(APP, default_timeout=30).run()
    assert not at.exception
    assert [b.label for b in at.button][:2] == ["👍 Gostei", "👎 Não gostei"]

    at.button(key=f"up{lid}").click().run()
    with SessionLocal() as db:
        assert db.query(Feedback).one().value == 1
    at.button(key=f"up{lid}").click().run()  # clicar de novo desfaz
    with SessionLocal() as db:
        assert db.query(Feedback).count() == 0
