-- Una fila por código de barra del SIP (el mismo en costo marginal y demanda real).
-- Incluye códigos nuevos que aún no pasaron por `python -m nodos geo` (sin coordenadas),
-- para que los tests de relaciones y de cobertura los detecten.
with geo as (
    select * from {{ ref('stg_nodos_geo') }}
),

codigos as (
    select barra from {{ ref('stg_demanda_real') }}
    union
    select barra from {{ ref('stg_cmg_real') }}
    union
    select barra from geo
)

select
    c.barra,
    g.id_barra_info,
    g.barra_infotecnica,
    g.id_subestacion,
    g.subestacion,
    coalesce(g.tension_kv, try_cast(right(c.barra, 3) as double)) as tension_kv,
    g.region,
    g.provincia,
    g.comuna,
    g.lat,
    g.lon,
    g.metodo_cruce,
    coalesce(g.coord_estado, 'sin_cruce')                         as coord_estado,
    g.lat is not null                                             as tiene_coordenadas
from codigos c
left join geo g using (barra)
