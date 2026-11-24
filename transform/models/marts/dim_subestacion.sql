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

-- Primero la ubicación vía barras del SIP (incluye correcciones manuales); si la subestación
-- no tiene barras en el SIP (p. ej. solo está en el pronóstico), la de su ficha técnica.
select
    s.id_subestacion,
    s.nombre,
    s.nemotecnico,
    s.propietario,
    s.coordinado,
    coalesce(geo.lat, f.lat)               as lat,
    coalesce(geo.lon, f.lon)               as lon,
    coalesce(geo.region, f.region)         as region,
    coalesce(geo.provincia, f.provincia)   as provincia,
    coalesce(geo.comuna, f.comuna)         as comuna,
    coalesce(geo.barras_sip, 0)            as barras_sip,
    coalesce(geo.lat, f.lat) is not null   as tiene_coordenadas
from {{ ref('stg_infotecnica_subestaciones') }} s
left join geo using (id_subestacion)
left join {{ ref('stg_coordenadas_subestaciones') }} f using (id_subestacion)
