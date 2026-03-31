"""Tests for dashboard.api FastAPI endpoints."""
from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from dashboard.api import app

client = TestClient(app)

FAKE_TRADES = [
    {
        "id": 1,
        "timestamp": "2026-03-28T12:00:00+00:00",
        "market_id": "0xabc123",
        "question": "Will X happen?",
        "side": "YES",
        "size_usdc": 10.0,
        "entry_price": 0.55,
        "agent_probability": 0.65,
        "market_probability": 0.55,
        "edge_net": 0.08,
        "confidence": 7,
        "status": "open",
        "exit_price": None,
        "pnl": None,
        "resolution_date": None,
    },
    {
        "id": 2,
        "timestamp": "2026-03-27T10:00:00+00:00",
        "market_id": "0xdef456",
        "question": "Will Y happen?",
        "side": "NO",
        "size_usdc": 8.0,
        "entry_price": 0.40,
        "agent_probability": 0.35,
        "market_probability": 0.45,
        "edge_net": 0.06,
        "confidence": 8,
        "status": "won",
        "exit_price": 0.0,
        "pnl": 12.0,
        "resolution_date": "2026-03-29T00:00:00+00:00",
    },
]

FAKE_SCANS = [
    {
        "id": 1,
        "timestamp": "2026-03-28T12:00:00+00:00",
        "markets_scanned": 25,
        "opportunities_found": 3,
        "trades_placed": 1,
    },
]

FAKE_CALIBRATION_REPORT: dict[str, object] = {
    "buckets": [
        {
            "range": "0.3-0.4",
            "predicted": 0.35,
            "actual": 0.40,
            "error": 0.05,
            "samples": 5,
        },
    ],
    "is_calibrated": False,
    "total_resolved": 5,
    "worst_bucket": {
        "range": "0.3-0.4",
        "error": 0.05,
        "samples": 5,
    },
}

FAKE_PORTFOLIO_SNAPSHOT: dict[str, object] = {
    "open_positions": [],
    "total_exposure_usdc": 0.0,
    "position_count": 0,
    "categories": {},
    "available_slots": 5,
}


class TestGetTrades:
    @patch("dashboard.api.db.get_all_trades", return_value=FAKE_TRADES)
    def test_returns_all_trades(self, mock_db: object) -> None:
        resp = client.get("/api/trades")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 2
        assert data[0]["market_id"] == "0xabc123"
        assert data[1]["status"] == "won"

    @patch("dashboard.api.db.get_all_trades", return_value=[])
    def test_returns_empty_list(self, mock_db: object) -> None:
        resp = client.get("/api/trades")
        assert resp.status_code == 200
        assert resp.json() == []


class TestGetScans:
    @patch("dashboard.api.db.get_scans", return_value=FAKE_SCANS)
    def test_returns_scans(self, mock_db: object) -> None:
        resp = client.get("/api/scans")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["markets_scanned"] == 25

    @patch("dashboard.api.db.get_scans", return_value=[])
    def test_returns_empty_scans(self, mock_db: object) -> None:
        resp = client.get("/api/scans")
        assert resp.status_code == 200
        assert resp.json() == []


class TestGetStatus:
    @patch("dashboard.api.db.get_all_trades", return_value=FAKE_TRADES)
    def test_returns_aggregated_stats(self, mock_db: object) -> None:
        resp = client.get("/api/status")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_trades"] == 2
        assert data["open_trades"] == 1
        assert data["resolved_trades"] == 1
        assert data["wins"] == 1
        assert data["losses"] == 0
        assert data["win_rate"] == 1.0
        assert data["total_pnl"] == 12.0
        assert "timestamp" in data

    @patch("dashboard.api.db.get_all_trades", return_value=[])
    def test_status_empty_db(self, mock_db: object) -> None:
        resp = client.get("/api/status")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_trades"] == 0
        assert data["win_rate"] == 0.0
        assert data["total_pnl"] == 0.0


class TestGetPositions:
    @patch("dashboard.api.get_portfolio_snapshot", return_value=FAKE_PORTFOLIO_SNAPSHOT)
    def test_returns_empty_portfolio(self, mock_snap: object) -> None:
        resp = client.get("/api/positions")
        assert resp.status_code == 200
        data = resp.json()
        assert data["position_count"] == 0
        assert data["open_positions"] == []
        assert data["available_slots"] == 5
        assert data["total_exposure_usdc"] == 0.0

    @patch("dashboard.api.get_portfolio_snapshot")
    def test_returns_positions_with_data(self, mock_snap: object) -> None:
        from infra.types import Position, TradingSignal

        signal = TradingSignal(
            market_id="0xabc123",
            question="Will X happen?",
            side="YES",
            agent_probability=0.65,
            market_probability=0.55,
            edge_net=0.08,
            confidence=7,
            tradeable=True,
            news_context="",
            timestamp=datetime(2026, 3, 28, 12, 0, tzinfo=UTC),
        )
        pos = Position(
            position_id="1",
            signal=signal,
            entry_price=0.55,
            size_usdc=10.0,
            size_shares=18.18,
            order_id="order-1",
            status="open",
            pnl=None,
        )
        mock_snap.return_value = {  # type: ignore[union-attr]
            "open_positions": [pos],
            "total_exposure_usdc": 10.0,
            "position_count": 1,
            "categories": {"other": 1},
            "available_slots": 4,
        }
        resp = client.get("/api/positions")
        assert resp.status_code == 200
        data = resp.json()
        assert data["position_count"] == 1
        assert len(data["open_positions"]) == 1
        assert data["open_positions"][0]["signal"]["market_id"] == "0xabc123"
        assert data["total_exposure_usdc"] == 10.0


class TestGetCalibration:
    @patch("dashboard.api.get_calibration_report", return_value=FAKE_CALIBRATION_REPORT)
    def test_returns_calibration_report(self, mock_cal: object) -> None:
        resp = client.get("/api/calibration")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["buckets"]) == 1
        assert data["buckets"][0]["predicted"] == 0.35
        assert data["is_calibrated"] is False
        assert data["total_resolved"] == 5
        assert data["worst_bucket"]["error"] == 0.05

    @patch(
        "dashboard.api.get_calibration_report",
        return_value={
            "buckets": [],
            "is_calibrated": False,
            "total_resolved": 0,
            "worst_bucket": None,
        },
    )
    def test_returns_empty_calibration(self, mock_cal: object) -> None:
        resp = client.get("/api/calibration")
        assert resp.status_code == 200
        data = resp.json()
        assert data["buckets"] == []
        assert data["total_resolved"] == 0


class TestGetHealth:
    @patch("dashboard.api.db.get_scans", return_value=FAKE_SCANS)
    @patch("dashboard.api.db.get_open_positions", return_value=[FAKE_TRADES[0]])
    def test_returns_health_status(self, mock_pos: object, mock_scans: object) -> None:
        resp = client.get("/api/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert data["open_positions"] == 1
        assert data["max_positions"] == 5
        assert data["last_cycle"] == "2026-03-28T12:00:00+00:00"
        assert data["cycle_interval_seconds"] == 900

    @patch("dashboard.api.db.get_scans", return_value=[])
    @patch("dashboard.api.db.get_open_positions", return_value=[])
    def test_health_no_data(self, mock_pos: object, mock_scans: object) -> None:
        resp = client.get("/api/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["open_positions"] == 0
        assert data["last_cycle"] is None


class TestCORS:
    def test_cors_headers_present(self) -> None:
        resp = client.options(
            "/api/health",
            headers={
                "Origin": "http://localhost:5173",
                "Access-Control-Request-Method": "GET",
            },
        )
        assert resp.status_code == 200
        assert "access-control-allow-origin" in resp.headers
