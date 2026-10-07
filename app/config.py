import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

# Local: SQLite. Nuvem: a connection string do Neon, como o painel entrega:
#   postgresql://usuario:senha@ep-xxx.sa-east-1.aws.neon.tech/neondb?sslmode=require
DATABASE_URL = os.getenv("DATABASE_URL", f"sqlite:///{BASE_DIR / 'olx_monitor.db'}")
# O SQLAlchemy precisa saber o driver: postgresql:// -> postgresql+psycopg://
for _prefix in ("postgres://", "postgresql://"):
    if DATABASE_URL.startswith(_prefix):
        DATABASE_URL = "postgresql+psycopg://" + DATABASE_URL[len(_prefix):]

OLX_BASE_URL = "https://www.olx.com.br"
# Região da busca: "brasil" = país inteiro. Ex.: "estado-sp" para só São Paulo.
OLX_REGION = os.getenv("OLX_REGION", "brasil")

# Educação com o servidor: pausa aleatória entre requisições (segundos)
REQUEST_DELAY_RANGE = (3.0, 8.0)
REQUEST_TIMEOUT = 30.0
MAX_RETRIES = 3

# Visitar a página de cada anúncio NOVO para pegar a descrição completa
FETCH_DETAILS_FOR_NEW = True

# "auto": httpx primeiro, Playwright se bloquear | "httpx" | "playwright"
FETCH_MODE = os.getenv("FETCH_MODE", "auto")
