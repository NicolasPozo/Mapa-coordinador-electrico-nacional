-- Demanda por barra y hora (suma de todos los suministradores y clientes).
select
    barra,
    fecha_hora,
    cast(fecha_hora as date)                                          as dia,
    hour(fecha_hora)                                                  as hora,
    sum(demanda_mwh)                                                  as demanda_mwh,
    coalesce(sum(demanda_mwh) filter (where tipo = 'R'), 0)           as mwh_regulado,
    coalesce(sum(demanda_mwh) filter (where tipo <> 'R'), 0)          as mwh_libre,
    count(*)                                                          as registros
from {{ ref('stg_demanda_real') }}
group by barra, fecha_hora
