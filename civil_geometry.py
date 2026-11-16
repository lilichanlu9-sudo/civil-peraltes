from collections import defaultdict
from pathlib import Path

from openpyxl import load_workbook


def metres(value):
    return float(str(value).strip().lower().removesuffix("m").replace("+", "").replace(",", "."))


def read_workbook(path):
    workbook = load_workbook(path, read_only=True, data_only=True)
    try:
        return [list(sheet.values) for sheet in workbook]
    finally:
        workbook.close()


def load_geometry(path, records, characteristics_path=None):
    sheets = read_workbook(path)
    required = {"Number", "Type", "Start Station", "End Station", "Radius"}
    curves = []
    design = {}
    for values in sheets:
        groups = defaultdict(list)
        for i, row in enumerate(values):
            if required <= set(row):
                columns = {name: row.index(name) for name in required}
                for entity in values[i+1:]:
                    if entity[columns["Type"]] not in ("Curve", "Spiral-Curve-Spiral", "Spiral-Curve-Spiral-Spiral-Curve-Spiral"):
                        continue
                    groups[entity[columns["Number"]]].append((
                        entity[columns["Type"]], metres(entity[columns["Start Station"]]),
                        metres(entity[columns["End Station"]]), entity[columns["Radius"]],
                    ))
                break
        for key, elements in groups.items():
            elements.sort(key=lambda row: row[1])
            for index, (kind, start, end, radius) in enumerate(elements):
                if radius is None:
                    continue
                spiral = kind != "Curve"
                before = elements[index-1] if index else None
                after = elements[index+1] if index+1 < len(elements) else None
                curves.append({
                    "Entidad": key, "Tipo": "Circular simple" if not spiral else f"Espiral · arco {'≤' if end-start <= 30.000001 else '>'} 30 m",
                    "PC o SC": start, "PT o CS": end, "Longitud circular (m)": round(end-start, 3),
                    "TS": before[1] if spiral and before and before[3] is None else None,
                    "ST": after[2] if spiral and after and after[3] is None else None,
                    "Radio (m)": metres(radius),
                })
    for values in (read_workbook(characteristics_path) if characteristics_path else sheets):
        for i, row in enumerate(values):
            if {"Radio", "Vd", "Bombeo", "P%", "Calzada"} <= set(row):
                key_index = next((j for j, value in enumerate(row) if isinstance(value, str) and value.startswith("N")), None)
                if key_index is None:
                    continue
                for line in values[i+1:]:
                    key = line[key_index]
                    if key is None:
                        continue
                    try:
                        number = metres(key)
                        entry = {name: metres(str(line[row.index(name)]).rstrip("%")) for name in ("Radio", "Vd", "Bombeo", "P%", "Calzada")}
                        design.setdefault(number, []).append(entry)
                    except ValueError:
                        continue
    if characteristics_path and not design:
        raise ValueError("La hoja de características debe incluir N° C, Radio, Vd, Bombeo, P% y Calzada.")
    if not curves:
        raise ValueError("No se encontró una tabla de geometría horizontal con Number, Type, Start Station y End Station.")

    critical = defaultdict(dict)
    for row in records:
        if row.get("Superelevation Region") and row.get("Description") in ("Begin Full Super", "End Full Super"):
            critical[row["Superelevation Region"]][row["Description"]] = metres(row["Station"])
    matches = {}
    for region, dates in critical.items():
        if len(dates) != 2:
            continue
        midpoint = sum(dates.values()) / 2
        candidates = [curve for curve in curves if curve["PC o SC"] <= midpoint <= curve["PT o CS"]]
        if len(candidates) == 1:
            curve = candidates[0]
            entries = design.get(metres(curve["Entidad"]), [])
            exact = [entry for entry in entries if abs(entry["Radio"] - curve["Radio (m)"]) <= 0.001]
            candidates = exact or entries
            criteria = candidates[0] if candidates and all(entry == candidates[0] for entry in candidates) else {}
            design_radius = criteria.get("Radio", entries[0]["Radio"] if len(entries) == 1 else None)
            matches[region] = {**curve, "Radio de la tabla Vd (m)": design_radius, **{key: criteria.get(key) for key in ("Vd", "Bombeo", "P%", "Calzada")}}
    return matches


def show_geometry(st, records, csv_path, uploaded_paths=None):
    if uploaded_paths:
        path, characteristics_path = uploaded_paths
    else:
        route = st.text_input(
            "Ruta de los datos de diseño geométrico (.xlsx o .xlsm)",
            placeholder="Pega la ruta de data_CIVIL_3D.xlsx",
            key=f"manual_geometry_path:{csv_path}",
        )
        if not route.strip():
            st.info("Pendiente cargar los datos de diseño geométrico.")
            return {}
        path = Path(route.strip().strip('"').strip("'")).expanduser()
        if path.suffix.lower() not in {".xlsx", ".xlsm"} or not path.is_file():
            st.error("Error en los datos de diseño geométrico. La ruta debe apuntar a un archivo Excel existente.")
            return {}
        characteristics_route = st.text_input(
            "Ruta del Excel de características de la carretera (.xlsx o .xlsm)",
            placeholder="N° C, Radio, Vd, Bombeo, P% y Calzada",
            key=f"characteristics_path:{csv_path}",
        )
        characteristics_path = None
        if characteristics_route.strip():
            characteristics_path = Path(characteristics_route.strip().strip('"').strip("'")).expanduser()
            if characteristics_path.suffix.lower() not in {".xlsx", ".xlsm"} or not characteristics_path.is_file():
                st.error("La ruta de características debe apuntar a un Excel existente.")
                return {}
    try:
        geometry = load_geometry(path, records, characteristics_path)
    except PermissionError as error:
        st.error(f"No se pudo leer {Path(error.filename).name}. Si está abierto en Excel, guarda y cierra el archivo y vuelve a cargarlo.")
        return {}
    except Exception as error:
        st.error(f"No se pudieron cargar los datos de diseño geométrico: {error}")
        return {}
    total = len({row["Superelevation Region"] for row in records if row.get("Superelevation Region")})
    if not geometry:
        st.error(f"Se leyó {path.name}, pero ninguna región coincide por progresiva con los datos de peraltes.")
        return {}
    st.success(f"Datos de diseño geométrico cargados: {path.name}.")
    if characteristics_path:
        st.success(f"Características de la carretera cargadas: {characteristics_path.name}.")
    if len(geometry) == total:
        st.success(f"Ambos archivos cargados correctamente. Geometría vinculada a {total} de {total} regiones.")
    else:
        st.warning(f"Ambos archivos cargados. Se vinculó la geometría de {len(geometry)} de {total} regiones.")
    st.caption("Se asignan Vd y Calzada por Number ↔ N° C. Si hay varias filas con el mismo número, el radio permite distinguirlas cuando la coincidencia es única. Calzada se interpreta como distancia a cada borde para giro central. Las pendientes existentes se leen del CSV; P% del Excel se muestra como referencia.")
    different_radii = [
        region for region, row in geometry.items()
        if row["Vd"] is not None and abs(row["Radio (m)"] - row["Radio de la tabla Vd (m)"]) > 0.001
    ]
    if different_radii:
        st.warning("Radios distintos entre las fuentes en las regiones " + ", ".join(different_radii) + ". Se asignaron las características por número.")
    with st.expander("Datos de Civil 3D vinculados"):
        st.dataframe([{"Región": region, **values} for region, values in geometry.items()], hide_index=True)
    return geometry












