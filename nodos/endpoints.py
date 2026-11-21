"""Endpoints del SIP (Sistema de Información Pública) que usa el proyecto.

Documentación: https://portal.api.coordinador.cl/documentacion?service=sipubv2
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Endpoint:
    alias: str
    ruta: str
    descripcion: str
    desfase: str  # hasta cuándo suele haber datos (observado en nov-2026)
    # Días que deben pasar desde el día consultado para dar su descarga por definitiva.
    # Si se bajó antes, se considera provisional y se vuelve a pedir en la siguiente ejecución.
    margen_dias: int = 3
    cambia: bool = False  # True si los datos de un día se reemiten (p. ej. pronósticos)


ENDPOINTS: dict[str, Endpoint] = {
    e.alias: e
    for e in [
        Endpoint(
            "pronostico",
            "pronosticos-demanda-corto-plazo/v4/findByDate",
            "Pronóstico horario de demanda por barra (MWh)",
            "hoy y mañana",
            margen_dias=1,
            cambia=True,
        ),
        Endpoint(
            "pronostico-mediano",
            "pronosticos-demanda-mediano-plazo/v4/findByDate",
            "Pronóstico de demanda del sistema a mediano plazo (MWh)",
            "por verificar",
            margen_dias=1,
            cambia=True,
        ),
        Endpoint(
            "demanda-neta",
            "demanda-neta/v4/findByDate",
            "Demanda neta horaria del sistema (MWh)",
            "~2 días",
            margen_dias=3,
        ),
        Endpoint(
            "demanda-real",
            "demanda-real-estimada/v4/findByDate",
            "Retiros horarios por barra, suministrador y cliente (kWh, negativos)",
            "~2 meses (liquidación mensual)",
            margen_dias=70,
        ),
        Endpoint(
            "cmg-real",
            "costo-marginal-real/v4/findByDate",
            "Costo marginal real por barra cada 15 min (USD/MWh y CLP/kWh)",
            "~1 semana",
            margen_dias=10,
        ),
        Endpoint(
            "cmg-online",
            "costo-marginal-online/v4/findByDate",
            "Costo marginal en línea por barra",
            "por verificar",
            margen_dias=1,
            cambia=True,
        ),
        Endpoint(
            "ens",
            "energia-no-suministrada/v4/findByDate",
            "Energía no suministrada por interrupciones (MWh)",
            "por verificar",
            margen_dias=30,
        ),
        Endpoint(
            "potencia-transitada",
            "potencia-transitada/v4/findByDate",
            "Energía y potencia por línea de transmisión",
            "por verificar",
            margen_dias=10,
        ),
    ]
}


def resolver(nombre: str) -> Endpoint:
    """Acepta el alias corto (cmg-real) o la ruta completa del SIP."""
    if nombre in ENDPOINTS:
        return ENDPOINTS[nombre]
    for e in ENDPOINTS.values():
        if nombre.strip("/") in (e.ruta, e.ruta.split("/")[0]):
            return e
    disponibles = ", ".join(ENDPOINTS)
    raise SystemExit(f"Endpoint desconocido: {nombre}. Disponibles: {disponibles}")
