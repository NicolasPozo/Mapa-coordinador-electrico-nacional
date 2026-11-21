-- Pronóstico de demanda del CEN por barra y hora. Las barras del pronóstico usan otro
-- formato de nombre (LoEspejo110); se unen a la geografía por id_barra_info.
select
    p.barra                         as barra_pronostico,
    p.id_barra_info,
    b.id_subestacion,
    p.fecha_hora,
    cast(p.fecha_hora as date)      as dia,
    hour(p.fecha_hora)              as hora,
    p.energia_mwh,
    p.emitido
from {{ ref('stg_pronostico') }} p
left join {{ ref('stg_infotecnica_barras') }} b using (id_barra_info)
