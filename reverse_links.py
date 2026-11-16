from collections import defaultdict
from decimal import Decimal, ROUND_CEILING, ROUND_FLOOR

from link_figure import link_figure


LANES = ("Left Outside Lane", "Right Outside Lane")
SHOULDERS = (
    "Left Outside Shoulder", "Left Inside Shoulder",
    "Right Outside Shoulder", "Right Inside Shoulder",
)


def decimal_value(value):
    return Decimal(str(value).strip().lower().removesuffix("m").removesuffix("%").replace("+", ""))


def circular_entry_link(zero, pc, bfs, slopes, limit, width):
    from spiral_dg2018 import circular_tangent_fraction

    bank = max(map(abs, slopes))
    if not zero < pc < bfs or bank < 2:
        return None
    fraction = circular_tangent_fraction(bank)
    at_pc = [slope * fraction for slope in slopes]
    first = width * bank * fraction / (pc - zero)
    second = width * bank * (1 - fraction) / (bfs - pc)
    if bank * fraction >= 2:
        to_two = (pc - zero) * 2 / (bank * fraction)
    else:
        to_two = pc - zero + (bfs - pc) * (2 - bank * fraction) / (bank * (1 - fraction))
    if max(first, second) > limit or to_two > 20:
        return None
    return at_pc, max(first, second), to_two


def reverse_links(records, proposed, geometry, pending, accepted=None, short_tangents=False):
    """Evaluate shared spiral junctions after the independent adjustment."""
    original = defaultdict(list)
    adjusted = defaultdict(dict)
    for before, after in zip(records, proposed):
        region = before["Superelevation Region"]
        original[region].append(before)
        adjusted[region][after["Description"]] = after

    ordered = sorted(geometry, key=lambda region: geometry[region]["PC o SC"])
    reports = []
    profiles = {}
    for left, right in zip(ordered, ordered[1:]):
        if not {left, right} <= pending:
            continue
        a, b = geometry[left], geometry[right]
        mixed = short_tangents and b["Tipo"] == "Circular simple"
        if not a["Tipo"].startswith("Espiral") or a.get("ST") is None:
            continue
        if not mixed and (not b["Tipo"].startswith("Espiral") or b.get("TS") is None):
            continue
        tangent_start = decimal_value(a["ST"])
        tangent_end = decimal_value(b["PC o SC"] if mixed else b["TS"])
        tangent_length = tangent_end - tangent_start
        if tangent_length < 0 or (tangent_length != 0 and not short_tangents):
            continue
        if short_tangents and tangent_length > 20:
            continue
        zero = ((tangent_start + tangent_end) / 2).quantize(Decimal("0.001"))
        name = f"C{a['Entidad']} · región {left} → C{b['Entidad']} · región {right}"
        report = {"Enlace": name, "Tangente entre clotoides (m)": float(tangent_length), "Progresiva 0 % (m)": float(zero)}
        reports.append(report)
        events = ("Begin Full Super", "End Full Super")
        if any(event not in adjusted[region] for region in (left, right) for event in events):
            report["Resultado"] = "Faltan estaciones de peralte completo."
            continue
        if any(len({r[column] for region in (left, right) for r in original[region]}) != 1 for column in SHOULDERS):
            report["Resultado"] = "Las bermas cambian. Se requiere un perfil de enlace para ellas."
            continue
        if any(g.get(key) is None or not decimal_value(g[key]).is_finite() or decimal_value(g[key]) <= 0
               for g in (a, b) for key in ("Vd", "Calzada")):
            report["Resultado"] = "Faltan velocidad o distancia al borde."
            continue

        first, last = (adjusted[left][event] for event in events)
        next_first, next_last = (adjusted[right][event] for event in events)
        x1, x2, x3, x4 = [decimal_value(row["Station"]) for row in (first, last, next_first, next_last)]
        left_slope = [decimal_value(last[lane]) for lane in LANES]
        right_slope = [decimal_value(next_first[lane]) for lane in LANES]
        if any(u * v >= 0 for u, v in zip(left_slope, right_slope)):
            report["Resultado"] = "El enlace no es una inversión de peralte en ambos carriles."
            continue
        if any([decimal_value(row[lane]) for lane in LANES] != target
               for row, target in ((first, left_slope), (next_last, right_slope))):
            report["Resultado"] = "El peralte completo cambia dentro de uno de los arcos."
            continue
        report.update({
            "BFS 1 (m)": float(x1), "EFS 1 (m)": float(x2),
            "BFS 2 (m)": float(x3), "EFS 2 (m)": float(x4),
            "Peralte completo 1 (m)": float(x2 - x1),
            "Peralte completo 2 (m)": float(x4 - x3),
        })
        right_minimum = decimal_value(b["Vd"]) / Decimal("3.6") if mixed else Decimal(30)
        if not (x2 - x1 >= 30 and x4 - x3 >= right_minimum and x2 < zero < x3):
            report["Resultado"] = "El peralte completo es demasiado corto o el cero queda fuera del enlace."
            continue
        left_covers = x1 <= decimal_value(a["PC o SC"]) < decimal_value(a["PT o CS"]) <= x2
        pc, pt = decimal_value(b["PC o SC"]), decimal_value(b["PT o CS"])
        right_covers = pc < x3 < x4 < pt if mixed else x3 <= pc < pt <= x4
        if not (left_covers and right_covers):
            report["Resultado"] = "El peralte completo debe cubrir ambos arcos circulares."
            continue
        if tangent_length > 0 and not mixed:
            # The feasible zero station is the intersection of the tangent
            # and each ramp's minimum and maximum lengths.
            bank_a, bank_b = max(map(abs, left_slope)), max(map(abs, right_slope))
            min_a = decimal_value(a["Calzada"]) * bank_a / (Decimal("1.8") - Decimal("0.01") * decimal_value(a["Vd"]))
            min_b = decimal_value(b["Calzada"]) * bank_b / (Decimal("1.8") - Decimal("0.01") * decimal_value(b["Vd"]))
            lower = max(tangent_start, x2 + min_a, x3 - 10 * bank_b).quantize(Decimal("0.001"), rounding=ROUND_CEILING)
            upper = min(tangent_end, x3 - min_b, x2 + 10 * bank_a).quantize(Decimal("0.001"), rounding=ROUND_FLOOR)
            if lower > upper:
                report["Resultado"] = f"No hay progresiva factible para el 0 %. Faltan {lower - upper:.3f} m."
                continue
            zero = min(upper, max(lower, zero))
            report["Progresiva 0 % (m)"] = float(zero)
        pc_point = []
        if mixed:
            limit_a, limit_b = [Decimal("1.8") - Decimal("0.01") * decimal_value(g["Vd"]) for g in (a, b)]
            width_a, width_b = (decimal_value(g["Calzada"]) for g in (a, b))
            bank_a = max(map(abs, left_slope))
            lower = max(tangent_start, x2 + width_a * bank_a / limit_a).quantize(Decimal("0.001"), rounding=ROUND_CEILING)
            upper = min(tangent_end - Decimal("0.001"), x2 + 10 * bank_a).quantize(Decimal("0.001"), rounding=ROUND_FLOOR)
            candidates = [lower, min(upper, max(lower, zero)), upper] if lower <= upper else []
            for candidate in sorted(set(candidates), key=lambda value: abs(value - zero)):
                right_result = circular_entry_link(candidate, pc, x3, right_slope, limit_b, width_b)
                if right_result:
                    zero = candidate
                    at_pc, right_gradient, right_to_two = right_result
                    pc_point = [(pc, at_pc)]
                    report["Progresiva 0 % (m)"] = float(zero)
                    report["PC (m)"] = float(pc)
                    report["Peralte en PC (%)"] = float(max(map(abs, at_pc)))
                    break
            if not pc_point:
                report["Resultado"] = "No se encontró un enlace que conserve la proporción de peralte en PC y los mínimos de rampa."
                continue
        legs = ((a, zero - x2, left_slope), (b, x3 - zero, right_slope))
        gradient = []
        distance_to_two = []
        limits = []
        for curve, length, slopes in legs:
            bank = max(map(abs, slopes))
            gradient.append(decimal_value(curve["Calzada"]) * bank / length)
            distance_to_two.append(length * 2 / bank if bank >= 2 else Decimal("Infinity"))
            limits.append(Decimal("1.8") - Decimal("0.01") * decimal_value(curve["Vd"]))
        if pc_point:
            gradient[1] = right_gradient
            distance_to_two[1] = right_to_two
        report.update({
            "Inclinación borde 1 (%)": round(float(gradient[0]), 3),
            "Inclinación borde 2 (%)": round(float(gradient[1]), 3),
            "Límite 1 (%)": float(limits[0]), "Límite 2 (%)": float(limits[1]),
            "Distancia 0 a 2 % lado 1 (m)": round(float(distance_to_two[0]), 3),
            "Distancia 0 a 2 % lado 2 (m)": round(float(distance_to_two[1]), 3),
            "Progresiva −2/2 % lado 1 (m)": float(zero - distance_to_two[0]),
            "Progresiva −2/2 % lado 2 (m)": float(zero + distance_to_two[1]),
        })
        if any(value > limit for value, limit in zip(gradient, limits)) or max(distance_to_two) > 20:
            report["Resultado"] = "La rampa lineal excede el límite de inclinación o los 20 m entre 0 % y 2 %."
            continue
        report["Resultado"] = "Pasa las comprobaciones del enlace · falta validación de drenaje e importación"
        profiles[name] = [(x1, left_slope), (x2, left_slope), (zero, [0, 0]), *pc_point, (x3, right_slope), (x4, right_slope)]
        if accepted is not None:
            accepted.append((left, right, profiles[name]))

    return reports, profiles


def show_reverse_links(st, records, proposed, geometry, pending, pending_count):
    if not pending:
        return
    def notify():
        enabled = st.session_state["apply_reverse_links"]
        st.session_state["adjustment_notice"] = (
            f"Segunda corrección {'activada' if enabled else 'desactivada'}. "
            f"Quedan {pending_count(enabled)} regiones pendientes."
        )

    st.info("Calcula una transición conjunta para curvas consecutivas de sentido contrario. Comprueba el cruce por 0 % y la inclinación relativa de ambos bordes.")
    if not st.toggle("② Aplicar segunda corrección", key="apply_reverse_links", on_change=notify):
        return
    st.subheader("Segunda corrección · curvas consecutivas")
    st.caption("Prueba enlaces de sentido contrario con clotoides contiguas y bermas constantes. Conserva Vd y los peraltes de diseño.")
    reports, profiles = reverse_links(records, proposed, geometry, pending)
    if not reports:
        st.info("No se encontraron pares pendientes con un punto ST/TS común.")
        return
    st.dataframe(reports, hide_index=True)
    if profiles:
        selected = st.selectbox("Ver enlace conjunto", list(profiles))
        report = next(row for row in reports if row["Enlace"] == selected)
        st.pyplot(link_figure(selected, profiles[selected], report), width="stretch")
        st.caption(
            f"Inclinación relativa de los bordes: {report['Inclinación borde 1 (%)']:.3f} % y "
            f"{report['Inclinación borde 2 (%)']:.3f} %. Límites: "
            f"{report['Límite 1 (%)']:.3f} % y {report['Límite 2 (%)']:.3f} %."
        )
    st.info("Los enlaces incorporados aparecen en la gráfica y en el CSV de diagnóstico. Verifica el drenaje en el punto de pendiente cero y prueba la importación en una copia del DWG.")



def merge_reverse_links(records, proposed, geometry, pending, station_text, short_tangents=False):
    accepted = []
    reverse_links(records, proposed, geometry, pending, accepted, short_tangents)
    merged = [dict(row) for row in proposed]
    indexes = defaultdict(list)
    for index, row in enumerate(merged):
        if row["Superelevation Region"]:
            indexes[row["Superelevation Region"]].append(index)
    applied = set()
    for left, right, profile in accepted:
        if not short_tangents and {left, right} & applied:
            continue
        (left_end, left_slopes), (zero, _) = profile[1:3]
        right_start, right_slopes = profile[-2]
        pc_point = profile[3] if len(profile) == 6 else None
        left_rows = [i for i in indexes[left] if decimal_value(merged[i]["Station"]) > left_end]
        right_rows = [i for i in indexes[right] if decimal_value(merged[i]["Station"]) < right_start]
        if not left_rows or not right_rows or (pc_point is not None and len(right_rows) < 2):
            continue
        for leg, start, end, start_slopes, end_slopes, offset in (
            (left_rows, left_end, zero, left_slopes, (0, 0), 1),
            (right_rows, zero, right_start, (0, 0), right_slopes, 0),
        ):
            leg.sort(key=lambda idx: decimal_value(merged[idx]["Station"]))
            for order, idx in enumerate(leg):
                fraction = Decimal(order + offset) / len(leg)
                station = (start + (end - start) * fraction).quantize(Decimal("0.001"))
                if station == zero and offset == 0:
                    station += Decimal("0.001")
                if offset == 0 and pc_point is not None:
                    pc, at_pc = pc_point
                    if order == 0:
                        station = zero + Decimal("0.001")
                    elif order == 1:
                        station = pc
                    else:
                        station = (pc + (end - pc) * Decimal(order - 1) / (len(leg) - 1)).quantize(Decimal("0.001"))
                    if station <= pc:
                        fraction = (station - zero) / (pc - zero)
                        section = (start_slopes, at_pc)
                    else:
                        fraction = (station - pc) / (end - pc)
                        section = (at_pc, end_slopes)
                else:
                    fraction = (station - start) / (end - start)
                    section = (start_slopes, end_slopes)
                row = merged[idx]
                row.update({"Station": station_text(station), "Description": "Manual Station", "Smoothing Curve Length": "0.000"})
                for lane, before, after, inside in zip(LANES, *section, ("Left Inside Lane", "Right Inside Lane")):
                    value = f"{before + fraction * (after - before):.6f}%"
                    if records[idx][inside] == records[idx][lane]:
                        row[inside] = value
                    row[lane] = value
        applied.update((left, right))
    return merged, applied





