"""Consultas sobre las tablas de dbt (data/nodos.duckdb) para el mapa y la API."""

from __future__ import annotations

from collections import defaultdict
from contextlib import contextmanager
from datetime import date

from . import config

BASE = config.RAIZ / "data" / "nodos.duckdb"


class SinDatos(RuntimeError):
    pass


@contextmanager
def conexion():
    """Conexión de solo lectura, abierta y cerrada por consulta (la base se reemplaza al actualizar)."""
    import duckdb

    if not BASE.exists():
        raise SinDatos("Todavía no hay datos: la primera actualización está en curso o falló.")
    con = duckdb.connect(str(BASE), read_only=True)
    try:
        yield con
    finally:
        con.close()


def _nombre(texto) -> str:
    return str(texto or "").replace("S/E ", "").title()


def _r(v, dec):
    return None if v is None else round(float(v), dec)


def dias_disponibles() -> dict:
    with conexion() as con:
        demanda = [r[0].isoformat() for r in con.execute(
            "select distinct dia from modelo.fct_demanda_horaria order by dia").fetchall()]
        cmg = {r[0].isoformat() for r in con.execute(
            "select distinct dia from modelo.fct_cmg_horario").fetchall()}
        pron = [r[0].isoformat() for r in con.execute(
            "select distinct dia from modelo.fct_pronostico_horario order by dia").fetchall()]
    return {
        "demanda": [{"dia": d, "con_precio": d in cmg} for d in demanda],
        "solo_precio": sorted(cmg - set(demanda)),
        "pronostico": pron,
    }


def datos_dia(dia: date) -> dict:
    """Subestaciones con demanda y costo marginal por hora, más los totales del sistema."""
    with conexion() as con:
        filas = con.execute(
            """
            select id_subestacion, subestacion, comuna, region, lat, lon, hora,
                   demanda_mwh, mwh_regulado, cmg_usd_mwh
            from modelo.mart_subestacion_horaria
            where dia = ?
            order by id_subestacion, hora
            """,
            [dia],
        ).fetchall()
        if not filas:
            raise SinDatos(f"No hay datos para {dia}.")
        barras = defaultdict(list)
        for id_sub, barra in con.execute(
            """
            select distinct b.id_subestacion, b.barra
            from modelo.dim_barra b
            where b.tiene_coordenadas and b.barra in (
                select barra from modelo.fct_demanda_horaria where dia = ?
                union select barra from modelo.fct_cmg_horario where dia = ?)
            """,
            [dia, dia],
        ).fetchall():
            barras[id_sub].append(barra)
        sistema = con.execute(
            """
            select hora, demanda_mwh, demanda_ubicada_mwh, cmg_ponderado_usd_mwh
            from modelo.fct_sistema_horario where dia = ? order by hora
            """,
            [dia],
        ).fetchall()
        barras_dia = con.execute(
            """
            select count(distinct d.barra), count(distinct d.barra) filter (where b.tiene_coordenadas)
            from modelo.fct_demanda_horaria d join modelo.dim_barra b using (barra)
            where d.dia = ?
            """,
            [dia],
        ).fetchone()

    nodos: dict[int, dict] = {}
    for id_sub, nombre, comuna, region, lat, lon, hora, dem, reg, cmg in filas:
        n = nodos.setdefault(
            id_sub,
            {
                "id": int(id_sub), "n": _nombre(nombre), "c": comuna, "r": region,
                "la": round(lat, 4), "lo": round(lon, 4), "b": sorted(barras.get(id_sub, [])),
                "d": [None] * 24, "p": [None] * 24, "_reg": 0.0, "_tot": 0.0,
            },
        )
        n["d"][hora] = _r(dem, 2)
        n["p"][hora] = _r(cmg, 1)
        if dem and dem > 0:
            n["_tot"] += dem
            n["_reg"] += reg or 0
    salida = []
    for n in nodos.values():
        n["reg"] = round(n["_reg"] / n["_tot"], 3) if n["_tot"] > 0 else None
        del n["_reg"], n["_tot"]
        if all(v is None for v in n["d"]):
            n["d"] = None
        if all(v is None for v in n["p"]):
            n["p"] = None
        salida.append(n)

    d, du, p = [None] * 24, [None] * 24, [None] * 24
    for hora, dem, dem_ub, cmg in sistema:
        d[hora], du[hora], p[hora] = _r(dem, 1), _r(dem_ub, 1), _r(cmg, 1)
    total = sum(v for v in d if v)
    ubicada = sum(v for v in du if v)
    return {
        "dia": dia.isoformat(),
        "nodos": salida,
        "sistema": {"d": d, "p": p},
        "cobertura": {
            "energia": round(ubicada / total, 3) if total else None,
            "barras_ubicadas": barras_dia[1],
            "barras_total": barras_dia[0],
        },
    }


def datos_pronostico(dia: date) -> dict:
    with conexion() as con:
        filas = con.execute(
            """
            select s.id_subestacion, s.nombre, s.comuna, s.region, s.lat, s.lon, f.hora,
                   sum(f.energia_mwh), list(distinct f.barra_pronostico)
            from modelo.fct_pronostico_horario f
            join modelo.dim_subestacion s using (id_subestacion)
            where f.dia = ? and s.tiene_coordenadas
            group by all
            order by 1, 7
            """,
            [dia],
        ).fetchall()
        total = con.execute(
            "select hora, sum(energia_mwh) from modelo.fct_pronostico_horario where dia = ? group by 1 order by 1",
            [dia],
        ).fetchall()
    if not filas:
        raise SinDatos(f"No hay pronóstico para {dia}.")
    nodos: dict[int, dict] = {}
    for id_sub, nombre, comuna, region, lat, lon, hora, mwh, bs in filas:
        n = nodos.setdefault(
            id_sub,
            {"id": int(id_sub), "n": _nombre(nombre), "c": comuna, "r": region,
             "la": round(lat, 4), "lo": round(lon, 4), "b": set(), "f": [None] * 24},
        )
        n["f"][hora] = _r(mwh, 2)
        n["b"].update(bs)
    for n in nodos.values():
        n["b"] = sorted(n["b"])
    f = [None] * 24
    for hora, mwh in total:
        f[hora] = _r(mwh, 1)
    return {"dia": dia.isoformat(), "nodos": list(nodos.values()), "sistema": {"f": f}}


def ultimo_dia(lista: list) -> date | None:
    return date.fromisoformat(lista[-1]) if lista else None
