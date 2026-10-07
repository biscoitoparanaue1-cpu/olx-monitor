from fastapi import APIRouter, BackgroundTasks, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import get_db, require_api_key
from app.models import Feedback, Listing, ModelVersion, ScrapeRun
from app.pipeline import reprocess_all
from app.schemas import ScrapeRunOut, StatsOut
from app.scoring.model import active_model, learn_from_feedback, prior_weights
from app.services import day_start_utc

router = APIRouter(prefix="/api", tags=["sistema"])


@router.get("/health")
def health():
    return {"ok": True}


@router.get("/stats", response_model=StatsOut)
def stats(db: Session = Depends(get_db)):
    since = day_start_utc()
    count = lambda *w: db.scalar(select(func.count(Listing.id)).where(*w))  # noqa: E731
    fb = dict(db.execute(select(Feedback.value, func.count()).group_by(Feedback.value)).all())
    return StatsOut(
        listings_total=count(),
        listings_active=count(Listing.is_active.is_(True)),
        listings_today=count(Listing.first_seen_at >= since),
        feedback_likes=fb.get(1, 0), feedback_dislikes=fb.get(-1, 0),
        active_model_version=db.scalar(
            select(ModelVersion.version).where(ModelVersion.is_active.is_(True))),
        last_runs=[ScrapeRunOut.model_validate(r) for r in db.scalars(
            select(ScrapeRun).order_by(ScrapeRun.id.desc()).limit(10))],
    )


@router.post("/jobs/run", status_code=202, dependencies=[Depends(require_api_key)],
             summary="Dispara o scraping agora (em segundo plano)")
def run_now(background: BackgroundTasks):
    from app.jobs.daily import main as daily_main
    background.add_task(daily_main)
    return {"started": True}


@router.get("/model", summary="Modelo de score ativo e o que ele aprendeu")
def model_info(db: Session = Depends(get_db)):
    version, weights = active_model(db)
    prior = prior_weights(db)
    mv = db.get(ModelVersion, version) if version else None
    deltas = sorted(((k, round(w - prior.get(k, 0.0), 3)) for k, w in weights.items()
                     if abs(w - prior.get(k, 0.0)) > 1e-3), key=lambda kv: kv[1])
    return {
        "version": version,
        "algorithm": mv.algorithm if mv else "weighted_rules",
        "metrics": mv.metrics_json if mv else None,
        "most_liked": dict(reversed(deltas[-10:])),
        "most_avoided": dict(deltas[:10]),
    }


@router.post("/model/retrain", dependencies=[Depends(require_api_key)])
def retrain(db: Session = Depends(get_db)):
    learn_from_feedback(db)
    return {"version": active_model(db)[0]}


@router.post("/listings/reprocess", dependencies=[Depends(require_api_key)],
             summary="Reaplica regras, avaliação de preço e score")
def reprocess(db: Session = Depends(get_db)):
    return {"processed": reprocess_all(db)}
