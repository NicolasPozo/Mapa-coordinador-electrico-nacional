"""Cliente de la API SIP del CEN con control de velocidad, reintentos y caché por día.

Comportamiento observado de la API (nov-2026):
- La clave va como parámetro `user_key` en la URL.
- Acepta páginas de hasta 10 000 filas; con 20 000 responde 502.
- Si se consulta muy seguido responde 429 "Too Many Requests" (no publica el límite).
- La numeración de páginas empieza en 0 o en 1 según el endpoint (se detecta sola).
"""

from __future__ import annotations

import time
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import requests

from . import config
from .endpoints import Endpoint

BASE_URL = "https://sipub.api.coordinador.cl"
LIMITE_POR_PAGINA = 10_000
LIMITE_MINIMO = 500
REINTENTOS = 6


class ErrorSIP(RuntimeError):
    pass


class ClienteSIP:
    def __init__(self, intervalo_min: float | None = None, timeout: float = 180):
        self._clave = config.user_key()
        self.intervalo_min = float(
            intervalo_min
            if intervalo_min is not None
            else config.obtener("CEN_SIP_MIN_INTERVAL", "2.0")
        )
        self.timeout = timeout
        self._sesion = requests.Session()
        self._sesion.headers["Accept"] = "application/json"
        self._ultima = 0.0
        self._bases: dict[str, int] = {}
        self.peticiones = 0
        # Opcional: función (dia, pagina, total) que se llama tras cada página (avance en la web).
        self.al_avanzar = None

    # -- utilidades ---------------------------------------------------------

    def _ocultar(self, texto: str) -> str:
        """Nunca dejar la clave en mensajes de error ni en logs."""
        return texto.replace(self._clave, "***")

    def _esperar_turno(self) -> None:
        espera = self._ultima + self.intervalo_min - time.monotonic()
        if espera > 0:
            time.sleep(espera)
        self._ultima = time.monotonic()

    # -- peticiones ---------------------------------------------------------

    def _get(self, ruta: str, params: dict) -> dict:
        """GET con reintentos. Devuelve el JSON o lanza ErrorSIP.

        Lanza _PaginaGrande en 502/504 para que el llamador reduzca el tamaño de página.
        """
        params = {**params, "user_key": self._clave}
        url = f"{BASE_URL}/{ruta}"
        for intento in range(REINTENTOS):
            self._esperar_turno()
            self.peticiones += 1
            try:
                r = self._sesion.get(url, params=params, timeout=self.timeout)
            except requests.RequestException as exc:
                motivo = self._ocultar(f"{type(exc).__name__}: {exc}")
                pausa = min(15 * 2**intento, 300)
                print(f"    ! error de red ({motivo[:120]}); reintento en {pausa}s")
                time.sleep(pausa)
                continue

            if r.status_code == 200:
                try:
                    return r.json()
                except ValueError as exc:
                    raise ErrorSIP(f"Respuesta no es JSON en {ruta}") from exc
            if r.status_code == 429:
                pausa = min(30 * 2**intento, 600)
                print(f"    ! 429 demasiadas peticiones; espero {pausa}s")
                time.sleep(pausa)
                continue
            if r.status_code in (502, 504):
                raise _PaginaGrande()
            if r.status_code in (500, 503):
                pausa = min(15 * 2**intento, 300)
                print(f"    ! {r.status_code} del servidor; reintento en {pausa}s")
                time.sleep(pausa)
                continue
            if r.status_code in (401, 403):
                raise ErrorClave(
                    f"{r.status_code}: la clave no tiene acceso a {ruta}. "
                    "Revisa que tu cuenta esté suscrita al plan SIP."
                )
            raise ErrorSIP(f"{r.status_code} en {ruta}: {self._ocultar(r.text[:200])}")
        raise ErrorSIP(f"Se agotaron los reintentos en {ruta}")

    def _base_paginacion(self, endpoint: Endpoint, dia: date) -> int | None:
        """Detecta si el endpoint numera las páginas desde 0 o desde 1.

        La API no es coherente: costo-marginal-real y demanda-real-estimada empiezan
        en 0, mientras que pronósticos y demanda-neta empiezan en 1 (y tratan page=0
        como page=1). Se compara page=0 con page=1 usando páginas de 2 filas.
        Devuelve None si ese día no tiene datos (no se puede decidir).
        """
        if endpoint.ruta in self._bases:
            return self._bases[endpoint.ruta]
        params = {"startDate": dia.isoformat(), "endDate": dia.isoformat(), "limit": 2}
        p0 = self._get(endpoint.ruta, {**params, "page": 0}).get("data") or []
        if not p0:
            return None
        p1 = self._get(endpoint.ruta, {**params, "page": 1}).get("data") or []
        base = 1 if p0 == p1 else 0
        self._bases[endpoint.ruta] = base
        print(f"    (paginación de {endpoint.alias}: empieza en {base})")
        return base

    def descargar_dia(self, endpoint: Endpoint, dia: date) -> pd.DataFrame:
        """Todas las filas de un día (startDate = endDate = dia), paginando."""
        base = self._base_paginacion(endpoint, dia)
        if base is None:
            return pd.DataFrame()
        filas: list[dict] = []
        limite = LIMITE_POR_PAGINA
        pagina = base
        total_paginas = None
        fallos = 0  # 502/504 seguidos con el tamaño actual
        while total_paginas is None or pagina < base + total_paginas:
            params = {
                "startDate": dia.isoformat(),
                "endDate": dia.isoformat(),
                "page": pagina,
                "limit": limite,
            }
            try:
                datos = self._get(endpoint.ruta, params)
            except _PaginaGrande:
                # Un 502/504 puede ser una caída breve del CEN y no la página: primero se
                # espera y se reintenta igual; si sigue fallando, se achica la página.
                fallos += 1
                if fallos <= 2:
                    pausa = 20 * fallos
                    print(f"    ! {endpoint.alias} respondió 502/504; reintento en {pausa}s")
                    time.sleep(pausa)
                    continue
                fallos = 0
                if limite // 2 < LIMITE_MINIMO:
                    raise ErrorSIP(f"El servidor falla incluso con páginas de {limite} filas")
                # Las páginas anteriores venían llenas, así que las filas ya bajadas
                # son múltiplo del nuevo tamaño y se puede seguir desde ahí.
                limite //= 2
                pagina = base + len(filas) // limite
                total_paginas = None
                print(f"    ! 502 con página grande; bajo a {limite} filas por página")
                continue
            fallos = 0
            lote = datos.get("data") or []
            total_paginas = int(datos.get("totalPages") or 0)
            indice = pagina - base + 1
            ultima = indice >= total_paginas
            if not ultima and len(lote) < limite:
                print(f"    ! la página {indice}/{total_paginas} trajo {len(lote)} filas en vez de {limite}")
            filas.extend(lote)
            if total_paginas > 1:
                print(f"    página {indice}/{total_paginas}")
            if self.al_avanzar:
                self.al_avanzar(dia, indice, total_paginas)
            pagina += 1
        return pd.DataFrame.from_records(filas)


class _PaginaGrande(Exception):
    pass


class ErrorClave(ErrorSIP):
    """401/403: la clave no sirve; no tiene sentido seguir con otros endpoints."""


# -- caché en disco -----------------------------------------------------------


def ruta_cache(endpoint: Endpoint, dia: date) -> Path:
    return config.DATA_RAW / endpoint.alias / f"{dia.isoformat()}.parquet"


def _guardar(df: pd.DataFrame, destino: Path) -> None:
    destino.parent.mkdir(parents=True, exist_ok=True)
    tmp = destino.with_suffix(".tmp")
    try:
        df.to_parquet(tmp, index=False)
    except (TypeError, ValueError, ImportError) as exc:
        if isinstance(exc, ImportError):
            raise
        # Columnas con tipos mezclados (p. ej. número y texto): se guardan como texto.
        df = df.copy()
        for col in df.columns[df.dtypes == object]:
            df[col] = df[col].map(lambda v: None if v is None else str(v))
        df.to_parquet(tmp, index=False)
    tmp.replace(destino)


def dias(desde: date, hasta: date):
    d = desde
    while d <= hasta:
        yield d
        d += timedelta(days=1)


def descargar_rango(
    cliente: ClienteSIP,
    endpoint: Endpoint,
    desde: date,
    hasta: date,
    refrescar: bool = False,
) -> dict[str, int]:
    """Descarga día a día. Los días ya guardados se saltan (salvo refrescar).

    Los días sin datos no se guardan, para volver a intentarlos más adelante
    (la API publica con desfase). Un día guardado antes de cumplirse su margen
    (endpoint.margen_dias) es provisional y se vuelve a pedir.
    """
    resumen = {"descargados": 0, "en_cache": 0, "vacios": 0, "filas": 0, "provisionales": 0}
    for dia in dias(desde, hasta):
        destino = ruta_cache(endpoint, dia)
        if destino.exists() and not refrescar:
            if es_definitivo(endpoint, dia, destino) or _reciente(endpoint, destino):
                resumen["en_cache"] += 1
                continue
            print(f"  {endpoint.alias} {dia} (provisional, se actualiza) ...")
        else:
            print(f"  {endpoint.alias} {dia} ...")
        df = cliente.descargar_dia(endpoint, dia)
        if df.empty:
            print("    sin datos (aún no publicado o no existe)")
            resumen["vacios"] += 1
            continue
        df.insert(0, "_dia_consulta", dia.isoformat())
        _guardar(df, destino)
        resumen["descargados"] += 1
        resumen["filas"] += len(df)
        marca = "" if es_definitivo(endpoint, dia, destino) else "  (provisional)"
        if marca:
            resumen["provisionales"] += 1
        print(f"    {len(df):,} filas -> {destino.relative_to(config.RAIZ)}{marca}")
    return resumen


def es_definitivo(endpoint: Endpoint, dia: date, archivo: Path) -> bool:
    """El archivo es definitivo si se descargó cuando ya había pasado el margen del día."""
    descargado = date.fromtimestamp(archivo.stat().st_mtime)
    return descargado > dia + timedelta(days=endpoint.margen_dias)


def _reciente(endpoint: Endpoint, archivo: Path) -> bool:
    """Un provisional bajado hace menos de endpoint.refresco_horas todavía no se vuelve a pedir."""
    if endpoint.refresco_horas <= 0:
        return False
    return time.time() - archivo.stat().st_mtime < endpoint.refresco_horas * 3600


def leer_cache(endpoint: Endpoint, desde: date | None = None, hasta: date | None = None) -> pd.DataFrame:
    carpeta = config.DATA_RAW / endpoint.alias
    archivos = sorted(carpeta.glob("*.parquet")) if carpeta.exists() else []
    if desde or hasta:
        archivos = [
            a
            for a in archivos
            if (not desde or a.stem >= desde.isoformat()) and (not hasta or a.stem <= hasta.isoformat())
        ]
    if not archivos:
        return pd.DataFrame()
    return pd.concat((pd.read_parquet(a) for a in archivos), ignore_index=True)
