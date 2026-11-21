-- Cada día con demanda real debe tener las 24 horas a nivel de sistema.
-- Si falla, la descarga de ese día quedó incompleta: python -m nodos descargar demanda-real --desde <dia> --hasta <dia> --refrescar
select dia, count(distinct hora) as horas
from {{ ref('fct_demanda_horaria') }}
group by dia
having count(distinct hora) <> 24
