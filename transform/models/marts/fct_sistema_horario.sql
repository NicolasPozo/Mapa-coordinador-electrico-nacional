-- Totales del sistema por hora: demanda (toda y la ubicada en el mapa), costo marginal
-- ponderado por demanda, demanda neta publicada por el CEN y pronóstico.
with demanda as (
    select
        d.fecha_hora,
        sum(d.demanda_mwh)                                            as demanda_mwh,
        sum(d.demanda_mwh) filter (where b.tiene_coordenadas)         as demanda_ubicada_mwh,
        count(distinct d.barra)                                       as barras_con_demanda
    from {{ ref('fct_demanda_horaria') }} d
    left join {{ ref('dim_barra') }} b using (barra)
    group by d.fecha_hora
),

precio as (
    select
        c.fecha_hora,
        sum(c.cmg_usd_mwh * d.demanda_mwh) filter (where d.demanda_mwh > 0)
            / nullif(sum(d.demanda_mwh) filter (where d.demanda_mwh > 0), 0)  as cmg_ponderado_usd_mwh,
        avg(c.cmg_usd_mwh)                                                    as cmg_promedio_usd_mwh
    from {{ ref('fct_cmg_horario') }} c
    left join {{ ref('fct_demanda_horaria') }} d using (barra, fecha_hora)
    group by c.fecha_hora
),

pronostico as (
    select fecha_hora, sum(energia_mwh) as pronostico_mwh
    from {{ ref('fct_pronostico_horario') }}
    group by fecha_hora
),

horas as (
    select fecha_hora from demanda
    union select fecha_hora from precio
    union select fecha_hora from pronostico
    union select fecha_hora from {{ ref('stg_demanda_neta') }}
)

select
    h.fecha_hora,
    cast(h.fecha_hora as date)    as dia,
    hour(h.fecha_hora)            as hora,
    d.demanda_mwh,
    d.demanda_ubicada_mwh,
    d.barras_con_demanda,
    p.cmg_ponderado_usd_mwh,
    p.cmg_promedio_usd_mwh,
    n.demanda_neta_mwh,
    f.pronostico_mwh
from horas h
left join demanda d using (fecha_hora)
left join precio p using (fecha_hora)
left join {{ ref('stg_demanda_neta') }} n using (fecha_hora)
left join pronostico f using (fecha_hora)
