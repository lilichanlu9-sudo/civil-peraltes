from pathlib import Path

import streamlit as st
from excel_peraltes import show_excel

st.set_page_config(page_title="Civil Peraltes", layout="wide")
st.image(str(Path(__file__).with_name("civil_peraltes_logo.png")), width=420)
st.caption("Calzada simétrica de dos carriles con giro en el eje central · apartado 302.08")

mode = st.radio("Origen de los datos", ["Ingreso manual DG-2018", "CSV o Excel de Civil 3D"], horizontal=True)
if mode == "CSV o Excel de Civil 3D":
    show_excel(st, web_uploads=globals().get("WEB_UPLOADS", False))
    st.stop()

with st.form("dg2018"):
    left, middle, right = st.columns(3)
    with left:
        speed = st.number_input("Velocidad de diseño (km/h)", min_value=20.0, max_value=130.0, value=60.0)
        width = st.number_input("Ancho total de calzada (m)", min_value=0.01, value=6.60)
        third_class = st.checkbox("Carretera de tercera clase")
    with middle:
        crown = st.number_input("Bombeo normal (%)", min_value=0.01, value=2.50)
        bank = st.number_input("Peralte completo (%)", min_value=0.01, value=3.60)
        geometry = st.selectbox("Geometría", ["Con espirales", "Circular sin espirales"])
    with right:
        entry = st.number_input("Longitud total de entrada A–D (m)", min_value=0.001, value=28.805, format="%.3f")
        exit_length = st.number_input("Longitud total de salida D'–A' (m)", min_value=0.001, value=28.805, format="%.3f")
        first = st.number_input("SC si hay espiral / PC si es circular (m)", min_value=0.0, value=100.49, format="%.3f")
        last = st.number_input("CS si hay espiral / PT si es circular (m)", min_value=0.0, value=134.73, format="%.3f")
    st.form_submit_button("Calcular y dibujar", type="primary")

if last <= first or bank < crown:
    st.error("Verifica que CS/PT sea posterior a SC/PC y que el peralte completo sea al menos igual al bombeo para esta secuencia de estaciones.")
    st.stop()

edge = width / 2
gradient = 1.8 - 0.01 * speed
minimum = edge * (crown + bank) / gradient
if geometry == "Con espirales":
    circular_length = last - first
    shift = max(0.0, (30 - circular_length) / 2)
    bfs, efs = first - shift, last + shift
else:
    fraction = 0.5 if bank < 4.5 else 0.7 if bank <= 7 else 0.8
    bfs = first + (1 - fraction) * bank / (crown + bank) * entry
    efs = last - (1 - fraction) * bank / (crown + bank) * exit_length

if bfs > efs:
    st.error("Las transiciones se solapan dentro de la curva. Revisa las longitudes y la ubicación antes de dibujar.")
    st.stop()

def transition(full_station, length, sign):
    start = full_station - sign * length
    level = start + sign * length * crown / (crown + bank)
    reverse = start + sign * length * 2 * crown / (crown + bank)
    return start, level, reverse

a, b, c = transition(bfs, entry, 1)
a_out, b_out, c_out = transition(efs, exit_length, -1)
events = [
    ("ENC", a, -crown, -crown),
    ("LC", b, 0.0, -crown),
    ("RC", c, crown, -crown),
    ("BFS", bfs, bank, -bank),
    ("EFS", efs, bank, -bank),
    ("RC salida", c_out, crown, -crown),
    ("LC salida", b_out, 0.0, -crown),
    ("BNC", a_out, -crown, -crown),
]

st.subheader("Diagrama de peralte")
rows = [
    {"Progresiva (m)": station, "Pendiente (%)": slope, "Borde": side}
    for _, station, exterior, interior in events
    for side, slope in (("Exterior", exterior), ("Interior", interior))
]
st.line_chart(rows, x="Progresiva (m)", y="Pendiente (%)", color="Borde")
with st.expander("Progresivas y cotas relativas al eje"):
    st.dataframe([
        {"Punto": name, "Progresiva (m)": round(station, 3),
         "Exterior (%)": exterior, "Interior (%)": interior,
         "Cota exterior (m)": round(edge * exterior / 100, 3),
         "Cota interior (m)": round(edge * interior / 100, 3)}
        for name, station, exterior, interior in events
    ], hide_index=True)

st.subheader("Resumen de la curva")
if geometry == "Con espirales":
    st.write(f"Tipo: espiral con arco circular {'≤ 30 m' if circular_length <= 30 else '> 30 m'} · CS − SC = {circular_length:.3f} m")
    if shift:
        st.write(f"El peralte completo se extiende {shift:.3f} m por cada extremo para mantener 30 m.")
else:
    st.write("Tipo: curva simple circular")

st.subheader("Verificación de longitudes")
st.write(f"Distancia al borde B = {edge:.3f} m · Inclinación relativa máxima = {gradient:.3f} %")
st.dataframe([
    {"Tramo": label, "Longitud (m)": length, "Mínimo por inclinación (m)": round(minimum, 4),
     "Aplanamiento (m)": round(length * crown / (crown + bank), 3),
     "Runoff (m)": round(length * bank / (crown + bank), 3),
     "Estado": "Revisar Tabla 302.13" if third_class else "Cumple" if length + 1e-9 >= minimum else "No cumple"}
    for label, length in (("Entrada", entry), ("Salida", exit_length))
], hide_index=True)
st.caption(f"Peralte completo mantenido: {efs - bfs:.3f} m · Referencia para curva corta V/3,6: {speed / 3.6:.3f} m.")
if geometry == "Con espirales":
    st.caption("El esquema toma SC y CS como referencia y extiende el peralte completo si el arco circular es corto. Comprueba con TS y ST que haya espacio para desarrollar la transición y que su ubicación sea válida.")
st.caption("Datos iniciales ilustrativos. La verificación cubre la inclinación del borde. Bermas, solapes con otras curvas y CSV de Civil 3D quedan pendientes.")






