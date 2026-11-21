-- Error si en un día más del 10% de las barras no tiene sus 96 intervalos de 15 minutos:
-- es la señal de una descarga cortada. Se arregla con:
-- python -m nodos descargar cmg-real --desde <dia> --hasta <dia> --refrescar
with por_barra as (
    select barra, cast(fecha_hora as date) as dia, count(*) as intervalos
    from {{ ref('stg_cmg_real') }}
    group by barra, cast(fecha_hora as date)
)

select
    dia,
    count(*)                                     as barras,
    count(*) filter (where intervalos <> 96)     as incompletas
from por_barra
group by dia
having count(*) filter (where intervalos <> 96) > 0.10 * count(*)
