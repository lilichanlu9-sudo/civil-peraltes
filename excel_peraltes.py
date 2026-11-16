import csv
import altair as alt
from pathlib import Path

from openpyxl import load_workbook
from dg2018_csv import export_preview, show_batch
from civil_geometry import show_geometry
from completed_curves import completed_geometry, show_completion


def read_sheet(path, sheet_name=None, header_row=1):
    workbook = load_workbook(path, read_only=True, data_only=True)
    try:
        if sheet_name is None:
            return workbook.sheetnames
        sheet = workbook[sheet_name]
        rows = sheet.iter_rows(min_row=header_row)
        header = next(rows, ())
        columns = {
            index: f"{cell.value} [col. {index + 1}]"
            for index, cell in enumerate(header)
            if cell.value is not None and str(cell.value).strip()
        }
        data = []
        for row in rows:
            record = {}
            for index, name in columns.items():
                cell = row[index]
                value = cell.value
                if isinstance(value, (float, int)) and "%" in cell.number_format:
                    value *= 100
                record[name] = value
            if any(value is not None for value in record.values()):
                data.append(record)
        return list(columns.values()), data
    finally:
        workbook.close()


def read_csv(path):
    content = path.read_bytes()
    try:
        decoded = content.decode("utf-8-sig")
    except UnicodeDecodeError:
        decoded = content.decode("cp1252")
    lines = decoded.splitlines()
    if not lines:
        return [], []
    delimiter = ";" if lines[0].count(";") > lines[0].count(",") else ","
    reader = csv.DictReader(lines, delimiter=delimiter)
    return reader.fieldnames or [], list(reader)


def number(value, station=False):
    if value is None:
        raise ValueError("Celda vacía")
    value = str(value).strip().replace(",", ".")
    if station:
        value = value.lower().removesuffix("m").strip().replace("+", "")
    else:
        value = value.removesuffix("%").strip()
    return float(value)


def profile_points(data, station, slopes):
    points = []
    skipped = 0
    for record in data:
        point_count = len(points)
        try:
            progress = number(record[station], station=True)
        except ValueError:
            skipped += 1
            continue
        for lane in slopes:
            try:
                slope = number(record[lane])
            except ValueError:
                continue
            points.append({"Progresiva (m)": progress, "Pendiente (%)": slope, "Carril": lane})
        skipped += int(len(points) == point_count)
    return points, skipped


def show_excel(st, web_uploads=False):
    st.subheader("Datos de Civil 3D")
    uploaded = None
    if web_uploads:
        from web_inputs import upload_inputs

        uploaded = upload_inputs(st)
        if uploaded is None:
            return
        path = uploaded[0]
    else:
        route = st.text_input("Ruta de los datos de peraltes (.csv, .xlsx o .xlsm)", placeholder=r"C:\Proyecto\Peraltes.csv")
        if not route.strip():
            st.info("Pega la ruta completa del archivo guardado en este equipo.")
            return
        path = Path(route.strip().strip('"').strip("'")).expanduser()
    if path.suffix.lower() not in {".csv", ".xlsx", ".xlsm"} or not path.is_file():
        st.error("Error en los datos de peraltes. La ruta debe apuntar a un archivo existente .csv, .xlsx o .xlsm.")
        return
    try:
        if path.suffix.lower() == ".csv":
            columns, data = read_csv(path)
        else:
            sheets = read_sheet(path)
            sheet = st.selectbox("Hoja", sheets)
            header_row = st.number_input("Fila de encabezados", min_value=1, value=1)
            columns, data = read_sheet(path, sheet, header_row)
    except Exception as error:
        st.error(f"No se pudieron cargar los datos de peraltes: {error}")
        return
    if not columns or not data:
        st.warning("No hay datos bajo esa fila de encabezados.")
        return

    st.success(f"Datos de peraltes cargados: {path.name} · {len(data)} filas.")
    geometry = {}
    if path.suffix.lower() == ".csv":
        geometry = show_geometry(st, data, path, uploaded[1:] if uploaded else None)
        try:
            geometry = completed_geometry(path, geometry)
        except (OSError, ValueError, KeyError, TypeError) as error:
            st.error(f"No se pudieron leer las características guardadas: {error}")
        if geometry:
            regions = list(dict.fromkeys(row["Superelevation Region"] for row in data if row.get("Superelevation Region")))
            missing = [region for region in regions if geometry.get(region, {}).get("Vd") is None]
            if missing:
                st.warning(f"Vd disponible en {len(regions) - len(missing)} de {len(regions)} regiones. Pendientes: {', '.join(missing)}.")
        show_batch(st, columns, data, geometry)

    original_rows = data
    region = None
    if "Superelevation Region" in columns:
        regions = list(dict.fromkeys(row["Superelevation Region"] for row in data if row["Superelevation Region"]))
        region = st.selectbox("Región de peralte", [None, *regions], format_func=lambda value: "Todas" if value is None else f"Región {value}")
        if region is not None:
            data = [row for row in data if row["Superelevation Region"] == region]

    station_candidates = [
        name for name in columns
        if name.lower().split(" [col.")[0].strip() in
        {"station", "start station", "chainage", "progresiva", "estación", "estacion", "progresiva (m)"}
    ]
    station = st.selectbox("Columna de progresiva", columns, index=columns.index(station_candidates[0]) if station_candidates else None)
    slope_candidates = [
        name for name in columns
        if any(term in name.lower() for term in ("outside lane", "carril exterior", "pendiente (%)"))
        and "rate of change" not in name.lower()
    ]
    slopes = st.multiselect("Columnas de pendiente por carril", columns, default=slope_candidates)
    with st.expander("Vista previa de la hoja"):
        st.dataframe([{key: "" if value is None else str(value) for key, value in row.items()} for row in data[:25]], hide_index=True)
    if station is None or not slopes:
        st.info("Selecciona una columna de progresiva y al menos una de pendiente.")
        return
    if station in slopes:
        st.error("Selecciona columnas distintas para la progresiva y la pendiente.")
        return

    points, skipped = profile_points(data, station, slopes)
    if not points:
        st.warning("No se encontraron pares válidos de progresiva y pendiente en las columnas seleccionadas.")
        return
    points.sort(key=lambda point: point["Progresiva (m)"])
    audit = st.session_state.get("dg_batch")
    current = audit and audit[0] == original_rows and audit[2] == geometry
    if path.suffix.lower() == ".csv" and current:
        exported, changes, pending = export_preview(original_rows, audit[1], geometry, st.session_state.get("apply_reverse_links", False))
        applied = [
            change for change in changes
            if change["En el CSV"] == "Aplicado" and (region is None or change["Región"] == region)
        ]
        st.caption("Usa la rueda sobre cada gráfica para acercar o alejar. Arrastra para desplazarte y haz doble clic para restablecer la vista.")
        st.write(f"{len(applied)} estaciones corregidas en esta vista.")
        if applied:
            with st.expander("Ver cambios de progresiva y pendiente"):
                st.dataframe(applied, hide_index=True)
        corrected = []
        sections = []
        previous = None
        for row in sorted(exported, key=lambda item: number(item["Station"], station=True)):
            key = row["Superelevation Region"]
            if region is not None and key != region:
                continue
            status = "Pendiente · perfil original" if key in pending else "Verificada · perfil de salida"
            if not sections or sections[-1][0] != status:
                sections.append((status, [previous] if previous is not None else []))
            sections[-1][1].append(row)
            previous = row
        for section_number, (status, section) in enumerate(sections):
            section_points, _ = profile_points(section, station, slopes)
            corrected.extend({**point, "Tramo": section_number, "Estado": status} for point in section_points)
        all_points = points + corrected
        domains = [
            [min(row[key] for row in all_points), max(row[key] for row in all_points)]
            for key in ("Progresiva (m)", "Pendiente (%)")
        ]
        for title, series in (("Diagrama original", points), ("Diagrama de salida · verificadas y pendientes", corrected)):
            st.subheader(title)
            if title != "Diagrama original":
                st.caption("Verde: perfil verificado. Rojo: región pendiente, con las progresivas y pendientes originales.")
            chart = alt.Chart(alt.Data(values=series)).mark_line().encode(
                x=alt.X("Progresiva (m):Q", scale=alt.Scale(domain=domains[0], zero=False)),
                y=alt.Y("Pendiente (%):Q", scale=alt.Scale(domain=domains[1], zero=False)),
                tooltip=["Carril:N", "Progresiva (m):Q", "Pendiente (%):Q"],
            )
            if title == "Diagrama original":
                chart = chart.encode(color=alt.Color("Carril:N", scale=alt.Scale(domain=slopes, scheme="tableau10")))
            else:
                chart = chart.encode(
                    color=alt.Color("Estado:N", scale=alt.Scale(
                        domain=["Verificada · perfil de salida", "Pendiente · perfil original"],
                        range=["#087443", "#c32637"],
                    )),
                    strokeDash=alt.StrokeDash("Carril:N"),
                    detail="Tramo:N",
                    tooltip=["Estado:N", "Carril:N", "Progresiva (m):Q", "Pendiente (%):Q"],
                )
            if applied:
                position = "Progresiva original" if title == "Diagrama original" else "Progresiva propuesta"
                markers = [
                    {"Progresiva (m)": number(change[position], station=True),
                     "Estación crítica": change["Estación crítica"], "Región": str(change["Región"])}
                    for change in applied if change["Progresiva original"] != change["Progresiva propuesta"]
                ]
                lines = alt.Chart(alt.Data(values=markers)).mark_rule(
                    color="#64748b", strokeDash=[4, 4], opacity=0.65
                ).encode(
                    x=alt.X("Progresiva (m):Q", scale=alt.Scale(domain=domains[0], zero=False)),
                    tooltip=["Región:N", "Estación crítica:N", "Progresiva (m):Q"],
                )
                chart = chart + lines
            zoom = alt.selection_interval(
                name="zoom_progresiva", bind="scales", encodings=["x"], clear="dblclick"
            )
            st.altair_chart(chart.properties(height=300).add_params(zoom), width="stretch")
        if not applied:
            st.info("No se aplicaron cambios de progresiva ni de pendiente en esta vista.")
    else:
        st.subheader("Diagrama original")
        st.line_chart(points, x="Progresiva (m)", y="Pendiente (%)", color="Carril")
        if path.suffix.lower() == ".csv":
            st.info("Pulsa Revisar y corregir todo para mostrar la comparación.")
    st.caption(f"{len(points)} puntos trazados. Filas sin datos utilizables: {skipped}. Los valores numéricos sin formato de porcentaje se leen como puntos porcentuales.")
    st.dataframe(points, hide_index=True)




    if path.suffix.lower() == ".csv":
        from dg2018_csv import show_curve_summary

        show_curve_summary(st, path, region, geometry)
        if geometry and show_completion(st, path, geometry):
            st.session_state["recalculate_completed"] = True
            st.rerun()

















