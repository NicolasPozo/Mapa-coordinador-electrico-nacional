-- Cada barra pronosticada debe tener las 24 horas de cada día.
select barra_pronostico, dia, count(*) as horas
from {{ ref('fct_pronostico_horario') }}
group by barra_pronostico, dia
having count(*) <> 24
