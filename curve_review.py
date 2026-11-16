from collections import Counter, defaultdict
import re

import altair as alt
from streamlit.components.v1 import html
from curve_surface import fullscreen_road_html, interactive_road, road_preview


def show_recommendations(st, pending, blocks, geometry):
    if not pending:
        return
    st.subheader("Ajustes recomendados con la velocidad fija")
    st.info("Evalúa estos cambios en el diseño geométrico. La app conserva la velocidad y el peralte de diseño de cada curva.")
    suggestions = []
    for block in blocks:
        prefix, _, reason = block.partition(": ")
        regions = re.findall(r"\b\d+\b", prefix)
        curves = [geometry.get(region, {}).get("Entidad") for region in regions]
        names = " / ".join(f"C{curve}" for curve in dict.fromkeys(curves) if curve is not None)
        if "solapan" in reason:
            action = "Repartir la transición entre ambas curvas. Si se conservan dos transiciones independientes, ganar al menos la distancia de solape indicada en el espacio disponible."
        elif "peralte completo" in reason and "requieren" in reason:
            action = "Aumentar el desarrollo circular o revisar la distribución entre recta y arco donde el DG-2018 lo permita. Mantener el tramo exigido de peralte completo."
        elif "espirales" in reason or "longitudes mínimas" in reason or "distribución" in reason:
            action = "Probar otra distribución entre entrada y salida. Si sigue faltando longitud, revisar TS/ST o extender la espiral dentro del espacio libre."
        elif "velocidad" in reason or "Vd" in reason or "distancias al borde" in reason:
            action = "Completar el dato faltante con el valor aprobado en el diseño. Mantener la velocidad de proyecto."
        else:
            action = "Revisar la secuencia y las progresivas de las estaciones críticas en el diseño geométrico."
        suggestions.append({"Curva": names, "Región": ", ".join(regions), "Motivo": reason, "Alternativa a evaluar": action})
    reported = {region for row in suggestions for region in row["Región"].split(", ")}
    for region in sorted(pending - reported, key=int):
        entity = geometry.get(region, {}).get("Entidad")
        suggestions.append({
            "Curva": f"C{entity}" if entity is not None else "",
            "Región": region, "Motivo": "El ajuste coincide con la transición original de una región vecina.",
            "Alternativa a evaluar": "Resolver primero la curva vecina y recalcular las dos juntas. Mantener la distancia disponible entre ambas transiciones.",
        })
    st.dataframe(suggestions, hide_index=True, width="stretch")


def show_corrected_gallery(st, history, geometry):
    records = history[max(history)][0]
    regions = list(dict.fromkeys(row["Superelevation Region"] for row in records if row["Superelevation Region"]))
    button = st.button("Ver todas las curvas", disabled=not regions)
    if not button:
        return

    @st.dialog("Curvas por tipo", width="large")
    def gallery():
        stages = sorted(history)
        stage = st.radio(
            "Etapa de corrección",
            stages,
            index=len(stages) - 1,
            format_func=lambda value: f"Corrección {value}",
            horizontal=True,
            key=f"gallery_stage_{'_'.join(map(str, stages))}",
        )
        records, pending = history[stage]
        st.write(f"Corrección {stage} · {len(pending)} regiones pendientes")
        groups = ["Circular simple", "Espiral · arco > 30 m", "Espiral · arco ≤ 30 m"]
        if any(region not in geometry for region in regions):
            groups.append("Sin geometría vinculada")
        st.caption("Verde: perfil verificado. Rojo: región pendiente con los datos originales. Los tonos distinguen los dos carriles.")
        counts = Counter(curve["Entidad"] for curve in geometry.values())
        def curve_label(region):
            entity = geometry.get(region, {}).get("Entidad")
            if entity is None:
                return f"Región {region}"
            return f"C{entity}" if counts[entity] == 1 else f"C{entity} · Región {region}"

        preview = st.cache_data(show_spinner=False, max_entries=150)(road_preview)
        st.caption("Vista 3D: eje en amarillo, secciones críticas en gris y relieve vertical ampliado 6×. Cotas relativas al eje.")
        rows = defaultdict(list)
        for record in records:
            rows[record["Superelevation Region"]].append(record)
        for group, tab in zip(groups, st.tabs(groups)):
            with tab:
                selected = [region for region in regions if geometry.get(region, {}).get("Tipo", "Sin geometría vinculada") == group]
                if not selected:
                    st.info("No hay curvas en esta categoría.")
                for region in selected:
                    label = curve_label(region)
                    colors = ["#a51e32", "#e45a64"] if region in pending else ["#087443", "#55a63b"]
                    st.subheader(label)
                    curve_rows = sorted(
                        rows[region],
                        key=lambda row: float(row["Station"].lower().replace("+", "").removesuffix("m")),
                    )
                    with st.expander(f"Estaciones críticas de {label}"):
                        st.dataframe([
                            {"Estación crítica": row["Description"], "Progresiva": row["Station"],
                             "Izquierdo (%)": row["Left Outside Lane"], "Derecho (%)": row["Right Outside Lane"]}
                            for row in curve_rows
                        ], hide_index=True)
                    points = [
                        {"Progresiva (m)": float(record["Station"].lower().replace("+", "").removesuffix("m")),
                         "Pendiente (%)": float(record[column].removesuffix("%")), "Carril": lane,
                         "Estación crítica": record["Description"]}
                        for record in curve_rows
                        for column, lane in (("Left Outside Lane", "Izquierdo"), ("Right Outside Lane", "Derecho"))
                    ]
                    zoom = alt.selection_interval(bind="scales", encodings=["x"], clear="dblclick")
                    chart = alt.Chart(alt.Data(values=points)).mark_line(point=True).encode(
                        x=alt.X("Progresiva (m):Q", scale=alt.Scale(zero=False)),
                        y=alt.Y("Pendiente (%):Q"),
                        color=alt.Color("Carril:N", scale=alt.Scale(
                            domain=["Izquierdo", "Derecho"], range=colors
                        )),
                        tooltip=["Estación crítica:N", "Carril:N", "Progresiva (m):Q", "Pendiente (%):Q"],
                    ).properties(height=200).add_params(zoom)
                    diagram, surface = st.columns([3, 2])
                    diagram.altair_chart(chart, width="stretch", key=f"corrected_curve_{region}")
                    image = preview(curve_rows, geometry.get(region, {}), colors)
                    if image is None:
                        surface.info("Vista 3D pendiente: falta geometría, ancho o una secuencia continua de pendientes.")
                    else:
                        if st.session_state.get("active_road_view") == region:
                            figure = interactive_road(curve_rows, geometry.get(region, {}), colors)
                            with surface:
                                html(fullscreen_road_html(figure), height=440)
                            surface.caption("Arrastra para rotar. Usa la rueda para acercar y pasa el cursor por un borde para ver sus valores.")
                            surface.button("Cerrar vista interactiva", key=f"close_road_{region}",
                                           on_click=lambda: st.session_state.pop("active_road_view", None))
                        else:
                            surface.image(image, width="stretch")
                            surface.button("Rotar y ampliar 3D", key=f"open_road_{region}",
                                           on_click=lambda value=region: st.session_state.update(active_road_view=value))
    gallery()








