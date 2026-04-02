from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler


NUMERIC_FEATURES = [
    "semanas_para_clase_inicio",
    "mes_inicio_proceso",
    "dia_semana_inicio",
    "edad_estudiante",
    "edad_padre",
    "edad_madre",
    "hijos_hogar_max",
    "max_nivel_estudio_padres_rank",
    "padres_identificados",
    "padres_con_empleo",
    "log_salario_total_hogar",
    "salario_max_hogar",
    "quintil_hogar_max",
    "padres_con_deuda",
    "log_deuda_total_hogar",
    "deuda_max_hogar",
    "registros_deuda_hogar",
    "peor_calificacion_hogar_rank",
    "ratio_deuda_ingreso_hogar",
]

CATEGORICAL_FEATURES = [
    "periodo",
    "carrera",
    "sexo_estudiante",
    "nivel_estudio_estudiante",
]

COMBO_DELIMITER = " | "

WEEK_SEGMENTS = [
    ("<= 0", None, 0.0),
    ("0 a < 2", 0.0, 2.0),
    ("2 a < 4", 2.0, 4.0),
    ("4 a < 8", 4.0, 8.0),
    ("8 a < 16", 8.0, 16.0),
    (">= 16", 16.0, None),
]


@dataclass
class PropensityResult:
    model_df: pd.DataFrame
    balance_df: pd.DataFrame
    coefficients_df: pd.DataFrame
    outcome_rates_df: pd.DataFrame
    summary_metrics: dict[str, float]
    pipeline: Pipeline


def _unique_non_empty_strings(values) -> list[str]:
    series = pd.Series(list(values), dtype="object").dropna()
    if series.empty:
        return []
    cleaned = series.astype(str).str.strip()
    cleaned = cleaned[cleaned != ""]
    if cleaned.empty:
        return []
    return sorted(cleaned.unique().tolist())


def _prepare_base_dataset(
    modelo_df: pd.DataFrame,
    socioeconomic_df: pd.DataFrame,
    outcome_column: str,
    periodos: list[str] | None = None,
    carreras: list[str] | None = None,
    weeks_range: tuple[float | None, float | None] | None = None,
) -> pd.DataFrame:
    modelo = modelo_df.copy()
    socioeconomic = socioeconomic_df.copy()

    modelo["identificacion"] = modelo["identificacion"].astype(str)
    modelo["periodo"] = modelo["periodo"].astype(str)
    modelo["carrera"] = (
        modelo["carrera"]
        .fillna("SIN_CARRERA")
        .astype(str)
        .str.strip()
        .replace("", "SIN_CARRERA")
    )
    modelo["programa"] = modelo.get("programa", pd.Series(index=modelo.index, dtype="object")).fillna("")
    modelo["fecha_inicio_proceso"] = pd.to_datetime(modelo["fecha_inicio_proceso"], errors="coerce")
    modelo["semanas_para_clase_inicio"] = pd.to_numeric(modelo["semanas_para_clase_inicio"], errors="coerce")
    modelo["mes_inicio_proceso"] = modelo["fecha_inicio_proceso"].dt.month
    modelo["dia_semana_inicio"] = modelo["fecha_inicio_proceso"].dt.dayofweek
    modelo[outcome_column] = pd.to_numeric(modelo[outcome_column], errors="coerce").fillna(0).astype(int)

    if periodos:
        modelo = modelo[modelo["periodo"].isin(periodos)]
    if carreras:
        modelo = modelo[modelo["carrera"].isin(carreras)]

    socioeconomic["identificacion"] = socioeconomic["identificacion"].astype(str)
    socioeconomic["fecha_nacimiento_estudiante"] = pd.to_datetime(
        socioeconomic["fecha_nacimiento_estudiante"],
        errors="coerce",
    )
    socioeconomic["fecha_nacimiento_padre"] = pd.to_datetime(
        socioeconomic["fecha_nacimiento_padre"],
        errors="coerce",
    )
    socioeconomic["fecha_nacimiento_madre"] = pd.to_datetime(
        socioeconomic["fecha_nacimiento_madre"],
        errors="coerce",
    )
    socioeconomic["sexo_estudiante"] = (
        socioeconomic["sexo_estudiante"]
        .fillna("SIN_DATO")
        .astype(str)
        .str.strip()
        .replace("", "SIN_DATO")
    )
    socioeconomic["nivel_estudio_estudiante"] = (
        socioeconomic["nivel_estudio_estudiante"]
        .fillna("SIN_DATO")
        .astype(str)
        .str.strip()
        .replace("", "SIN_DATO")
    )

    dataset = modelo.drop_duplicates(subset=["opportunity_id"]).merge(
        socioeconomic,
        on="identificacion",
        how="left",
    )
    dataset["resultado"] = dataset[outcome_column].fillna(0).astype(int)
    dataset["edad_estudiante"] = _compute_age_at_reference(
        dataset["fecha_nacimiento_estudiante"],
        dataset["fecha_inicio_proceso"],
    )
    dataset["edad_padre"] = _compute_age_at_reference(
        dataset["fecha_nacimiento_padre"],
        dataset["fecha_inicio_proceso"],
    )
    dataset["edad_madre"] = _compute_age_at_reference(
        dataset["fecha_nacimiento_madre"],
        dataset["fecha_inicio_proceso"],
    )

    numeric_fill_columns = [
        "hijos_hogar_max",
        "max_nivel_estudio_padres_rank",
        "padres_identificados",
        "padres_con_empleo",
        "salario_total_hogar",
        "salario_max_hogar",
        "quintil_hogar_max",
        "padres_con_deuda",
        "deuda_total_hogar",
        "deuda_max_hogar",
        "registros_deuda_hogar",
        "peor_calificacion_hogar_rank",
    ]
    for column in numeric_fill_columns:
        if column in dataset.columns:
            dataset[column] = pd.to_numeric(dataset[column], errors="coerce")

    dataset["log_salario_total_hogar"] = np.log1p(dataset["salario_total_hogar"].clip(lower=0))
    dataset["log_deuda_total_hogar"] = np.log1p(dataset["deuda_total_hogar"].clip(lower=0))
    dataset["ratio_deuda_ingreso_hogar"] = np.where(
        dataset["salario_total_hogar"].fillna(0) > 0,
        dataset["deuda_total_hogar"] / dataset["salario_total_hogar"],
        np.nan,
    )

    if weeks_range is not None:
        lower_bound, upper_bound = weeks_range
        if lower_bound is not None:
            dataset = dataset[dataset["semanas_para_clase_inicio"] >= lower_bound]
        if upper_bound is not None:
            dataset = dataset[dataset["semanas_para_clase_inicio"] < upper_bound]

    return dataset


def build_propensity_dataset(
    modelo_df: pd.DataFrame,
    beneficios_df: pd.DataFrame,
    socioeconomic_df: pd.DataFrame,
    beneficio_nombre: str,
    treatment_flag: str,
    outcome_column: str,
    periodos: list[str] | None = None,
    carreras: list[str] | None = None,
    weeks_range: tuple[float | None, float | None] | None = None,
) -> pd.DataFrame:
    if treatment_flag not in {"aplicable", "ofrecido", "otorgado"}:
        raise ValueError(f"Treatment flag no soportado: {treatment_flag}")

    dataset = _prepare_base_dataset(
        modelo_df=modelo_df,
        socioeconomic_df=socioeconomic_df,
        outcome_column=outcome_column,
        periodos=periodos,
        carreras=carreras,
        weeks_range=weeks_range,
    )

    beneficios = beneficios_df.copy()

    beneficios["periodo"] = beneficios["periodo"].astype(str)
    beneficios["beneficio_nombre"] = beneficios["beneficio_nombre"].fillna("").astype(str)
    beneficios["fecha_referencia"] = pd.to_datetime(beneficios["fecha_referencia"], errors="coerce")

    beneficios_filtrados = beneficios[beneficios["beneficio_nombre"] == beneficio_nombre].copy()
    if periodos:
        beneficios_filtrados = beneficios_filtrados[beneficios_filtrados["periodo"].isin(periodos)]
    if carreras:
        beneficios_filtrados = beneficios_filtrados[beneficios_filtrados["carrera"].isin(carreras)]

    flag_col = beneficios_filtrados[treatment_flag].fillna(0).astype(int)
    beneficios_filtrados[treatment_flag] = flag_col

    treatment_frame = (
        beneficios_filtrados.groupby("opportunity_id", as_index=False)
        .agg(
            tratamiento=(treatment_flag, "max"),
            exposiciones_beneficio=("beneficio_evento_id", "count"),
            primera_fecha_beneficio=("fecha_referencia", "min"),
            ultima_fecha_beneficio=("fecha_referencia", "max"),
            beneficio_tipo=("beneficio_tipo", "first"),
        )
    )

    dataset = dataset.merge(
        treatment_frame,
        on="opportunity_id",
        how="left",
    )
    dataset["tratamiento"] = dataset["tratamiento"].fillna(0).astype(int)
    dataset["exposiciones_beneficio"] = dataset["exposiciones_beneficio"].fillna(0).astype(int)
    dataset["beneficio_tipo"] = dataset["beneficio_tipo"].fillna("")
    dataset["primera_fecha_beneficio"] = pd.to_datetime(dataset["primera_fecha_beneficio"], errors="coerce")
    dataset["ultima_fecha_beneficio"] = pd.to_datetime(dataset["ultima_fecha_beneficio"], errors="coerce")

    return dataset


def fit_propensity_model(
    dataset: pd.DataFrame,
    outcome_column: str = "resultado",
    min_probability: float = 0.02,
    max_weight: float = 10.0,
) -> PropensityResult:
    if dataset.empty:
        raise ValueError("No hay datos para entrenar el modelo.")
    if dataset["tratamiento"].nunique() < 2:
        raise ValueError("La cohorte filtrada solo tiene una clase de tratamiento.")

    working = dataset.copy()

    numeric_features = [column for column in NUMERIC_FEATURES if column in working.columns]
    categorical_features = [column for column in CATEGORICAL_FEATURES if column in working.columns]

    X = working[numeric_features + categorical_features]
    y = working["tratamiento"].astype(int)

    preprocessor = ColumnTransformer(
        transformers=[
            (
                "numeric",
                Pipeline(
                    steps=[
                        ("imputer", SimpleImputer(strategy="median")),
                        ("scaler", StandardScaler()),
                    ]
                ),
                numeric_features,
            ),
            (
                "categorical",
                Pipeline(
                    steps=[
                        ("imputer", SimpleImputer(strategy="most_frequent")),
                        (
                            "encoder",
                            OneHotEncoder(handle_unknown="ignore", sparse_output=False),
                        ),
                    ]
                ),
                categorical_features,
            ),
        ]
    )

    pipeline = Pipeline(
        steps=[
            ("preprocessor", preprocessor),
            ("model", LogisticRegression(max_iter=2000)),
        ]
    )
    pipeline.fit(X, y)

    propensity_score = pipeline.predict_proba(X)[:, 1]
    lower_bound = max(0.001, min_probability)
    upper_bound = min(0.999, 1.0 - min_probability)
    clipped_score = np.clip(propensity_score, lower_bound, upper_bound)

    treatment_rate = float(y.mean())
    stabilized_weight = np.where(
        y == 1,
        treatment_rate / clipped_score,
        (1.0 - treatment_rate) / (1.0 - clipped_score),
    )
    stabilized_weight = np.clip(stabilized_weight, 0.0, max_weight)

    working["propensity_score"] = propensity_score
    working["propensity_score_clip"] = clipped_score
    working["peso_ate_estabilizado"] = stabilized_weight
    working["grupo_tratamiento"] = np.where(working["tratamiento"] == 1, "Tratado", "Control")

    balance_df = _build_balance_frame(
        working,
        numeric_features=numeric_features,
        treatment_column="tratamiento",
        weight_column="peso_ate_estabilizado",
    )
    coefficients_df = _extract_coefficients(pipeline)
    outcome_rates_df = _build_outcome_rates_frame(
        working,
        outcome_column=outcome_column,
        treatment_column="tratamiento",
        weight_column="peso_ate_estabilizado",
    )

    raw_treated = _safe_mean(working.loc[working["tratamiento"] == 1, outcome_column])
    raw_control = _safe_mean(working.loc[working["tratamiento"] == 0, outcome_column])
    weighted_treated = _weighted_mean(
        working.loc[working["tratamiento"] == 1, outcome_column],
        working.loc[working["tratamiento"] == 1, "peso_ate_estabilizado"],
    )
    weighted_control = _weighted_mean(
        working.loc[working["tratamiento"] == 0, outcome_column],
        working.loc[working["tratamiento"] == 0, "peso_ate_estabilizado"],
    )

    summary_metrics = {
        "total_oportunidades": float(len(working)),
        "tratadas": float(int((working["tratamiento"] == 1).sum())),
        "controles": float(int((working["tratamiento"] == 0).sum())),
        "tasa_tratamiento": float(working["tratamiento"].mean()),
        "resultado_tratadas_raw": raw_treated,
        "resultado_controles_raw": raw_control,
        "uplift_raw": raw_treated - raw_control,
        "resultado_tratadas_weighted": weighted_treated,
        "resultado_controles_weighted": weighted_control,
        "uplift_weighted": weighted_treated - weighted_control,
    }

    return PropensityResult(
        model_df=working,
        balance_df=balance_df,
        coefficients_df=coefficients_df,
        outcome_rates_df=outcome_rates_df,
        summary_metrics=summary_metrics,
        pipeline=pipeline,
    )


def build_score_band_summary(
    dataset: pd.DataFrame,
    outcome_column: str = "resultado",
    bands: int = 10,
) -> pd.DataFrame:
    if dataset.empty or "propensity_score" not in dataset.columns:
        return pd.DataFrame()

    unique_scores = dataset["propensity_score"].nunique(dropna=True)
    if unique_scores < 2:
        return pd.DataFrame()

    quantiles = min(bands, unique_scores)
    summary = dataset.copy()
    summary["banda_score"] = pd.qcut(
        summary["propensity_score"],
        q=quantiles,
        duplicates="drop",
    )
    grouped = (
        summary.groupby(["banda_score", "grupo_tratamiento"], observed=True)
        .agg(
            oportunidades=("opportunity_id", "count"),
            tasa_resultado=(outcome_column, "mean"),
            score_promedio=("propensity_score", "mean"),
        )
        .reset_index()
    )
    grouped["banda_score"] = grouped["banda_score"].astype(str)
    return grouped


def build_combination_dataset(
    modelo_df: pd.DataFrame,
    beneficios_df: pd.DataFrame,
    socioeconomic_df: pd.DataFrame,
    treatment_flag: str,
    outcome_column: str,
    periodos: list[str] | None = None,
    carreras: list[str] | None = None,
    weeks_range: tuple[float | None, float | None] | None = None,
) -> pd.DataFrame:
    if treatment_flag not in {"aplicable", "ofrecido", "otorgado"}:
        raise ValueError(f"Treatment flag no soportado: {treatment_flag}")

    dataset = _prepare_base_dataset(
        modelo_df=modelo_df,
        socioeconomic_df=socioeconomic_df,
        outcome_column=outcome_column,
        periodos=periodos,
        carreras=carreras,
        weeks_range=weeks_range,
    )

    beneficios = beneficios_df.copy()
    beneficios["periodo"] = beneficios["periodo"].astype(str)
    beneficios["carrera"] = beneficios["carrera"].fillna("").astype(str)
    beneficios["beneficio_nombre"] = beneficios["beneficio_nombre"].fillna("").astype(str)
    beneficios["fecha_referencia"] = pd.to_datetime(beneficios["fecha_referencia"], errors="coerce")
    beneficios[treatment_flag] = beneficios[treatment_flag].fillna(0).astype(int)

    if periodos:
        beneficios = beneficios[beneficios["periodo"].isin(periodos)]
    if carreras:
        beneficios = beneficios[beneficios["carrera"].isin(carreras)]

    beneficios = beneficios[beneficios[treatment_flag] == 1].copy()
    if beneficios.empty:
        dataset["combo_beneficios"] = "SIN_ACCION"
        dataset["num_beneficios_combo"] = 0
        dataset["primera_fecha_beneficio"] = pd.NaT
        dataset["ultima_fecha_beneficio"] = pd.NaT
        return dataset

    combo_frame = (
        beneficios.groupby("opportunity_id")
        .agg(
            combo_beneficios=(
                "beneficio_nombre",
                lambda values: COMBO_DELIMITER.join(_unique_non_empty_strings(values)),
            ),
            num_beneficios_combo=(
                "beneficio_nombre",
                lambda values: len(_unique_non_empty_strings(values)),
            ),
            primera_fecha_beneficio=("fecha_referencia", "min"),
            ultima_fecha_beneficio=("fecha_referencia", "max"),
        )
        .reset_index()
    )
    combo_frame["combo_beneficios"] = combo_frame["combo_beneficios"].replace("", "SIN_ACCION")

    dataset = dataset.merge(combo_frame, on="opportunity_id", how="left")
    dataset["combo_beneficios"] = dataset["combo_beneficios"].fillna("SIN_ACCION")
    dataset["num_beneficios_combo"] = dataset["num_beneficios_combo"].fillna(0).astype(int)
    dataset["primera_fecha_beneficio"] = pd.to_datetime(dataset["primera_fecha_beneficio"], errors="coerce")
    dataset["ultima_fecha_beneficio"] = pd.to_datetime(dataset["ultima_fecha_beneficio"], errors="coerce")
    return dataset


def evaluate_action(
    modelo_df: pd.DataFrame,
    beneficios_df: pd.DataFrame,
    socioeconomic_df: pd.DataFrame,
    beneficio_nombre: str,
    treatment_flag: str,
    outcome_column: str,
    periodos: list[str] | None = None,
    carreras: list[str] | None = None,
    weeks_range: tuple[float | None, float | None] | None = None,
    min_treated: int = 25,
    min_control: int = 25,
    min_probability: float = 0.02,
    max_weight: float = 10.0,
) -> dict[str, float | str | int] | None:
    dataset = build_propensity_dataset(
        modelo_df=modelo_df,
        beneficios_df=beneficios_df,
        socioeconomic_df=socioeconomic_df,
        beneficio_nombre=beneficio_nombre,
        treatment_flag=treatment_flag,
        outcome_column=outcome_column,
        periodos=periodos,
        carreras=carreras,
        weeks_range=weeks_range,
    )
    if dataset.empty:
        return None

    treated = int(dataset["tratamiento"].sum())
    control = int((dataset["tratamiento"] == 0).sum())
    total = int(len(dataset))
    if treated < min_treated or control < min_control:
        return None

    try:
        result = fit_propensity_model(
            dataset=dataset,
            min_probability=min_probability,
            max_weight=max_weight,
        )
    except ValueError:
        return None

    metrics = result.summary_metrics
    return {
        "beneficio_nombre": beneficio_nombre,
        "total_oportunidades": total,
        "tratadas": treated,
        "controles": control,
        "tasa_tratamiento": float(metrics["tasa_tratamiento"]),
        "resultado_tratadas_raw": float(metrics["resultado_tratadas_raw"]),
        "resultado_controles_raw": float(metrics["resultado_controles_raw"]),
        "uplift_raw": float(metrics["uplift_raw"]),
        "resultado_tratadas_weighted": float(metrics["resultado_tratadas_weighted"]),
        "resultado_controles_weighted": float(metrics["resultado_controles_weighted"]),
        "uplift_weighted": float(metrics["uplift_weighted"]),
        "peso_promedio": float(result.model_df["peso_ate_estabilizado"].mean()),
        "score_promedio": float(result.model_df["propensity_score"].mean()),
    }


def rank_actions(
    modelo_df: pd.DataFrame,
    beneficios_df: pd.DataFrame,
    socioeconomic_df: pd.DataFrame,
    treatment_flag: str,
    outcome_column: str,
    periodos: list[str] | None = None,
    carreras: list[str] | None = None,
    weeks_range: tuple[float | None, float | None] | None = None,
    min_treated: int = 25,
    min_control: int = 25,
    min_probability: float = 0.02,
    max_weight: float = 10.0,
) -> pd.DataFrame:
    benefits = sorted(
        beneficios_df["beneficio_nombre"]
        .dropna()
        .astype(str)
        .loc[lambda s: s.str.len() > 0]
        .unique()
    )

    rows: list[dict[str, float | str | int]] = []
    for beneficio_nombre in benefits:
        row = evaluate_action(
            modelo_df=modelo_df,
            beneficios_df=beneficios_df,
            socioeconomic_df=socioeconomic_df,
            beneficio_nombre=beneficio_nombre,
            treatment_flag=treatment_flag,
            outcome_column=outcome_column,
            periodos=periodos,
            carreras=carreras,
            weeks_range=weeks_range,
            min_treated=min_treated,
            min_control=min_control,
            min_probability=min_probability,
            max_weight=max_weight,
        )
        if row is not None:
            rows.append(row)

    if not rows:
        return pd.DataFrame()

    ranking = pd.DataFrame(rows)
    ranking["ranking"] = ranking["uplift_weighted"].rank(method="first", ascending=False).astype(int)
    return ranking.sort_values(
        ["uplift_weighted", "tratadas", "total_oportunidades"],
        ascending=[False, False, False],
    ).reset_index(drop=True)


def evaluate_combination(
    modelo_df: pd.DataFrame,
    beneficios_df: pd.DataFrame,
    socioeconomic_df: pd.DataFrame,
    combo_name: str,
    treatment_flag: str,
    outcome_column: str,
    periodos: list[str] | None = None,
    carreras: list[str] | None = None,
    weeks_range: tuple[float | None, float | None] | None = None,
    min_treated: int = 25,
    min_control: int = 25,
    min_probability: float = 0.02,
    max_weight: float = 10.0,
) -> dict[str, float | str | int] | None:
    dataset = build_combination_dataset(
        modelo_df=modelo_df,
        beneficios_df=beneficios_df,
        socioeconomic_df=socioeconomic_df,
        treatment_flag=treatment_flag,
        outcome_column=outcome_column,
        periodos=periodos,
        carreras=carreras,
        weeks_range=weeks_range,
    )
    if dataset.empty:
        return None

    dataset = dataset.copy()
    dataset["tratamiento"] = (dataset["combo_beneficios"] == combo_name).astype(int)
    treated = int(dataset["tratamiento"].sum())
    control = int((dataset["tratamiento"] == 0).sum())
    total = int(len(dataset))
    if treated < min_treated or control < min_control:
        return None

    try:
        result = fit_propensity_model(
            dataset=dataset,
            min_probability=min_probability,
            max_weight=max_weight,
        )
    except ValueError:
        return None

    metrics = result.summary_metrics
    return {
        "combo_beneficios": combo_name,
        "total_oportunidades": total,
        "tratadas": treated,
        "controles": control,
        "num_beneficios_combo": int(
            dataset.loc[dataset["tratamiento"] == 1, "num_beneficios_combo"].max()
            if treated > 0
            else 0
        ),
        "tasa_tratamiento": float(metrics["tasa_tratamiento"]),
        "resultado_tratadas_raw": float(metrics["resultado_tratadas_raw"]),
        "resultado_controles_raw": float(metrics["resultado_controles_raw"]),
        "uplift_raw": float(metrics["uplift_raw"]),
        "resultado_tratadas_weighted": float(metrics["resultado_tratadas_weighted"]),
        "resultado_controles_weighted": float(metrics["resultado_controles_weighted"]),
        "uplift_weighted": float(metrics["uplift_weighted"]),
        "peso_promedio": float(result.model_df["peso_ate_estabilizado"].mean()),
        "score_promedio": float(result.model_df["propensity_score"].mean()),
    }


def rank_combinations(
    modelo_df: pd.DataFrame,
    beneficios_df: pd.DataFrame,
    socioeconomic_df: pd.DataFrame,
    treatment_flag: str,
    outcome_column: str,
    periodos: list[str] | None = None,
    carreras: list[str] | None = None,
    weeks_range: tuple[float | None, float | None] | None = None,
    min_treated: int = 25,
    min_control: int = 25,
    min_combo_size: int = 2,
    min_probability: float = 0.02,
    max_weight: float = 10.0,
) -> pd.DataFrame:
    base = build_combination_dataset(
        modelo_df=modelo_df,
        beneficios_df=beneficios_df,
        socioeconomic_df=socioeconomic_df,
        treatment_flag=treatment_flag,
        outcome_column=outcome_column,
        periodos=periodos,
        carreras=carreras,
        weeks_range=weeks_range,
    )
    if base.empty:
        return pd.DataFrame()

    base = base.loc[base["num_beneficios_combo"] >= int(min_combo_size)].copy()
    if base.empty:
        return pd.DataFrame()

    combos = (
        base.loc[base["combo_beneficios"] != "SIN_ACCION", "combo_beneficios"]
        .dropna()
        .astype(str)
        .value_counts()
        .index
        .tolist()
    )

    rows: list[dict[str, float | str | int]] = []
    for combo_name in combos:
        row = evaluate_combination(
            modelo_df=modelo_df,
            beneficios_df=beneficios_df,
            socioeconomic_df=socioeconomic_df,
            combo_name=combo_name,
            treatment_flag=treatment_flag,
            outcome_column=outcome_column,
            periodos=periodos,
            carreras=carreras,
            weeks_range=weeks_range,
            min_treated=min_treated,
            min_control=min_control,
            min_probability=min_probability,
            max_weight=max_weight,
        )
        if row is not None:
            rows.append(row)

    if not rows:
        return pd.DataFrame()

    ranking = pd.DataFrame(rows)
    ranking["ranking"] = ranking["uplift_weighted"].rank(method="first", ascending=False).astype(int)
    return ranking.sort_values(
        ["uplift_weighted", "tratadas", "total_oportunidades"],
        ascending=[False, False, False],
    ).reset_index(drop=True)


def build_week_segment_rankings(
    modelo_df: pd.DataFrame,
    beneficios_df: pd.DataFrame,
    socioeconomic_df: pd.DataFrame,
    treatment_flag: str,
    outcome_column: str,
    periodos: list[str] | None = None,
    carreras: list[str] | None = None,
    min_treated: int = 25,
    min_control: int = 25,
    min_probability: float = 0.02,
    max_weight: float = 10.0,
) -> pd.DataFrame:
    frames: list[pd.DataFrame] = []

    for label, lower_bound, upper_bound in WEEK_SEGMENTS:
        ranking = rank_actions(
            modelo_df=modelo_df,
            beneficios_df=beneficios_df,
            socioeconomic_df=socioeconomic_df,
            treatment_flag=treatment_flag,
            outcome_column=outcome_column,
            periodos=periodos,
            carreras=carreras,
            weeks_range=(lower_bound, upper_bound),
            min_treated=min_treated,
            min_control=min_control,
            min_probability=min_probability,
            max_weight=max_weight,
        )
        if ranking.empty:
            continue
        current = ranking.copy()
        current["segmento_semana"] = label
        frames.append(current)

    if not frames:
        return pd.DataFrame()

    return pd.concat(frames, ignore_index=True)


def _build_balance_frame(
    dataset: pd.DataFrame,
    numeric_features: list[str],
    treatment_column: str,
    weight_column: str,
) -> pd.DataFrame:
    rows: list[dict[str, float | str]] = []
    treatment = dataset[treatment_column].astype(int)

    for feature in numeric_features:
        values = pd.to_numeric(dataset[feature], errors="coerce")
        rows.append(
            {
                "variable": feature,
                "media_tratadas": _safe_mean(values[treatment == 1]),
                "media_control": _safe_mean(values[treatment == 0]),
                "smd_sin_ponderar": _standardized_mean_difference(values, treatment),
                "media_tratadas_ponderada": _weighted_mean(
                    values[treatment == 1],
                    dataset.loc[treatment == 1, weight_column],
                ),
                "media_control_ponderada": _weighted_mean(
                    values[treatment == 0],
                    dataset.loc[treatment == 0, weight_column],
                ),
                "smd_ponderado": _standardized_mean_difference(
                    values,
                    treatment,
                    dataset[weight_column],
                ),
            }
        )

    return pd.DataFrame(rows).sort_values("smd_sin_ponderar", key=np.abs, ascending=False)


def _build_outcome_rates_frame(
    dataset: pd.DataFrame,
    outcome_column: str,
    treatment_column: str,
    weight_column: str,
) -> pd.DataFrame:
    rows: list[dict[str, float | str]] = []

    for label, treatment_value in (("Tratado", 1), ("Control", 0)):
        subset = dataset[dataset[treatment_column] == treatment_value]
        rows.append(
            {
                "grupo": label,
                "tasa_sin_ponderar": _safe_mean(subset[outcome_column]),
                "tasa_ponderada": _weighted_mean(subset[outcome_column], subset[weight_column]),
                "oportunidades": float(len(subset)),
            }
        )

    return pd.DataFrame(rows)


def _extract_coefficients(pipeline: Pipeline) -> pd.DataFrame:
    feature_names = pipeline.named_steps["preprocessor"].get_feature_names_out()
    coefficients = pipeline.named_steps["model"].coef_[0]

    coefficient_frame = pd.DataFrame(
        {
            "feature": feature_names,
            "coeficiente": coefficients,
        }
    )
    coefficient_frame["magnitud"] = coefficient_frame["coeficiente"].abs()
    coefficient_frame["feature"] = coefficient_frame["feature"].str.replace("numeric__", "", regex=False)
    coefficient_frame["feature"] = coefficient_frame["feature"].str.replace("categorical__", "", regex=False)

    return coefficient_frame.sort_values("magnitud", ascending=False).reset_index(drop=True)


def _safe_mean(series: pd.Series) -> float:
    cleaned = pd.to_numeric(series, errors="coerce").dropna()
    if cleaned.empty:
        return 0.0
    return float(cleaned.mean())


def _compute_age_at_reference(
    birth_dates: pd.Series,
    reference_dates: pd.Series,
) -> pd.Series:
    birth = pd.to_datetime(birth_dates, errors="coerce")
    reference = pd.to_datetime(reference_dates, errors="coerce")
    age_days = (reference - birth).dt.days
    return age_days / 365.25


def _weighted_mean(values: pd.Series, weights: pd.Series) -> float:
    value_array = pd.to_numeric(values, errors="coerce").to_numpy(dtype=float)
    weight_array = pd.to_numeric(weights, errors="coerce").to_numpy(dtype=float)

    mask = np.isfinite(value_array) & np.isfinite(weight_array) & (weight_array > 0)
    if not np.any(mask):
        return 0.0

    return float(np.average(value_array[mask], weights=weight_array[mask]))


def _weighted_variance(values: pd.Series, weights: pd.Series) -> float:
    value_array = pd.to_numeric(values, errors="coerce").to_numpy(dtype=float)
    weight_array = pd.to_numeric(weights, errors="coerce").to_numpy(dtype=float)

    mask = np.isfinite(value_array) & np.isfinite(weight_array) & (weight_array > 0)
    if not np.any(mask):
        return 0.0

    value_array = value_array[mask]
    weight_array = weight_array[mask]
    average = np.average(value_array, weights=weight_array)
    variance = np.average((value_array - average) ** 2, weights=weight_array)
    return float(variance)


def _standardized_mean_difference(
    values: pd.Series,
    treatment: pd.Series,
    weights: pd.Series | None = None,
) -> float:
    treatment_mask = treatment.astype(int) == 1
    control_mask = treatment.astype(int) == 0

    if weights is None:
        treated_mean = _safe_mean(values[treatment_mask])
        control_mean = _safe_mean(values[control_mask])
        treated_var = float(pd.to_numeric(values[treatment_mask], errors="coerce").var(ddof=0) or 0.0)
        control_var = float(pd.to_numeric(values[control_mask], errors="coerce").var(ddof=0) or 0.0)
    else:
        treated_mean = _weighted_mean(values[treatment_mask], weights[treatment_mask])
        control_mean = _weighted_mean(values[control_mask], weights[control_mask])
        treated_var = _weighted_variance(values[treatment_mask], weights[treatment_mask])
        control_var = _weighted_variance(values[control_mask], weights[control_mask])

    pooled_std = np.sqrt(max((treated_var + control_var) / 2.0, 0.0))
    if pooled_std == 0:
        return 0.0

    return float((treated_mean - control_mean) / pooled_std)
