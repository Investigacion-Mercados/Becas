from __future__ import annotations

import pandas as pd
from sqlalchemy.engine import Engine

from .sql_config import PROPENSITY_TABLES
from .sql_connection import read_sql_df, read_table_df


BENEFICIOS_RESUMEN_QUERY = """
SELECT
    beneficio_nombre,
    COUNT(DISTINCT CASE WHEN aplicable = 1 THEN identificacion END) AS personasAplicables,
    COUNT(DISTINCT CASE WHEN otorgado = 1 THEN identificacion END) AS personasOtorgadas
FROM [salesforce].[ps_oportunidad_beneficio]
GROUP BY beneficio_nombre
ORDER BY beneficio_nombre;
"""


BENEFICIO_VIGENCIAS_QUERY = """
SELECT
    CAST(bc.nombre_beneficio AS nvarchar(150)) AS beneficio_nombre,
    CAST(bv.fecha_inicio AS date) AS fecha_inicio,
    CAST(bv.fecha_fin AS date) AS fecha_fin
FROM [salesforce].[beneficio_vigencia] bv
INNER JOIN [salesforce].[beneficio_catalogo] bc
    ON bc.beneficio_id = bv.beneficio_id
ORDER BY
    bc.nombre_beneficio,
    bv.fecha_inicio,
    bv.fecha_fin;
"""


PROPENSITY_SOCIOECONOMIC_QUERY = """
WITH cohorte AS (
    SELECT DISTINCT
        CAST(identificacion AS varchar(40)) AS identificacion
    FROM [salesforce].[ps_oportunidad_modelo]
),
familiares AS (
    SELECT
        c.identificacion,
        NULLIF(LTRIM(RTRIM(uf.CED_PADRE)), '') AS ced_padre,
        NULLIF(LTRIM(RTRIM(uf.CED_MADRE)), '') AS ced_madre
    FROM cohorte c
    LEFT JOIN [salesforce].[Universo_Familiares] uf
        ON uf.IDENTIFICACION = c.identificacion
),
estudiante AS (
    SELECT
        c.identificacion,
        UPPER(LTRIM(RTRIM(ip.SEXO))) AS sexo_estudiante,
        ip.FECHA_NACIMIENTO AS fecha_nacimiento_estudiante,
        UPPER(LTRIM(RTRIM(ip.NIVEL_ESTUDIO))) AS nivel_estudio_estudiante
    FROM cohorte c
    LEFT JOIN [salesforce].[Informacion_Personal] ip
        ON ip.IDENTIFICACION = c.identificacion
),
padres_info AS (
    SELECT
        f.identificacion,
        ipp.FECHA_NACIMIENTO AS fecha_nacimiento_padre,
        ipm.FECHA_NACIMIENTO AS fecha_nacimiento_madre,
        TRY_CONVERT(int, ipp.HIJOS) AS hijos_padre,
        TRY_CONVERT(int, ipm.HIJOS) AS hijos_madre,
        CASE
            WHEN UPPER(LTRIM(RTRIM(ipp.NIVEL_ESTUDIO))) IN ('NINGUNA') THEN 0
            WHEN UPPER(LTRIM(RTRIM(ipp.NIVEL_ESTUDIO))) IN ('INICIAL', 'ELEMENTAL') THEN 1
            WHEN UPPER(LTRIM(RTRIM(ipp.NIVEL_ESTUDIO))) IN ('PRIMARIA', 'BASICA') THEN 2
            WHEN UPPER(LTRIM(RTRIM(ipp.NIVEL_ESTUDIO))) IN ('SECUNDARIA', 'BACHILLERATO') THEN 3
            WHEN UPPER(LTRIM(RTRIM(ipp.NIVEL_ESTUDIO))) IN (
                'SUPERIOR', 'TERCER NIVEL', 'TECNICO', 'TECNOLOGICO', 'TECNOLOGIA',
                'TECNICO SUPERIOR'
            ) THEN 4
            WHEN UPPER(LTRIM(RTRIM(ipp.NIVEL_ESTUDIO))) IN (
                'POSGRADO', 'MAESTRIA', 'DOCTORADO', 'PHD', 'ESPECIALIDAD'
            ) THEN 5
            ELSE NULL
        END AS nivel_estudio_padre_rank,
        CASE
            WHEN UPPER(LTRIM(RTRIM(ipm.NIVEL_ESTUDIO))) IN ('NINGUNA') THEN 0
            WHEN UPPER(LTRIM(RTRIM(ipm.NIVEL_ESTUDIO))) IN ('INICIAL', 'ELEMENTAL') THEN 1
            WHEN UPPER(LTRIM(RTRIM(ipm.NIVEL_ESTUDIO))) IN ('PRIMARIA', 'BASICA') THEN 2
            WHEN UPPER(LTRIM(RTRIM(ipm.NIVEL_ESTUDIO))) IN ('SECUNDARIA', 'BACHILLERATO') THEN 3
            WHEN UPPER(LTRIM(RTRIM(ipm.NIVEL_ESTUDIO))) IN (
                'SUPERIOR', 'TERCER NIVEL', 'TECNICO', 'TECNOLOGICO', 'TECNOLOGIA',
                'TECNICO SUPERIOR'
            ) THEN 4
            WHEN UPPER(LTRIM(RTRIM(ipm.NIVEL_ESTUDIO))) IN (
                'POSGRADO', 'MAESTRIA', 'DOCTORADO', 'PHD', 'ESPECIALIDAD'
            ) THEN 5
            ELSE NULL
        END AS nivel_estudio_madre_rank
    FROM familiares f
    LEFT JOIN [salesforce].[Informacion_Personal] ipp
        ON ipp.IDENTIFICACION = f.ced_padre
    LEFT JOIN [salesforce].[Informacion_Personal] ipm
        ON ipm.IDENTIFICACION = f.ced_madre
),
empleo_latest AS (
    SELECT
        e.IDENTIFICACION,
        CAST(e.SALARIO AS float) AS salario,
        TRY_CONVERT(int, e.QUINTIL) AS quintil,
        ROW_NUMBER() OVER (
            PARTITION BY e.IDENTIFICACION
            ORDER BY e.ANIO DESC, e.MES DESC, e.FECHA_INGRESO DESC, e.Id DESC
        ) AS rn
    FROM [salesforce].[Empleo] e
),
empleo_hogar AS (
    SELECT
        f.identificacion,
        CASE WHEN ep.IDENTIFICACION IS NOT NULL THEN 1 ELSE 0 END
        + CASE WHEN em.IDENTIFICACION IS NOT NULL THEN 1 ELSE 0 END AS padres_con_empleo,
        COALESCE(ep.salario, 0.0) + COALESCE(em.salario, 0.0) AS salario_total_hogar,
        CASE
            WHEN COALESCE(ep.salario, 0.0) >= COALESCE(em.salario, 0.0) THEN COALESCE(ep.salario, 0.0)
            ELSE COALESCE(em.salario, 0.0)
        END AS salario_max_hogar,
        CASE
            WHEN ep.quintil IS NULL THEN em.quintil
            WHEN em.quintil IS NULL THEN ep.quintil
            WHEN ep.quintil >= em.quintil THEN ep.quintil
            ELSE em.quintil
        END AS quintil_hogar_max
    FROM familiares f
    LEFT JOIN empleo_latest ep
        ON ep.IDENTIFICACION = f.ced_padre
       AND ep.rn = 1
    LEFT JOIN empleo_latest em
        ON em.IDENTIFICACION = f.ced_madre
       AND em.rn = 1
),
deuda_snapshot AS (
    SELECT
        d.*,
        DENSE_RANK() OVER (
            PARTITION BY d.IDENTIFICACION
            ORDER BY d.ANIO DESC, d.MES DESC
        ) AS snapshot_rank
    FROM [salesforce].[Deuda] d
),
deuda_parent_agg AS (
    SELECT
        d.IDENTIFICACION,
        SUM(CAST(d.VALOR AS float)) AS deuda_total_parent,
        MAX(CAST(d.VALOR AS float)) AS deuda_max_parent,
        COUNT(*) AS registros_deuda_parent,
        MAX(
            CASE
                WHEN d.COD_CALIFICACION IN ('A1') THEN 1
                WHEN d.COD_CALIFICACION IN ('A2') THEN 2
                WHEN d.COD_CALIFICACION IN ('A3') THEN 3
                WHEN d.COD_CALIFICACION IN ('B1') THEN 4
                WHEN d.COD_CALIFICACION IN ('B2') THEN 5
                WHEN d.COD_CALIFICACION IN ('C1') THEN 6
                WHEN d.COD_CALIFICACION IN ('C2') THEN 7
                WHEN d.COD_CALIFICACION IN ('D') THEN 8
                WHEN d.COD_CALIFICACION IN ('E') THEN 9
                ELSE 0
            END
        ) AS peor_calificacion_parent_rank
    FROM deuda_snapshot d
    WHERE d.snapshot_rank = 1
    GROUP BY d.IDENTIFICACION
),
deuda_hogar AS (
    SELECT
        f.identificacion,
        CASE WHEN dp.IDENTIFICACION IS NOT NULL THEN 1 ELSE 0 END
        + CASE WHEN dm.IDENTIFICACION IS NOT NULL THEN 1 ELSE 0 END AS padres_con_deuda,
        COALESCE(dp.deuda_total_parent, 0.0) + COALESCE(dm.deuda_total_parent, 0.0) AS deuda_total_hogar,
        CASE
            WHEN COALESCE(dp.deuda_max_parent, 0.0) >= COALESCE(dm.deuda_max_parent, 0.0) THEN COALESCE(dp.deuda_max_parent, 0.0)
            ELSE COALESCE(dm.deuda_max_parent, 0.0)
        END AS deuda_max_hogar,
        COALESCE(dp.registros_deuda_parent, 0) + COALESCE(dm.registros_deuda_parent, 0) AS registros_deuda_hogar,
        CASE
            WHEN dp.peor_calificacion_parent_rank IS NULL THEN COALESCE(dm.peor_calificacion_parent_rank, 0)
            WHEN dm.peor_calificacion_parent_rank IS NULL THEN COALESCE(dp.peor_calificacion_parent_rank, 0)
            WHEN dp.peor_calificacion_parent_rank >= dm.peor_calificacion_parent_rank THEN dp.peor_calificacion_parent_rank
            ELSE dm.peor_calificacion_parent_rank
        END AS peor_calificacion_hogar_rank
    FROM familiares f
    LEFT JOIN deuda_parent_agg dp
        ON dp.IDENTIFICACION = f.ced_padre
    LEFT JOIN deuda_parent_agg dm
        ON dm.IDENTIFICACION = f.ced_madre
)
SELECT
    c.identificacion,
    e.sexo_estudiante,
    e.fecha_nacimiento_estudiante,
    e.nivel_estudio_estudiante,
    p.fecha_nacimiento_padre,
    p.fecha_nacimiento_madre,
    CASE
        WHEN p.hijos_padre IS NULL THEN p.hijos_madre
        WHEN p.hijos_madre IS NULL THEN p.hijos_padre
        WHEN p.hijos_padre >= p.hijos_madre THEN p.hijos_padre
        ELSE p.hijos_madre
    END AS hijos_hogar_max,
    CASE
        WHEN p.nivel_estudio_padre_rank IS NULL THEN p.nivel_estudio_madre_rank
        WHEN p.nivel_estudio_madre_rank IS NULL THEN p.nivel_estudio_padre_rank
        WHEN p.nivel_estudio_padre_rank >= p.nivel_estudio_madre_rank THEN p.nivel_estudio_padre_rank
        ELSE p.nivel_estudio_madre_rank
    END AS max_nivel_estudio_padres_rank,
    CASE WHEN f.ced_padre IS NOT NULL THEN 1 ELSE 0 END
    + CASE WHEN f.ced_madre IS NOT NULL THEN 1 ELSE 0 END AS padres_identificados,
    eh.padres_con_empleo,
    eh.salario_total_hogar,
    eh.salario_max_hogar,
    eh.quintil_hogar_max,
    dh.padres_con_deuda,
    dh.deuda_total_hogar,
    dh.deuda_max_hogar,
    dh.registros_deuda_hogar,
    dh.peor_calificacion_hogar_rank
FROM cohorte c
LEFT JOIN familiares f
    ON f.identificacion = c.identificacion
LEFT JOIN estudiante e
    ON e.identificacion = c.identificacion
LEFT JOIN padres_info p
    ON p.identificacion = c.identificacion
LEFT JOIN empleo_hogar eh
    ON eh.identificacion = c.identificacion
LEFT JOIN deuda_hogar dh
    ON dh.identificacion = c.identificacion
ORDER BY c.identificacion;
"""


def get_ps_oportunidad_evento(
    engine: Engine | None = None,
    limit: int | None = None,
) -> pd.DataFrame:
    return read_table_df(
        PROPENSITY_TABLES["evento"],
        order_by="opportunity_id, orden_hito",
        limit=limit,
        engine=engine,
    )


def get_ps_oportunidad_beneficio(
    engine: Engine | None = None,
    limit: int | None = None,
) -> pd.DataFrame:
    return read_table_df(
        PROPENSITY_TABLES["beneficio"],
        order_by="identificacion, opportunity_id, fecha_referencia, beneficio_nombre",
        limit=limit,
        engine=engine,
    )


def get_ps_oportunidad_modelo(
    engine: Engine | None = None,
    limit: int | None = None,
) -> pd.DataFrame:
    return read_table_df(
        PROPENSITY_TABLES["modelo"],
        order_by="identificacion, opportunity_id",
        limit=limit,
        engine=engine,
    )


def get_beneficios_resumen(engine: Engine | None = None) -> pd.DataFrame:
    return read_sql_df(BENEFICIOS_RESUMEN_QUERY, engine=engine)


def get_beneficio_vigencias(engine: Engine | None = None) -> pd.DataFrame:
    return read_sql_df(BENEFICIO_VIGENCIAS_QUERY, engine=engine)


def get_propensity_socioeconomic_features(engine: Engine | None = None) -> pd.DataFrame:
    return read_sql_df(PROPENSITY_SOCIOECONOMIC_QUERY, engine=engine)
