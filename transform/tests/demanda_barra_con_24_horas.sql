{{ config(severity = 'warn') }}
-- Aviso: barras que en un día no reportan las 24 horas (puede ser legítimo: retiros
-- que empiezan o terminan ese día). Útil para detectar huecos.
select barra, dia, count(*) as horas
from {{ ref('fct_demanda_horaria') }}
group by barra, dia
having count(*) <> 24
