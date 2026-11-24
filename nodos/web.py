"""Servidor web: mapa + API, con actualización automática de los datos.

    python -m nodos servir --host 0.0.0.0 --port 8000

Al arrancar lanza `actualizar()` en segundo plano y lo repite cada
NODOS_ACTUALIZAR_CADA_HORAS (6 por defecto; 0 = solo al arrancar).
Con NODOS_SIN_ACTUALIZAR=1 solo sirve lo que ya hay en data/nodos.duckdb.
POST /api/ampliar pide más historia y adelanta el siguiente ciclo
(se desactiva con NODOS_PERMITIR_AMPLIAR=0, útil si el mapa es público).
"""

from __future__ import annotations

import threading
from contextlib import asynccontextmanager
from datetime import date, datetime
from pathlib import Path

from fastapi import Body, FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse

from . import config, servicio
from .actualizar import (
    MINUTOS_POR_DIA,
    OPCIONES_AMPLIAR,
    actualizar,
    ampliar_ventana,
    leer_estado,
    ventana_actual,
)

WEB = config.RAIZ / "web"
_bloqueo = threading.Lock()
_detener = threading.Event()
_despertar = threading.Event()  # adelanta el siguiente ciclo (p. ej. al pedir más datos)
_cache: dict = {}
_hilo: threading.Thread | None = None


def _horas() -> float:
    try:
        return float(config.obtener("NODOS_ACTUALIZAR_CADA_HORAS", "6"))
    except ValueError:
        return 6.0


def _permite_ampliar() -> bool:
    return _hilo is not None and config.obtener("NODOS_PERMITIR_AMPLIAR", "1") not in ("0", "false", "no")


def _ciclo() -> None:
    while not _detener.is_set():
        _despertar.clear()
        if _bloqueo.acquire(blocking=False):
            try:
                actualizar()
                _cache.clear()
            finally:
                _bloqueo.release()
        horas = _horas()
        # Espera hasta el próximo ciclo; con 0 horas solo despierta si se piden más datos.
        _despertar.wait(horas * 3600 if horas > 0 else None)


@asynccontextmanager
async def _vida(app: FastAPI):
    global _hilo
    if config.obtener("NODOS_SIN_ACTUALIZAR", "0") not in ("1", "true", "si", "sí"):
        _hilo = threading.Thread(target=_ciclo, name="actualizador", daemon=True)
        _hilo.start()
    yield
    _detener.set()
    _despertar.set()


app = FastAPI(title="Nodos del SEN", lifespan=_vida, docs_url="/api/docs", redoc_url=None)


def _cacheado(clave, funcion):
    """Memoriza respuestas mientras no cambie la base publicada."""
    try:
        version = servicio.BASE.stat().st_mtime_ns
    except FileNotFoundError:
        version = None
    k = (version, *clave)
    if k not in _cache:
        try:
            _cache[k] = funcion()
        except servicio.SinDatos as exc:
            raise HTTPException(status_code=503, detail=str(exc))
    return _cache[k]


@app.get("/", include_in_schema=False)
def inicio():
    return FileResponse(WEB / "index.html", headers={"Cache-Control": "no-cache"})


@app.get("/2d", include_in_schema=False)
@app.get("/3d", include_in_schema=False)
def enlaces_antiguos():
    return RedirectResponse("/", status_code=308)


@app.get("/ampliar.js", include_in_schema=False)
def ampliar_js():
    return FileResponse(WEB / "ampliar.js", media_type="text/javascript", headers={"Cache-Control": "no-cache"})


@app.get("/salud", include_in_schema=False)
def salud():
    return {"ok": True}


@app.get("/api/estado")
def estado():
    """Última actualización, paso en curso y resultado de los tests de dbt."""
    e = leer_estado()
    e["hay_datos"] = servicio.BASE.exists()
    if e.get("en_curso") and e.get("inicio"):
        # Se calcula aquí para no depender de la zona horaria del navegador.
        try:
            e["transcurrido_s"] = max(0, round((datetime.now() - datetime.fromisoformat(e["inicio"])).total_seconds()))
        except ValueError:
            pass
    e["actualizar_cada_horas"] = _horas()
    e["ventana"] = ventana_actual()
    e["ampliar"] = {
        "permitido": _permite_ampliar(),
        "opciones": [{"dias": d, "minutos": d * MINUTOS_POR_DIA} for d in OPCIONES_AMPLIAR],
    }
    return JSONResponse(e, headers={"Cache-Control": "no-cache"})


@app.post("/api/ampliar")
def ampliar(dias: int = Body(..., embed=True, description=f"Días de historia de demanda real: {OPCIONES_AMPLIAR}")):
    """Pide más historia: la guarda y adelanta el siguiente ciclo de actualización."""
    if not _permite_ampliar():
        raise HTTPException(status_code=403, detail="Este servidor no permite pedir más datos.")
    try:
        ventana = ampliar_ventana(dias)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    ocupado = _bloqueo.locked()  # antes de despertar: si no, el ciclo recién lanzado cuenta como "en curso"
    _despertar.set()
    return {"ok": True, "ventana": ventana_actual(), "pedido": ventana, "en_curso": ocupado}


@app.get("/api/dias")
def dias():
    return _cacheado(("dias",), servicio.dias_disponibles)


@app.get("/api/mapa")
def mapa(dia: date | None = Query(None, description="AAAA-MM-DD; por defecto el último con demanda y precio")):
    if dia is None:
        disp = _cacheado(("dias",), servicio.dias_disponibles)
        con_precio = [d["dia"] for d in disp["demanda"] if d["con_precio"]] or [d["dia"] for d in disp["demanda"]]
        dia = servicio.ultimo_dia(con_precio)
        if dia is None:
            raise HTTPException(status_code=503, detail="Todavía no hay demanda real cargada.")
    return _cacheado(("mapa", dia), lambda: servicio.datos_dia(dia))


@app.get("/api/pronostico")
def pronostico(dia: date | None = Query(None, description="AAAA-MM-DD; por defecto el último")):
    if dia is None:
        dia = servicio.ultimo_dia(_cacheado(("dias",), servicio.dias_disponibles)["pronostico"])
        if dia is None:
            raise HTTPException(status_code=503, detail="Todavía no hay pronóstico cargado.")
    return _cacheado(("pron", dia), lambda: servicio.datos_pronostico(dia))


@app.get("/api/base")
def base():
    """Contornos de Chile y países vecinos (Natural Earth 1:50m), para el mapa base «Mínimo»."""
    from .mapa import base_mapa

    if "base" not in _cache:
        _cache["base"] = base_mapa()
    return JSONResponse(_cache["base"], headers={"Cache-Control": "public, max-age=86400"})


def servir(host: str = "127.0.0.1", port: int = 8000) -> None:
    import uvicorn

    uvicorn.run(app, host=host, port=port, log_level="info")
