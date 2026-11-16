import numpy as np
import plotly.graph_objects as go


def station_m(row):
    return float(row["Station"].lower().replace("+", "").removesuffix("m"))


def road_figure(rows, geometry, colors):
    width = geometry.get("Calzada")
    radius = geometry.get("Radio (m)")
    start = geometry.get("PC o SC")
    end = geometry.get("PT o CS")
    if not width or not radius or start is None or end is None or start >= end:
        return None
    spiral = geometry.get("Tipo", "").startswith("Espiral")
    ts, st = geometry.get("TS"), geometry.get("ST")
    if spiral and (ts is None or st is None or not ts < start < end < st):
        return None

    # Duplicate stations with different slopes cannot define one continuous surface.
    sections = {}
    for row in rows:
        slopes = tuple(float(row[column].removesuffix("%")) for column in ("Left Outside Lane", "Right Outside Lane"))
        station = station_m(row)
        if station in sections and sections[station] != slopes:
            return None
        sections[station] = slopes
    critical = sorted(sections)
    if len(critical) < 2:
        return None
    full = next((row for row in rows if row["Description"] == "Begin Full Super"), None)
    if full is None:
        return None
    left_bank, right_bank = sections[station_m(full)]
    if left_bank * right_bank >= 0:
        return None
    turn = -1 if left_bank > 0 else 1

    lower, upper = critical[0], critical[-1]
    breaks = [station for station in (ts, start, end, st) if station is not None and lower <= station <= upper]
    stations = np.unique([*critical, *breaks, *np.linspace(lower, upper, 240)])
    mid = (stations[:-1] + stations[1:]) / 2
    curvature = np.where((mid >= start) & (mid <= end), 1 / radius, 0)
    if spiral:
        curvature = np.where((mid >= ts) & (mid < start), (mid - ts) / ((start - ts) * radius), curvature)
        curvature = np.where((mid > end) & (mid <= st), (st - mid) / ((st - end) * radius), curvature)
    step = np.diff(stations)
    angle_steps = turn * curvature * step
    headings = np.r_[0, np.cumsum(angle_steps)]
    mid_heading = headings[:-1] + angle_steps / 2
    x = np.r_[0, np.cumsum(np.cos(mid_heading) * step)]
    y = np.r_[0, np.cumsum(np.sin(mid_heading) * step)]
    nx, ny = -np.sin(headings), np.cos(headings)
    left, right = np.array([sections[station] for station in critical]).T
    edge_slopes = [np.interp(stations, critical, values) for values in (left, right)]
    left_z, right_z = [width * values / 100 for values in edge_slopes]
    center_z = np.zeros_like(stations)
    edges = ((x + width * nx, y + width * ny, left_z), (x - width * nx, y - width * ny, right_z))

    figure = go.Figure()
    for edge, color, name, slopes in zip(edges, colors, ("Borde izquierdo", "Borde derecho"), edge_slopes):
        ex, ey, ez = edge
        figure.add_surface(
            x=[x, ex], y=[y, ey], z=[center_z, ez], colorscale=[[0, color], [1, color]],
            surfacecolor=np.zeros((2, len(stations))), showscale=False, opacity=0.78, hoverinfo="skip",
        )
        figure.add_scatter3d(x=ex, y=ey, z=ez, mode="lines", line={"color": color, "width": 4},
                             name=name, customdata=np.column_stack((stations, slopes)),
                             hovertemplate="Progresiva %{customdata[0]:.3f} m<br>Pendiente del carril: %{customdata[1]:+.2f} %<br>Cota al eje: %{z:+.3f} m<extra>%{fullData.name}</extra>")
    figure.add_scatter3d(x=x, y=y, z=center_z, mode="lines", line={"color": "#edb836", "width": 4},
                         name="Eje de calzada", hoverinfo="skip")
    figure.update_layout(
        height=320, margin={"l": 0, "r": 0, "t": 0, "b": 0},
        legend={"orientation": "h", "y": 1},
        scene={"xaxis_title": "X local (m)", "yaxis_title": "Y local (m)", "zaxis_title": "Cota al eje (m)",
               "aspectmode": "data", "camera": {"eye": {"x": 1.3, "y": -1.7, "z": 0.9}}},
    )
    return figure


def interactive_road(rows, geometry, colors):
    figure = road_figure(rows, geometry, colors)
    if figure is None:
        return None
    labels = {"End Normal Crown": "ENC", "Level Crown": "LC", "Begin Full Super": "BFS",
              "End Full Super": "EFS", "Begin Normal Crown": "BNC"}
    left, right, center = figure.data[1], figure.data[3], figure.data[4]
    stations = np.asarray(left.customdata)[:, 0]
    sections = {}
    for row in rows:
        position = station_m(row)
        sections.setdefault(position, []).append(row["Description"])
    indices = [int(np.argmin(abs(stations - position))) for position in sorted(sections)]
    x_lines, y_lines, z_lines = [], [], []
    for i in indices:
        x_lines += [left.x[i], center.x[i], right.x[i], None]
        y_lines += [left.y[i], center.y[i], right.y[i], None]
        z_lines += [left.z[i], center.z[i], right.z[i], None]
    figure.add_scatter3d(x=x_lines, y=y_lines, z=z_lines, mode="lines",
                         line={"color": "#64748b", "width": 2}, name="Secciones críticas", hoverinfo="skip")
    for edge, color in zip((left, right), colors):
        text = []
        hover = []
        for i in indices:
            names = sections[stations[i]]
            label = next((labels[name] for name in names if name in labels), "")
            slope = edge.customdata[i][1]
            text.append(f"{label} {slope:+.2f} %" if label else "")
            hover.append(" / ".join(names))
        figure.add_scatter3d(
            x=[edge.x[i] for i in indices], y=[edge.y[i] for i in indices], z=[edge.z[i] for i in indices],
            mode="markers+text", text=text, textposition="top center", textfont={"color": color, "size": 10},
            marker={"size": 3, "color": color}, customdata=edge.customdata[indices],
            hovertext=hover, showlegend=False, name=edge.name,
            hovertemplate="%{hovertext}<br>Progresiva %{customdata[0]:.3f} m<br>Pendiente %{customdata[1]:+.2f} %"
                          "<br>Cota al eje %{z:+.3f} m<extra>%{fullData.name}</extra>",
        )
    x_span = max(np.ptp([*left.x, *right.x]), 1)
    y_span = max(np.ptp([*left.y, *right.y]), 1)
    z_span = max(np.ptp([*left.z, *right.z]), 0.05)
    planar = max(x_span, y_span)
    figure.update_layout(
        height=400, uirevision="road-camera",
        scene={"aspectmode": "manual", "aspectratio": {"x": x_span / planar, "y": y_span / planar, "z": 6 * z_span / planar},
               "dragmode": "orbit"},
    )
    return figure


def road_preview(rows, geometry, colors):
    from io import BytesIO

    from matplotlib.backends.backend_agg import FigureCanvasAgg
    from matplotlib.figure import Figure

    road = road_figure(rows, geometry, colors)
    if road is None:
        return None
    fig = Figure(figsize=(6, 3.2), dpi=120, facecolor="white")
    FigureCanvasAgg(fig)
    ax = fig.add_axes((0.01, 0.06, 0.98, 0.94), projection="3d")
    for idx, color in zip((0, 2), colors):
        surface, edge = road.data[idx:idx + 2]
        ax.plot_surface(np.asarray(surface.x), np.asarray(surface.y), np.asarray(surface.z),
                        color=color, alpha=0.8, shade=False, linewidth=0)
        ax.plot(edge.x, edge.y, edge.z, color="#263441", linewidth=1.0)
    center = road.data[-1]
    ax.plot(center.x, center.y, center.z, color="#edb836", linewidth=1.8, zorder=8)
    left, right = road.data[1], road.data[3]
    stations = np.asarray(left.customdata)[:, 0]
    for row in rows:
        i = int(np.argmin(abs(stations - station_m(row))))
        ax.plot([left.x[i], center.x[i], right.x[i]], [left.y[i], center.y[i], right.y[i]],
                [left.z[i], center.z[i], right.z[i]], color="#334155", linewidth=0.55, alpha=0.65)
    x_span = max(np.ptp([*left.x, *right.x]), 1)
    y_span = max(np.ptp([*left.y, *right.y]), 1)
    z_span = max(np.ptp([*left.z, *right.z]), 0.05)
    ax.set_box_aspect((x_span, y_span, z_span * 6), zoom=1.16)
    ax.view_init(elev=35, azim=-58)
    ax.set_axis_off()
    output = BytesIO()
    fig.savefig(output, format="png")
    return output.getvalue()



def fullscreen_road_html(figure):
    import plotly.io as pio

    figure.update_layout(autosize=True, height=None)
    chart = pio.to_html(
        figure, full_html=False, include_plotlyjs=True, default_height="100%",
        config={"scrollZoom": True, "displaylogo": False, "responsive": True},
        div_id="road-chart",
    )
    return """<!doctype html>
<html lang="es">
<meta charset="utf-8">
<style>
html, body { margin: 0; height: 100%; font-family: system-ui, sans-serif; background: white; }
#road-view { display: flex; flex-direction: column; width: 100%; height: 100%; background: white; }
#road-controls { display: flex; align-items: center; gap: 0.6rem; padding: 0.35rem; }
#road-fullscreen { border: 1px solid #94a3b8; background: white; border-radius: 0.4rem;
                   padding: 0.42rem 0.7rem; cursor: pointer; color: #1e293b; }
#road-stage { flex: 1; min-height: 0; }
#road-stage > div { height: 100%; }
#road-status { font-size: 0.8rem; color: #334155; }
</style>
<main id="road-view">
  <div id="road-controls">
    <button id="road-fullscreen" type="button">Pantalla completa</button>
    <span id="road-status" role="status"></span>
  </div>
  <div id="road-stage">""" + chart + """</div>
</main>
<script>
const view = document.getElementById('road-view');
const button = document.getElementById('road-fullscreen');
const status = document.getElementById('road-status');
button.addEventListener('click', async () => {
    try {
        status.textContent = '';
        if (document.fullscreenElement) await document.exitFullscreen();
        else await view.requestFullscreen();
    } catch {
        status.textContent = 'El navegador no permitió abrir la pantalla completa.';
    }
});
document.addEventListener('fullscreenchange', () => {
    button.textContent = document.fullscreenElement ? 'Salir de pantalla completa' : 'Pantalla completa';
});
new ResizeObserver(() => {
    const graph = document.getElementById('road-chart');
    if (graph && graph._fullLayout) Plotly.Plots.resize(graph);
}).observe(document.getElementById('road-stage'));
</script>
</html>"""

