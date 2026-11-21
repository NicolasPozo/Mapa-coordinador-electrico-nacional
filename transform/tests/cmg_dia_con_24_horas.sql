-- Cada día con costo marginal debe tener las 24 horas a nivel de sistema.
select dia, count(distinct hora) as horas
from {{ ref('fct_cmg_horario') }}
group by dia
having count(distinct hora) <> 24
