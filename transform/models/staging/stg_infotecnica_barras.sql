select
    id                      as id_barra_info,
    nombre                  as barra_infotecnica,
    id_subestacion,
    subestacion_nombre      as subestacion,
    codigo,
    nemotecnico,
    propietario_nombre      as propietario,
    try_cast(
        replace(regexp_extract(nombre, '([0-9]+(?:[.,][0-9]+)?)\s*KV', 1), ',', '.')
        as double
    )                       as tension_kv
from {{ source('infotecnica', 'barras') }}
