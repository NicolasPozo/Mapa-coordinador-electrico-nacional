{{ config(severity = 'warn') }}
-- Aviso: barras que en un día no tienen los 96 intervalos de 15 minutos.
-- Unas pocas por día es normal (barras que entran o salen); el corte de una descarga
-- lo detecta cmg_dia_sin_cortes.
select barra, cast(fecha_hora as date) as dia, count(*) as intervalos
from {{ ref('stg_cmg_real') }}
group by barra, cast(fecha_hora as date)
having count(*) <> 96
