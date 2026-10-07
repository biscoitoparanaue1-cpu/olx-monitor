"""Configuração: termos de busca, regras de filtro e grupos de preço."""
import re

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import get_db, require_api_key
from app.models import FilterRule, Listing, ProductCategory, SearchTerm
from app.pipeline import reprocess_all
from app.schemas import CategoryOut, FilterRuleIn, FilterRuleOut, SearchTermIn, SearchTermOut

router = APIRouter(prefix="/api", tags=["configuração"])
write = [Depends(require_api_key)]


def _crud(model, schema_in, schema_out, path: str, label: str, validate=None, after=None):
    @router.get(f"/{path}", response_model=list[schema_out], name=f"list_{path}")
    def list_items(db: Session = Depends(get_db)):
        return db.scalars(select(model).order_by(model.id)).all()

    @router.post(f"/{path}", response_model=schema_out, status_code=201,
                 dependencies=write, name=f"create_{path}")
    def create(body: schema_in, db: Session = Depends(get_db)):
        if validate:
            validate(body)
        obj = model(**body.model_dump())
        db.add(obj)
        db.commit()
        if after:
            after(db)
        return obj

    @router.put(f"/{path}/{{item_id}}", response_model=schema_out,
                dependencies=write, name=f"update_{path}")
    def update(item_id: int, body: schema_in, db: Session = Depends(get_db)):
        obj = db.get(model, item_id)
        if not obj:
            raise HTTPException(404, f"{label} não encontrado(a)")
        if validate:
            validate(body)
        for k, v in body.model_dump().items():
            setattr(obj, k, v)
        db.commit()
        if after:
            after(db)
        return obj

    @router.delete(f"/{path}/{{item_id}}", status_code=204,
                   dependencies=write, name=f"delete_{path}")
    def delete(item_id: int, db: Session = Depends(get_db)):
        obj = db.get(model, item_id)
        if obj:
            if hasattr(obj, "is_active"):  # preserva histórico: só desativa
                obj.is_active = False
            else:
                db.delete(obj)
            db.commit()
            if after:
                after(db)
        return Response(status_code=204)


def _validate_rule(body: FilterRuleIn) -> None:
    if body.pattern_type == "regex":
        try:
            re.compile(body.pattern, re.I)
        except re.error as exc:
            raise HTTPException(422, f"Regex inválida: {exc}")


_crud(SearchTerm, SearchTermIn, SearchTermOut, "search-terms", "Termo")
# Mudou regra -> reaplica estado, preço e score em todos os anúncios ativos
_crud(FilterRule, FilterRuleIn, FilterRuleOut, "rules", "Regra", _validate_rule, after=reprocess_all)


@router.get("/categories", response_model=list[CategoryOut], summary="Grupos de comparação de preço")
def list_categories(db: Session = Depends(get_db)):
    counts = dict(db.execute(select(Listing.category_id, func.count(Listing.id))
                             .group_by(Listing.category_id)).all())
    cats = db.scalars(select(ProductCategory).order_by(ProductCategory.name)).all()
    return [CategoryOut(id=c.id, name=c.name, brand=c.brand, model_line=c.model_line,
                        screen_size=c.screen_size, listings=counts.get(c.id, 0)) for c in cats]
