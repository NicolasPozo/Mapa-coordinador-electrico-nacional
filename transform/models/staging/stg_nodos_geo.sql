-- Cruce código SIP -> subestación -> coordenadas, calculado en Python (python -m nodos geo).
select
    barra,
    id_barra_info,
    barra_infotecnica,
    cast(id_subestacion as integer)   as id_subestacion,
    subestacion,
    metodo_cruce,
    region,
    provincia,
    comuna,
    lat,
    lon,
    coord_estado,
    tension_kv
from {{ source('infotecnica', 'nodos_geo') }}
