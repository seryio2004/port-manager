"""Read-only API and static site. It cannot talk to the Docker daemon."""

import json
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles


SNAPSHOT = Path("/data/snapshot.json")
STATIC = Path(__file__).parent / "static"

app = FastAPI(title="Port Manager", docs_url=None, redoc_url=None, openapi_url=None)
app.mount("/static", StaticFiles(directory=STATIC), name="static")


@app.get("/api/snapshot")
def snapshot():
    try:
        data = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return JSONResponse(
            {"ready": False, "message": "Esperando la primera lectura del recolector"},
            status_code=503,
            headers={"Cache-Control": "no-store"},
        )
    except (OSError, ValueError):
        return JSONResponse(
            {"ready": False, "message": "No se ha podido leer el inventario"},
            status_code=503,
            headers={"Cache-Control": "no-store"},
        )
    return JSONResponse(data, headers={"Cache-Control": "no-store"})


@app.get("/api/health")
def health():
    return {"web": "ok", "collector_snapshot": SNAPSHOT.exists()}


@app.get("/", include_in_schema=False)
def index():
    return FileResponse(STATIC / "index.html", headers={"Cache-Control": "no-cache"})
