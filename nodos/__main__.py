"""Línea de comandos.

    python -m nodos servir                      # app web: mapa + API, se actualiza sola
    python -m nodos actualizar                  # un ciclo: descargar -> geo -> dbt build
    python -m nodos descargar pronostico --desde 2026-11-15 --hasta 2026-11-20
    python -m nodos geo
    python -m nodos dbt build
    python -m nodos mapa                        # exportación estática (HTML con datos incrustados)
    python -m nodos estado
"""

from __future__ import annotations

import argparse
import sys
from datetime import date, timedelta

from . import config
from .agregar import agregar
from .endpoints import ENDPOINTS, resolver
from .sip import ClienteSIP, ErrorSIP, descargar_rango


def _fecha(texto: str) -> date:
    try:
        return date.fromisoformat(texto)
    except ValueError:
        raise argparse.ArgumentTypeError(f"Fecha inválida: {texto} (usa AAAA-MM-DD)")


def _rango(args) -> tuple[date, date]:
    hasta = args.hasta or date.today()
    desde = args.desde or hasta - timedelta(days=args.dias - 1)
    if desde > hasta:
        raise SystemExit("--desde no puede ser posterior a --hasta")
    return desde, hasta


def cmd_endpoints(_args) -> None:
    for e in ENDPOINTS.values():
        print(f"{e.alias:<20} {e.descripcion}  [datos hasta: {e.desfase}]")


def cmd_descargar(args) -> None:
    desde, hasta = _rango(args)
    cliente = ClienteSIP(intervalo_min=args.intervalo)
    for nombre in args.endpoint:
        e = resolver(nombre)
        print(f"{e.alias}: {desde} -> {hasta}")
        r = descargar_rango(cliente, e, desde, hasta, refrescar=args.refrescar or (e.cambia and args.refrescar_pronosticos))
        print(
            f"  listo: {r['descargados']} días nuevos ({r['filas']:,} filas), "
            f"{r['en_cache']} ya en caché, {r['vacios']} sin datos"
            + (f", {r['provisionales']} provisionales (se actualizarán)" if r["provisionales"] else "")
        )
    print(f"Peticiones a la API: {cliente.peticiones}")


def cmd_agregar(args) -> None:
    nombres = args.endpoint or [
        e.alias for e in ENDPOINTS.values() if (config.DATA_RAW / e.alias).exists()
    ]
    for nombre in nombres:
        agregar(resolver(nombre), args.desde, args.hasta)


def cmd_estado(_args) -> None:
    alguno = False
    for e in ENDPOINTS.values():
        carpeta = config.DATA_RAW / e.alias
        archivos = sorted(carpeta.glob("*.parquet")) if carpeta.exists() else []
        if not archivos:
            continue
        alguno = True
        mb = sum(a.stat().st_size for a in archivos) / 1e6
        print(f"{e.alias:<20} {len(archivos):>4} días  {archivos[0].stem} -> {archivos[-1].stem}  {mb:,.1f} MB")
    if not alguno:
        print("Caché vacía. Prueba: python -m nodos descargar pronostico --dias 3")


def cmd_geo(args) -> None:
    from .infotecnica import construir_nodos

    construir_nodos(refrescar=args.refrescar)


def cmd_mapa(args) -> None:
    from pathlib import Path

    from .mapa import generar

    generar(args.dia, args.dia_pronostico, Path(args.salida) if args.salida else None, args.sin_envoltura)


def cmd_dbt(args) -> None:
    """Ejecuta dbt sobre transform/ con la base data/nodos.duckdb."""
    from . import dbt

    sys.exit(dbt.ejecutar(args.argumentos or ["build"]).returncode)


def cmd_actualizar(args) -> None:
    from .actualizar import actualizar

    estado = actualizar(descargar=not args.sin_descargar)
    sys.exit(0 if estado.get("ok") else 1)


def cmd_servir(args) -> None:
    import os

    if args.sin_actualizar:
        os.environ["NODOS_SIN_ACTUALIZAR"] = "1"
    from .web import servir

    servir(args.host, args.port)


def main(argv=None) -> None:
    p = argparse.ArgumentParser(prog="python -m nodos", description="Datos del CEN (API SIP)")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("endpoints", help="lista los endpoints disponibles").set_defaults(func=cmd_endpoints)

    d = sub.add_parser("descargar", help="descarga días a la caché local (data/raw)")
    d.add_argument("endpoint", nargs="+", help="alias, p. ej. pronostico cmg-real demanda-real")
    d.add_argument("--desde", type=_fecha)
    d.add_argument("--hasta", type=_fecha, help="por defecto hoy")
    d.add_argument("--dias", type=int, default=3, help="si no das --desde (por defecto 3)")
    d.add_argument("--refrescar", action="store_true", help="vuelve a bajar días ya guardados")
    d.add_argument(
        "--refrescar-pronosticos",
        action="store_true",
        help="vuelve a bajar solo endpoints que se reemiten (pronósticos)",
    )
    d.add_argument("--intervalo", type=float, help="segundos mínimos entre peticiones (por defecto 2)")
    d.set_defaults(func=cmd_descargar)

    a = sub.add_parser("agregar", help="(heredado) tablas por barra y hora con pandas en data/processed")
    a.add_argument("endpoint", nargs="*", help="por defecto todos los que tengan caché")
    a.add_argument("--desde", type=_fecha)
    a.add_argument("--hasta", type=_fecha)
    a.set_defaults(func=cmd_agregar)

    sub.add_parser("estado", help="muestra qué hay en la caché").set_defaults(func=cmd_estado)

    g = sub.add_parser("geo", help="ubica las barras con coordenadas de Infotécnica (data/processed/nodos.parquet)")
    g.add_argument("--refrescar", action="store_true", help="vuelve a bajar catálogo y fichas")
    g.set_defaults(func=cmd_geo)

    t = sub.add_parser("dbt", help="transformaciones y tests con dbt + DuckDB (por defecto: build)")
    t.add_argument("argumentos", nargs=argparse.REMAINDER, help="argumentos para dbt, p. ej. build, test, docs generate")
    t.set_defaults(func=cmd_dbt)

    u = sub.add_parser("actualizar", help="un ciclo completo: descargar lo nuevo, geo y dbt build")
    u.add_argument("--sin-descargar", action="store_true", help="solo geo y dbt build con la caché actual")
    u.set_defaults(func=cmd_actualizar)

    s = sub.add_parser("servir", help="app web (mapa + API) que se actualiza sola")
    s.add_argument("--host", default=config.obtener("NODOS_HOST", "127.0.0.1"))
    s.add_argument("--port", type=int, default=int(config.obtener("NODOS_PORT", "8000")))
    s.add_argument("--sin-actualizar", action="store_true", help="solo servir lo que ya hay (sin ciclo de actualización)")
    s.set_defaults(func=cmd_servir)

    m = sub.add_parser("mapa", help="exporta el mapa con los datos incrustados (salida/mapa.html)")
    m.add_argument("--dia", type=_fecha, help="día de demanda y costo marginal (por defecto el último con ambos)")
    m.add_argument("--dia-pronostico", type=_fecha, help="día del pronóstico (por defecto el último)")
    m.add_argument("--salida", help="ruta del HTML (por defecto salida/mapa.html)")
    m.add_argument("--sin-envoltura", action="store_true", help="sin <html>/<head>/<body> (formato Artifact)")
    m.set_defaults(func=cmd_mapa)

    args = p.parse_args(argv)
    try:
        args.func(args)
    except ErrorSIP as exc:
        sys.exit(f"Error: {exc}")
    except KeyboardInterrupt:
        sys.exit("\nInterrumpido. Lo ya descargado queda en caché.")


if __name__ == "__main__":
    main()
