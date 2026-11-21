select
    id                      as id_subestacion,
    nombre,
    nemotecnico,
    propietario_nombre      as propietario,
    coordinado_nombre       as coordinado
from {{ source('infotecnica', 'subestaciones') }}
