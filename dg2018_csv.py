import csv
from collections import defaultdict
from decimal import Decimal, ROUND_CEILING
from io import StringIO
import re
from curve_review import show_corrected_gallery, show_recommendations
from spiral_dg2018 import circular_positions, spiral_positions
from reverse_links import merge_reverse_links, show_reverse_links

REGION = "Superelevation Region"
STATION = "Station"
DESCRIPTION = "Description"
LEFT = "Left Outside Lane"
RIGHT = "Right Outside Lane"
HEADER = (
    REGION, STATION, DESCRIPTION, "Smoothing Curve Length", "Left Outside Shoulder",
    LEFT, "Left Inside Lane", "Left Inside Shoulder", "Right Outside Shoulder",
    RIGHT, "Right Inside Lane", "Right Inside Shoulder",
)
MM = Decimal("0.001")


def blocked_regions(message):
    prefix = message.split(":", 1)[0]
    return re.findall(r"\b\d+\b", prefix)


def station_text(value):
    kilometres, metres = divmod(value, Decimal(1000))
    return f"{int(kilometres)}+{metres:07.3f}m"


def audit_and_correct(columns, rows, speed, left_width, right_width, geometry=None, compact_regions=frozenset()):
    if tuple(columns) != HEADER:
        raise ValueError("La corrección requiere el CSV nativo de peraltes de Civil 3D.")
    geometry = geometry or {}

    stations = [Decimal(row[STATION].strip().lower().removesuffix("m").replace("+", "")) for row in rows]
    if any(not value.is_finite() or value < 0 for value in stations):
        raise ValueError("El archivo contiene progresivas no válidas.")
    groups = defaultdict(list)
    for index, row in enumerate(rows):
        if row[REGION]:
            groups[row[REGION]].append(index)
    if not groups:
        raise ValueError("El CSV no contiene regiones de peralte.")

    begin = [s for row, s in zip(rows, stations) if row[DESCRIPTION] == "Begin Alignment"]
    end = [s for row, s in zip(rows, stations) if row[DESCRIPTION] == "End Alignment"]
    if len(begin) != 1 or len(end) != 1 or begin[0] >= end[0]:
        raise ValueError("Se necesitan las progresivas válidas de inicio y fin del alineamiento.")

    proposed = stations.copy()
    proposed_slopes = {}
    reports = []
    blocks = []
    extents = []
    plans = {}
    for name, indexes in groups.items():
        criteria = geometry.get(name, {})
        design_speed = criteria.get("Vd") or speed
        if design_speed is None or not 20 <= design_speed <= 130:
            design_radius = criteria.get("Radio de la tabla Vd (m)")
            if design_radius is None:
                blocks.append(f"Región {name}: falta una velocidad de diseño vinculada a la entidad del Excel.")
            else:
                blocks.append(f"Región {name}: la tabla de características no permite asignar una Vd inequívoca.")
            continue
        width = criteria.get("Calzada")
        distances = (width, width) if width is not None else (left_width, right_width)
        if any(value is None or value <= 0 for value in distances):
            blocks.append(f"Región {name}: faltan las distancias al borde.")
            continue
        widths = [Decimal(str(value)) for value in distances]
        limit = Decimal("1.8") - Decimal("0.01") * Decimal(str(design_speed))
        is_spiral = criteria.get("Tipo", "").startswith("Espiral")
        is_circular = criteria.get("Tipo") == "Circular simple"
        if is_spiral or is_circular:
            sequence = ("End Normal Shoulder", "End Normal Crown", "Level Crown", "Reverse Crown",
                        "Begin Full Super", "End Full Super", "Reverse Crown", "Level Crown",
                        "Begin Normal Crown", "Begin Normal Shoulder")
            by_event = defaultdict(list)
            for index in sorted(indexes, key=stations.__getitem__):
                by_event[rows[index][DESCRIPTION]].append(index)
            if len(indexes) != len(sequence) or any(len(by_event[event]) != sequence.count(event) for event in sequence):
                blocks.append(f"Región {name}: la secuencia de estaciones críticas no coincide con la del perfil de dos carriles.")
                continue
            indexes[:] = [by_event[event].pop(0) for event in sequence]
        else:
            indexes.sort(key=stations.__getitem__)
        descriptions = [rows[i][DESCRIPTION] for i in indexes]
        if descriptions.count("Begin Full Super") != 1 or descriptions.count("End Full Super") != 1:
            blocks.append(f"Región {name}: falta identificar un único BFS y EFS.")
            continue
        bfs, efs = map(descriptions.index, ("Begin Full Super", "End Full Super"))
        if not 0 < bfs < efs < len(indexes) - 1:
            blocks.append(f"Región {name}: orden de estaciones críticas no reconocido.")
            continue
        slopes = [
            [Decimal(rows[i][key].strip().removesuffix("%")) for key in (LEFT, RIGHT)]
            for i in indexes
        ]
        original_slopes = slopes
        if is_spiral or is_circular:
            exterior = max(range(2), key=lambda side: original_slopes[bfs][side])
            bank_value = criteria.get("P%")
            crown_value = criteria.get("Bombeo")
            bank = abs(Decimal(str(bank_value))) if bank_value is not None else original_slopes[bfs][exterior]
            crown = abs(Decimal(str(crown_value))) if crown_value is not None else -original_slopes[1][exterior]
            if not bank.is_finite() or not crown.is_finite() or not 0 < crown <= bank:
                blocks.append(f"Región {name}: el bombeo y el peralte completo requieren otro esquema de transición.")
                continue
            pairs = [(-crown, -crown), (-crown, -crown), (Decimal(0), -crown),
                     (crown, -crown), (bank, -bank), (bank, -bank),
                     (crown, -crown), (Decimal(0), -crown), (-crown, -crown), (-crown, -crown)]
            slopes = [list(pair if exterior == 0 else reversed(pair)) for pair in pairs]
        required = []
        for before, after in zip(slopes, slopes[1:]):
            required.append(max(abs(b-a)*width/limit for a,b,width in zip(before,after,widths)).quantize(MM, rounding=ROUND_CEILING))
        if any(required[bfs:efs]):
            blocks.append(f"Región {name}: las pendientes cambian entre BFS y EFS.")
            continue
        if is_spiral:
            candidates, reason = spiral_positions(criteria, required, slopes, begin[0], end[0], compact=name in compact_regions)
            if not candidates:
                blocks.append(f"Región {name}: {reason}.")
                continue
        elif is_circular:
            candidates, reason = circular_positions(criteria, required, slopes, design_speed, begin[0], end[0])
            if not candidates:
                blocks.append(f"Región {name}: {reason}.")
                continue
        else:
            for j in range(bfs - 1, -1, -1):
                i, k = indexes[j:j+2]
                proposed[i] = min(stations[i], proposed[k] - required[j])
            for j in range(efs, len(indexes) - 1):
                i, k = indexes[j:j+2]
                proposed[k] = max(stations[k], proposed[i] + required[j])
            candidates = [[proposed[i] for i in indexes]]
        for index, original, target in zip(indexes, original_slopes, slopes):
            fields = {}
            for old, new, outside, inside in zip(original, target, (LEFT, RIGHT), ("Left Inside Lane", "Right Inside Lane")):
                if old != new:
                    fields[outside] = f"{new:.3f}%"
                    if rows[index][inside] == rows[index][outside]:
                        fields[inside] = fields[outside]
            if fields:
                proposed_slopes[index] = fields
        plans[name] = (indexes, candidates)
        for i, value in zip(indexes, candidates[0]):
            proposed[i] = value
        start, finish = proposed[indexes[0]], proposed[indexes[-1]]
        if start < begin[0] or finish > end[0]:
            blocks.append(f"Región {name}: la propuesta sale de los límites del alineamiento.")
        extents.append((start, finish, name))

        for j, (i, k) in enumerate(zip(indexes, indexes[1:])):
            current = stations[k] - stations[i]
            current_minimum = max(abs(a-b)*width/limit for a,b,width in zip(original_slopes[j],original_slopes[j+1],widths))
            candidate = proposed[k] - proposed[i]
            reports.append({
                "Región": name, "Vd (km/h)": design_speed, "B izq. (m)": float(widths[0]), "B der. (m)": float(widths[1]), "Desde": rows[i][DESCRIPTION], "Hasta": rows[k][DESCRIPTION],
                "Longitud actual (m)": float(current), "Mínimo (m)": float(required[j]),
                "Longitud propuesta (m)": float(candidate),
                "Inicio propuesto": str(proposed[i]), "Fin propuesto": str(proposed[k]),
                "Actual": "Cumple" if current >= current_minimum else "No cumple",
                "Propuesta": "Cumple" if candidate >= required[j] else "No cumple",
            })
    # Pick a nonoverlapping chain. Keeping the earliest feasible finish leaves
    # the largest possible interval for the next region.
    last_end = begin[0]
    ordered = sorted(plans.items(), key=lambda item: min(stations[i] for i in item[1][0]))
    chosen = {}
    for name, (indexes, candidates) in ordered:
        feasible = [candidate for candidate in candidates if candidate[0] >= last_end]
        if not feasible:
            feasible = candidates
        candidate = min(feasible, key=lambda profile: profile[-1])
        chosen[name] = candidate
        last_end = max(last_end, candidate[-1])
    if chosen:
        extents = []
        for name, (indexes, _) in ordered:
            candidate = chosen[name]
            for i, value in zip(indexes, candidate):
                proposed[i] = value
            extents.append((candidate[0], candidate[-1], name))
        offsets = defaultdict(int)
        for report in reports:
            name = report["Región"]
            index = offsets[name]
            first, last = chosen[name][index:index + 2]
            report.update({"Inicio propuesto": str(first), "Fin propuesto": str(last), "Longitud propuesta (m)": float(last - first)})
            offsets[name] += 1

    extents.sort()
    if extents:
        _, furthest, previous = extents[0]
        for start, finish, name in extents[1:]:
            if start < furthest:
                earliest_end = min(profile[-1] for profile in plans[previous][1])
                latest_start = max(profile[0] for profile in plans[name][1])
                residual = earliest_end - latest_start
                reason = f"las transiciones se solapan por {furthest - start:.3f} m"
                if residual > 0:
                    reason += f"; aun ajustando ambas progresivas, las alternativas probadas requieren {residual:.3f} m adicionales"
                else:
                    reason += "; el par admite alternativas por separado, pero la selección también debe encajar con las curvas vecinas"
                blocks.append(f"Regiones {previous} y {name}: {reason}.")
            if finish > furthest:
                furthest, previous = finish, name

    output = StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=columns)
    writer.writeheader()
    updated = []
    for index, (row, source, candidate) in enumerate(zip(rows, stations, proposed)):
        fields = dict(proposed_slopes.get(index, {}))
        if candidate != source and candidate >= 0:
            fields[STATION] = station_text(candidate)
        updated.append({**row, **fields})
    writer.writerows(updated)
    changed = sum(a != b for a,b in zip(rows, updated))
    return reports, blocks, changed, output.getvalue().encode("utf-8"), updated


def show_batch(st, columns, records, geometry):
    st.subheader("Revisar y corregir todas las regiones · DG-2018")
    st.caption("Comprueba el apartado 302.08 en ambos bordes. Usa la geometría para recolocar el peralte completo en clotoides cortas y busca una distribución que evite solapes.")
    with st.form("batch"):
        fallback_speed = any(not geometry.get(region, {}).get("Vd") for region in {r[REGION] for r in records if r.get(REGION)})
        fallback_width = any(not geometry.get(region, {}).get("Calzada") for region in {r[REGION] for r in records if r.get(REGION)})
        widths_in_book = {row["Calzada"] for row in geometry.values() if row.get("Calzada")}
        common_width = next(iter(widths_in_book)) if len(widths_in_book) == 1 else None
        a, b, c = st.columns(3)
        speed = a.number_input("Velocidad de respaldo (km/h)", 20.0, 130.0, value=None) if fallback_speed and not geometry else None
        left = b.number_input("Distancia de respaldo al borde izquierdo (m)", min_value=0.01, value=common_width) if fallback_width else None
        right = c.number_input("Distancia de respaldo al borde derecho (m)", min_value=0.01, value=common_width) if fallback_width else None
        third = st.checkbox("Carretera de tercera clase", key="batch_third_class")
        submitted = st.form_submit_button("Revisar y corregir todo", type="primary")
    completed = st.session_state.pop("recalculate_completed", False)
    if completed:
        st.success("Características completadas guardadas. Revisión recalculada con los datos guardados.")
    submitted = submitted or completed
    if not submitted and "dg_batch" not in st.session_state:
        return
    if submitted:
        st.session_state.pop("third_adjustment", None)
        st.session_state.pop("correction_history", None)
        st.session_state.pop("dg_batch", None)
        if third:
            st.warning("La corrección por lotes para tercera clase requiere la Tabla 302.13.")
            return
        try:
            st.session_state.dg_batch = (records, audit_and_correct(columns, records, speed, left, right, geometry), geometry)
            st.session_state["batch_inputs"] = (columns, speed, left, right)
            first = export_preview(records, st.session_state.dg_batch[1])
            st.session_state["correction_history"] = {1: (first[0], first[2])}
            st.session_state["first_correction_result"] = st.session_state.dg_batch[1]
            pending_count = len(first[2])
            st.toast(f"Primera revisión: {pending_count} regiones pendientes.")
        except (ValueError, ArithmeticError, KeyError, AttributeError) as error:
            st.error(f"No se pudo revisar el archivo: {error}")
            return
    source, result, source_geometry = st.session_state.dg_batch
    if source != records or source_geometry != geometry:
        return
    notice = st.session_state.pop("adjustment_notice", None)
    if notice:
        st.toast(notice)
    reports, blocks, changed, output, updated = result
    failures = [row for row in reports if row["Actual"] == "No cumple"]
    st.write(f"{len(reports)} intervalos revisados · {len(failures)} fuera del límite · {changed} estaciones con ajuste propuesto")
    if reports:
        st.dataframe(failures or reports, hide_index=True)
    adjusted_regions = list(dict.fromkeys(
        old[REGION] for old, new in zip(records, updated) if old != new
    ))
    if adjusted_regions:
        region = st.selectbox("Comparar perfil original y propuesto", adjusted_regions)
        chart = [
            {"Progresiva (m)": float(row[STATION].strip().lower().removesuffix("m").replace("+", "")),
             "Pendiente (%)": float(row[lane].strip().removesuffix("%")), "Serie": f"{label} · {side}"}
            for label, series in (("Original", records), ("Propuesta", updated))
            for row in series if row[REGION] == region
            for lane, side in ((LEFT, "Izquierdo"), (RIGHT, "Derecho"))
        ]
        st.line_chart(chart, x="Progresiva (m)", y="Pendiente (%)", color="Serie")
def show_curve_summary(st, path, selected_region, linked_geometry):
    from collections import Counter

    from excel_peraltes import read_csv

    _, records = read_csv(path)
    regions = list(dict.fromkeys(row[REGION] for row in records if row.get(REGION)))
    if not regions:
        return
    st.subheader("Resumen de curvas")
    audit = st.session_state.get("dg_batch")
    reports, blocks = audit[1][:2] if audit and audit[0] == records and audit[2] == linked_geometry else ([], [])
    count = Counter(row["Región"] for row in reports)
    failures = Counter(row["Región"] for row in reports if row["Actual"] == "No cumple")
    blocked = {region for message in blocks for region in blocked_regions(message)}
    second_applied = set()
    if audit and audit[0] == records and audit[2] == linked_geometry:
        _, changes, blocked = export_preview(
            records, audit[1], linked_geometry, st.session_state.get("apply_reverse_links", False)
        )
        second_applied = {row["Región"] for row in changes if row["En el CSV"] == "Aplicado" and row["Corrección"].startswith("Segunda")}
    summary = []
    for region in regions:
        linked = linked_geometry.get(region, {})
        kind = linked.get("Tipo", "Sin geometría vinculada")
        length = linked.get("Longitud circular (m)")
        state = (
            "Corregida · enlace conjunto" if region in second_applied else
            "Revisión geométrica" if region in blocked else
            "Sin evaluar" if not count[region] else
            "No cumple" if failures[region] else "Cumple por inclinación"
        )
        summary.append({
            "Región": region, "Number / N° C": linked.get("Entidad"), "Tipo": kind, "Longitud circular (m)": length,
            "Radio geométrico (m)": linked.get("Radio (m)"), "Radio de la tabla Vd (m)": linked.get("Radio de la tabla Vd (m)"), "Vd (km/h)": linked.get("Vd"), "Calzada (m)": linked.get("Calzada"), "Origen de Vd": "Completada" if linked.get("Vd manual") else "Excel" if linked.get("Vd") is not None else "Pendiente", "Intervalos revisados": count[region], "No cumplen": failures[region], "Estado": state,
        })

    st.dataframe(summary, hide_index=True)
    if selected_region is not None:
        detail = next(row for row in summary if row["Región"] == selected_region)
        st.write(f"Región {selected_region} · {detail['Tipo']} · {detail['Estado']}")
        intervals = [row for row in reports if row["Región"] == selected_region and row["Actual"] == "No cumple"]
        if intervals:
            st.dataframe(intervals, hide_index=True)
        if selected_region in blocked:
            for message in blocks:
                if selected_region in blocked_regions(message):
                    st.warning(message)





    if audit and audit[0] == records and audit[2] == linked_geometry:
        show_export_report(st, records, audit[1], linked_geometry)

def export_preview(records, result, geometry=None, second=False):

    _, blocks, _, _, proposed = result
    pending = {region for message in blocks for region in blocked_regions(message)}
    linked = set()
    if second and geometry:
        proposed, linked = merge_reverse_links(records, proposed, geometry, pending, station_text)
        pending.difference_update(linked)
    original_bounds = {}
    for row in records:
        region = row[REGION]
        if not region:
            continue
        position = Decimal(row[STATION].lower().replace("+", "").removesuffix("m"))
        lower, upper = original_bounds.get(region, (position, position))
        original_bounds[region] = min(lower, position), max(upper, position)

    adjusted = defaultdict(list)
    for position, (old, new) in enumerate(zip(records, proposed)):
        if old != new:
            adjusted[old[REGION]].append(position)
    # Validate against the actual output: neighboring regions may also move.
    candidate_bounds = {}
    for row in proposed:
        region = row[REGION]
        if not region:
            continue
        position = Decimal(row[STATION].lower().replace("+", "").removesuffix("m"))
        lower, upper = candidate_bounds.get(region, (position, position))
        candidate_bounds[region] = min(lower, position), max(upper, position)

    while True:
        active = set(adjusted) - pending
        bounds = [
            (low, high, region)
            for region in original_bounds
            for low, high in [candidate_bounds[region] if region in active else original_bounds[region]]
        ]
        bounds.sort()
        rejected = set()
        for index, (_, end, left_region) in enumerate(bounds):
            for start, _, right_region in bounds[index + 1:]:
                if start >= end:
                    break
                rejected.update({left_region, right_region} & active)
        if not rejected:
            break
        pending.update(rejected)

    exported = records.copy()
    changes = []
    for region, positions in adjusted.items():
        for index in positions:
            old, new = records[index], proposed[index]
            applied = region not in pending
            if applied:
                exported[index] = new
            changes.append({
                "Región": region, "Estación crítica": old[DESCRIPTION],
                "Progresiva original": old[STATION], "Progresiva propuesta": new[STATION],
                "Izquierdo original": old[LEFT], "Izquierdo corregido": new[LEFT],
                "Derecho original": old[RIGHT], "Derecho corregido": new[RIGHT],
                "En el CSV": "Aplicado" if applied else "Pendiente · conserva original",
                "Corrección": "Segunda · enlace conjunto" if region in linked else "Primera",
            })

    return exported, changes, pending


def show_export_report(st, records, result, geometry):
    base_pending = export_preview(records, result)[2]
    second = st.session_state.get("apply_reverse_links", False)
    exported, changes, pending = export_preview(records, result, geometry, second)
    blocks = result[1]
    st.subheader("Reporte de cambios y exportación")
    applied_count = sum(row["En el CSV"] == "Aplicado" for row in changes)
    st.write(f"{applied_count} estaciones corregidas · {len(pending)} regiones pendientes")
    if changes:
        st.dataframe(changes, hide_index=True)
    else:
        st.info("La descarga conserva todas las progresivas originales porque no se aplicaron cambios.")
    if pending:
        st.warning("Regiones pendientes: " + ", ".join(sorted(pending)) + ". Se conservan sus progresivas originales.")
        for block in blocks:
            if pending.intersection(blocked_regions(block)):
                st.write(block)

    show_recommendations(st, pending, blocks, geometry)

    output = StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=HEADER)
    writer.writeheader()
    writer.writerows(sorted(exported, key=lambda row: Decimal(row[STATION].lower().replace("+", "").removesuffix("m"))))
    st.download_button(
        "Descargar diagnóstico CSV" if pending else "Descargar CSV para importar a Civil 3D",
        output.getvalue().encode("utf-8"),
        file_name=("Peraltes_revisado_sin_cambios.csv" if not applied_count else
                   "Peraltes_DG2018_diagnostico.csv" if pending else "Peraltes_DG2018_corregido.csv"),
        mime="text/csv",
    )
    if pending:
        st.caption("El diagnóstico incluye regiones sin resolver. El CSV para importar queda pendiente hasta resolverlas.")
    else:
        st.caption("Prueba la importación en una copia del DWG. Civil 3D sustituye los datos de peralte del alineamiento.")
    history = st.session_state.setdefault("correction_history", {})
    if not history:
        first = export_preview(records, result)
        history[1] = first[0], first[2]
        st.session_state["first_correction_result"] = result
    if second and 2 not in history:
        stage_two = export_preview(records, st.session_state["first_correction_result"], geometry, True)
        history[2] = stage_two[0], stage_two[2]
    show_corrected_gallery(st, history, geometry)
    show_reverse_links(st, records, result[4], geometry, base_pending,
                       lambda enabled: len(export_preview(records, result, geometry, enabled)[2]))
    show_third_adjustment(st, records, geometry, result, pending, second)

def show_third_adjustment(st, records, geometry, result, pending, second):
    if not pending or "batch_inputs" not in st.session_state:
        return
    st.subheader("Tercera corrección · probar aplanamientos más cortos")
    st.caption(
        "Se recalcula el aplanamiento de las curvas con espirales hasta su mínimo por inclinación. "
        "Los cambios que requieren rediseñar radios o espirales se mantienen como recomendaciones."
    )
    groups = []
    covered = set()
    for message in result[1]:
        group = set(blocked_regions(message)) & pending
        if group:
            groups.append(tuple(sorted(group)))
            covered.update(group)
    groups.extend((region,) for region in sorted(pending - covered))
    groups = list(dict.fromkeys(groups))
    selection = st.selectbox(
        "Caso a recalcular",
        [(), *groups],
        format_func=lambda group: "Todas las regiones pendientes" if not group else "Regiones " + " y ".join(group),
    )
    if not st.button("Aplicar tercera corrección"):
        return
    target = set(selection) if selection else set(pending)
    # Try the same change on each adjacent counterpart named in a conflict.
    for message in result[1]:
        involved = set(blocked_regions(message))
        if involved & target:
            target.update(involved)
    eligible = {region for region in target if geometry.get(region, {}).get("Tipo", "").startswith("Espiral")}
    if not eligible:
        st.toast(f"Este caso necesita un ajuste de geometría. Quedan {len(pending)} regiones pendientes.")
        return
    columns, speed, left, right = st.session_state["batch_inputs"]
    prior = set(st.session_state.get("third_adjustment", ()))
    best = None
    best_pending = pending
    attempts = [eligible, *({region} for region in sorted(eligible))]
    for attempt in attempts:
        compact = prior | attempt
        trial = audit_and_correct(columns, records, speed, left, right, geometry, compact_regions=compact)
        _, _, trial_pending = export_preview(records, trial, geometry, second)
        if trial_pending < pending and len(trial_pending) < len(best_pending):
            best = (trial, compact)
            best_pending = trial_pending
    if best is None:
        unchanged = export_preview(records, result, geometry, second)
        st.session_state["correction_history"][3] = unchanged[0], unchanged[2]
        st.toast(f"El ajuste probado no liberó regiones sin generar otros conflictos. Quedan {len(pending)} pendientes.")
        return
    trial, compact = best
    st.session_state.dg_batch = (records, trial, geometry)
    snapshot = export_preview(records, trial, geometry, second)
    st.session_state["correction_history"][3] = snapshot[0], snapshot[2]
    st.session_state["third_adjustment"] = compact
    st.session_state["adjustment_notice"] = (
        f"Tercera corrección: {len(pending) - len(best_pending)} regiones resueltas. "
        f"Quedan {len(best_pending)} pendientes."
    )
    st.rerun()




