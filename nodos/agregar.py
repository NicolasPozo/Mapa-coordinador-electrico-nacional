"""Convierte la caché cruda en tablas limpias por barra y hora (data/processed)."""

from __future__ import annotations

from datetime import date

import pandas as pd

from . import config
from .endpoints import ENDPOINTS, Endpoint
from .sip import leer_cache


def _demanda_real(df: pd.DataFrame) -> pd.DataFrame:
    """Suma los retiros de todos los suministradores/clientes de cada barra.

    La API entrega los retiros en kWh con signo negativo; aquí se pasan a MWh positivos.
    Columnas: barra, fecha_hora, demanda_mwh (total) y mwh_<tipo> (p. ej. mwh_R regulado).
    """
    df = df.assign(
        fecha_hora=pd.to_datetime(df["fecha_hora"]),
        mwh=-pd.to_numeric(df["medida_kwh"], errors="coerce") / 1000,
    )
    por_tipo = (
        df.pivot_table(index=["barra", "fecha_hora"], columns="tipo", values="mwh", aggfunc="sum", fill_value=0)
        .add_prefix("mwh_")
    )
    por_tipo.columns.name = None
    por_tipo.insert(0, "demanda_mwh", por_tipo.sum(axis=1))
    return por_tipo.reset_index().sort_values(["fecha_hora", "barra"])


def _cmg_real(df: pd.DataFrame) -> pd.DataFrame:
    """Promedio horario del costo marginal (viene cada 15 min) por barra."""
    df = df.assign(
        fecha_hora=pd.to_datetime(df["fecha"]) + pd.to_timedelta(pd.to_numeric(df["hra"]), unit="h"),
    )
    valores = [c for c in ("cmg_usd_mwh_", "cmg_clp_kwh_") if c in df.columns]
    for c in valores:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    salida = (
        df.groupby(["barra_transf", "fecha_hora"], as_index=False)
        .agg(barra_info=("barra_info", "first"), **{c.rstrip("_"): (c, "mean") for c in valores})
        .rename(columns={"barra_transf": "barra"})
    )
    return salida.sort_values(["fecha_hora", "barra"])


def _pronostico(df: pd.DataFrame) -> pd.DataFrame:
    """Pronóstico por barra y hora; si hay varias emisiones, se queda la más reciente."""
    df = df.assign(
        fecha_hora=pd.to_datetime(df["fecha_hora"]),
        energia_mwh=pd.to_numeric(df["energia_mwh"], errors="coerce"),
    )
    if "date_control" in df.columns:
        df = df.sort_values("date_control").drop_duplicates(["barra", "fecha_hora"], keep="last")
    columnas = [c for c in ("barra", "id_barra_info", "fecha_hora", "energia_mwh", "date_control") if c in df.columns]
    return df[columnas].sort_values(["fecha_hora", "barra"])


def _generico(df: pd.DataFrame) -> pd.DataFrame:
    if "fecha_hora" in df.columns:
        df = df.assign(fecha_hora=pd.to_datetime(df["fecha_hora"], errors="coerce"))
    return df.drop(columns=["_dia_consulta"], errors="ignore")


TRANSFORMACIONES = {
    "demanda-real": _demanda_real,
    "cmg-real": _cmg_real,
    "pronostico": _pronostico,
}


def agregar(endpoint: Endpoint, desde: date | None = None, hasta: date | None = None) -> pd.DataFrame | None:
    crudo = leer_cache(endpoint, desde, hasta)
    if crudo.empty:
        print(f"  {endpoint.alias}: no hay datos en caché; primero usa 'descargar'")
        return None
    tabla = TRANSFORMACIONES.get(endpoint.alias, _generico)(crudo)
    destino = config.DATA_PROCESSED / f"{endpoint.alias}.parquet"
    destino.parent.mkdir(parents=True, exist_ok=True)
    tabla.to_parquet(destino, index=False)
    print(f"  {endpoint.alias}: {len(crudo):,} filas crudas -> {len(tabla):,} filas en {destino.relative_to(config.RAIZ)}")
    return tabla


__all__ = ["agregar", "ENDPOINTS"]
