from decimal import Decimal, ROUND_CEILING, ROUND_FLOOR

MM = Decimal("0.001")


def mm(value, rounding):
    return value.quantize(MM, rounding=rounding)


def spiral_positions(curve, required, slopes, alignment_start, alignment_end, compact=False):
    """Search valid placements of the 30 m plateau in the adjacent spirals."""
    if any(curve.get(key) is None for key in ("TS", "PC o SC", "PT o CS", "ST")):
        return [], "faltan las progresivas TS, SC, CS o ST"
    ts, sc, cs, st = (Decimal(str(curve[key])) for key in ("TS", "PC o SC", "PT o CS", "ST"))
    if not ts < sc < cs < st:
        return [], "las progresivas TS, SC, CS y ST no están en orden"
    gap = max(Decimal(0), Decimal(30) - (cs - sc))
    lower = max(Decimal(0), gap - (st - cs - sum(required[5:7])))
    upper = min(gap, sc - ts - sum(required[2:4]))
    lower = mm(lower, ROUND_CEILING)
    upper = mm(upper, ROUND_FLOOR)
    if lower > upper:
        return [], "las espirales no tienen longitud suficiente para la transición y el peralte completo"

    # For a fixed plateau length every movable progressiva is affine in the entry shift.
    # Try the symmetric placement first, then the extremes and intermediate placements.
    midpoint = min(upper, max(lower, mm(gap / 2, ROUND_CEILING)))
    shifts = list(dict.fromkeys([midpoint, lower, upper, *(
        mm(lower + (upper - lower) * i / 16, ROUND_CEILING) for i in range(1, 16)
    )]))
    profiles = []
    for shift in shifts:
        bfs, efs = sc - shift, cs + gap - shift
        entry_runoff, exit_runoff = bfs - ts, st - efs
        if min(entry_runoff, exit_runoff) <= 0:
            continue
        exterior = max(range(2), key=lambda side: slopes[4][side])
        bank = slopes[4][exterior]
        crown = -slopes[1][exterior]
        if not 0 < crown <= bank:
            return [], "se requiere un esquema distinto porque el peralte completo es menor que el bombeo"
        # In a single carriageway the tangent runout can use its own
        # gradient if the proportional length exceeds the 20 m limit.
        max_runout = Decimal(20)
        entry_runout = max(required[1], min(max_runout, mm(entry_runoff * crown / bank, ROUND_CEILING)))
        exit_runout = max(required[7], min(max_runout, mm(exit_runoff * crown / bank, ROUND_CEILING)))
        if compact:
            entry_runout, exit_runout = max(MM, required[1]), max(MM, required[7])
        if max(entry_runout, exit_runout) > 20:
            continue
        entry_rc = ts + mm(entry_runoff * crown / bank, ROUND_CEILING)
        exit_rc = st - mm(exit_runoff * crown / bank, ROUND_CEILING)
        a, z = ts - entry_runout, st + exit_runout
        profile = [a - required[0], a, ts, entry_rc, bfs, efs, exit_rc, st, z, z + required[8]]
        if profile[0] < alignment_start or profile[-1] > alignment_end:
            continue
        if any(after - before < need for before, after, need in zip(profile, profile[1:], required)):
            continue
        profiles.append(profile)
    return profiles, "ninguna distribución probada satisface las longitudes mínimas dentro de la geometría"



def circular_positions(curve, required, slopes, speed, alignment_start, alignment_end):
    """Place a circular curve's linear transitions relative to PC and PT."""
    pc, pt = (Decimal(str(curve[key])) for key in ("PC o SC", "PT o CS"))
    exterior = max(range(2), key=lambda side: slopes[4][side])
    bank = slopes[4][exterior]
    if bank <= 0 or slopes[4] != slopes[5]:
        return [], "el perfil no conserva una pendiente constante en peralte completo"
    fraction = Decimal("0.5") if bank < Decimal("4.5") else Decimal("0.7") if bank <= 7 else Decimal("0.8")
    pc_slope = fraction * bank

    ramps = (slopes[1:5], list(reversed(slopes[5:9])))
    gradients = []
    for ramp, requirements in zip(ramps, (required[1:4], list(reversed(required[5:8])))):
        changes = [after[exterior] - before[exterior] for before, after in zip(ramp, ramp[1:])]
        if any(change < 0 or (change == 0 and need > 0) for change, need in zip(changes, requirements)):
            return [], "la secuencia de pendientes requiere redefinir las estaciones críticas"
        gradients.append(max((need / change for need, change in zip(requirements, changes) if change), default=Decimal(0)))
    entry_scale, exit_scale = gradients
    # Increase the ramp scale slightly where millimetre rounding would
    # otherwise leave an interval shorter than its computed minimum.
    scales = [Decimal("1"), Decimal("1.001"), Decimal("1.005"), Decimal("1.02")]
    minimum_full = mm(Decimal(str(speed)) / Decimal("3.6"), ROUND_CEILING)
    profiles = []
    best_full = None
    for factor in scales:
        ins = [mm(pc + (pair[exterior] - pc_slope) * entry_scale * factor, ROUND_CEILING) for pair in ramps[0]]
        outs = [mm(pt - (pair[exterior] - pc_slope) * exit_scale * factor, ROUND_FLOOR) for pair in reversed(ramps[1])]
        full = outs[0] - ins[-1]
        best_full = full if best_full is None else max(best_full, full)
        profile = [ins[0] - required[0], *ins, *outs, outs[-1] + required[8]]
        if full < minimum_full or profile[0] < alignment_start or profile[-1] > alignment_end:
            continue
        if all(after - before >= need for before, after, need in zip(profile, profile[1:], required)):
            profiles.append(profile)
    if best_full is not None and best_full < minimum_full:
        return [], f"con la distribución aplicada solo quedan {max(0, best_full):.3f} m de peralte completo y se requieren {minimum_full:.3f} m"
    return profiles, "ninguna distribución circular probada satisface las longitudes mínimas"



