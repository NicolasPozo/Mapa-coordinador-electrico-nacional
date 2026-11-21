{#- Cada fila debe pertenecer al día del archivo del que salió (dia_consulta).
    Así un mismo día no puede quedar contado en dos archivos. -#}
{% test fila_en_su_dia(model) %}
select dia_consulta, cast(fecha_hora as date) as dia_dato, count(*) as filas
from {{ model }}
where cast(fecha_hora as date) <> dia_consulta
group by all
{% endtest %}
