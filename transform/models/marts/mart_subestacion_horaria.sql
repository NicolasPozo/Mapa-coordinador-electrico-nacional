-- Lo que dibuja el mapa: una fila por subestación ubicada y hora, con su demanda
-- (suma de sus barras) y su costo marginal (ponderado por demanda; si no hay, promedio).
with barras as (
    select barra, id_subestacion
    from {{ ref('dim_barra') }}
    where tiene_coordenadas and id_subestacion is not null
),

por_barra as (
    select
        coalesce(d.barra, c.barra)            as barra,
        coalesce(d.fecha_hora, c.fecha_hora)  as fecha_hora,
        d.demanda_mwh,
        d.mwh_regulado,
        c.cmg_usd_mwh
    from {{ ref('fct_demanda_horaria') }} d
    full outer join {{ ref('fct_cmg_horario') }} c using (barra, fecha_hora)
)

select
    b.id_subestacion,
    s.nombre                                                          as subestacion,
    s.comuna,
    s.region,
    s.lat,
    s.lon,
    p.fecha_hora,
    cast(p.fecha_hora as date)                                        as dia,
    hour(p.fecha_hora)                                                as hora,
    sum(p.demanda_mwh)                                                as demanda_mwh,
    sum(p.mwh_regulado)                                               as mwh_regulado,
    coalesce(
        sum(p.cmg_usd_mwh * p.demanda_mwh) filter (where p.demanda_mwh > 0)
            / nullif(sum(p.demanda_mwh) filter (where p.demanda_mwh > 0 and p.cmg_usd_mwh is not null), 0),
        avg(p.cmg_usd_mwh)
    )                                                                 as cmg_usd_mwh,
    count(distinct p.barra)                                           as barras
from por_barra p
join barras b using (barra)
join {{ ref('dim_subestacion') }} s using (id_subestacion)
group by all
