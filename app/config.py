import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent


def _load_dotenv(path: Path) -> None:
    """Lê um .env simples (CHAVE=valor) sem sobrescrever variáveis já definidas."""
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, _, value = line.partition("=")
            os.environ.setdefault(key.strip(), value.strip().strip("'\""))


_load_dotenv(BASE_DIR / ".env")  # usado quando o scraper roda na sua máquina

# Local: SQLite. Nuvem: a connection string do Neon, como o painel entrega:
#   postgresql://usuario:senha@ep-xxx.sa-east-1.aws.neon.tech/neondb?sslmode=require
# "or": no GitHub Actions um secret não configurado chega como string vazia
DATABASE_URL = os.getenv("DATABASE_URL") or f"sqlite:///{BASE_DIR / 'olx_monitor.db'}"
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

# Visitar a página dos anúncios ainda sem descrição (novos ou que falharam antes)
FETCH_DETAILS_FOR_NEW = True
MAX_DETAILS_PER_RUN = int(os.getenv("MAX_DETAILS_PER_RUN", "150"))

# Proxy opcional (ex.: residencial), formato http://usuario:senha@host:porta
OLX_PROXY = os.getenv("OLX_PROXY") or None

# "auto": httpx primeiro, Playwright se bloquear | "httpx" | "playwright"
FETCH_MODE = os.getenv("FETCH_MODE", "auto")
