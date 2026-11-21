{#- Usa el nombre de esquema tal cual (limpio, modelo) en vez de main_limpio. -#}
{% macro generate_schema_name(custom_schema_name, node) -%}
    {{ custom_schema_name if custom_schema_name else target.schema }}
{%- endmacro %}
