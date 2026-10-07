import os
from collections.abc import Iterator

from fastapi import Header, HTTPException
from sqlalchemy.orm import Session

from app.db import SessionLocal

API_KEY = os.getenv("API_KEY")  # se definido, rotas de escrita exigem o header X-API-Key


def get_db() -> Iterator[Session]:
    with SessionLocal() as db:
        yield db


def require_api_key(x_api_key: str | None = Header(default=None)) -> None:
    if API_KEY and x_api_key != API_KEY:
        raise HTTPException(status_code=401, detail="X-API-Key inválida ou ausente")
