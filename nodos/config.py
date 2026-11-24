"""Rutas del proyecto y lectura de la clave desde .env (sin dependencias extra)."""

from __future__ import annotations

import os
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
DATA_RAW = RAIZ / "data" / "raw"
DATA_PROCESSED = RAIZ / "data" / "processed"
ENV_FILE = RAIZ / ".env"


def _leer_env(path: Path) -> dict[str, str]:
    valores: dict[str, str] = {}
    if not path.exists():
        return valores
    for linea in path.read_text(encoding="utf-8-sig").splitlines():
        linea = linea.strip()
        if not linea or linea.startswith("#") or "=" not in linea:
            continue
        clave, valor = linea.split("=", 1)
        valores[clave.strip()] = valor.strip().strip('"').strip("'")
    return valores


def obtener(nombre: str, por_defecto: str | None = None) -> str | None:
    """Variable de entorno del sistema; si no existe, la del archivo .env.

    Se limpian espacios y comillas: `docker run --env-file` con un .env guardado en Windows
    (CRLF) deja un "\\r" pegado al valor, y la API respondería 403 con esa clave.
    """
    valor = (os.environ.get(nombre) or "").strip().strip('"').strip("'")
    if valor:
        return valor
    return _leer_env(ENV_FILE).get(nombre) or por_defecto


def user_key() -> str:
    clave = obtener("CEN_SIP_USER_KEY")
    if not clave:
        raise SystemExit(
            "Falta CEN_SIP_USER_KEY. Pega tu user_key del portal "
            "https://portal.api.coordinador.cl en el archivo .env"
        )
    return clave
