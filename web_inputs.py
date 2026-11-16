from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryDirectory


def upload_inputs(st):
    peraltes = st.file_uploader("Peraltes de Civil 3D", type=["csv"])
    geometry = st.file_uploader("Diseño geométrico", type=["xlsx", "xlsm"])
    characteristics = st.file_uploader("Características de la carretera", type=["xlsx", "xlsm"])
    if not all((peraltes, geometry, characteristics)):
        st.info("Carga los tres archivos para empezar la revisión.")
        return None
    files = (peraltes, geometry, characteristics)
    fingerprint = tuple(sha256(file.getbuffer()).hexdigest() for file in files)
    previous = st.session_state.get("uploaded_civil_inputs")
    if previous and previous[0] == fingerprint:
        return previous[2]
    temp_dir = TemporaryDirectory(prefix="civil_peraltes_")
    root = Path(temp_dir.name)
    paths = tuple(root / f"{key}{Path(file.name).suffix.lower()}" for key, file in zip(
        ("peraltes", "geometria", "caracteristicas"), files
    ))
    for path, file in zip(paths, files):
        path.write_bytes(file.getbuffer())
    st.session_state["uploaded_civil_inputs"] = (fingerprint, temp_dir, paths)
    if previous:
        previous[1].cleanup()
    return paths

