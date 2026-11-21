-- Costo marginal horario por barra: promedio de los cuatro intervalos de 15 minutos.
select
    barra,
    fecha_hora,
    cast(fecha_hora as date)      as dia,
    hour(fecha_hora)              as hora,
    any_value(id_barra_info)      as id_barra_info,
    avg(cmg_usd_mwh)              as cmg_usd_mwh,
    avg(cmg_clp_kwh)              as cmg_clp_kwh,
    count(*)                      as intervalos
from {{ ref('stg_cmg_real') }}
group by barra, fecha_hora
