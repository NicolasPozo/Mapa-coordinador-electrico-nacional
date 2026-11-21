-- Demanda neta horaria del sistema (generación bruta menos consumos propios).
with origen as (
    select * from {{ source('sip', 'demanda_neta') }}
)

select
    cast(fecha_hora as timestamp)     as fecha_hora,
    demanda_neta_mwh,
    gen_bruta_mwh,
    gen_erv_mwh,
    cons_propio_mwh,
    cast(_dia_consulta as date)       as dia_consulta
from origen
qualify row_number() over (partition by cast(fecha_hora as timestamp) order by _dia_consulta desc) = 1
