-- Pronóstico horario por barra. Si hay varias emisiones para la misma hora, queda la más reciente.
with origen as (
    select * from {{ source('sip', 'pronostico') }}
)

select
    barra,
    cast(id_barra_info as integer)    as id_barra_info,
    cast(fecha_hora as timestamp)     as fecha_hora,
    energia_mwh,
    cast(date_control as date)        as emitido,
    cast(_dia_consulta as date)       as dia_consulta
from origen
qualify row_number() over (
    partition by barra, cast(fecha_hora as timestamp)
    order by date_control desc, _dia_consulta desc
) = 1
