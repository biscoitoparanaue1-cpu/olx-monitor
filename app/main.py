"""API do OLX Monitor.  Local:  uvicorn app.main:app --reload  ->  http://localhost:8000"""
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.api import feedback, listings, settings, system
from app.config import BASE_DIR
from app.db import init_db


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    yield


app = FastAPI(title="OLX Monitor", version="0.3", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

for r in (listings.router, feedback.router, settings.router, system.router):
    app.include_router(r)

# O painel principal é o Streamlit (streamlit_app.py); isto serve um front estático opcional
_frontend = BASE_DIR / "frontend"
if _frontend.is_dir():
    app.mount("/", StaticFiles(directory=_frontend, html=True), name="frontend")
