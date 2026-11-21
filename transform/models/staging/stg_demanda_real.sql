-- Retiros por barra, suministrador y cliente. La API los entrega en kWh con signo
-- negativo; aquí pasan a MWh positivos (demanda). Hay registros positivos (inyecciones
-- o correcciones) que quedan como demanda negativa.
--
-- No se quitan filas repetidas: un mismo cliente puede tener varios medidores en la
-- misma barra y la API no trae el id del medidor, así que dos filas iguales pueden ser
-- dos medidores con la misma lectura. El doble conteo se evita a nivel de archivo
-- (un Parquet por día; ver test fila_en_su_dia).
select
    barra,
    cast(fecha_hora as timestamp)     as fecha_hora,
    suministrador,
    retiro                            as cliente,
    tipo,
    medida_kwh,
    -medida_kwh / 1000.0              as demanda_mwh,
    cast(_dia_consulta as date)       as dia_consulta
from {{ source('sip', 'demanda_real') }}
