import logging
from contextlib import asynccontextmanager
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from graph import recommend
from database import init_db
from schemas import RecommendationRequest

load_dotenv()
BASE_DIR = Path(__file__).resolve().parent

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db(seed=True)
    yield


app = FastAPI(
    title="AI Listing Recommendation Engine",
    version="1.0.0",
    lifespan=lifespan,
)
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")


@app.get("/")
def home():
    return FileResponse(BASE_DIR / "static" / "index.html")


@app.get("/health")
def health():
    return {"status": "ok"}




@app.post("/recommend")
def get_recommendations(payload: RecommendationRequest):
    try:
        result = recommend(payload.query)
        logger.info("Recommendation API response: %s", result)
        return result

    except RuntimeError as exc:
        logger.warning("Recommendation unavailable: %s", exc)
        raise HTTPException(status_code=503, detail=str(exc))

    except Exception:
        logger.exception("Recommendation failed")
        raise HTTPException(
            status_code=500,
            detail="Recommendation failed. Please try again.",
        )
