"""Mapa base y exportación estática del mapa (una «foto» con los datos incrustados).

La app normal es `python -m nodos servir`: web/index.html pide los datos a la API.
`python -m nodos mapa` usa la misma página y los mismos datos (tablas de dbt), pero
los incrusta en un único HTML para compartirlo sin servidor.
"""

from __future__ import annotations

import json
import re
from datetime import date
from pathlib import Path

import requests

from . import config, servicio
from .actualizar import leer_estado

PAGINA = config.RAIZ / "web" / "index.html"
BASE_MAPA = config.RAIZ / "data" / "ref" / "base_mapa.geojson"
WORLD_ATLAS = "https://cdn.jsdelivr.net/npm/world-atlas@2.0.2/countries-50m.json"
PAISES = {"152": "CHL", "032": "ARG", "068": "BOL", "604": "PER"}
# Recorte del mapa base (Chile continental y alrededores) para no cargar toda Argentina.
LON_MIN, LON_MAX, LAT_MIN, LAT_MAX = -80.0, -62.0, -57.0, -16.0


# -- mapa base ----------------------------------------------------------------


def _decodificar_topojson(topo: dict, ids: dict[str, str]) -> list[dict]:
    """TopoJSON -> features GeoJSON (solo los países pedidos)."""
    escala = topo.get("transform", {}).get("scale", [1, 1])
    traslado = topo.get("transform", {}).get("translate", [0, 0])
    arcos = []
    for arco in topo["arcs"]:
        x = y = 0
        puntos = []
        for dx, dy in arco:
            x += dx
            y += dy
            puntos.append((x * escala[0] + traslado[0], y * escala[1] + traslado[1]))
        arcos.append(puntos)

    def anillo(indices):
        pts: list = []
        for i in indices:
            arco = arcos[i] if i >= 0 else list(reversed(arcos[~i]))
            pts.extend(arco if not pts else arco[1:])
        return pts

    features = []
    for g in topo["objects"]["countries"]["geometries"]:
        if g.get("id") not in ids:
            continue
        poligonos = [g["arcs"]] if g["type"] == "Polygon" else g["arcs"]
        coords = []
        for pol in poligonos:
            anillos = [anillo(r) for r in pol]
            xs = [p[0] for p in anillos[0]]
            ys = [p[1] for p in anillos[0]]
            if max(xs) < LON_MIN or min(xs) > LON_MAX or max(ys) < LAT_MIN or min(ys) > LAT_MAX:
                continue  # fuera del recorte (Isla de Pascua, norte de Perú…)
            coords.append([[[round(x, 3), round(y, 3)] for x, y in a] for a in anillos])
        if coords:
            features.append(
                {
                    "type": "Feature",
                    "properties": {"iso": ids[g["id"]]},
                    "geometry": {"type": "MultiPolygon", "coordinates": coords},
                }
            )
    return features


def base_mapa() -> dict:
    """Contornos de Chile y vecinos (Natural Earth 1:50m vía world-atlas). Se guarda en caché."""
    if BASE_MAPA.exists():
        return json.loads(BASE_MAPA.read_text(encoding="utf-8"))
    print("  descargando mapa base (Natural Earth 1:50m) ...")
    r = requests.get(WORLD_ATLAS, timeout=120, headers={"User-Agent": "nodos/0.1"})
    r.raise_for_status()
    base = {"type": "FeatureCollection", "features": _decodificar_topojson(r.json(), PAISES)}
    BASE_MAPA.parent.mkdir(parents=True, exist_ok=True)
    BASE_MAPA.write_text(json.dumps(base, separators=(",", ":")), encoding="utf-8")
    return base


# -- exportación estática ---------------------------------------------------------


def generar(
    dia: date | None = None,
    dia_pron: date | None = None,
    salida: Path | None = None,
    sin_envoltura: bool = False,
) -> Path:
    """Escribe el mapa con los datos incrustados. Requiere haber corrido `dbt build`.

    sin_envoltura=True quita <!doctype>, <html>, <head> y <body> (formato de Artifact).
    """
    disp = servicio.dias_disponibles()
    if dia is None:
        con_precio = [d["dia"] for d in disp["demanda"] if d["con_precio"]] or [d["dia"] for d in disp["demanda"]]
        dia = servicio.ultimo_dia(con_precio)
        if dia is None:
            raise SystemExit("No hay demanda real en la base. Descarga datos y ejecuta: python -m nodos dbt build")
    dia_pron = dia_pron or servicio.ultimo_dia(disp["pronostico"])
    datos = {
        "dias": disp,
        "mapa": servicio.datos_dia(dia),
        "pron": servicio.datos_pronostico(dia_pron) if dia_pron else None,
        "base": base_mapa(),
        "estado": leer_estado(),
    }
    html = PAGINA.read_text(encoding="utf-8")
    incrustado = json.dumps(datos, ensure_ascii=False, separators=(",", ":"), default=str).replace("</", "<\\/")
    html = html.replace("/*__DATOS__*/null", incrustado)
    if sin_envoltura:
        html = re.sub(
            r"^\s*(<!doctype html>|<html[^>]*>|</html>|<head>|</head>|<body>|</body>|<meta charset=[^>]*>|<meta name=\"viewport\"[^>]*>)\s*\n",
            "",
            html,
            flags=re.I | re.M,
        )
    salida = salida or (config.RAIZ / "salida" / "mapa.html")
    salida.parent.mkdir(parents=True, exist_ok=True)
    salida.write_text(html, encoding="utf-8")
    print(
        f"  mapa: {len(datos['mapa']['nodos'])} subestaciones ({dia}), "
        f"pronóstico {dia_pron} -> {salida} ({salida.stat().st_size / 1e6:.1f} MB)"
    )
    return salida
