"""Ciclo completo de actualización: descargar lo nuevo -> ubicar barras -> dbt build.

    python -m nodos actualizar

Pensado para correr al iniciar el contenedor y luego cada N horas (lo hace `servir`).
Solo publica la base nueva si `dbt build` termina sin errores: dbt construye en
data/nodos_nuevo.duckdb y, si todo pasa, reemplaza data/nodos.duckdb de una vez.

Por defecto se baja una MUESTRA pequeña para que el primer arranque tome minutos:
    NODOS_DIAS_DEMANDA      1   (demanda real: el último día completo; llega con ~7 semanas de desfase)
    NODOS_DIAS_CMG          1   (costo marginal real; llega con ~1 semana de desfase)
    NODOS_DIAS_DEMANDA_NETA 3
    NODOS_DIAS_PRONOSTICO   3   (ayer, hoy y mañana; se vuelve a pedir porque el CEN lo reemite)

Desde el mapa (botón «Más datos», POST /api/ampliar) se puede pedir más historia; la
elección se guarda en data/ventana.json y en cada ciclo se usa el mayor entre ella y las variables.
Además se baja el costo marginal real de los mismos días de la demanda real, para que el
mapa tenga demanda y precio juntos. Lo descargado queda en caché: la historia se acumula.
"""

from __future__ import annotations

import json
import os
import time
import traceback
from datetime import date, datetime, timedelta

from . import config
from . import dbt as dbt_runner
from .endpoints import ENDPOINTS
from .sip import ClienteSIP, ErrorClave, _PaginaGrande, descargar_rango

BASE = config.RAIZ / "data" / "nodos.duckdb"
BASE_NUEVA = config.RAIZ / "data" / "nodos_nuevo.duckdb"
ESTADO = config.RAIZ / "data" / "estado.json"
VENTANA = config.RAIZ / "data" / "ventana.json"

# alias -> (variable de entorno, días por defecto, desde cuántos días atrás empezar a buscar)
PLAN = {
    "pronostico": ("NODOS_DIAS_PRONOSTICO", 3, -1),
    "demanda-neta": ("NODOS_DIAS_DEMANDA_NETA", 3, 0),
    "cmg-real": ("NODOS_DIAS_CMG", 1, 0),
    "demanda-real": ("NODOS_DIAS_DEMANDA", 1, 20),
}
BUSQUEDA_MAXIMA = 120  # días hacia atrás para encontrar el último día publicado

# Historia que se puede pedir desde el mapa (días de demanda real) y lo que amplía.
OPCIONES_AMPLIAR = (7, 14, 30)
AMPLIA = ("demanda-real", "cmg-real", "demanda-neta")
# Minutos aproximados por día de demanda real (~41 páginas) + su costo marginal (~16),
# medido con la API respondiendo en 4–5 s por página.
MINUTOS_POR_DIA = 5


NOMBRES_PASO = {
    "pronostico": "descargando pronóstico",
    "demanda-neta": "descargando demanda neta",
    "cmg-real": "descargando costo marginal",
    "demanda-real": "descargando demanda real",
    "cmg-real-demanda": "descargando costo marginal de los días con demanda",
    "rapida": "publicando vista rápida (pronóstico)",
    "ubicar": "ubicando subestaciones",
    "dbt": "transformando y verificando (dbt)",
}
MESES = ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic"]


def leer_ventana() -> dict:
    try:
        datos = json.loads(VENTANA.read_text(encoding="utf-8"))
        return {k: int(v) for k, v in datos.items() if k in PLAN}
    except (FileNotFoundError, ValueError, TypeError, AttributeError):
        return {}


def ampliar_ventana(dias: int) -> dict:
    """Guarda la historia pedida desde el mapa (nunca la reduce)."""
    if dias not in OPCIONES_AMPLIAR:
        raise ValueError(f"dias debe ser uno de {OPCIONES_AMPLIAR}")
    ventana = leer_ventana()
    for alias in AMPLIA:
        ventana[alias] = max(ventana.get(alias, 0), dias)
    VENTANA.parent.mkdir(parents=True, exist_ok=True)
    tmp = VENTANA.with_suffix(".tmp")
    tmp.write_text(json.dumps(ventana, indent=2), encoding="utf-8")
    tmp.replace(VENTANA)
    return ventana


def dias_plan(alias: str) -> int:
    """Días que se mantienen: el mayor entre la variable de entorno y lo pedido desde el mapa."""
    variable, defecto = PLAN[alias][:2]
    try:
        base = max(0, int(config.obtener(variable, str(defecto))))
    except ValueError:
        base = defecto
    if base == 0:
        return 0  # desactivado explícitamente
    return max(base, leer_ventana().get(alias, 0))


def ventana_actual() -> dict:
    return {alias: dias_plan(alias) for alias in PLAN}


def ultimo_dia_publicado(cliente: ClienteSIP, alias: str, empezar_atras: int) -> date | None:
    """Último día con datos, por búsqueda binaria (~8 consultas mínimas en vez de una por día).

    Supone que lo publicado es continuo hacia atrás: si un día tiene datos, los anteriores
    también. La demanda real se publica por mes completo, así que su desfase varía mucho.
    """
    e = ENDPOINTS[alias]
    hoy = date.today()

    def hay(atras: int) -> bool:
        dia = (hoy - timedelta(days=atras)).isoformat()
        for intento in range(4):
            try:
                return bool(cliente._get(e.ruta, {"startDate": dia, "endDate": dia, "page": 1, "limit": 1}).get("data"))
            except _PaginaGrande:  # 502/504 pasajero del CEN (aquí la página es de 1 fila)
                if intento == 3:
                    raise
                time.sleep(5 * (intento + 1))

    if hay(empezar_atras):
        return hoy - timedelta(days=empezar_atras)
    sin, con = empezar_atras, BUSQUEDA_MAXIMA
    if not hay(con):
        return None
    while con - sin > 1:
        medio = (sin + con) // 2
        if hay(medio):
            con = medio
        else:
            sin = medio
    return hoy - timedelta(days=con)


def guardar_estado(**campos) -> dict:
    estado = leer_estado()
    estado.update(campos)
    ESTADO.parent.mkdir(parents=True, exist_ok=True)
    tmp = ESTADO.with_suffix(".tmp")
    tmp.write_text(json.dumps(estado, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    tmp.replace(ESTADO)
    return estado


def leer_estado() -> dict:
    try:
        return json.loads(ESTADO.read_text(encoding="utf-8"))
    except (FileNotFoundError, ValueError):
        return {}


def _publicar_base() -> None:
    """Reemplaza la base publicada por la nueva (reintenta si un lector la tiene abierta)."""
    for intento in range(10):
        try:
            os.replace(BASE_NUEVA, BASE)
            return
        except PermissionError:
            time.sleep(1 + intento)
    raise RuntimeError("No pude reemplazar data/nodos.duckdb (¿está abierta en otro programa?)")


def actualizar(descargar: bool = True) -> dict:
    inicio = time.monotonic()
    guardar_estado(en_curso=True, inicio=datetime.now().isoformat(timespec="seconds"), paso="descargando")
    resumen: dict = {"descargas": {}, "avisos": []}

    def intentar(nombre: str, funcion):
        """Una descarga que falla (p. ej. el CEN responde 502 un buen rato) no tumba el ciclo:
        se anota y se sigue con lo que hay en caché; se reintenta en el próximo ciclo.
        Solo un problema con la clave (401/403) detiene todo."""
        try:
            return funcion()
        except ErrorClave:
            raise
        except Exception as exc:  # noqa: BLE001
            aviso = f"{nombre}: {exc}"[:300]
            print(f"  ! falló la descarga ({aviso}); sigo con lo que hay en caché")
            resumen["avisos"].append(aviso)
            return None

    # Pasos visibles en la web («Paso 3 de 6 · descargando demanda real · 29 sep · página 12/41»).
    pasos = [a for a in PLAN if descargar and dias_plan(a) > 0]
    # Vista rápida: en el primer arranque (sin base publicada) se publica el pronóstico apenas
    # se baja (~1 min) para que el mapa muestre algo mientras llega lo pesado.
    rapida = "pronostico" in pasos and not BASE.exists()
    if rapida:
        pasos.insert(pasos.index("pronostico") + 1, "rapida")
    if descargar and dias_plan("cmg-real") > 0 and dias_plan("demanda-real") > 0:
        pasos.append("cmg-real-demanda")
    pasos += ["ubicar", "dbt"]

    def marcar(clave: str) -> None:
        guardar_estado(paso=NOMBRES_PASO[clave], paso_n=pasos.index(clave) + 1, pasos_total=len(pasos), detalle=None)

    def publicar_vista_rapida() -> None:
        from .infotecnica import construir_nodos

        construir_nodos()
        BASE_NUEVA.unlink(missing_ok=True)
        proc = dbt_runner.ejecutar(
            ["build", "--select", "+fct_pronostico_horario", "+dim_subestacion", "--indirect-selection", "cautious"], duckdb=BASE_NUEVA, capturar=True
        )
        if proc.returncode != 0:
            BASE_NUEVA.unlink(missing_ok=True)
            raise RuntimeError("dbt build de la vista rápida falló: " + " / ".join((proc.stdout or "").splitlines()[-3:]))
        _publicar_base()
        guardar_estado(ultima_actualizacion=datetime.now().isoformat(timespec="seconds"), fase="pronostico")
        print("Vista rápida publicada (solo pronóstico); sigue la descarga de demanda real y precios")

    def avance(dia: date, pagina: int, total: int) -> None:
        texto = f"{dia.day} {MESES[dia.month - 1]}"
        guardar_estado(detalle=f"{texto} · página {pagina}/{total}" if total > 1 else texto)

    try:
        if descargar:
            cliente = ClienteSIP()
            cliente.al_avanzar = avance
            rango_demanda = None
            for alias, (_variable, _defecto, atras) in PLAN.items():
                n = dias_plan(alias)
                if n == 0:
                    continue
                marcar(alias)
                e = ENDPOINTS[alias]
                ultimo = intentar(f"{alias} (buscar último día)", lambda: ultimo_dia_publicado(cliente, alias, atras))
                if ultimo is None:
                    print(f"{alias}: sin último día publicado (no encontrado o error)")
                    continue
                if alias == "demanda-real":
                    # El último día publicado llega incompleto (le falta la última hora): se
                    # usa hasta el anterior, así la muestra de un día tiene las 24 horas.
                    ultimo -= timedelta(days=1)
                desde = ultimo - timedelta(days=n - 1)
                print(f"{alias}: {desde} -> {ultimo}")
                r = intentar(alias, lambda: descargar_rango(cliente, e, desde, ultimo, refrescar=e.cambia))
                resumen["descargas"][alias] = {"desde": desde, "hasta": ultimo, **(r or {"error": True})}
                if alias == "demanda-real":
                    rango_demanda = (desde, ultimo)
                if alias == "pronostico" and rapida:
                    marcar("rapida")
                    intentar("vista rápida", publicar_vista_rapida)

            # La demanda real llega ~7 semanas atrasada: sin esto, sus días no tendrían
            # costo marginal en el mapa. Esos días ya son definitivos, así que solo se bajan una vez.
            if rango_demanda and dias_plan("cmg-real") > 0:
                marcar("cmg-real-demanda")
                e = ENDPOINTS["cmg-real"]
                desde, hasta = rango_demanda
                print(f"cmg-real (días con demanda): {desde} -> {hasta}")
                r = intentar("cmg-real (días con demanda)", lambda: descargar_rango(cliente, e, desde, hasta))
                resumen["descargas"]["cmg-real-demanda"] = {"desde": desde, "hasta": hasta, **(r or {"error": True})}
            resumen["peticiones_sip"] = cliente.peticiones

        marcar("ubicar")
        from .infotecnica import construir_nodos

        construir_nodos()

        marcar("dbt")
        BASE_NUEVA.unlink(missing_ok=True)
        proc = dbt_runner.ejecutar(["build"], duckdb=BASE_NUEVA, capturar=True)
        resumen["dbt"] = dbt_runner.resumen_resultados()
        if proc.returncode != 0:
            BASE_NUEVA.unlink(missing_ok=True)
            ultimas = "\n".join((proc.stdout or "").splitlines()[-25:])
            raise RuntimeError(f"dbt build falló; se mantiene la base anterior.\n{ultimas}")
        _publicar_base()

        estado = guardar_estado(
            en_curso=False,
            paso=None,
            paso_n=None,
            detalle=None,
            ok=True,
            error=None,
            fase="completa",
            ultima_actualizacion=datetime.now().isoformat(timespec="seconds"),
            duracion_s=round(time.monotonic() - inicio),
            **resumen,
        )
        print(f"Actualización completa en {estado['duracion_s']} s")
        return estado
    except (Exception, SystemExit) as exc:  # se registra y se deja la base anterior publicada
        traceback.print_exc()
        return guardar_estado(
            en_curso=False,
            paso=None,
            paso_n=None,
            detalle=None,
            ok=False,
            error=str(exc)[:4000],
            ultimo_intento=datetime.now().isoformat(timespec="seconds"),
            duracion_s=round(time.monotonic() - inicio),
            **resumen,
        )
