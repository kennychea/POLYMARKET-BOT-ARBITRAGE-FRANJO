"""FastAPI backend for the Polymarket Agent dashboard."""
from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import asdict
from datetime import UTC, datetime
from typing import Any

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

import infra.config as cfg
import infra.db as db

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    db.init_db()
    yield


app = FastAPI(title="Polymarket Agent API", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["GET"],
    allow_headers=["*"],
)


@app.get("/api/trades")
def get_trades() -> list[dict[str, Any]]:
    """Return all trades (open + resolved)."""
    return db.get_all_trades()


@app.get("/api/scans")
def get_scans() -> list[dict[str, Any]]:
    """Return recent market scan results."""
    return db.get_scans()


@app.get("/api/calibration")
def get_calibration() -> list[dict[str, Any]]:
    """Return calibration buckets for resolved trades."""
    buckets = db.compute_calibration()
    return [asdict(b) for b in buckets]


@app.get("/api/health")
def get_health() -> dict[str, Any]:
    """Return system health: scheduler status, last cycle, open positions."""
    open_positions = db.get_open_positions()
    scans = db.get_scans(limit=1)
    last_cycle = scans[0]["timestamp"] if scans else None

    return {
        "status": "ok",
        "timestamp": datetime.now(UTC).isoformat(),
        "open_positions": len(open_positions),
        "max_positions": cfg.MAX_SIMULTANEOUS_POSITIONS,
        "last_cycle": last_cycle,
        "cycle_interval_seconds": cfg.CYCLE_INTERVAL_SECONDS,
    }


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("dashboard.api:app", host="0.0.0.0", port=8000, reload=True)
