# Documentacion Modelo Beneficios y Propensity

## Objetivo

Este documento resume:

- que hace cada tabla del modelo
- que significa cada columna principal
- como se conectan las tablas
- como se determina si un beneficio fue:
  - `aplicable`
  - `ofrecido`
  - `otorgado`

## Tablas de configuracion de beneficios

### `salesforce.beneficio_catalogo`

Contiene el catalogo base de beneficios.

Columnas:

- `beneficio_id`: identificador unico del beneficio.
- `nombre_beneficio`: nombre de negocio del beneficio.

Ejemplos:

- `Matricula Sin Costo`
- `Beca Preaprobada 35%`
- `Exoneracion Examen`

### `salesforce.beneficio_vigencia`

Define en que fechas estuvo vigente cada beneficio del catalogo.

Columnas:

- `beneficio_vigencia_id`: identificador unico de la vigencia.
- `beneficio_id`: referencia a `beneficio_catalogo`.
- `fecha_inicio`: fecha desde la que aplica la vigencia.
- `fecha_fin`: fecha hasta la que aplica la vigencia.

Idea:

- un mismo beneficio puede tener varias vigencias.

### `salesforce.estado`

Catalogo de estados del proceso comercial/admisiones.

Columnas:

- `estado_id`: identificador unico del estado.
- `estado`: nombre del estado.
- `area`: agrupacion de negocio del estado.
- `tipo`: clasificacion de negocio del estado.

Ejemplos:

- `Afluente`
- `Inscrito Pregrado`
- `Test Pregrado`
- `Matricula Pregrado`
- `Documentado`
- `Closed Won`
- `Closed Lost`

### `salesforce.beneficio_estado`

Tabla puente entre vigencias y estados.

Columnas:

- `beneficio_vigencia_id`: referencia a una vigencia.
- `estado_id`: referencia a un estado.

Uso:

- define en que estados puede aplicar cada beneficio.

### `salesforce.beneficio_carrera_regla`

Reglas por carrera para una vigencia de beneficio.

Columnas:

- `beneficio_vigencia_id`: referencia a una vigencia.
- `carrera`: nombre de carrera ya normalizado.
- `tipo_regla`: puede ser `INCLUYENTE` o `EXCLUYENTE`.

Interpretacion:

- si una vigencia no tiene filas aqui, aplica a todas las carreras.
- si tiene reglas `INCLUYENTE`, solo aplica a las carreras listadas.
- si tiene reglas `EXCLUYENTE`, aplica a todas menos a las listadas.
- si una vigencia mezcla ambas, la carrera debe cumplir:
  - estar incluida
  - y no estar excluida

## Tablas de beca priorizada

### `salesforce.beca_priorizada_lote`

Representa el rango de fechas de una carga de becas priorizadas.

Columnas:

- `lote_id`: identificador del lote.
- `fecha_inicio_oferta`: inicio de la ventana del lote.
- `fecha_fin_oferta`: fin de la ventana del lote.

### `salesforce.beca_priorizada_detalle`

Contiene las personas a las que se ofrecio una beca priorizada.

Columnas:

- `detalle_id`: identificador del detalle.
- `lote_id`: referencia al lote.
- `identificacion`: identificacion limpia de la persona.
- `etapa_oferta`: etapa reportada en el archivo original.
- `porcentaje_beca`: porcentaje ofrecido.
- `periodo`: periodo academico.
- `carrera`: carrera normalizada.

Uso:

- esta tabla no describe una campaña general
- describe ofertas persona a persona

## Tablas analiticas principales

### `salesforce.ps_oportunidad_evento`

Es la tabla base del historico por oportunidad.

Grano:

- `1 fila = 1 evento/hito/estado de una Opportunity`

Columnas:

- `opportunity_id`: identificador de la oportunidad en Salesforce.
- `identificacion`: identificacion limpia de la persona.
- `periodo`: periodo de la oportunidad.
- `programa`: valor original del programa.
- `carrera`: carrera normalizada.
- `fecha_hito`: fecha y hora del hito.
- `estado`: estado del historico.
- `area`: agrupacion del estado desde la tabla `estado`.
- `tipo_estado`: tipo del estado desde la tabla `estado`.
- `semanas_para_clase`: semanas restantes a la fecha de inicio de clase al momento del evento.
- `orden_hito`: secuencia del evento dentro de la oportunidad.
- `es_test_pregrado`: indicador si el evento es `Test Pregrado`.
- `es_documentado`: indicador si el evento es `Documentado`.
- `es_closed_won`: indicador si el evento es `Closed Won`.
- `es_closed_lost`: indicador si el evento es `Closed Lost`.
- `es_estado_final`: marca el ultimo estado real de la oportunidad.

Regla importante de estado final:

- el estado final no se decide por orden alfabetico
- se desempata por jerarquia de negocio
- prioridad usada:
  - `Closed Won`
  - `Closed Lost`
  - `Documentado`
  - `Matricula Pregrado`
  - `Test Pregrado`
  - `Inscrito Pregrado`
  - `Afluente`

Esto evita que `Documentado` gane sobre `Closed Won` cuando comparten la misma fecha.

### `salesforce.ps_oportunidad_beneficio`

Tabla base detallada de exposiciones a beneficios por oportunidad.

Grano:

- para beneficios generales:
  - `1 fila = 1 exposicion aplicable de un beneficio para una Opportunity en una fecha_referencia`
- excepcion:
  - `BECA_PRIORIZADA` queda como `1 fila = 1 detalle del lote asociado a una Opportunity`

Columnas:

- `beneficio_evento_id`: identificador tecnico de la fila.
- `opportunity_id`: oportunidad asociada.
- `identificacion`: persona asociada.
- `periodo`: periodo academico.
- `carrera`: carrera normalizada.
- `fecha_referencia`: fecha del evento del historico que ancla el beneficio.
- `semanas_para_clase`: semanas para clase al momento de ese evento.
- `beneficio_tipo`: familia del beneficio.
- `beneficio_nombre`: nombre del beneficio.
- `porcentaje_ofrecido`: porcentaje ofrecido si aplica, principalmente en beca priorizada.
- `porcentaje_otorgado`: porcentaje real detectado desde la fuente externa o resultado calculado.
- `aplicable`: indica si el beneficio aplicaba segun reglas.
- `ofrecido`: indica si hubo oferta nominal del beneficio.
- `otorgado`: indica si se detecto que efectivamente fue concedido.

Tipos de beneficio actualmente usados:

- `BECA`
- `MATRICULA`
- `EXONERACION_EXAMEN`
- `BECA_PRIORIZADA`

Regla de detalle:

- la tabla conserva todos los registros aplicables en la base detallada
- por eso una misma `Opportunity` puede tener varias filas del mismo `beneficio_nombre`
- esto pasa cuando la oportunidad entra varias veces a una misma logica de beneficio en fechas o vigencias distintas
- la unica excepcion practica es `BECA_PRIORIZADA`, donde se conserva una fila por detalle del lote ya asociado a una oportunidad

### `salesforce.ps_oportunidad_modelo`

Tabla final resumida por oportunidad, lista para modelos y analisis.

Grano:

- `1 fila = 1 Opportunity`

Columnas:

- `opportunity_id`: identificador de la oportunidad.
- `identificacion`: identificacion limpia.
- `id_banner`: id institucional si se logro mapear.
- `periodo`: periodo academico.
- `programa`: programa original.
- `carrera`: carrera normalizada.
- `fecha_inicio_proceso`: primer evento de la oportunidad.
- `fecha_primer_test`: primera fecha donde aparece `Test Pregrado`.
- `fecha_primer_documentado`: primera fecha donde aparece `Documentado`.
- `fecha_primer_closed_won`: primera fecha donde aparece `Closed Won`.
- `fecha_primer_closed_lost`: primera fecha donde aparece `Closed Lost`.
- `estado_final`: ultimo estado real de la oportunidad.
- `fecha_estado_final`: fecha del ultimo estado real.
- `semanas_para_clase_inicio`: semanas para clase al inicio del proceso.
- `flag_beca_priorizada`: indica si hubo beca priorizada ofrecida.
- `porcentaje_beca_priorizada`: porcentaje ofrecido de beca priorizada.
- `flag_beca_otorgada`: indica si hubo una beca efectivamente otorgada.
- `porcentaje_beca_otorgada`: porcentaje real de la beca otorgada.
- `flag_matricula_sin_costo`: indicador de matricula sin costo otorgada.
- `flag_matricula_30`: indicador de matricula 30% otorgada.
- `porcentaje_descuento_matricula`: porcentaje real de descuento de matricula otorgado.
- `flag_exoneracion_examen`: indicador de exoneracion de examen otorgada.
- `target_closed_won`: target final de conversion.
- `target_documentado`: target intermedio de documentacion.
- `target_closed_lost`: target final de perdida.

## Fuentes externas usadas para otorgamiento

### `dbo.GestionAdmisionesUdla`

Se usa para becas reales.

Columnas usadas:

- `cedula`
- `semestre`
- `porcentajeBeca`
- `Beca`

### `dbo.Contacto_Persona`

Se usa para mapear identificacion a `IdBanner`.

Columnas usadas:

- `CedulaPasaporte`
- `IdBanner`

### `Reportes.dbo.BX_FacturacionEstudiantes`

Se usa para descuentos de matricula reales.

Columnas usadas:

- `IdBanner`
- `Periodo`
- `BaseFEE`
- `DiscountFEE`
- `TotalFEE`

## Como se determina un beneficio

### 1. Logica de `aplicable`

Un beneficio general entra como `aplicable = 1` cuando se cumplen al mismo tiempo:

- la fecha del evento cae dentro de una vigencia del beneficio
- el estado del evento esta mapeado para esa vigencia
- la carrera cumple la regla de carrera

En otras palabras:

- `fecha + estado + carrera`

Si no cumple eso, la fila del beneficio no deberia existir o queda fuera del universo aplicable.

### 2. Logica de `ofrecido`

Solo aplica de forma explicita para `BECA_PRIORIZADA`.

Se considera `ofrecido = 1` cuando:

- la persona coincide exactamente por `identificacion`
- coincide exactamente por `periodo`
- existe un evento de esa oportunidad dentro de la ventana del lote de beca priorizada

La logica actual para `Beca Priorizada` es abierta y persona-centrica:

- no bloquea por etapa
- no bloquea por carrera
- si hay varios eventos posibles, se escoge el mas cercano al inicio del lote

### 3. Logica de `otorgado`

#### `BECA`

Fuente:

- `GestionAdmisionesUdla`

Paso clave:

- el porcentaje se normaliza
- si viene como `0.35`, se convierte a `35`
- si viene como `35`, se conserva como `35`

Reglas:

- `Beca Preaprobada 15%` si el porcentaje real esta entre `14.5` y `15.5`
- `Beca Preaprobada 35%` si el porcentaje real esta entre `34.5` y `35.5`
- `Beca Alta 40% - 50 %` si el porcentaje real esta entre `40` y `50`

Interpretacion:

- no se usa un estado para decir que la beca fue otorgada
- el estado solo sirve para saber si la beca era aplicable
- el otorgamiento real se confirma por la fuente de admisiones

#### `MATRICULA`

Fuente:

- `BX_FacturacionEstudiantes`

Calculo:

- `% descuento = DiscountFEE / BaseFEE * 100`
- caso especial:
  - si `TotalFEE <= 0.01`, se interpreta como `100%`

Reglas:

- `Matricula Sin Costo` si el descuento real es practicamente `100%`
- `Matricula 30%` si el descuento real esta entre `29.5` y `30.5`

#### `EXONERACION_EXAMEN`

Fuente:

- historico de `ps_oportunidad_evento`

Regla:

- el evento que prueba que la persona dio el examen es `Test Pregrado`

Interpretacion:

- la exoneracion solo puede marcarse `otorgado = 1` cuando existe `Test Pregrado`
- y el registro aplicable corresponde a la fecha donde ocurre el `Test Pregrado`
- la tabla base puede conservar otras exposiciones aplicables del mismo beneficio en otras fechas, pero esas no quedan como otorgadas

#### `BECA_PRIORIZADA`

Fuente:

- `beca_priorizada_detalle`
- `beca_priorizada_lote`
- comparacion con beca real de `GestionAdmisionesUdla`

Reglas:

- `ofrecido = 1` cuando la persona fue encontrada por identificacion, periodo y fecha del lote
- la asociacion se hace por persona exacta, periodo exacto y evento dentro de la ventana del lote
- si una persona tiene varios eventos candidatos dentro del lote, se escoge el mas cercano al inicio del lote
- `otorgado = 1` cuando el porcentaje real de beca coincide con el porcentaje ofrecido

Comparacion usada:

- `ABS(porcentaje_real - porcentaje_ofrecido) <= 0.5`

## Como se conectan las tablas

### Flujo principal

1. `ps_oportunidad_evento`

- contiene el historico de cada oportunidad

2. `ps_oportunidad_beneficio`

- toma eventos del historico
- cruza reglas de beneficio
- conserva todas las exposiciones aplicables de la base detallada
- cruza fuentes externas para saber si cada exposicion fue otorgada

3. `ps_oportunidad_modelo`

- resume el historico y los beneficios en una sola fila por oportunidad
- sirve para propensity score, radar y analisis general

### Llaves practicas

- `opportunity_id`
  - conecta `ps_oportunidad_evento`, `ps_oportunidad_beneficio` y `ps_oportunidad_modelo`

- `identificacion`
  - conecta persona con beca priorizada y con admisiones

- `periodo`
  - ayuda a acotar la relacion en beneficios y fuentes externas

## Reglas operativas importantes

- `ps_oportunidad_evento` es la base historica del proceso.
- `ps_oportunidad_beneficio` no es una tabla consolidada final; es la base detallada de exposiciones a beneficios.
- `ps_oportunidad_modelo` es la capa resumida para modelamiento.
- las carreras deben estar normalizadas sin prefijo `UDLA...-`.
- `Beca Priorizada` no necesita vivir en `beneficio_catalogo` porque su logica es nominal y persona-centrica.

## Query util de auditoria

### Ver beneficios por oportunidad

```sql
SELECT
    opportunity_id,
    identificacion,
    beneficio_tipo,
    beneficio_nombre,
    aplicable,
    ofrecido,
    otorgado,
    porcentaje_ofrecido,
    porcentaje_otorgado
FROM [BDD_Proyectos].[salesforce].[ps_oportunidad_beneficio]
ORDER BY
    identificacion,
    opportunity_id,
    beneficio_tipo,
    beneficio_nombre;
```

### Ver resumen final por oportunidad

```sql
SELECT
    opportunity_id,
    identificacion,
    carrera,
    estado_final,
    flag_beca_priorizada,
    porcentaje_beca_priorizada,
    flag_beca_otorgada,
    porcentaje_beca_otorgada,
    flag_matricula_sin_costo,
    flag_matricula_30,
    porcentaje_descuento_matricula,
    flag_exoneracion_examen,
    target_closed_won,
    target_closed_lost
FROM [BDD_Proyectos].[salesforce].[ps_oportunidad_modelo];
```
