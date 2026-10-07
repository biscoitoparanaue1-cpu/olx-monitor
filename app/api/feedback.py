from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy.orm import Session

from app.api.deps import get_db, require_api_key
from app.models import Listing
from app.schemas import FeedbackIn, FeedbackOut
from app.services import clear_feedback, set_feedback

router = APIRouter(prefix="/api/feedback", tags=["feedback"],
                   dependencies=[Depends(require_api_key)])


@router.post("", response_model=FeedbackOut, summary="Gostei (1) / Não gostei (-1)")
def give_feedback(body: FeedbackIn, db: Session = Depends(get_db)):
    listing = db.get(Listing, body.listing_id)
    if not listing:
        raise HTTPException(404, "Anúncio não encontrado")
    return set_feedback(db, listing, body.value)


@router.delete("/{listing_id}", status_code=204, summary="Desfazer feedback")
def undo_feedback(listing_id: int, db: Session = Depends(get_db)):
    clear_feedback(db, listing_id)
    return Response(status_code=204)
