import hashlib
import json
import math
from pathlib import Path
from tempfile import NamedTemporaryFile


def completion_file(csv_path):
    return csv_path.with_suffix(".caracteristicas_completadas.json")


def input_signature(csv_path):
    return hashlib.sha256(csv_path.read_bytes()).hexdigest()


def curve_identity(curve):
    return [curve.get(key) for key in ("Entidad", "PC o SC", "PT o CS")]


def valid_value(key, value):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        return False
    return 20 <= value <= 130 if key == "Vd" else value > 0


def completed_geometry(csv_path, geometry):
    path = completion_file(csv_path)
    if not geometry or not path.exists():
        return geometry
    data = json.loads(path.read_text(encoding="utf-8"))
    if data["csv_sha256"] != input_signature(csv_path):
        return geometry
    merged = {region: dict(curve) for region, curve in geometry.items()}
    for region, saved in data["regions"].items():
        curve = merged.get(region)
        if not curve or saved["identity"] != curve_identity(curve):
            continue
        for key, value in saved["values"].items():
            if key in ("Vd", "Calzada") and curve.get(key) is None and valid_value(key, value):
                curve[key] = value
                curve[f"{key} manual"] = True
    return merged


def save_completion(csv_path, geometry, updates):
    path = completion_file(csv_path)
    signature = input_signature(csv_path)
    data = {"csv_sha256": signature, "regions": {}}
    if path.exists():
        previous = json.loads(path.read_text(encoding="utf-8"))
        if previous["csv_sha256"] == signature:
            data = previous
    for region, values in updates.items():
        identity = curve_identity(geometry[region])
        saved = data["regions"].get(region)
        if not saved or saved["identity"] != identity:
            saved = {"identity": identity, "values": {}}
        saved["values"].update(values)
        data["regions"][region] = saved
    with NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as stream:
        temp = Path(stream.name)
        json.dump(data, stream, ensure_ascii=False, indent=2)
    try:
        temp.replace(path)
    finally:
        temp.unlink(missing_ok=True)


def show_completion(st, csv_path, geometry):
    missing = {
        region: {key for key in ("Vd", "Calzada") if curve.get(key) is None}
        for region, curve in geometry.items()
    }
    missing = {region: keys for region, keys in missing.items() if keys}
    if not missing:
        return False
    st.subheader("Completar características pendientes")
    st.caption("Vd en km/h. Calzada es la distancia del eje de giro a cada borde para giro central. Las celdas ya registradas se conservan.")
    width_values = {curve["Calzada"] for curve in geometry.values() if curve.get("Calzada") is not None}
    default_width = next(iter(width_values)) if len(width_values) == 1 else None
    rows = [
        {"Región": region, "Number / N° C": geometry[region]["Entidad"],
         "Radio geométrico (m)": geometry[region]["Radio (m)"],
         "Vd": None, "Calzada": default_width if "Calzada" in keys else None}
        for region, keys in missing.items()
    ]
    with st.form(f"complete:{csv_path}"):
        edited = st.data_editor(
            rows, hide_index=True, disabled=["Región", "Number / N° C", "Radio geométrico (m)"],
            column_config={
                "Vd": st.column_config.NumberColumn("Vd pendiente (km/h)", min_value=20.0, max_value=130.0, step=1.0),
                "Calzada": st.column_config.NumberColumn("Calzada pendiente (m)", min_value=0.01, step=0.01),
            },
        )
        _, corner = st.columns([4, 1])
        submitted = corner.form_submit_button("Guardar completado", type="primary")
    if not submitted:
        return False
    updates = {
        row["Región"]: {key: row[key] for key in missing[row["Región"]]}
        for row in edited
    }
    invalid = [
        f"{region} ({', '.join(sorted(key for key, value in values.items() if not valid_value(key, value)))})"
        for region, values in updates.items() if any(not valid_value(k, v) for k, v in values.items())
    ]
    if invalid:
        st.error("Completa los datos pendientes antes de guardar: " + ", ".join(invalid))
        return False
    try:
        save_completion(csv_path, geometry, updates)
    except (OSError, ValueError, KeyError) as error:
        st.error(f"No se pudieron guardar los datos completados: {error}")
        return False
    return True

