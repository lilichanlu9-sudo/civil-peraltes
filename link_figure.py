from matplotlib.figure import Figure
from matplotlib.ticker import FuncFormatter, MaxNLocator


def format_station(value):
    millimetres = round(float(value) * 1000)
    kilometres, remainder = divmod(millimetres, 1_000_000)
    return f"{kilometres}+{remainder // 1000:03d},{remainder % 1000:03d}"


def format_number(value, digits=3):
    return f"{float(value):.{digits}f}".replace(".", ",")


def link_figure(name, profile, report):
    stations = [float(station) for station, _ in profile]
    bfs1, efs1, zero, bfs2, efs2 = stations
    figure = Figure(figsize=(13, 5.5), layout="constrained")
    ax = figure.add_subplot()
    ax.set_title(name, loc="left", fontsize=14, fontweight="bold", pad=12)
    ax.set_xlabel("Progresiva (m)")
    ax.set_ylabel("Pendiente transversal (%)")
    ax.grid(axis="y", color="#e2e8f0", linewidth=0.8)
    ax.axhline(0, color="#64748b", linewidth=0.9)
    ax.xaxis.set_major_locator(MaxNLocator(8))
    ax.xaxis.set_major_formatter(FuncFormatter(lambda x, _: format_station(x)))

    colors = ("#165baf", "#11754d")
    for index, (lane, color) in enumerate(zip(("Carril izquierdo", "Carril derecho"), colors)):
        slopes = [float(values[index]) for _, values in profile]
        ax.plot(stations, slopes, color=color, marker="o", markersize=4, linewidth=2, label=lane)
        for station, slope in zip(stations, slopes):
            if station in (efs1, bfs2):
                ax.annotate(f"{format_number(slope, 2)} %", (station, slope), xytext=(0, 7 if slope > 0 else -13),
                            textcoords="offset points", color=color, ha="center", fontsize=9)

    bank = max(abs(float(value)) for _, slopes in profile for value in slopes)
    ax.set_ylim(-bank * 1.43, bank * 1.47)
    sized = (
        (bfs1, efs1, "Peralte completo", efs1 - bfs1),
        (bfs2, efs2, "Peralte completo", efs2 - bfs2),
        (report["Progresiva −2/2 % lado 1 (m)"], zero, "2 % → 0 %", report["Distancia 0 a 2 % lado 1 (m)"]),
        (zero, report["Progresiva −2/2 % lado 2 (m)"], "0 % → 2 %", report["Distancia 0 a 2 % lado 2 (m)"]),
    )
    for idx, (start, end, label, length) in enumerate(sized):
        y = bank * (1.27 if idx < 2 else 0.72)
        ax.annotate("", xy=(end, y), xytext=(start, y),
                    arrowprops={"arrowstyle": "<->", "color": "#64748b", "linewidth": 0.9})
        ax.text((start + end) / 2, y + bank * 0.055, f"{label}\n{format_number(length)} m",
                ha="center", va="bottom", fontsize=8, color="#334155")

    for idx, (station, label) in enumerate(zip(stations, ("BFS 1", "EFS 1", "ST/TS · 0 %", "BFS 2", "EFS 2"))):
        ax.axvline(station, color="#94a3b8", linestyle="--", linewidth=0.8, zorder=0)
        ax.annotate(f"{label}\n{format_station(station)}", (station, -bank * (1.20 if idx % 2 == 0 else 1.30)),
                    ha="center", va="center", fontsize=8, color="#334155")
    for field in ("Progresiva −2/2 % lado 1 (m)", "Progresiva −2/2 % lado 2 (m)"):
        station = report[field]
        ax.axvline(station, color="#cbd5e1", linestyle=":", linewidth=0.9, zorder=0)
        ax.scatter([station, station], [2, -2], facecolor="white", edgecolors="#475569", s=22, zorder=4)
    ax.legend(loc="upper right", bbox_to_anchor=(1, -0.13), ncols=2, frameon=False)
    return figure

