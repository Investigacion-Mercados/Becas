from __future__ import annotations

import altair as alt
import numpy as np
import pandas as pd
import streamlit as st
from sklearn.neighbors import KernelDensity

from analytics import (
    WEEK_SEGMENTS,
    build_combination_dataset,
    build_propensity_dataset,
    build_score_band_summary,
    build_week_segment_rankings,
    fit_propensity_model,
    rank_actions,
    rank_combinations,
)
from db.propensity_repository import (
    get_beneficio_vigencias,
    get_propensity_socioeconomic_features,
)
from db.sql_config import SQL_DATABASE, SQL_SCHEMA, SQL_SERVER
from db.sql_streamlit import read_table_cached


TABLES = {
    "modelo": "ps_oportunidad_modelo",
    "beneficio": "ps_oportunidad_beneficio",
}

OUTCOME_OPTIONS = {
    "Closed Won": "target_closed_won",
    "Documentado": "target_documentado",
    "Closed Lost": "target_closed_lost",
}

TREATMENT_FLAG_HELP = {
    "aplicable": "Expone a la oportunidad a la ventana o regla del beneficio.",
    "ofrecido": "Usa la marca de oferta explicita. Es mas util para Beca Priorizada.",
    "otorgado": "Usa la evidencia final de asignacion real del beneficio.",
}


st.set_page_config(
    page_title="Propensity Score Beneficios",
    page_icon="PS",
    layout="wide",
)


def inject_styles() -> None:
    st.markdown(
        """
        <style>
        .stApp {
            background:
                radial-gradient(circle at top left, rgba(210, 235, 255, 0.9), transparent 35%),
                radial-gradient(circle at bottom right, rgba(214, 240, 221, 0.85), transparent 30%),
                linear-gradient(180deg, #f4f8fb 0%, #ffffff 48%, #eef5f1 100%);
        }
        .hero {
            padding: 1.4rem 1.6rem;
            border-radius: 20px;
            background: linear-gradient(135deg, #0d3b66 0%, #195b87 48%, #2a7f62 100%);
            color: #f8fbff;
            box-shadow: 0 14px 32px rgba(13, 59, 102, 0.18);
            margin-bottom: 1rem;
        }
        .hero h1 {
            margin: 0;
            font-size: 2rem;
            letter-spacing: 0.01em;
        }
        .hero p {
            margin: 0.45rem 0 0;
            max-width: 66rem;
            opacity: 0.94;
        }
        .caption-card {
            border-radius: 16px;
            padding: 0.9rem 1rem;
            background: rgba(255, 255, 255, 0.82);
            border: 1px solid rgba(13, 59, 102, 0.08);
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


@st.cache_data(show_spinner=False, ttl=600)
def load_base_data() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    modelo_df = read_table_cached(
        TABLES["modelo"],
        order_by="identificacion, opportunity_id",
    )
    beneficio_df = read_table_cached(
        TABLES["beneficio"],
        order_by="identificacion, opportunity_id, fecha_referencia, beneficio_nombre",
    )
    socioeconomic_df = get_propensity_socioeconomic_features()
    vigencias_df = get_beneficio_vigencias()
    return modelo_df, beneficio_df, socioeconomic_df, vigencias_df


def render_header() -> None:
    st.markdown(
        f"""
        <section class="hero">
            <h1>Dashboard de Acciones y Propensity Score</h1>
            <p>
                Esta etapa ya no se enfoca solo en el diagnostico de una accion.
                Prioriza la pregunta de negocio: <strong>que acciones son mas efectivas en general,
                por semanas y por carrera</strong>. La unidad analitica sigue siendo la
                <strong>opportunity</strong>, usando datos de <strong>{SQL_SERVER}</strong> /
                <strong>{SQL_DATABASE}</strong> / schema <strong>{SQL_SCHEMA}</strong>.
            </p>
        </section>
        """,
        unsafe_allow_html=True,
    )


def build_bar_chart(
    dataframe: pd.DataFrame,
    x_field: str,
    y_field: str,
    color_field: str | None = None,
    title_x: str = "",
    title_y: str = "",
    height: int = 360,
) -> alt.Chart:
    chart = alt.Chart(dataframe).mark_bar(cornerRadiusEnd=4)
    encoding = {
        "x": alt.X(f"{x_field}:Q", title=title_x),
        "y": alt.Y(f"{y_field}:N", title=title_y, sort="-x"),
        "tooltip": [
            alt.Tooltip(f"{y_field}:N", title="Accion"),
            alt.Tooltip(f"{x_field}:Q", title=title_x or x_field, format=".2%"),
        ],
    }
    if color_field:
        encoding["color"] = alt.Color(
            f"{color_field}:N",
            scale=alt.Scale(domain=["Positivo", "Negativo"], range=["#2a7f62", "#c94747"]),
            legend=alt.Legend(title="Direccion"),
        )
    return chart.encode(**encoding).properties(height=height)


def build_histogram(dataframe: pd.DataFrame) -> alt.Chart:
    chart_data = dataframe.copy()
    chart_data["grupo"] = chart_data["grupo_tratamiento"]

    return (
        alt.Chart(chart_data)
        .mark_bar(opacity=0.72)
        .encode(
            x=alt.X("propensity_score:Q", bin=alt.Bin(maxbins=24), title="Propensity score"),
            y=alt.Y("count():Q", title="Oportunidades"),
            color=alt.Color(
                "grupo:N",
                title="Grupo",
                scale=alt.Scale(range=["#0d3b66", "#2a7f62"]),
            ),
            tooltip=[
                alt.Tooltip("grupo:N", title="Grupo"),
                alt.Tooltip("count():Q", title="Oportunidades"),
            ],
        )
        .properties(height=320)
    )


def build_band_chart(score_band_df: pd.DataFrame) -> alt.Chart:
    return (
        alt.Chart(score_band_df)
        .mark_line(point=True, strokeWidth=3)
        .encode(
            x=alt.X("banda_score:N", title="Banda de propensity score", sort=None),
            y=alt.Y("tasa_resultado:Q", title="Tasa de resultado", axis=alt.Axis(format=".0%")),
            color=alt.Color(
                "grupo_tratamiento:N",
                title="Grupo",
                scale=alt.Scale(range=["#0d3b66", "#2a7f62"]),
            ),
            tooltip=[
                alt.Tooltip("banda_score:N", title="Banda"),
                alt.Tooltip("grupo_tratamiento:N", title="Grupo"),
                alt.Tooltip("oportunidades:Q", title="Oportunidades"),
                alt.Tooltip("score_promedio:Q", title="Score promedio", format=".3f"),
                alt.Tooltip("tasa_resultado:Q", title="Tasa resultado", format=".2%"),
            ],
        )
        .properties(height=320)
    )


def build_heatmap(
    dataframe: pd.DataFrame,
    x_field: str,
    y_field: str,
    value_field: str,
    x_title: str,
    y_title: str,
    color_title: str,
    height: int = 360,
) -> alt.Chart:
    return (
        alt.Chart(dataframe)
        .mark_rect()
        .encode(
            x=alt.X(f"{x_field}:N", title=x_title, sort=None),
            y=alt.Y(f"{y_field}:N", title=y_title, sort=None),
            color=alt.Color(
                f"{value_field}:Q",
                title=color_title,
                scale=alt.Scale(scheme="redyellowgreen"),
            ),
            tooltip=[
                alt.Tooltip(f"{x_field}:N", title=x_title),
                alt.Tooltip(f"{y_field}:N", title=y_title),
                alt.Tooltip(f"{value_field}:Q", title=color_title, format=".2%"),
            ],
        )
        .properties(height=height)
    )


def build_group_density_chart(
    dataframe: pd.DataFrame,
    value_field: str,
    x_title: str,
    group_field: str = "grupo_tratamiento",
    height: int = 320,
    reference_dates: list[pd.Timestamp] | None = None,
) -> alt.Chart | None:
    chart_data = dataframe[[value_field, group_field]].dropna().copy()
    if chart_data.empty or chart_data[group_field].nunique() < 2:
        return None

    chart_data[value_field] = pd.to_datetime(chart_data[value_field], errors="coerce")
    chart_data = chart_data.dropna(subset=[value_field]).copy()
    if chart_data.empty or chart_data[group_field].nunique() < 2:
        return None

    min_date = chart_data[value_field].min()
    max_date = chart_data[value_field].max()
    if pd.isna(min_date) or pd.isna(max_date) or min_date == max_date:
        return None

    date_range_days = max(1.0, (max_date - min_date).days)
    bandwidth_days = max(3.0, min(12.0, date_range_days / 10.0))
    grid = pd.date_range(min_date, max_date, periods=200)
    grid_days = ((grid - pd.Timestamp("1970-01-01")) / pd.Timedelta(days=1)).to_numpy().reshape(-1, 1)

    density_frames: list[pd.DataFrame] = []
    for group_name, group_df in chart_data.groupby(group_field):
        days = (
            (group_df[value_field] - pd.Timestamp("1970-01-01")) / pd.Timedelta(days=1)
        ).to_numpy().reshape(-1, 1)
        if len(np.unique(days)) < 2:
            continue
        kde = KernelDensity(kernel="gaussian", bandwidth=bandwidth_days)
        kde.fit(days)
        density = np.exp(kde.score_samples(grid_days))
        density_frames.append(
            pd.DataFrame(
                {
                    value_field: grid,
                    "densidad": density,
                    group_field: group_name,
                }
            )
        )

    if not density_frames:
        return None

    density_df = pd.concat(density_frames, ignore_index=True)
    area = alt.Chart(density_df).mark_area(opacity=0.42).encode(
        x=alt.X(f"{value_field}:T", title=x_title),
        y=alt.Y("densidad:Q", title="Frecuencia relativa"),
        color=alt.Color(
            f"{group_field}:N",
            title="Grupo",
            scale=alt.Scale(domain=["Control", "Tratado"], range=["#e9a3a3", "#69d0d0"]),
        ),
        tooltip=[
            alt.Tooltip(f"{group_field}:N", title="Grupo"),
            alt.Tooltip(f"{value_field}:T", title=x_title),
            alt.Tooltip("densidad:Q", title="Densidad", format=".3f"),
        ],
    )
    line = alt.Chart(density_df).mark_line(strokeWidth=2).encode(
        x=alt.X(f"{value_field}:T", title=x_title),
        y=alt.Y("densidad:Q", title="Frecuencia relativa"),
        color=alt.Color(
            f"{group_field}:N",
            title="Grupo",
            scale=alt.Scale(domain=["Control", "Tratado"], range=["#4f4f4f", "#1b6f6f"]),
            legend=None,
        ),
    )
    layers: list[alt.Chart] = [area, line]

    valid_reference_dates = [
        pd.to_datetime(value, errors="coerce")
        for value in (reference_dates or [])
    ]
    valid_reference_dates = [value for value in valid_reference_dates if pd.notna(value)]
    if valid_reference_dates:
        rule_df = pd.DataFrame({value_field: valid_reference_dates})
        rules = alt.Chart(rule_df).mark_rule(color="black", strokeWidth=2).encode(
            x=alt.X(f"{value_field}:T")
        )
        layers.append(rules)

    return alt.layer(*layers).properties(height=height)


def sidebar_filters(modelo_df: pd.DataFrame) -> dict[str, object]:
    st.sidebar.header("Configuracion")
    if st.sidebar.button("Recargar datos SQL", use_container_width=True):
        st.cache_data.clear()
        st.cache_resource.clear()
        st.rerun()

    periodos = sorted(modelo_df["periodo"].dropna().astype(str).unique())
    treatment_flag = st.sidebar.selectbox(
        "Definicion de tratamiento",
        ["aplicable", "ofrecido", "otorgado"],
        index=0,
        help="Elige que bandera del beneficio define el tratamiento.",
    )
    st.sidebar.caption(TREATMENT_FLAG_HELP[treatment_flag])

    outcome_label = st.sidebar.selectbox(
        "Resultado a modelar",
        list(OUTCOME_OPTIONS.keys()),
        index=0,
    )

    selected_periodos = st.sidebar.multiselect(
        "Periodo",
        options=periodos,
        default=periodos,
    )

    with st.sidebar.expander("Avanzado metodologico", expanded=False):
        min_treated = st.slider(
            "Minimo tratados por accion",
            min_value=5,
            max_value=100,
            value=25,
            step=5,
            key="sidebar_min_treated",
        )
        min_control = st.slider(
            "Minimo controles por accion",
            min_value=5,
            max_value=200,
            value=25,
            step=5,
            key="sidebar_min_control",
        )
        min_probability = st.slider(
            "Piso de clipping para propensity",
            min_value=0.01,
            max_value=0.20,
            value=0.02,
            step=0.01,
            key="sidebar_min_probability",
        )
        max_weight = st.slider(
            "Peso maximo estabilizado",
            min_value=2.0,
            max_value=30.0,
            value=10.0,
            step=1.0,
            key="sidebar_max_weight",
        )

    return {
        "treatment_flag": treatment_flag,
        "outcome_label": outcome_label,
        "outcome_column": OUTCOME_OPTIONS[outcome_label],
        "periodos": selected_periodos,
        "min_treated": min_treated,
        "min_control": min_control,
        "min_probability": min_probability,
        "max_weight": max_weight,
    }


def filtered_career_list(modelo_df: pd.DataFrame, periodos: list[str], top_n: int) -> list[str]:
    filtered = modelo_df.copy()
    if periodos:
        filtered = filtered[filtered["periodo"].astype(str).isin(periodos)]
    counts = (
        filtered.groupby("carrera", as_index=False)
        .agg(oportunidades=("opportunity_id", "count"))
        .sort_values(["oportunidades", "carrera"], ascending=[False, True])
    )
    return counts["carrera"].head(top_n).tolist()


def describe_top_action(ranking_df: pd.DataFrame, context_label: str) -> None:
    if ranking_df.empty:
        st.info(f"No hubo acciones evaluables para {context_label} con los filtros actuales.")
        return

    top_row = ranking_df.iloc[0]
    direction = "positiva" if top_row["uplift_weighted"] >= 0 else "negativa"
    st.markdown(
        f"""
        <div class="caption-card">
            En <strong>{context_label}</strong>, la accion mejor posicionada es
            <strong>{top_row['beneficio_nombre']}</strong>.
            Su uplift ponderado estimado es <strong>{top_row['uplift_weighted']:.2%}</strong>,
            con <strong>{int(top_row['tratadas'])}</strong> tratados y
            <strong>{int(top_row['controles'])}</strong> controles.
            La senal observada es <strong>{direction}</strong> bajo la definicion actual.
        </div>
        """,
        unsafe_allow_html=True,
    )


def decorate_ranking(ranking_df: pd.DataFrame) -> pd.DataFrame:
    decorated = ranking_df.copy()
    decorated["direccion"] = decorated["uplift_weighted"].apply(
        lambda value: "Positivo" if value >= 0 else "Negativo"
    )
    return decorated


def render_general_tab(
    ranking_df: pd.DataFrame,
    outcome_label: str,
) -> None:
    st.subheader("General")
    describe_top_action(ranking_df, "general")

    if ranking_df.empty:
        return

    max_actions = max(1, min(12, len(ranking_df)))
    top_actions = st.slider(
        "Acciones a mostrar",
        min_value=1,
        max_value=max_actions,
        value=min(8, max_actions),
        step=1,
        key="general_top_actions",
    )

    summary = decorate_ranking(ranking_df).head(top_actions)
    cols = st.columns(4)
    cols[0].metric("Acciones evaluadas", f"{len(ranking_df):,}")
    cols[1].metric("Mejor uplift ponderado", f"{summary.iloc[0]['uplift_weighted']:.2%}")
    cols[2].metric("Accion lider", summary.iloc[0]["beneficio_nombre"])
    cols[3].metric("Tratadas accion lider", f"{int(summary.iloc[0]['tratadas']):,}")

    st.altair_chart(
        build_bar_chart(
            summary,
            x_field="uplift_weighted",
            y_field="beneficio_nombre",
            color_field="direccion",
            title_x=f"Uplift ponderado en {outcome_label}",
            title_y="Accion",
            height=360,
        ),
        use_container_width=True,
    )

    show_columns = [
        "ranking",
        "beneficio_nombre",
        "tratadas",
        "controles",
        "tasa_tratamiento",
        "resultado_tratadas_weighted",
        "resultado_controles_weighted",
        "uplift_weighted",
        "uplift_raw",
    ]
    display_df = summary[show_columns].copy()
    st.dataframe(display_df, use_container_width=True, hide_index=True)


def render_weeks_tab(
    week_rankings: pd.DataFrame,
    general_ranking: pd.DataFrame,
    outcome_label: str,
) -> None:
    st.subheader("Semanas")
    if week_rankings.empty:
        st.info("No hubo segmentos de semanas con muestra suficiente.")
        return

    ordered_segments = [label for label, _, _ in WEEK_SEGMENTS]
    week_rankings = week_rankings.copy()
    week_rankings["segmento_semana"] = pd.Categorical(
        week_rankings["segmento_semana"],
        categories=ordered_segments,
        ordered=True,
    )
    best_by_week = (
        week_rankings.sort_values(
            ["segmento_semana", "uplift_weighted", "tratadas"],
            ascending=[True, False, False],
        )
        .groupby("segmento_semana", as_index=False)
        .first()
    )
    st.markdown(
        """
        <div class="caption-card">
            Esta vista resume cual accion domina en cada tramo de semanas para clase.
            Se privilegia la lectura por segmento antes que el detalle tecnico del modelo.
        </div>
        """,
        unsafe_allow_html=True,
    )
    st.dataframe(
        best_by_week[
            ["segmento_semana", "beneficio_nombre", "tratadas", "controles", "uplift_weighted"]
        ],
        use_container_width=True,
        hide_index=True,
    )

    max_actions = max(1, min(12, len(general_ranking)))
    top_actions = st.slider(
        "Acciones a incluir en el mapa",
        min_value=1,
        max_value=max_actions,
        value=min(8, max_actions),
        step=1,
        key="weeks_top_actions",
    )

    top_benefits = general_ranking["beneficio_nombre"].head(top_actions).tolist()
    heatmap_df = week_rankings[week_rankings["beneficio_nombre"].isin(top_benefits)].copy()
    if not heatmap_df.empty:
        st.altair_chart(
            build_heatmap(
                heatmap_df,
                x_field="segmento_semana",
                y_field="beneficio_nombre",
                value_field="uplift_weighted",
                x_title="Segmento semana",
                y_title="Accion",
                color_title="Uplift ponderado",
                height=360,
            ),
            use_container_width=True,
        )

    available_segments = best_by_week["segmento_semana"].tolist()
    selected_segment = st.selectbox("Segmento de semanas", available_segments, index=0)
    selected_ranking = week_rankings[week_rankings["segmento_semana"] == selected_segment].copy()
    describe_top_action(selected_ranking, f"semanas {selected_segment}")

    st.dataframe(
        selected_ranking[
            [
                "ranking",
                "beneficio_nombre",
                "tratadas",
                "controles",
                "resultado_tratadas_weighted",
                "resultado_controles_weighted",
                "uplift_weighted",
            ]
        ].sort_values("uplift_weighted", ascending=False),
        use_container_width=True,
        hide_index=True,
    )


def build_best_action_by_career(
    modelo_df: pd.DataFrame,
    beneficio_df: pd.DataFrame,
    socioeconomic_df: pd.DataFrame,
    careers: list[str],
    config: dict[str, object],
) -> pd.DataFrame:
    rows: list[pd.DataFrame] = []
    for career in careers:
        ranking = rank_actions(
            modelo_df=modelo_df,
            beneficios_df=beneficio_df,
            socioeconomic_df=socioeconomic_df,
            treatment_flag=str(config["treatment_flag"]),
            outcome_column=str(config["outcome_column"]),
            periodos=list(config["periodos"]),
            carreras=[career],
            min_treated=int(config["min_treated"]),
            min_control=int(config["min_control"]),
            min_probability=float(config["min_probability"]),
            max_weight=float(config["max_weight"]),
        )
        if ranking.empty:
            continue
        best = ranking.iloc[[0]].copy()
        best["carrera"] = career
        rows.append(best)

    if not rows:
        return pd.DataFrame()
    return pd.concat(rows, ignore_index=True)


def render_careers_tab(
    modelo_df: pd.DataFrame,
    beneficio_df: pd.DataFrame,
    socioeconomic_df: pd.DataFrame,
    config: dict[str, object],
) -> None:
    st.subheader("Carreras")

    filtered = modelo_df.copy()
    if list(config["periodos"]):
        filtered = filtered[filtered["periodo"].astype(str).isin(list(config["periodos"]))]

    career_counts = (
        filtered.groupby("carrera", as_index=False)
        .agg(oportunidades=("opportunity_id", "count"))
        .sort_values(["oportunidades", "carrera"], ascending=[False, True])
    )
    if career_counts.empty:
        st.info("No hay carreras disponibles para los filtros actuales.")
        return

    max_careers = max(1, min(20, len(career_counts)))
    top_careers = st.slider(
        "Carreras a comparar",
        min_value=1,
        max_value=max_careers,
        value=min(10, max_careers),
        step=1,
        key="careers_top_n",
        help="Define cuantas carreras entran al ranking resumido de esta pestana.",
    )
    careers = career_counts["carrera"].head(top_careers).tolist()
    if not careers:
        st.info("No hay carreras disponibles para los filtros actuales.")
        return

    selected_career = st.selectbox("Carrera a analizar", careers, index=0)
    max_actions = max(
        1,
        min(
            12,
            max(
                1,
                beneficio_df["beneficio_nombre"]
                .dropna()
                .astype(str)
                .loc[lambda s: s.str.len() > 0]
                .nunique(),
            ),
        ),
    )
    top_actions = st.slider(
        "Acciones a mostrar para la carrera",
        min_value=1,
        max_value=max_actions,
        value=min(8, max_actions),
        step=1,
        key="careers_top_actions",
    )
    ranking_career = rank_actions(
        modelo_df=modelo_df,
        beneficios_df=beneficio_df,
        socioeconomic_df=socioeconomic_df,
        treatment_flag=str(config["treatment_flag"]),
        outcome_column=str(config["outcome_column"]),
        periodos=list(config["periodos"]),
        carreras=[selected_career],
        min_treated=int(config["min_treated"]),
        min_control=int(config["min_control"]),
        min_probability=float(config["min_probability"]),
        max_weight=float(config["max_weight"]),
    )
    describe_top_action(ranking_career, f"carrera {selected_career}")
    if not ranking_career.empty:
        st.altair_chart(
            build_bar_chart(
                decorate_ranking(ranking_career).head(top_actions),
                x_field="uplift_weighted",
                y_field="beneficio_nombre",
                color_field="direccion",
                title_x=f"Uplift ponderado en {config['outcome_label']}",
                title_y="Accion",
                height=340,
            ),
            use_container_width=True,
        )
        st.dataframe(
            ranking_career[
                [
                    "ranking",
                    "beneficio_nombre",
                    "tratadas",
                    "controles",
                    "resultado_tratadas_weighted",
                    "resultado_controles_weighted",
                    "uplift_weighted",
                ]
            ],
            use_container_width=True,
            hide_index=True,
        )

    st.markdown("**Mejor accion por carrera**")
    best_by_career = build_best_action_by_career(
        modelo_df=modelo_df,
        beneficio_df=beneficio_df,
        socioeconomic_df=socioeconomic_df,
        careers=careers,
        config=config,
    )
    if best_by_career.empty:
        st.info("No hubo carreras con muestra suficiente para comparar acciones.")
        return

    best_view = best_by_career[["carrera", "beneficio_nombre", "tratadas", "uplift_weighted"]].copy()
    st.dataframe(best_view, use_container_width=True, hide_index=True)


def format_combo_label(combo_name: str, max_length: int = 60) -> str:
    compact = combo_name.replace(" | ", " + ")
    if len(compact) <= max_length:
        return compact
    return compact[: max_length - 3] + "..."


def render_combinations_tab(
    modelo_df: pd.DataFrame,
    beneficio_df: pd.DataFrame,
    socioeconomic_df: pd.DataFrame,
    config: dict[str, object],
) -> None:
    st.subheader("Combinaciones")
    min_combo_size = st.slider(
        "Minimo beneficios por combinacion",
        min_value=2,
        max_value=5,
        value=2,
        step=1,
        key="combos_min_size",
        help="La vista mostrara solo portfolios observados con al menos este numero de beneficios distintos.",
    )
    top_combos = st.slider(
        "Combinaciones a mostrar",
        min_value=1,
        max_value=12,
        value=8,
        step=1,
        key="combos_top_n",
    )

    with st.spinner("Calculando ranking de combinaciones..."):
        combo_ranking = rank_combinations(
            modelo_df=modelo_df,
            beneficios_df=beneficio_df,
            socioeconomic_df=socioeconomic_df,
            treatment_flag=str(config["treatment_flag"]),
            outcome_column=str(config["outcome_column"]),
            periodos=list(config["periodos"]),
            min_treated=int(config["min_treated"]),
            min_control=int(config["min_control"]),
            min_combo_size=min_combo_size,
            min_probability=float(config["min_probability"]),
            max_weight=float(config["max_weight"]),
        )

    if combo_ranking.empty:
        st.info(
            f"No hubo combinaciones de al menos {min_combo_size} beneficios con muestra suficiente para evaluar."
        )
        return

    top_row = combo_ranking.iloc[0]
    st.markdown(
        f"""
        <div class="caption-card">
            La combinacion observada con mejor senal es
            <strong>{top_row['combo_beneficios']}</strong>.
            Su uplift ponderado estimado es <strong>{top_row['uplift_weighted']:.2%}</strong>,
            con <strong>{int(top_row['tratadas'])}</strong> opportunities tratadas.
            Esta vista filtra portfolios con al menos <strong>{min_combo_size}</strong> beneficios y
            sirve para priorizar combinaciones observadas, no para recomendar aun una optimizacion causal perfecta.
        </div>
        """,
        unsafe_allow_html=True,
    )

    summary = combo_ranking.head(top_combos).copy()
    summary["combo_label"] = summary["combo_beneficios"].map(format_combo_label)
    summary["direccion"] = summary["uplift_weighted"].apply(
        lambda value: "Positivo" if value >= 0 else "Negativo"
    )

    cols = st.columns(4)
    cols[0].metric("Combos evaluables", f"{len(combo_ranking):,}")
    cols[1].metric("Mejor uplift ponderado", f"{summary.iloc[0]['uplift_weighted']:.2%}")
    cols[2].metric("Tamano combo lider", f"{int(summary.iloc[0]['tratadas']):,}")
    cols[3].metric("Beneficios en combo lider", int(summary.iloc[0]["num_beneficios_combo"]))

    st.altair_chart(
        build_bar_chart(
            summary,
            x_field="uplift_weighted",
            y_field="combo_label",
            color_field="direccion",
            title_x=f"Uplift ponderado en {config['outcome_label']}",
            title_y="Combinacion",
            height=380,
        ),
        use_container_width=True,
    )

    st.dataframe(
        summary[
            [
                "ranking",
                "combo_beneficios",
                "num_beneficios_combo",
                "tratadas",
                "controles",
                "resultado_tratadas_weighted",
                "resultado_controles_weighted",
                "uplift_weighted",
            ]
        ],
        use_container_width=True,
        hide_index=True,
    )

    selected_combo = st.selectbox(
        "Combinacion a revisar",
        combo_ranking["combo_beneficios"].tolist(),
        index=0,
    )

    combo_dataset = build_combination_dataset(
        modelo_df=modelo_df,
        beneficios_df=beneficio_df,
        socioeconomic_df=socioeconomic_df,
        treatment_flag=str(config["treatment_flag"]),
        outcome_column=str(config["outcome_column"]),
        periodos=list(config["periodos"]),
    )
    combo_dataset = combo_dataset.copy()
    combo_dataset["tratamiento"] = (combo_dataset["combo_beneficios"] == selected_combo).astype(int)

    try:
        combo_result = fit_propensity_model(
            dataset=combo_dataset,
            outcome_column="resultado",
            min_probability=float(config["min_probability"]),
            max_weight=float(config["max_weight"]),
        )
    except ValueError as exc:
        st.warning(f"No se pudo calcular el drilldown de la combinacion: {exc}")
        return

    combo_score_bands = build_score_band_summary(combo_result.model_df, outcome_column="resultado")

    left, right = st.columns([1, 1.2])
    with left:
        st.subheader("Drilldown de combinacion")
        metrics = combo_result.summary_metrics
        st.metric("Tratadas", f"{int(metrics['tratadas']):,}")
        st.metric("Controles", f"{int(metrics['controles']):,}")
        st.metric("Uplift ponderado", f"{metrics['uplift_weighted']:.2%}")
        st.metric("Uplift sin ponderar", f"{metrics['uplift_raw']:.2%}")

    with right:
        st.subheader("Distribucion del score")
        st.altair_chart(build_histogram(combo_result.model_df), use_container_width=True)

    if not combo_score_bands.empty:
        st.subheader("Bandas de score para la combinacion")
        st.altair_chart(build_band_chart(combo_score_bands), use_container_width=True)


def render_drilldown_tab(
    modelo_df: pd.DataFrame,
    beneficio_df: pd.DataFrame,
    socioeconomic_df: pd.DataFrame,
    vigencias_df: pd.DataFrame,
    general_ranking: pd.DataFrame,
    config: dict[str, object],
) -> None:
    st.subheader("Drilldown de accion")
    benefit_options = (
        general_ranking["beneficio_nombre"].dropna().astype(str).tolist()
        if not general_ranking.empty
        else sorted(
            beneficio_df["beneficio_nombre"]
            .dropna()
            .astype(str)
            .loc[lambda s: s.str.len() > 0]
            .unique()
            .tolist()
        )
    )
    if not benefit_options:
        st.warning("No hay beneficios disponibles para el drilldown.")
        return

    benefit_name = st.selectbox(
        "Accion a revisar",
        benefit_options,
        index=0,
        help="Esta seleccion solo afecta la pestana Drilldown.",
    )

    try:
        drilldown_dataset = build_propensity_dataset(
            modelo_df=modelo_df,
            beneficios_df=beneficio_df,
            socioeconomic_df=socioeconomic_df,
            beneficio_nombre=benefit_name,
            treatment_flag=str(config["treatment_flag"]),
            outcome_column=str(config["outcome_column"]),
            periodos=list(config["periodos"]),
        )
    except Exception as exc:
        st.warning(f"No se pudo construir la cohorte de drilldown: {exc}")
        return

    if drilldown_dataset.empty:
        st.warning("No hay oportunidades para la accion seleccionada con los filtros actuales.")
        return

    try:
        result = fit_propensity_model(
            dataset=drilldown_dataset,
            outcome_column="resultado",
            min_probability=float(config["min_probability"]),
            max_weight=float(config["max_weight"]),
        )
    except ValueError as exc:
        st.warning(str(exc))
        return

    score_band_df = build_score_band_summary(result.model_df, outcome_column="resultado")
    outcome_label = str(config["outcome_label"])
    treatment_flag = str(config["treatment_flag"])
    benefit_start_dates = (
        vigencias_df.loc[vigencias_df["beneficio_nombre"] == benefit_name, "fecha_inicio"]
        .dropna()
        .drop_duplicates()
        .sort_values()
        .tolist()
        if not vigencias_df.empty
        else []
    )

    metrics = result.summary_metrics
    cols = st.columns(4)
    cols[0].metric("Oportunidades", f"{int(metrics['total_oportunidades']):,}")
    cols[1].metric("Tratadas", f"{int(metrics['tratadas']):,}", f"{metrics['tasa_tratamiento']:.1%}")
    cols[2].metric(
        f"{outcome_label} tratado vs control",
        f"{metrics['uplift_raw']:.2%}",
        "sin ponderar",
    )
    cols[3].metric(
        "Uplift ponderado",
        f"{metrics['uplift_weighted']:.2%}",
        "ATE estabilizado",
    )

    st.markdown(
        f"""
        <div class="caption-card">
            Esta vista conserva el analisis profundo de una accion individual.
            La accion seleccionada es <strong>{benefit_name}</strong> y el tratamiento usa
            <strong>{treatment_flag}</strong>.
        </div>
        """,
        unsafe_allow_html=True,
    )

    tab_a, tab_b, tab_c, tab_d = st.tabs(
        ["Diagnostico", "Distribucion", "Variables", "Datos"]
    )

    with tab_a:
        left, right = st.columns([1.1, 1.4])
        with left:
            st.subheader("Tasas de resultado")
            rates = result.outcome_rates_df.copy()
            rates["tasa_sin_ponderar"] = rates["tasa_sin_ponderar"].map(lambda x: f"{x:.2%}")
            rates["tasa_ponderada"] = rates["tasa_ponderada"].map(lambda x: f"{x:.2%}")
            rates["oportunidades"] = rates["oportunidades"].astype(int)
            st.dataframe(rates, use_container_width=True, hide_index=True)

        with right:
            st.subheader("Balance numerico")
            balance = result.balance_df.copy()
            if balance.empty:
                st.info("No hubo variables numericas suficientes para evaluar balance.")
            else:
                for column in [
                    "media_tratadas",
                    "media_control",
                    "smd_sin_ponderar",
                    "media_tratadas_ponderada",
                    "media_control_ponderada",
                    "smd_ponderado",
                ]:
                    balance[column] = balance[column].map(lambda x: round(float(x), 4))
                st.dataframe(balance, use_container_width=True, hide_index=True)

    with tab_b:
        st.subheader("Distribucion de propensity score")
        st.altair_chart(build_histogram(result.model_df), use_container_width=True)

        st.subheader("Distribucion temporal de control y tratamiento")
        density_chart = build_group_density_chart(
            result.model_df,
            value_field="fecha_inicio_proceso",
            x_title="Fecha de inicio del proceso",
            reference_dates=benefit_start_dates,
        )
        if density_chart is None:
            st.info("No hubo variacion suficiente en fechas para dibujar la densidad de control vs tratado.")
        else:
            st.altair_chart(density_chart, use_container_width=True)
            if benefit_start_dates:
                st.caption("La linea negra marca el inicio de vigencia del beneficio seleccionado. Si el beneficio tiene varias vigencias, se muestra una linea por cada inicio.")
            else:
                st.caption("No se encontraron vigencias cargadas para el beneficio seleccionado.")

        st.subheader("Resultado por banda de score")
        if score_band_df.empty:
            st.info("No hubo suficiente variacion en el score para construir bandas.")
        else:
            st.altair_chart(build_band_chart(score_band_df), use_container_width=True)
            st.dataframe(score_band_df, use_container_width=True, hide_index=True)

    with tab_c:
        st.subheader("Coeficientes del modelo")
        coefficients = result.coefficients_df.head(25).copy()
        coefficients["coeficiente"] = coefficients["coeficiente"].map(lambda x: round(float(x), 4))
        coefficients["magnitud"] = coefficients["magnitud"].map(lambda x: round(float(x), 4))
        st.dataframe(coefficients, use_container_width=True, hide_index=True)

    with tab_d:
        show_columns = [
            "opportunity_id",
            "identificacion",
            "periodo",
            "carrera",
            "tratamiento",
            "resultado",
            "propensity_score",
            "peso_ate_estabilizado",
            "exposiciones_beneficio",
            "primera_fecha_beneficio",
            "ultima_fecha_beneficio",
            "edad_estudiante",
            "sexo_estudiante",
            "nivel_estudio_estudiante",
            "hijos_hogar_max",
            "padres_con_empleo",
            "log_salario_total_hogar",
            "padres_con_deuda",
            "log_deuda_total_hogar",
            "ratio_deuda_ingreso_hogar",
        ]
        dataset_view = result.model_df[show_columns].copy()
        dataset_view = dataset_view.rename(
            columns={
                "tratamiento": f"tratamiento_{benefit_name}",
                "resultado": outcome_label,
            }
        )
        st.dataframe(dataset_view, use_container_width=True, hide_index=True)
        st.download_button(
            "Descargar dataset analitico CSV",
            data=dataset_view.to_csv(index=False).encode("utf-8"),
            file_name="dataset_propensity.csv",
            mime="text/csv",
            use_container_width=True,
        )


def main() -> None:
    inject_styles()
    render_header()

    try:
        modelo_df, beneficio_df, socioeconomic_df, vigencias_df = load_base_data()
    except Exception as exc:
        st.error(f"No se pudo leer SQL Server: {exc}")
        st.stop()

    try:
        config = sidebar_filters(modelo_df)
    except ValueError as exc:
        st.warning(str(exc))
        st.stop()

    with st.spinner("Calculando ranking general de acciones..."):
        general_ranking = rank_actions(
            modelo_df=modelo_df,
            beneficios_df=beneficio_df,
            socioeconomic_df=socioeconomic_df,
            treatment_flag=str(config["treatment_flag"]),
            outcome_column=str(config["outcome_column"]),
            periodos=list(config["periodos"]),
            min_treated=int(config["min_treated"]),
            min_control=int(config["min_control"]),
            min_probability=float(config["min_probability"]),
            max_weight=float(config["max_weight"]),
        )

    with st.spinner("Calculando segmentos por semanas..."):
        week_rankings = build_week_segment_rankings(
            modelo_df=modelo_df,
            beneficios_df=beneficio_df,
            socioeconomic_df=socioeconomic_df,
            treatment_flag=str(config["treatment_flag"]),
            outcome_column=str(config["outcome_column"]),
            periodos=list(config["periodos"]),
            min_treated=int(config["min_treated"]),
            min_control=int(config["min_control"]),
            min_probability=float(config["min_probability"]),
            max_weight=float(config["max_weight"]),
        )

    st.markdown(
        f"""
        <div class="caption-card">
            El dashboard esta organizado en etapas. Primero responde
            <strong>que accion parece mas efectiva</strong>, luego
            <strong>que combinaciones observadas parecen mas fuertes</strong>,
            despues <strong>donde cambia esa respuesta por semanas y carreras</strong>,
            y al final deja un <strong>drilldown tecnico</strong> para validar una accion concreta.
        </div>
        """,
        unsafe_allow_html=True,
    )

    tab_general, tab_combos, tab_weeks, tab_careers, tab_drilldown = st.tabs(
        ["General", "Combinaciones", "Semanas", "Carreras", "Drilldown"]
    )

    with tab_general:
        render_general_tab(
            ranking_df=general_ranking,
            outcome_label=str(config["outcome_label"]),
        )

    with tab_combos:
        render_combinations_tab(
            modelo_df=modelo_df,
            beneficio_df=beneficio_df,
            socioeconomic_df=socioeconomic_df,
            config=config,
        )

    with tab_weeks:
        render_weeks_tab(
            week_rankings=week_rankings,
            general_ranking=general_ranking,
            outcome_label=str(config["outcome_label"]),
        )

    with tab_careers:
        render_careers_tab(
            modelo_df=modelo_df,
            beneficio_df=beneficio_df,
            socioeconomic_df=socioeconomic_df,
            config=config,
        )

    with tab_drilldown:
        render_drilldown_tab(
            modelo_df=modelo_df,
            beneficio_df=beneficio_df,
            socioeconomic_df=socioeconomic_df,
            vigencias_df=vigencias_df,
            general_ranking=general_ranking,
            config=config,
        )


if __name__ == "__main__":
    main()
