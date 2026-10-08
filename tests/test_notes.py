"""Comentário "o que gostei / não gostei": vai para o banco e pesa no score na hora."""
from sqlalchemy import event

from app.db import engine
from app.models import FeedbackNote
from app.pipeline import process
from app.scoring.model import note_word_weights
from app.services import save_note, set_feedback
from tests.test_scoring import mk


def test_note_is_saved_and_moves_scores_right_away(db):
    liked = mk(db, 1, "TV LG OLED 55", 1500, desc="sem imagem, backlight queimado")
    other = mk(db, 2, "TV LG OLED 55", 1500, desc="sem imagem, backlight com defeito")
    avoid = mk(db, 3, "TV LG OLED 55", 1500, desc="só retirada, sem imagem")
    process(db, [liked, other, avoid])
    before = {l.id: l.score.score for l in (other, avoid)}

    save_note(db, liked, "Gostei do backlight", "Não gostei de retirada")
    assert db.query(FeedbackNote).one().liked == "Gostei do backlight"
    assert note_word_weights(db) == {"palavra:backlight": 0.5, "palavra:retirada": -0.5}
    assert other.score.score > before[other.id]   # outro anúncio com backlight sobe
    assert avoid.score.score < before[avoid.id]   # "retirada" desce

    save_note(db, liked, "  ", "")                # apagar os dois textos remove o comentário
    assert db.query(FeedbackNote).count() == 0


def test_click_does_not_query_once_per_listing(db):
    ls = [mk(db, i, "TV LG OLED 55", 1000 + i, desc="tela trincada") for i in range(1, 41)]
    process(db, ls)
    db.commit()
    db.expire_all()
    n = [0]
    count = lambda *a: n.__setitem__(0, n[0] + 1)  # noqa: E731
    event.listen(engine, "before_cursor_execute", count)
    try:
        set_feedback(db, ls[0], 1)
    finally:
        event.remove(engine, "before_cursor_execute", count)
    assert n[0] < 30  # antes: uma consulta + um UPDATE por anúncio (cada um é uma ida ao Neon)
