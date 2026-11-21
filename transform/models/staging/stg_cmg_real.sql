-- Costo marginal real cada 15 minutos por barra.
-- id_info es el id de barra de Infotécnica.
with origen as (
    select * from {{ source('sip', 'cmg_real') }}
),

tipado as (
    select
        barra_transf                                                      as barra,
        cast(id_info as integer)                                          as id_barra_info,
        barra_info,
        cast(fecha as timestamp)
            + to_hours(cast(hra as integer))
            + to_minutes(cast("min" as integer))                          as fecha_minuto,
        cmg_usd_mwh_                                                      as cmg_usd_mwh,
        cmg_clp_kwh_                                                      as cmg_clp_kwh,
        version,
        cast(_dia_consulta as date)                                       as dia_consulta
    from origen
)

select
    *,
    date_trunc('hour', fecha_minuto) as fecha_hora
from tipado
qualify row_number() over (partition by barra, fecha_minuto order by dia_consulta desc) = 1
