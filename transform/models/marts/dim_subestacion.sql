with geo as (
    select
        id_subestacion,
        any_value(lat)        as lat,
        any_value(lon)        as lon,
        any_value(region)     as region,
        any_value(provincia)  as provincia,
        any_value(comuna)     as comuna,
        count(*)              as barras_sip
    from {{ ref('stg_nodos_geo') }}
    where id_subestacion is not null and lat is not null
    group by id_subestacion
)

select
    s.id_subestacion,
    s.nombre,
    s.nemotecnico,
    s.propietario,
    s.coordinado,
    geo.lat,
    geo.lon,
    geo.region,
    geo.provincia,
    geo.comuna,
    coalesce(geo.barras_sip, 0)   as barras_sip,
    geo.lat is not null           as tiene_coordenadas
from {{ ref('stg_infotecnica_subestaciones') }} s
left join geo using (id_subestacion)
