"""Ejecuta dbt sobre transform/ (local: entorno .venv-dbt; Docker: dbt del mismo entorno)."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

from . import config

PROYECTO = config.RAIZ / "transform"


def ejecutable() -> Path:
    candidatos = [
        config.RAIZ / ".venv-dbt" / "Scripts" / "dbt.exe",
        config.RAIZ / ".venv-dbt" / "bin" / "dbt",
        Path(sys.executable).parent / ("dbt.exe" if os.name == "nt" else "dbt"),
    ]
    for c in candidatos:
        if c.exists():
            return c
    en_path = shutil.which("dbt")
    if en_path:
        return Path(en_path)
    raise SystemExit(
        "No encuentro dbt. Crea su entorno:\n"
        "  python -m venv .venv-dbt\n"
        "  .venv-dbt\\Scripts\\python -m pip install -r requirements-dbt.txt"
    )


def ejecutar(argumentos: list[str], duckdb: Path | None = None, capturar: bool = False) -> subprocess.CompletedProcess:
    """Corre `dbt <argumentos>`. `duckdb` permite construir en otra base (p. ej. una temporal)."""
    entorno = {
        **os.environ,
        "NODOS_RAIZ": config.RAIZ.as_posix(),
        "DBT_SEND_ANONYMOUS_USAGE_STATS": "False",
    }
    if duckdb is not None:
        entorno["NODOS_DUCKDB"] = Path(duckdb).as_posix()
    comando = [str(ejecutable()), *argumentos, "--project-dir", str(PROYECTO), "--profiles-dir", str(PROYECTO)]
    return subprocess.run(comando, env=entorno, cwd=PROYECTO, text=True, capture_output=capturar)


def resumen_resultados() -> dict:
    """Cuenta resultados del último dbt build (target/run_results.json)."""
    archivo = PROYECTO / "target" / "run_results.json"
    if not archivo.exists():
        return {}
    datos = json.loads(archivo.read_text(encoding="utf-8"))
    conteo: dict[str, int] = {}
    problemas = []
    for r in datos.get("results", []):
        estado = r.get("status")
        conteo[estado] = conteo.get(estado, 0) + 1
        if estado in ("warn", "fail", "error"):
            problemas.append({"nodo": r.get("unique_id", "").split(".")[-1], "estado": estado, "filas": r.get("failures")})
    return {"conteo": conteo, "problemas": problemas}
