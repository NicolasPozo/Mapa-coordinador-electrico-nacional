"""Coordenadas de barras y subestaciones desde Infotécnica (CEN).

API pública (sin clave) que usa https://infotecnica.coordinador.cl:
- /v1/barras/          -> 3800 barras, cada una con su id_subestacion
- /v1/subestaciones/   -> 1276 subestaciones
- /v1/subestaciones/<id>/fichas-tecnicas/general/ -> Coordenada Este/Norte (UTM), Huso, Región, Comuna

Cruce con el SIP: el `id_info` de costo-marginal-real y el `id_barra_info` de los
pronósticos son el id de barra de Infotécnica. El código de barra del SIP
(p. ej. LASARANAS_____110) es el mismo en costo marginal y en demanda real.
"""

from __future__ import annotations

import json
import re
import time

import pandas as pd
import requests

from . import config

BASE_URL = "https://api-infotecnica.coordinador.cl/v1"
REF = config.RAIZ / "data" / "ref"
FICHAS = REF / "fichas_subestaciones"
USER_AGENT = "nodos/0.1 (proyecto de datos abiertos CEN)"

# Límites aproximados de Chile continental + margen (para descartar coordenadas erróneas).
LAT_MIN, LAT_MAX = -56.5, -17.0
LON_MIN, LON_MAX = -76.5, -66.0


class ClienteInfotecnica:
    def __init__(self, intervalo_min: float = 0.5, timeout: float = 60):
        self.intervalo_min = intervalo_min
        self.timeout = timeout
        self._sesion = requests.Session()
        self._sesion.headers.update({"Accept": "application/json", "User-Agent": USER_AGENT})
        self._ultima = 0.0
        self.peticiones = 0

    def _get(self, url: str, params: dict | None = None):
        for intento in range(6):
            espera = self._ultima + self.intervalo_min - time.monotonic()
            if espera > 0:
                time.sleep(espera)
            self._ultima = time.monotonic()
            self.peticiones += 1
            try:
                r = self._sesion.get(url, params=params, timeout=self.timeout)
            except requests.RequestException as exc:
                pausa = min(10 * 2**intento, 300)
                print(f"    ! error de red ({type(exc).__name__}); reintento en {pausa}s")
                time.sleep(pausa)
                continue
            if r.status_code == 200:
                return r.json()
            if r.status_code == 404:
                return None
            if r.status_code in (429, 500, 502, 503, 504):
                pausa = min(15 * 2**intento, 600)
                print(f"    ! {r.status_code} en Infotécnica; reintento en {pausa}s")
                time.sleep(pausa)
                continue
            raise RuntimeError(f"Infotécnica respondió {r.status_code} en {url}")
        raise RuntimeError(f"Se agotaron los reintentos en {url}")

    def listar(self, recurso: str) -> list[dict]:
        """Recorre todas las páginas de un recurso (máximo 1000 por página)."""
        url = f"{BASE_URL}/{recurso}/"
        params = {"page": 1, "page_size": 1000, "ordering": "id"}
        filas: list[dict] = []
        while url:
            datos = self._get(url, params)
            filas.extend(datos.get("results") or [])
            url, params = datos.get("next"), None
        return filas

    def ficha_general(self, id_subestacion: int, refrescar: bool = False) -> dict | None:
        destino = FICHAS / f"{id_subestacion}.json"
        if destino.exists() and not refrescar:
            return json.loads(destino.read_text(encoding="utf-8"))
        datos = self._get(f"{BASE_URL}/subestaciones/{id_subestacion}/fichas-tecnicas/general/")
        if datos is None:
            return None
        destino.parent.mkdir(parents=True, exist_ok=True)
        destino.write_text(json.dumps(datos, ensure_ascii=False), encoding="utf-8")
        return datos


# -- catálogo -----------------------------------------------------------------


def actualizar_catalogo(cliente: ClienteInfotecnica, refrescar: bool = False) -> tuple[pd.DataFrame, pd.DataFrame]:
    REF.mkdir(parents=True, exist_ok=True)
    tablas = []
    for recurso in ("barras", "subestaciones"):
        destino = REF / f"infotecnica_{recurso}.parquet"
        if destino.exists() and not refrescar:
            tablas.append(pd.read_parquet(destino))
            continue
        print(f"  Infotécnica: descargando {recurso} ...")
        df = pd.DataFrame.from_records(cliente.listar(recurso))
        df.to_parquet(destino, index=False)
        print(f"    {len(df):,} {recurso}")
        tablas.append(df)
    return tablas[0], tablas[1]


# -- coordenadas ----------------------------------------------------------------


def _numero(texto) -> float | None:
    if texto is None:
        return None
    t = str(texto).strip().replace(" ", "")
    if not t:
        return None
    if "," in t and "." in t:  # 6.292.393,01 -> 6292393.01
        t = t.replace(".", "").replace(",", ".")
    else:
        t = t.replace(",", ".")
    try:
        return float(t)
    except ValueError:
        return None


def _zona(huso) -> int | None:
    m = re.search(r"(\d{1,2})", str(huso or ""))
    return int(m.group(1)) if m else None


def _campos_ficha(ficha: dict) -> dict:
    """Extrae región, provincia, comuna, este, norte y huso de la ficha general."""
    salida: dict = {}
    for v in ficha.values():
        if not isinstance(v, dict):
            continue
        concepto = (v.get("nombre_concepto") or "").lower()
        valor = v.get("valor_texto")
        if valor in (None, "") and v.get("valor_numerico") not in (None, 0.0):
            valor = v.get("valor_numerico")
        if concepto.startswith("coordenada este"):
            salida["este"] = _numero(valor)
        elif concepto.startswith("coordenada norte"):
            salida["norte"] = _numero(valor)
        elif "huso" in concepto:
            salida["huso"] = valor
        elif concepto == "región":
            salida["region"] = valor
        elif concepto == "provincia":
            salida["provincia"] = valor
        elif concepto == "comuna":
            salida["comuna"] = valor
    return salida


_transformadores: dict = {}


def _en_chile(lat: float, lon: float) -> bool:
    return LAT_MIN <= lat <= LAT_MAX and LON_MIN <= lon <= LON_MAX


def a_latlon(este: float | None, norte: float | None, huso) -> tuple[float | None, float | None, str]:
    """UTM (WGS84/SIRGAS, hemisferio sur) -> (lat, lon, estado)."""
    from pyproj import Transformer

    if este is None or norte is None:
        return None, None, "sin_coordenadas"
    # Algunas fichas traen grados decimales en vez de UTM.
    if abs(este) <= 180 and abs(norte) <= 90:
        for lat, lon in ((norte, este), (este, norte)):
            if _en_chile(lat, lon):
                return lat, lon, "grados"
        return None, None, "fuera_de_chile"
    zonas = [z for z in (_zona(huso), 19, 18) if z]
    for zona in dict.fromkeys(zonas):  # primero la declarada, luego 19 y 18
        if zona not in _transformadores:
            _transformadores[zona] = Transformer.from_crs(f"EPSG:{32700 + zona}", "EPSG:4326", always_xy=True)
        for x, y in ((este, norte), (norte, este)):
            lon, lat = _transformadores[zona].transform(x, y)
            if _en_chile(lat, lon):
                estado = "ok" if zona == _zona(huso) and x == este else "corregido"
                return lat, lon, estado
    return None, None, "fuera_de_chile"


def coordenadas(cliente: ClienteInfotecnica, ids_subestacion, refrescar: bool = False) -> pd.DataFrame:
    ids = sorted({int(i) for i in ids_subestacion if pd.notna(i)})
    pendientes = [i for i in ids if refrescar or not (FICHAS / f"{i}.json").exists()]
    if pendientes:
        print(f"  Infotécnica: {len(pendientes)} fichas de subestación por descargar (~{len(pendientes) * cliente.intervalo_min / 60:.0f} min)")
    filas = []
    for n, i in enumerate(ids, 1):
        ficha = cliente.ficha_general(i, refrescar=refrescar)
        if pendientes and n % 100 == 0:
            print(f"    {n}/{len(ids)}")
        campos = _campos_ficha(ficha or {})
        lat, lon, estado = a_latlon(campos.get("este"), campos.get("norte"), campos.get("huso"))
        filas.append({"id_subestacion": i, **campos, "lat": lat, "lon": lon, "coord_estado": estado})
    return pd.DataFrame(filas)


# -- tabla de nodos -----------------------------------------------------------------


def _tension_kv(nombre) -> float | None:
    m = re.search(r"(\d+(?:[.,]\d+)?)\s*KV", str(nombre or ""), re.I)
    return float(m.group(1).replace(",", ".")) if m else None


def _normalizar(texto) -> str:
    """'S/E Las Arañas (CGE)' -> 'LASARANASCGE'."""
    import unicodedata

    t = unicodedata.normalize("NFKD", str(texto or "")).encode("ascii", "ignore").decode().upper()
    t = re.sub(r"^\s*S/?E\s+", "", t)
    return re.sub(r"[^A-Z0-9]", "", t)


def _patron_codigo(codigo: str) -> tuple[re.Pattern, int | None, bool] | None:
    """Código SIP 'A.JAHUEL______110' -> (regex que acepta 'ALTOJAHUEL...', 110, truncado).

    El código son 14 caracteres de nombre + 3 de tensión. Los tokens de una letra
    (o terminados en punto) son abreviaturas: 'A.' -> 'A[A-Z]{0,8}' (ALTO), 'L.' -> LOS/LAS.
    """
    codigo = str(codigo or "")
    if len(codigo) < 6:
        return None
    nombre, kv = codigo[:-3], codigo[-3:]
    tension = int(kv) if kv.isdigit() else None
    truncado = not nombre.endswith("_")
    tokens = [t for t in re.split(r"([._])", nombre.strip("_")) if t]
    partes = []
    for i, tok in enumerate(tokens):
        if tok in "._":
            continue
        siguiente = tokens[i + 1] if i + 1 < len(tokens) else ""
        tok = re.sub(r"[^A-Z0-9]", "", tok.upper())
        if not tok:
            continue
        abreviado = siguiente == "." or len(tok) == 1
        # Abreviatura de una sola palabra: 'P.' -> PUERTO, 'L.' -> LIRQUEN (máx. 8 letras más).
        partes.append(re.escape(tok) + ("[A-Z]{0,8}" if abreviado else ""))
    if not partes or sum(len(p) for p in partes) < 4:
        return None
    return re.compile("^" + "".join(partes)), tension, truncado


def emparejar_por_nombre(codigos, barras_inf: pd.DataFrame) -> pd.DataFrame:
    """Cruce de respaldo: código SIP -> subestación de Infotécnica por nombre.

    Solo acepta resultados sin ambigüedad. Orden de preferencia:
    nombre idéntico > subestación con una barra de la misma tensión > nombre más corto.
    """
    sin_parentesis = lambda n: _normalizar(re.sub(r"\(.*?\)", "", str(n or "")))  # noqa: E731
    subs = (
        barras_inf.assign(
            clave=lambda d: d["subestacion"].map(_normalizar),
            kv=lambda d: d["barra_infotecnica"].map(_tension_kv),
        )
        .groupby(["id_subestacion", "subestacion", "clave"], as_index=False)
        .agg(kvs=("kv", lambda s: {int(round(v)) for v in s.dropna()}))
    )
    # Variantes del nombre que cuentan como coincidencia exacta:
    # sin el texto entre paréntesis ('S/E TALTAL (ELECDA)') y sin 'CENTRAL' inicial.
    subs["claves_exactas"] = subs["subestacion"].map(
        lambda n: {_normalizar(n), sin_parentesis(n), re.sub(r"^CENTRAL", "", sin_parentesis(n))}
    )
    filas = []
    for codigo in sorted(set(codigos)):
        patron = _patron_codigo(codigo)
        if not patron:
            continue
        regex, tension, truncado = patron
        exactos = subs[subs["claves_exactas"].map(lambda cs: any(regex.fullmatch(c) for c in cs))]
        if not exactos.empty:
            cand = exactos
        elif truncado:
            # El código cortó el nombre a 14 caracteres: basta con que coincida el inicio.
            cand = subs[subs["claves_exactas"].map(lambda cs: any(regex.match(c) for c in cs))]
        else:
            continue
        if cand.empty:
            continue
        if tension is not None and len(cand) > 1:
            con_kv = cand[cand["kvs"].map(lambda k: tension in k or round(tension) in k)]
            if not con_kv.empty:
                cand = con_kv
        if len(cand) > 1:
            minimo = cand["clave"].str.len().min()
            cand = cand[cand["clave"].str.len() == minimo]
        if len(cand) == 1:
            r = cand.iloc[0]
            filas.append({"barra": codigo, "id_subestacion": int(r["id_subestacion"]), "subestacion": r["subestacion"]})
    return pd.DataFrame(filas, columns=["barra", "id_subestacion", "subestacion"])


def construir_nodos(refrescar: bool = False) -> pd.DataFrame:
    """Une las barras del SIP con Infotécnica y sus coordenadas.

    Escribe data/processed/nodos.parquet (una fila por código de barra del SIP)
    y data/processed/nodos_pronostico.parquet (barras del pronóstico).
    """
    from .endpoints import ENDPOINTS
    from .sip import leer_cache

    cmg = leer_cache(ENDPOINTS["cmg-real"])
    if cmg.empty:
        raise SystemExit("Necesito al menos un día de cmg-real en caché: python -m nodos descargar cmg-real --dias 1 --hasta <fecha>")
    pron = leer_cache(ENDPOINTS["pronostico"])
    dem = leer_cache(ENDPOINTS["demanda-real"])

    cliente = ClienteInfotecnica()
    barras_inf, subest = actualizar_catalogo(cliente, refrescar)
    barras_inf = barras_inf.rename(
        columns={"id": "id_barra_info", "nombre": "barra_infotecnica", "subestacion_nombre": "subestacion"}
    )[["id_barra_info", "barra_infotecnica", "id_subestacion", "subestacion"]]

    # Código SIP -> id de barra Infotécnica (desde costo marginal). Se conservan
    # también los códigos sin id_info y los de demanda real que no estén en cmg.
    # Si un código cambió de id con el tiempo, se usa el del día más reciente.
    pares = (
        cmg[["barra_transf", "id_info", "_dia_consulta"]]
        .rename(columns={"barra_transf": "barra", "id_info": "id_barra_info"})
        .assign(id_barra_info=lambda d: pd.to_numeric(d["id_barra_info"], errors="coerce"))
        .sort_values("_dia_consulta", ascending=False)
        .drop_duplicates(["barra", "id_barra_info"])
        .drop(columns="_dia_consulta")
    )
    con_id = pares.dropna(subset=["id_barra_info"])
    conflictos = con_id["barra"].duplicated().sum()
    if conflictos:
        print(f"  {conflictos} códigos SIP cambiaron de id en Infotécnica; se usa el más reciente")
    codigos = set(pares["barra"]) | (set(dem["barra"]) if not dem.empty else set())
    mapa = pd.DataFrame({"barra": sorted(codigos)}).merge(
        con_id.drop_duplicates("barra"), on="barra", how="left"
    )
    mapa["id_barra_info"] = mapa["id_barra_info"].astype("Int64")

    # 1) Cruce exacto por id de barra.
    nodos = mapa.merge(
        barras_inf.astype({"id_barra_info": "Int64"}), on="id_barra_info", how="left"
    )
    nodos["metodo_cruce"] = nodos["barra_infotecnica"].notna().map({True: "id", False: None})

    # 2) Respaldo por nombre para los que no cruzaron por id.
    sin = nodos["id_subestacion"].isna()
    por_nombre = emparejar_por_nombre(nodos.loc[sin, "barra"], barras_inf).set_index("barra")
    idx = nodos.index[sin & nodos["barra"].isin(por_nombre.index)]
    nodos.loc[idx, "id_subestacion"] = nodos.loc[idx, "barra"].map(por_nombre["id_subestacion"])
    nodos.loc[idx, "subestacion"] = nodos.loc[idx, "barra"].map(por_nombre["subestacion"])
    nodos.loc[idx, "metodo_cruce"] = "nombre"
    print(f"  cruce por id: {(nodos['metodo_cruce'] == 'id').sum()}, por nombre: {len(idx)}, sin cruce: {nodos['metodo_cruce'].isna().sum()}")

    ids_pron = pd.to_numeric(pron.get("id_barra_info"), errors="coerce").dropna().astype(int) if not pron.empty else pd.Series(dtype=int)
    subest_necesarias = set(nodos["id_subestacion"].dropna().astype(int)) | set(
        barras_inf.loc[barras_inf["id_barra_info"].isin(set(ids_pron)), "id_subestacion"]
    )
    coords = coordenadas(cliente, subest_necesarias, refrescar)

    nodos = nodos.merge(coords, on="id_subestacion", how="left")
    nodos["tension_kv"] = nodos["barra_infotecnica"].map(_tension_kv)
    kv_codigo = pd.to_numeric(nodos["barra"].str[-3:], errors="coerce")
    nodos["tension_kv"] = nodos["tension_kv"].fillna(kv_codigo)
    nodos["en_demanda_real"] = nodos["barra"].isin(set(dem["barra"])) if not dem.empty else False
    nodos["en_pronostico"] = nodos["id_barra_info"].isin(set(ids_pron))

    base = barras_inf.merge(coords, on="id_subestacion", how="left")
    base["tension_kv"] = base["barra_infotecnica"].map(_tension_kv)

    nodos = _aplicar_manuales(nodos)
    _listar_pendientes(nodos, dem)

    config.DATA_PROCESSED.mkdir(parents=True, exist_ok=True)
    nodos.to_parquet(config.DATA_PROCESSED / "nodos.parquet", index=False)

    # Barras del pronóstico (usan otro formato de nombre, p. ej. LoEspejo110).
    if not pron.empty:
        np_ = (
            pron[["barra", "id_barra_info"]]
            .drop_duplicates("barra")
            .assign(id_barra_info=lambda d: pd.to_numeric(d["id_barra_info"], errors="coerce").astype("Int64"))
            .merge(base, on="id_barra_info", how="left")
        )
        np_.to_parquet(config.DATA_PROCESSED / "nodos_pronostico.parquet", index=False)
    else:
        np_ = pd.DataFrame()

    _reporte(nodos, np_, dem, cliente)
    return nodos


MANUALES = config.RAIZ / "ubicaciones_manuales.csv"
PENDIENTES = config.RAIZ / "data" / "ref" / "barras_sin_ubicar.csv"


def _aplicar_manuales(nodos: pd.DataFrame) -> pd.DataFrame:
    """Aplica ubicaciones_manuales.csv (barra,lat,lon,fuente) sobre los nodos sin coordenadas."""
    if not MANUALES.exists():
        return nodos
    man = pd.read_csv(MANUALES, comment="#", dtype={"barra": str})
    man = man.dropna(subset=["barra", "lat", "lon"])
    man = man[[_en_chile(float(a), float(o)) for a, o in zip(man["lat"], man["lon"])]]
    if man.empty:
        return nodos
    man = man.drop_duplicates("barra", keep="last").set_index("barra")
    idx = nodos.index[nodos["barra"].isin(man.index)]
    nodos.loc[idx, "lat"] = nodos.loc[idx, "barra"].map(man["lat"]).astype(float)
    nodos.loc[idx, "lon"] = nodos.loc[idx, "barra"].map(man["lon"]).astype(float)
    nodos.loc[idx, "metodo_cruce"] = "manual"
    nodos.loc[idx, "coord_estado"] = "manual"
    print(f"  ubicaciones manuales aplicadas: {len(idx)}")
    return nodos


def _listar_pendientes(nodos: pd.DataFrame, dem: pd.DataFrame) -> None:
    """Escribe las barras sin coordenadas, ordenadas por energía, para completarlas a mano."""
    sin = nodos[nodos["lat"].isna()][["barra", "subestacion", "coord_estado"]].copy()
    if not dem.empty:
        mwh = dem.assign(mwh=-pd.to_numeric(dem["medida_kwh"], errors="coerce") / 1000).groupby("barra")["mwh"].sum()
        sin["mwh_dia_muestra"] = sin["barra"].map(mwh).round(1)
        sin = sin.sort_values("mwh_dia_muestra", ascending=False, na_position="last")
    PENDIENTES.parent.mkdir(parents=True, exist_ok=True)
    sin.to_csv(PENDIENTES, index=False, encoding="utf-8")


def _reporte(nodos: pd.DataFrame, nodos_pron: pd.DataFrame, dem: pd.DataFrame, cliente: ClienteInfotecnica) -> None:
    con = nodos["lat"].notna()
    print(f"\n  Barras SIP: {len(nodos):,}; con coordenadas: {con.sum():,} ({con.mean():.0%})")
    print(f"  Ubicadas por método: {nodos.loc[con, 'metodo_cruce'].value_counts().to_dict()}")
    print(f"  Estado de coordenadas: {nodos['coord_estado'].value_counts(dropna=False).to_dict()}")
    if not dem.empty:
        barras_dem = set(dem["barra"])
        con_geo = set(nodos.loc[con, "barra"])
        mwh = dem.assign(mwh=-pd.to_numeric(dem["medida_kwh"], errors="coerce")).groupby("barra")["mwh"].sum()
        cubierto = mwh[mwh.index.isin(con_geo)].sum() / mwh.sum()
        print(
            f"  Barras con demanda real: {len(barras_dem):,}; ubicadas: {len(barras_dem & con_geo):,} "
            f"({len(barras_dem & con_geo) / len(barras_dem):.0%}); energía cubierta: {cubierto:.1%}"
        )
    if not nodos_pron.empty:
        ok = nodos_pron["lat"].notna()
        print(f"  Barras del pronóstico: {len(nodos_pron)}; ubicadas: {ok.sum()} ({ok.mean():.0%})")
    print(f"  Peticiones a Infotécnica: {cliente.peticiones}")
