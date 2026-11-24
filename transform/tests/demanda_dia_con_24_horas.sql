-- Cada día con demanda real debe tener las 24 horas a nivel de sistema.
-- Se excluye el día más reciente: el CEN lo publica por partes (p. ej. hasta las 22:00) y
-- queda como provisional, así que se vuelve a descargar en los ciclos siguientes.
-- Si falla, la descarga de ese día quedó incompleta: python -m nodos descargar demanda-real --desde <dia> --hasta <dia> --refrescar
select dia, count(distinct hora) as horas
from {{ ref('fct_demanda_horaria') }}
where dia < (select max(dia) from {{ ref('fct_demanda_horaria') }})
group by dia
having count(distinct hora) <> 24
