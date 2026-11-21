{#- Falla si la combinación de columnas se repite (clave compuesta, p. ej. barra + hora). -#}
{% test unico_combinado(model, columnas) %}
select {{ columnas | join(', ') }}, count(*) as repeticiones
from {{ model }}
group by {{ columnas | join(', ') }}
having count(*) > 1
{% endtest %}
