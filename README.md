# Nodos

Mapa 3D interactivo de la demanda eléctrica y el costo marginal en las subestaciones del Sistema Eléctrico Nacional de Chile, con datos del Coordinador Eléctrico Nacional que **se actualizan solos** mientras la app está corriendo. Es la base para simular y proyectar demanda por nodo.

> Fuente: Coordinador Eléctrico Nacional (CEN) - Datos Abiertos

## Cómo funciona

```
API SIP (CEN) ──┐                        ┌─ dbt build (tests) ─┐
                ├─ descargar ─ Parquet ──┤                     ├─ data/nodos.duckdb ─ API ─ mapa
Infotécnica ────┘   (caché por día)      └─ geo (coordenadas) ─┘
```

1. **Descargar** (`nodos/sip.py`): API SIP con caché diaria en Parquet, control de velocidad, reintentos y días provisionales.
2. **Ubicar** (`nodos/infotecnica.py`): cada barra del SIP se cruza con Infotécnica (por id, por nombre o manual) para obtener lat/lon.
3. **Transformar** (`transform/`, dbt + DuckDB): capas raw → limpio → modelo, con 53 tests. dbt construye en una base temporal y **solo se publica si pasa**.
4. **Servir** (`nodos/web.py`, FastAPI): el mapa 3D (`web/index.html`, deck.gl + MapLibre) pide los datos a la API y recarga solo cuando hay datos nuevos.

La app ejecuta los pasos 1–3 **al arrancar y luego cada 6 horas**.

### El mapa

- **Agujas por subestación**: la altura es la energía de la hora (MWh) y el color, el costo marginal (USD/MWh). Al mediodía casi todo queda en 0 USD/MWh por el excedente solar.
- **Demanda real** o **pronóstico** del CEN, con control de hora (▶ reproduce las 24 h) y la fecha de cada dato con su atraso («hace 55 días»).
- **Mapas base**: claro, oscuro, calles (CARTO), satélite (Esri) o mínimo (solo contornos, sin servicios externos). Botones para volar al norte, centro, Santiago o sur.
- Se gira e inclina con clic derecho (o dos dedos); clic en una aguja para acercarse.

## Despliegue con Docker

```powershell
copy .env.example .env
```

Edita `.env` y pega tu `CEN_SIP_USER_KEY` (se obtiene en el [portal del desarrollador](https://portal.api.coordinador.cl), plan **Información Pública (SIP) → Plan Consulta de Datos**). Luego:

```powershell
docker compose up -d --build
```

En Windows necesitas Docker Desktop con WSL2: si el instalador pide la «Plataforma de máquina virtual», elige *All-users installation* o ejecuta `wsl --install` como administrador y reinicia. Construir la imagen la primera vez toma unos 2–3 minutos.

Abre http://localhost:8000. El avance se ve con `docker compose logs -f`. La primera vez, a los **~30 segundos** aparece una **vista rápida** con el pronóstico del CEN (hoy y mañana) mientras se descarga el resto; a los **~10 minutos** el mapa cambia solo a la demanda real con precios. Esa primera carga es una **muestra** (el último día completo de demanda real con sus precios, más 1 día reciente de costo marginal y 3 de demanda neta y pronóstico). Las coordenadas de las subestaciones vienen incluidas en `semilla/`, así que no hay que bajar las ~800 fichas de Infotécnica.

¿Quieres más historia? Usa el botón **«Más datos»** del mapa (1 semana ≈ 35 min, 2 semanas ≈ 1 h, 1 mes ≈ 2,5 h de descarga; la API del CEN tarda 4–5 s por página). La elección queda guardada en el volumen y se mantiene en las actualizaciones siguientes; lo ya descargado no se vuelve a pedir. Si el mapa queda público, pon `NODOS_PERMITIR_AMPLIAR=0` para que nadie más pueda disparar descargas.

- **Datos persistentes**: el volumen `nodos-data` (`/app/data`) guarda la caché, la base DuckDB y el estado. Sobrevive a reinicios y a nuevas versiones de la imagen.
- **La clave nunca entra en la imagen**: llega por variable de entorno (`env_file: .env`). `.env` está en `.gitignore` y `.dockerignore`.
- **GitHub Actions** (`.github/workflows/docker.yml`): en cada push construye la imagen y comprueba que la app y dbt cargan; en `main` la publica en `ghcr.io/<usuario>/<repo>`.

Para usar la imagen publicada en un servidor, cambia `build: .` por `image: ghcr.io/<usuario>/<repo>:latest` en `docker-compose.yml`.

### Por qué tarda: límites de la API del Coordinador

- La API pública (SIP) entrega como máximo **10.000 filas por consulta** y responde en unos **4–5 s** cada una (páginas de 20.000 devuelven 502).
- Un día de **demanda real** son ~400.000 registros (≈41 consultas); uno de **costo marginal**, ~160.000 (un precio cada 15 min en ~1.650 barras, ≈16 consultas).
- Se esperan 2 s entre consultas para no saturarla (`CEN_SIP_MIN_INTERVAL`); ante 429 o 502/504 se reintenta con pausas, y una descarga que falla no detiene el ciclo.
- La **demanda real** se publica por mes completo, con **1–2 meses de desfase**; el costo marginal con ~1 semana. Por eso el mapa no muestra el día de hoy (el pronóstico sí: ayer, hoy y mañana).
- La API no trae el id del medidor: filas idénticas pueden ser medidores distintos, así que no se deduplican.

Mientras no hay datos, el mapa muestra el paso en curso («Paso 4 de 7 · descargando demanda real · 29 sep · página 12/41») y este mismo resumen.

### Configuración (variables de entorno)

| Variable | Por defecto | Qué hace |
|---|---|---|
| `CEN_SIP_USER_KEY` | — | Clave de la API SIP (obligatoria) |
| `NODOS_ACTUALIZAR_CADA_HORAS` | `6` | Cada cuánto se actualiza; `0` = solo al arrancar |
| `NODOS_DIAS_PRONOSTICO` | `3` | Días de pronóstico (ayer, hoy, mañana); se vuelven a pedir porque el CEN los reemite |
| `NODOS_DIAS_DEMANDA_NETA` | `3` | Últimos días publicados de demanda neta |
| `NODOS_DIAS_CMG` | `1` | Últimos días publicados de costo marginal (~1 semana de desfase) |
| `NODOS_DIAS_DEMANDA` | `1` | Últimos días completos de demanda real (~7 semanas de desfase; ~41 peticiones por día) |
| `NODOS_PERMITIR_AMPLIAR` | `1` | `0` = oculta «Más datos» y desactiva `POST /api/ampliar` |
| `NODOS_SIN_ACTUALIZAR` | `0` | `1` = solo servir lo que ya hay en el volumen |
| `CEN_SIP_MIN_INTERVAL` | `2.0` | Segundos entre peticiones a la API SIP |

Los días ya descargados no se vuelven a pedir, así que la historia se acumula en el volumen con el tiempo.

### API

| Ruta | Devuelve |
|---|---|
| `GET /` | El mapa 3D (agujas por subestación; deck.gl + MapLibre) |
| `GET /api/estado` | Última actualización, paso en curso, error, tests de dbt y ventana de días |
| `POST /api/ampliar` | Pide más historia: `{"dias": 7 \| 14 \| 30}`; adelanta la siguiente actualización |
| `GET /api/dias` | Días disponibles de demanda, costo marginal y pronóstico |
| `GET /api/mapa?dia=AAAA-MM-DD` | Subestaciones con demanda y costo marginal por hora + totales del sistema |
| `GET /api/pronostico?dia=AAAA-MM-DD` | Pronóstico del CEN por subestación y hora |
| `GET /api/base` | Contornos de Chile y vecinos (GeoJSON), para el mapa base «Mínimo» |
| `GET /api/docs` | Documentación interactiva de la API |

## Desarrollo local (sin Docker)

```powershell
python -m venv .venv
```
```powershell
.venv\Scripts\python -m pip install -r requirements.txt -r requirements-web.txt
```
```powershell
python -m venv .venv-dbt
```
```powershell
.venv-dbt\Scripts\python -m pip install -r requirements-dbt.txt
```

Con la clave en `.env`:

```powershell
.venv\Scripts\python -m nodos servir
```

Comandos sueltos:

| Comando | Qué hace |
|---|---|
| `python -m nodos servir [--sin-actualizar]` | App web en http://127.0.0.1:8000 |
| `python -m nodos actualizar [--sin-descargar]` | Un ciclo completo: descargar → geo → dbt build → publicar |
| `python -m nodos descargar <endpoint…> --desde AAAA-MM-DD --hasta AAAA-MM-DD` | Bajar un rango a la caché (p. ej. historia) |
| `python -m nodos geo` | Recalcular coordenadas de las barras |
| `python -m nodos dbt <comando>` | Pasar un comando a dbt (`build`, `test`, `docs generate`…) |
| `python -m nodos semilla` | Regenerar `semilla/` con las fichas de Infotécnica ya descargadas |
| `python -m nodos estado` | Qué hay en la caché |
| `python -m nodos endpoints` | Endpoints disponibles |

Endpoints del SIP: `pronostico`, `pronostico-mediano`, `demanda-neta`, `demanda-real`, `cmg-real`, `cmg-online`, `ens`, `potencia-transitada`.

## Datos

| Alias | Qué es | Hasta dónde llega |
|---|---|---|
| `pronostico` | Pronóstico horario de demanda por barra (MWh) | mañana |
| `demanda-neta` | Demanda neta horaria del sistema | hoy (parcial) |
| `cmg-real` | Costo marginal real por barra cada 15 min | ~1 semana atrás |
| `demanda-real` | Retiros por barra, suministrador y cliente | 1–2 meses atrás (se publica por mes) |

Comportamiento observado de la API SIP:

- La clave va como parámetro `user_key`. Páginas de hasta 10 000 filas (con 20 000 responde 502; el cliente baja el tamaño solo). Responde 429 si se consulta muy seguido (el cliente espera y reintenta).
- La numeración de páginas **no es coherente**: `cmg-real` y `demanda-real` empiezan en `page=0`; `pronostico` y `demanda-neta` en `page=1`. El cliente lo detecta.
- Un día de `demanda-real` son ~400 000 filas; de `cmg-real`, ~158 000.
- Los días descargados antes de estar completos quedan **provisionales** y se vuelven a pedir (margen por endpoint en `nodos/endpoints.py`).

## Coordenadas de los nodos

La API SIP no trae coordenadas. Se obtienen de **Infotécnica** (`api-infotecnica.coordinador.cl/v1`, pública):

1. El `id_info` de `cmg-real` y el `id_barra_info` del pronóstico son el id de barra de Infotécnica (cruce exacto; si un código cambió de id, se usa el más reciente).
2. Cada barra pertenece a una subestación, cuya ficha técnica trae Coordenada Este/Norte (UTM) y Huso → lat/lon (WGS84).
3. El código de barra (`LASARANAS_____110`) es el mismo en `cmg-real` y `demanda-real`, así que la demanda hereda la ubicación.
4. **Respaldo por nombre** para códigos sin id: 14 letras del nombre + 3 de tensión, con abreviaturas (`A.JAHUEL` → Alto Jahuel). Conservador: descarta lo ambiguo.
5. **Manual**: `ubicaciones_manuales.csv` (`barra,lat,lon,fuente`). Las pendientes, ordenadas por energía, quedan en `data/ref/barras_sin_ubicar.csv`.

Cobertura actual: **94% de la energía demandada**. Faltan sobre todo grandes consumos mineros (Pallata, Esperanza, Enlace, Cahuiza…).

## Transformaciones (dbt + DuckDB)

| Capa | Esquema | Modelos |
|---|---|---|
| raw | (Parquet) | fuentes `sip.*` e `infotecnica.*` |
| limpio | `limpio` (vistas) | `stg_demanda_real`, `stg_cmg_real`, `stg_pronostico`, `stg_demanda_neta`, `stg_infotecnica_barras`, `stg_infotecnica_subestaciones`, `stg_nodos_geo`, `stg_coordenadas_subestaciones` |
| modelo | `modelo` (tablas) | `dim_barra`, `dim_subestacion`, `fct_demanda_horaria`, `fct_cmg_horario`, `fct_pronostico_horario`, `fct_sistema_horario`, `mart_subestacion_horaria` |

Tests:

- Claves: `not_null`, `unique`, combinaciones únicas (barra × hora, subestación × hora). Relaciones entre hechos y dimensiones.
- **Horas completas**: 24 h por día (demanda y costo marginal), 24 h por barra pronosticada.
- **Cortes de descarga**: error si en un día más del 10% de las barras no tiene sus 96 intervalos de costo marginal (aviso por barra).
- **Cobertura de ubicación ≥ 90%** de la energía por día (`--vars "{cobertura_minima: 0.95}"` para cambiarla).
- Rangos (costo marginal 0–2000 USD/MWh, coordenadas dentro de Chile, demanda del sistema > 0), valores aceptados y `fila_en_su_dia` (ningún día contado dos veces).

Decisiones:

- `stg_demanda_real` no quita filas repetidas: un cliente puede tener varios medidores en la misma barra y la API no trae su id.
- Hay retiros con signo positivo (inyecciones o correcciones): el test de demanda > 0 se aplica al sistema, no a cada barra.
- El cruce de coordenadas por nombre queda en Python y entra a dbt como `infotecnica.nodos_geo`.

## Estructura

```
nodos/          paquete Python (descarga, geo, actualizar, servicio, web, CLI)
transform/      proyecto dbt (modelos, tests, profiles.yml)
web/index.html  el mapa 3D (deck.gl 9.1 + MapLibre 4.7; mapas base CARTO, Esri o Natural Earth)
web/ampliar.js  botón «Más datos» y pantalla de espera del primer arranque
semilla/        coordenadas de las subestaciones (python -m nodos semilla), para un primer arranque rápido
data/           caché, base DuckDB y estado (volumen en Docker; no se versiona)
```
