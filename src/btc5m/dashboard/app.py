"""FastAPI app for the keyless research dashboard (btc5m dashboard, port 8791).

Serves a small vanilla-JS quant-desk frontend plus JSON endpoints, all backed by
committed artifacts (see data.py). Hermetic: no network, no keys, no live compute.
"""
from __future__ import annotations

from pathlib import Path

from . import data

STATIC = Path(__file__).resolve().parent / "static"


def create_app():
    try:
        from fastapi import FastAPI
        from fastapi.responses import JSONResponse
        from fastapi.staticfiles import StaticFiles
    except Exception as exc:  # pragma: no cover - import guard
        raise RuntimeError(
            "The dashboard needs FastAPI. Install with: pip install -e \".[dashboard]\""
        ) from exc

    app = FastAPI(
        title="Kalshi Microstructure Lab",
        description="Keyless research dashboard — every number traces to a committed artifact.",
        docs_url="/api/docs",
        openapi_url="/api/openapi.json",
    )

    @app.get("/api/health")
    def _health():
        return JSONResponse(data.health())

    @app.get("/api/overview")
    def _overview():
        h = data.load_headline()
        return JSONResponse({
            "plain_story": h.get("plain_story", {}),
            "tiles": h.get("tiles", []),
            "fees_kill_alpha": h.get("fees_kill_alpha", {}),
            "verdict_of_the_lab": h.get("verdict_of_the_lab", ""),
            "verdict_breakdown": data.verdict_breakdown(),
            "glossary": h.get("glossary", {}),
            "market": h.get("market", ""),
            "as_of": h.get("as_of", ""),
        })

    @app.get("/api/ledger")
    def _ledger():
        led = data.load_ledger()
        return JSONResponse({
            "legs": led.get("legs", []),
            "verdict_legend": led.get("verdict_legend", {}),
            "source_doc": led.get("source_doc", "docs/RESEARCH_LEDGER.md"),
            "breakdown": data.verdict_breakdown(),
        })

    @app.get("/api/calibration")
    def _calibration():
        return JSONResponse(data.calibration_view())

    @app.get("/api/backtest")
    def _backtest():
        return JSONResponse(data.backtest_view())

    @app.get("/api/replay")
    def _replay():
        return JSONResponse(data.load_replay())

    if STATIC.is_dir():
        app.mount("/", StaticFiles(directory=str(STATIC), html=True), name="static")

    return app


def run(host: str = "127.0.0.1", port: int = 8791) -> int:
    import uvicorn

    uvicorn.run(create_app(), host=host, port=port, log_level="info")
    return 0
