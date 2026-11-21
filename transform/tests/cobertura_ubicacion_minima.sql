-- Por día, la energía demandada en barras con coordenadas debe ser al menos
-- var('cobertura_minima') (90% por defecto) del total. Si baja, hay barras nuevas:
-- ejecuta python -m nodos geo y revisa data/ref/barras_sin_ubicar.csv.
with por_dia as (
    select
        d.dia,
        sum(d.demanda_mwh) filter (where d.demanda_mwh > 0)                          as total,
        sum(d.demanda_mwh) filter (where d.demanda_mwh > 0 and b.tiene_coordenadas)  as ubicada
    from {{ ref('fct_demanda_horaria') }} d
    join {{ ref('dim_barra') }} b using (barra)
    group by d.dia
)

select dia, total, ubicada, round(ubicada / total, 4) as cobertura
from por_dia
where ubicada / total < {{ var('cobertura_minima') }}
