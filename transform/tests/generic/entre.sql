{#- Falla si hay valores fuera de [minimo, maximo] (los nulos no cuentan). -#}
{% test entre(model, column_name, minimo=none, maximo=none) %}
select {{ column_name }}
from {{ model }}
where {{ column_name }} is not null
  and (
    {% if minimo is not none %} {{ column_name }} < {{ minimo }} {% else %} false {% endif %}
    or
    {% if maximo is not none %} {{ column_name }} > {{ maximo }} {% else %} false {% endif %}
  )
{% endtest %}
