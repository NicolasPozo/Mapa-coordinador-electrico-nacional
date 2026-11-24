"""Mapa base «Mínimo» del mapa 3D: contornos de Chile y países vecinos (Natural Earth 1:50m).

Lo sirve GET /api/base; así el mapa puede funcionar sin teselas de terceros.
"""

from __future__ import annotations

import json

import requests

from . import config

BASE_MAPA = config.RAIZ / "data" / "ref" / "base_mapa.geojson"
WORLD_ATLAS = "https://cdn.jsdelivr.net/npm/world-atlas@2.0.2/countries-50m.json"
PAISES = {"152": "CHL", "032": "ARG", "068": "BOL", "604": "PER"}
# Recorte del mapa base (Chile continental y alrededores) para no cargar toda Argentina.
LON_MIN, LON_MAX, LAT_MIN, LAT_MAX = -80.0, -62.0, -57.0, -16.0


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
