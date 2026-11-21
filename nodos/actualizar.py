"""Ciclo completo de actualización: descargar lo nuevo -> ubicar barras -> dbt build.

    python -m nodos actualizar

Pensado para correr al iniciar el contenedor y luego cada N horas (lo hace `servir`).
Solo publica la base nueva si `dbt build` termina sin errores: dbt construye en
data/nodos_nuevo.duckdb y, si todo pasa, reemplaza data/nodos.duckdb de una vez.

Cuántos días recientes se mantienen (variables de entorno):
    NODOS_DIAS_PRONOSTICO   3   (ayer, hoy y mañana; se vuelve a pedir porque el CEN lo reemite)
    NODOS_DIAS_DEMANDA_NETA 14
    NODOS_DIAS_CMG          14  (costo marginal real; llega con ~1 semana de desfase)
    NODOS_DIAS_DEMANDA      7   (demanda real; llega con ~2 meses de desfase y es lo más pesado)
"""

from __future__ import annotations

import json
import os
import time
import traceback
from datetime import date, datetime, timedelta

from . import config
from . import dbt as dbt_runner
from .endpoints import ENDPOINTS
from .sip import ClienteSIP, descargar_rango

BASE = config.RAIZ / "data" / "nodos.duckdb"
BASE_NUEVA = config.RAIZ / "data" / "nodos_nuevo.duckdb"
ESTADO = config.RAIZ / "data" / "estado.json"

# alias -> (variable de entorno, días por defecto, desde cuántos días atrás empezar a buscar)
PLAN = {
    "pronostico": ("NODOS_DIAS_PRONOSTICO", 3, -1),
    "demanda-neta": ("NODOS_DIAS_DEMANDA_NETA", 14, 0),
    "cmg-real": ("NODOS_DIAS_CMG", 14, 0),
    "demanda-real": ("NODOS_DIAS_DEMANDA", 7, 30),
}
BUSQUEDA_MAXIMA = 120  # días hacia atrás para encontrar el último día publicado


def _dias(variable: str, defecto: int) -> int:
    try:
        return max(0, int(config.obtener(variable, str(defecto))))
    except ValueError:
        return defecto


def ultimo_dia_publicado(cliente: ClienteSIP, alias: str, empezar_atras: int) -> date | None:
    """Busca hacia atrás el último día con datos (una consulta mínima por día)."""
    e = ENDPOINTS[alias]
    hoy = date.today()
    for atras in range(empezar_atras, BUSQUEDA_MAXIMA):
        dia = hoy - timedelta(days=atras)
        datos = cliente._get(e.ruta, {"startDate": dia.isoformat(), "endDate": dia.isoformat(), "page": 1, "limit": 1})
        if datos.get("data"):
            return dia
    return None


def guardar_estado(**campos) -> dict:
    estado = leer_estado()
    estado.update(campos)
    ESTADO.parent.mkdir(parents=True, exist_ok=True)
    tmp = ESTADO.with_suffix(".tmp")
    tmp.write_text(json.dumps(estado, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    tmp.replace(ESTADO)
    return estado


def leer_estado() -> dict:
    try:
        return json.loads(ESTADO.read_text(encoding="utf-8"))
    except (FileNotFoundError, ValueError):
        return {}


def _publicar_base() -> None:
    """Reemplaza la base publicada por la nueva (reintenta si un lector la tiene abierta)."""
    for intento in range(10):
        try:
            os.replace(BASE_NUEVA, BASE)
            return
        except PermissionError:
            time.sleep(1 + intento)
    raise RuntimeError("No pude reemplazar data/nodos.duckdb (¿está abierta en otro programa?)")


def actualizar(descargar: bool = True) -> dict:
    inicio = time.monotonic()
    guardar_estado(en_curso=True, inicio=datetime.now().isoformat(timespec="seconds"), paso="descargando")
    resumen: dict = {"descargas": {}}
    try:
        if descargar:
            cliente = ClienteSIP()
            for alias, (variable, defecto, atras) in PLAN.items():
                n = _dias(variable, defecto)
                if n == 0:
                    continue
                ultimo = ultimo_dia_publicado(cliente, alias, atras)
                if ultimo is None:
                    print(f"{alias}: no encontré días publicados en los últimos {BUSQUEDA_MAXIMA} días")
                    continue
                desde = ultimo - timedelta(days=n - 1)
                e = ENDPOINTS[alias]
                print(f"{alias}: {desde} -> {ultimo}")
                r = descargar_rango(cliente, e, desde, ultimo, refrescar=e.cambia)
                resumen["descargas"][alias] = {"desde": desde, "hasta": ultimo, **r}
            resumen["peticiones_sip"] = cliente.peticiones

        guardar_estado(paso="ubicando barras")
        from .infotecnica import construir_nodos

        construir_nodos()

        guardar_estado(paso="dbt build")
        BASE_NUEVA.unlink(missing_ok=True)
        proc = dbt_runner.ejecutar(["build"], duckdb=BASE_NUEVA, capturar=True)
        resumen["dbt"] = dbt_runner.resumen_resultados()
        if proc.returncode != 0:
            BASE_NUEVA.unlink(missing_ok=True)
            ultimas = "\n".join((proc.stdout or "").splitlines()[-25:])
            raise RuntimeError(f"dbt build falló; se mantiene la base anterior.\n{ultimas}")
        _publicar_base()

        estado = guardar_estado(
            en_curso=False,
            paso=None,
            ok=True,
            error=None,
            ultima_actualizacion=datetime.now().isoformat(timespec="seconds"),
            duracion_s=round(time.monotonic() - inicio),
            **resumen,
        )
        print(f"Actualización completa en {estado['duracion_s']} s")
        return estado
    except (Exception, SystemExit) as exc:  # se registra y se deja la base anterior publicada
        traceback.print_exc()
        return guardar_estado(
            en_curso=False,
            paso=None,
            ok=False,
            error=str(exc)[:4000],
            ultimo_intento=datetime.now().isoformat(timespec="seconds"),
            duracion_s=round(time.monotonic() - inicio),
            **resumen,
        )
