-- Coordenadas por subestación desde su ficha técnica (calculadas en Python, python -m nodos geo).
select
    cast(id_subestacion as integer)   as id_subestacion,
    lat,
    lon,
    region,
    provincia,
    comuna,
    coord_estado
from {{ source('infotecnica', 'coordenadas_subestaciones') }}
where lat is not null
