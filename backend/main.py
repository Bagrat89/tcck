"""
main.py — FastAPI точка входа.
"""
from __future__ import annotations
import asyncio
import logging
import sys
from contextlib import asynccontextmanager
from pathlib import Path

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse

from config import get_settings
from database import init_db, get_active_locations, run_cleanup_loop
from models import LocationResponse
from telethon_listener import run_listener

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)-8s] %(name)s: %(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger(__name__)
settings = get_settings()

BASE   = Path(__file__).parent.parent
STATIC = BASE / "frontend" / "static"
TMPL   = BASE / "frontend" / "templates"


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    tasks = [
        asyncio.create_task(run_listener(),    name="listener"),
        asyncio.create_task(run_cleanup_loop(), name="cleanup"),
    ]
    logger.info("Фоновые задачи запущены")
    try:
        yield
    finally:
        for t in tasks:
            t.cancel()
            try:
                await t
            except asyncio.CancelledError:
                pass
        logger.info("Остановлено")


app = FastAPI(title="TCCK Map", version="1.1.0", lifespan=lifespan,
              docs_url="/api/docs" if settings.debug else None)

app.add_middleware(CORSMiddleware,
                   allow_origins=["*"], allow_methods=["GET"], allow_headers=["*"])
app.mount("/static", StaticFiles(directory=str(STATIC)), name="static")


@app.get("/", include_in_schema=False)
async def index():
    return FileResponse(str(TMPL / "index.html"))


@app.get("/locations", response_model=LocationResponse)
async def locations():
    """Активные маркеры — frontend опрашивает каждые 15 сек."""
    records = await get_active_locations()
    return LocationResponse(total=len(records), locations=records)


@app.get("/health")
async def health():
    return JSONResponse({"status": "ok"})


if __name__ == "__main__":
    uvicorn.run("main:app",
                host=settings.app_host, port=settings.app_port,
                reload=settings.debug, log_level="info")
