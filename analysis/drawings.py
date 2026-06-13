"""
Raptor — Peças Desenhadas
Generates engineering drawings: foundation plan, slab plans, column schedule,
footing schedule.
"""
import io
import math
import matplotlib
try:
    matplotlib.use('Agg')
except Exception:
    pass
import matplotlib.pyplot as plt
import matplotlib.patches as patches
from matplotlib.gridspec import GridSpec
from core.model import Project, SlabType


# ── Helpers ──────────────────────────────────────────────────────────────────

def _col_bounds(project):
    xs = [c.x for c in project.columns] or [0, 10]
    ys = [c.y for c in project.columns] or [0, 10]
    return min(xs), max(xs), min(ys), max(ys)


def _engineering_style(ax):
    ax.set_facecolor('white')
    ax.tick_params(labelsize=7, length=3)
    ax.set_xlabel('X (m)', fontsize=8)
    ax.set_ylabel('Y (m)', fontsize=8)
    for spine in ax.spines.values():
        spine.set_linewidth(1.2)


def _draw_column_on_ax(ax, col, label=True, zorder=4):
    w = col.width_cm / 100
    d = col.depth_cm / 100
    if col.shape == 'circular':
        ax.add_patch(patches.Circle((col.x, col.y), w / 2,
                                    fill=True, facecolor='black', zorder=zorder))
    else:
        ax.add_patch(patches.Rectangle(
            (col.x - w / 2, col.y - d / 2), w, d,
            fill=True, facecolor='black', edgecolor='black', zorder=zorder))
    if label:
        ax.text(col.x, col.y + d / 2 + 0.15, col.id,
                ha='center', va='bottom', fontsize=6.5, fontweight='bold', zorder=zorder + 1)


def _fig_to_bytes(fig, dpi=150):
    buf = io.BytesIO()
    fig.savefig(buf, format='png', dpi=dpi, bbox_inches='tight', facecolor='white')
    plt.close(fig)
    buf.seek(0)
    return buf.read()


# ── Bay detection ─────────────────────────────────────────────────────────────

def _find_bays(project):
    """Find rectangular bays enclosed by the column grid."""
    xs = sorted(set(round(c.x, 2) for c in project.columns))
    ys = sorted(set(round(c.y, 2) for c in project.columns))
    col_set = {(round(c.x, 2), round(c.y, 2)) for c in project.columns}
    bays = []
    for i in range(len(xs) - 1):
        for j in range(len(ys) - 1):
            x1, x2 = xs[i], xs[i + 1]
            y1, y2 = ys[j], ys[j + 1]
            corners = [(x1, y1), (x2, y1), (x1, y2), (x2, y2)]
            if all(c in col_set for c in corners):
                bays.append((x1, y1, x2, y2))
    return bays


def _assign_slabs_to_bays(project, bays):
    """Match non-cantilever slabs to bays by closest span length."""
    non_cant = [s for s in project.slabs if s.slab_type != SlabType.CANTILEVER]
    sorted_slabs = sorted(non_cant, key=lambda s: s.span_m)
    sorted_bays = sorted(bays, key=lambda b: min(b[2] - b[0], b[3] - b[1]))
    result = {}
    for k, bay in enumerate(sorted_bays):
        slab = sorted_slabs[min(k, len(sorted_slabs) - 1)] if sorted_slabs else None
        result[bay] = slab
    return result


# ── Slab panel drawing ────────────────────────────────────────────────────────

def _draw_slab_bay(ax, x1, y1, x2, y2, slab):
    """Draw a bay with fill colour + vigota lines if ribbed."""
    w = x2 - x1
    h = y2 - y1

    # Span direction: vigotas run in the SHORT direction
    short_is_x = w <= h
    span_dir = 'x' if short_is_x else 'y'

    slab_type = slab.slab_type if slab else SlabType.ONE_WAY

    color_map = {
        SlabType.ONE_WAY:    '#ddeeff',
        SlabType.TWO_WAY:    '#eeddff',
        SlabType.RIBBED:     '#fff8e8',
        SlabType.CANTILEVER: '#ffeedd',
    }
    bg_color = color_map.get(slab_type, '#f0f0f0')

    # Background rectangle
    ax.add_patch(patches.Rectangle(
        (x1, y1), w, h,
        fill=True, facecolor=bg_color, edgecolor='#555555',
        linewidth=0.9, zorder=1))

    if slab_type == SlabType.RIBBED:
        _draw_vigota_lines(ax, x1, y1, x2, y2, span_dir)
        _draw_span_arrow(ax, x1, y1, x2, y2, span_dir)

    elif slab_type == SlabType.TWO_WAY:
        # Cross hatch for 2-way
        ax.add_patch(patches.Rectangle(
            (x1, y1), w, h, fill=False,
            hatch='xxx', edgecolor='#aaaaaa', linewidth=0, zorder=2, alpha=0.7))

    elif slab_type == SlabType.ONE_WAY:
        ax.add_patch(patches.Rectangle(
            (x1, y1), w, h, fill=False,
            hatch='///', edgecolor='#aaaaaa', linewidth=0, zorder=2, alpha=0.7))
        _draw_span_arrow(ax, x1, y1, x2, y2, span_dir)

    # Bay label
    cx, cy = (x1 + x2) / 2, (y1 + y2) / 2
    if slab:
        stype_label = {
            SlabType.ONE_WAY:    '1D',
            SlabType.TWO_WAY:    '2D',
            SlabType.RIBBED:     'Alig.',
            SlabType.CANTILEVER: 'Cons.',
        }.get(slab_type, '')
        ax.text(cx, cy + 0.12, slab.id,
                ha='center', va='center', fontsize=7, fontweight='bold', zorder=6)
        cat = f' [{slab.catalog_id}]' if getattr(slab, 'catalog_id', None) else ''
        ax.text(cx, cy - 0.18,
                f'{stype_label} h={slab.thickness_cm}cm  L={slab.span_m}m{cat}',
                ha='center', va='top', fontsize=5.5, color='#333333', zorder=6)


def _draw_vigota_lines(ax, x1, y1, x2, y2, span_dir, spacing=0.42):
    """Parallel vigota/rib lines — spacing 42 cm matches a typical BL40 block."""
    color = '#aaaaaa'
    lw = 0.45
    margin = 0.05
    if span_dir == 'x':  # vigotas run horizontally (East–West)
        y = y1 + spacing
        while y < y2 - margin:
            ax.plot([x1 + margin, x2 - margin], [y, y],
                    color=color, linewidth=lw, zorder=2)
            y += spacing
    else:  # vigotas run vertically (North–South)
        x = x1 + spacing
        while x < x2 - margin:
            ax.plot([x, x], [y1 + margin, y2 - margin],
                    color=color, linewidth=lw, zorder=2)
            x += spacing


def _draw_span_arrow(ax, x1, y1, x2, y2, span_dir):
    """Double-headed arrow indicating vigota span direction."""
    cx, cy = (x1 + x2) / 2, (y1 + y2) / 2
    if span_dir == 'x':
        half = min((x2 - x1) * 0.28, 0.9)
        ax.annotate('', xy=(cx + half, cy), xytext=(cx - half, cy),
                    arrowprops=dict(arrowstyle='<->', color='#333333',
                                   lw=1.2, mutation_scale=8),
                    zorder=5)
    else:
        half = min((y2 - y1) * 0.28, 0.9)
        ax.annotate('', xy=(cx, cy + half), xytext=(cx, cy - half),
                    arrowprops=dict(arrowstyle='<->', color='#333333',
                                   lw=1.2, mutation_scale=8),
                    zorder=5)


# ── 1. Planta de Fundações ────────────────────────────────────────────────────

def draw_foundation_plan(project: Project) -> bytes:
    fig, ax = plt.subplots(figsize=(14, 10))
    fig.patch.set_facecolor('white')

    col_lookup = {c.id: c for c in project.columns}
    footing_map = {f.related_column_id: f for f in project.footings}

    # --- Sapatas (dashed outline) ---
    for col in project.columns:
        f = footing_map.get(col.id)
        if not f:
            continue
        fw = f.width_a_cm / 100
        fh = f.width_b_cm / 100
        ax.add_patch(patches.Rectangle(
            (col.x - fw / 2, col.y - fh / 2), fw, fh,
            fill=True, facecolor='#f0f0f0', edgecolor='black',
            linewidth=0.8, linestyle='--', zorder=1))
        ax.text(col.x, col.y - fh / 2 - 0.18,
                f'{int(f.width_a_cm)}×{int(f.width_b_cm)}×{int(f.height_cm)}',
                ha='center', va='top', fontsize=5.5, color='#444444')

    # --- Vigas de amarração ---
    for tb in project.tie_beams:
        f1 = next((f for f in project.footings if f.id == tb.start_footing_id), None)
        f2 = next((f for f in project.footings if f.id == tb.end_footing_id), None)
        if not (f1 and f2):
            continue
        c1 = col_lookup.get(f1.related_column_id)
        c2 = col_lookup.get(f2.related_column_id)
        if not (c1 and c2):
            continue
        bw = tb.width_cm / 100
        dx, dy = c2.x - c1.x, c2.y - c1.y
        length = math.hypot(dx, dy)
        if length < 1e-6:
            continue
        nx, ny = -dy / length * bw / 2, dx / length * bw / 2
        xs = [c1.x + nx, c2.x + nx, c2.x - nx, c1.x - nx]
        ys = [c1.y + ny, c2.y + ny, c2.y - ny, c1.y - ny]
        ax.add_patch(patches.Polygon(list(zip(xs, ys)), closed=True,
                                     fill=True, facecolor='#cccccc',
                                     edgecolor='black', linewidth=0.8, zorder=2))
        mx, my = (c1.x + c2.x) / 2, (c1.y + c2.y) / 2
        angle = math.degrees(math.atan2(dy, dx))
        ax.text(mx, my, tb.id, ha='center', va='center', fontsize=6,
                rotation=angle if abs(angle) < 60 else angle - 90, zorder=6,
                bbox=dict(boxstyle='round,pad=0.1', facecolor='white', alpha=0.7,
                          edgecolor='none'))

    # --- Pilares ---
    for col in project.columns:
        _draw_column_on_ax(ax, col)

    # --- Labels de sapatas ---
    for col in project.columns:
        f = footing_map.get(col.id)
        if f:
            ax.text(col.x - 0.05, col.y, f.id,
                    ha='right', va='center', fontsize=5.5, color='#333333',
                    style='italic')

    xmin, xmax, ymin, ymax = _col_bounds(project)
    m = 1.5
    ax.set_xlim(xmin - m, xmax + m)
    ax.set_ylim(ymin - m, ymax + m)
    ax.set_aspect('equal')
    ax.set_title(f'PLANTA DE FUNDAÇÕES — {project.name}',
                 fontsize=11, fontweight='bold', pad=8)
    _engineering_style(ax)
    ax.grid(True, linestyle=':', linewidth=0.4, alpha=0.5)
    return _fig_to_bytes(fig)


# ── 2. Planta da Laje ─────────────────────────────────────────────────────────

def draw_slab_plan(project: Project, title: str = "PLANTA DA LAJE DE PISO") -> bytes:
    fig, ax = plt.subplots(figsize=(14, 10))
    fig.patch.set_facecolor('white')

    col_lookup = {c.id: c for c in project.columns}

    # --- Detect bays and assign slabs ---
    bays = _find_bays(project)
    bay_slab = _assign_slabs_to_bays(project, bays)

    # --- Draw slabs with polygon_points (if available) ---
    hatch_map = {
        SlabType.ONE_WAY:    ('///', '#ddeeff'),
        SlabType.TWO_WAY:    ('xxx', '#eeddff'),
        SlabType.RIBBED:     ('',    '#fff8e8'),
        SlabType.CANTILEVER: ('---', '#ffeedd'),
    }
    drawn_slab_ids = set()
    for slab in project.slabs:
        pts = slab.polygon_points
        if pts and len(pts) >= 3:
            hatch, fc = hatch_map.get(slab.slab_type, ('', '#eeeeee'))
            ax.add_patch(patches.Polygon(pts, closed=True,
                                         fill=True, facecolor=fc, edgecolor='#888888',
                                         linewidth=0.6, hatch=hatch, zorder=1, alpha=0.7))
            cx = sum(p[0] for p in pts) / len(pts)
            cy = sum(p[1] for p in pts) / len(pts)
            ax.text(cx, cy + 0.1, slab.id,
                    ha='center', va='center', fontsize=6.5, fontweight='bold', zorder=5)
            drawn_slab_ids.add(slab.id)

    # --- Draw auto-detected bays with vigota lines ---
    for bay, slab in bay_slab.items():
        x1, y1, x2, y2 = bay
        # Skip if slab already drawn from polygon_points
        if slab and slab.id in drawn_slab_ids:
            continue
        _draw_slab_bay(ax, x1, y1, x2, y2, slab)

    # --- Vigas ---
    for b in project.beams:
        c1 = col_lookup.get(b.start_node)
        c2 = col_lookup.get(b.end_node)
        if not (c1 and c2):
            continue
        bw = b.width_cm / 100
        dx, dy = c2.x - c1.x, c2.y - c1.y
        length = math.hypot(dx, dy)
        if length < 1e-6:
            continue
        nx = -dy / length * bw / 2
        ny = dx / length * bw / 2
        xs = [c1.x + nx, c2.x + nx, c2.x - nx, c1.x - nx]
        ys = [c1.y + ny, c2.y + ny, c2.y - ny, c1.y - ny]
        ax.add_patch(patches.Polygon(list(zip(xs, ys)), closed=True,
                                     fill=True, facecolor='#888888',
                                     edgecolor='black', linewidth=0.7, zorder=3))
        mx, my = (c1.x + c2.x) / 2, (c1.y + c2.y) / 2
        angle = math.degrees(math.atan2(dy, dx))
        rot = angle if abs(angle) < 60 else angle - 90
        ax.text(mx, my, b.id, ha='center', va='center', fontsize=6,
                rotation=rot, zorder=6,
                bbox=dict(boxstyle='round,pad=0.1', facecolor='white',
                          alpha=0.85, edgecolor='none'))

    # --- Pilares ---
    for col in project.columns:
        _draw_column_on_ax(ax, col, zorder=7)

    xmin, xmax, ymin, ymax = _col_bounds(project)
    m = 1.5
    ax.set_xlim(xmin - m, xmax + m)
    ax.set_ylim(ymin - m, ymax + m)
    ax.set_aspect('equal')
    ax.set_title(f'{title} — {project.name}', fontsize=11, fontweight='bold', pad=8)
    _engineering_style(ax)
    ax.grid(True, linestyle=':', linewidth=0.4, alpha=0.5)

    # --- Legend ---
    legend_items = [
        patches.Patch(facecolor='#fff8e8', edgecolor='#aaaaaa',
                      label='Aligeirada (vigotas)'),
        patches.Patch(facecolor='#ddeeff', hatch='///', edgecolor='#aaaaaa',
                      label='Laje 1 Dir.'),
        patches.Patch(facecolor='#eeddff', hatch='xxx', edgecolor='#aaaaaa',
                      label='Laje 2 Dir.'),
        patches.Patch(facecolor='#ffeedd', hatch='---', edgecolor='#aaaaaa',
                      label='Consola'),
        patches.Patch(facecolor='#888888', edgecolor='black', label='Viga'),
        patches.Patch(facecolor='black', edgecolor='black', label='Pilar'),
    ]
    ax.legend(handles=legend_items, loc='lower right', fontsize=7, framealpha=0.92)
    return _fig_to_bytes(fig)


# ── 3. Quadro de Pilares ──────────────────────────────────────────────────────

def draw_column_schedule(project: Project) -> bytes:
    cols = project.columns
    if not cols:
        return b""

    levels = ['Cobertura', 'Piso 1', 'Fundação']
    n = len(cols)
    n_lev = len(levels)

    cell_w = 2.0
    cell_h = 2.6
    label_w = 1.0
    fig_w = label_w + n * cell_w + 0.3
    fig_h = n_lev * cell_h + 0.8

    fig = plt.figure(figsize=(fig_w, fig_h), facecolor='white')
    fig.text(0.5, 0.99, f'QUADRO DE PILARES — {project.name}',
             ha='center', va='top', fontsize=10, fontweight='bold')

    left = label_w / fig_w
    gs = GridSpec(n_lev, n, figure=fig,
                  left=left + 0.01, right=0.99,
                  top=0.94, bottom=0.01,
                  hspace=0.0, wspace=0.05)

    for j, level in enumerate(levels):
        fig.text(left * 0.45, 1 - (j + 0.5) / n_lev * 0.93 - 0.03,
                 level, ha='center', va='center', fontsize=8,
                 fontweight='bold', rotation=90, transform=fig.transFigure)
        for i, col in enumerate(cols):
            ax = fig.add_subplot(gs[j, i])
            _draw_single_column_cell(ax, col, level, j == 0)

    for j in range(1, n_lev):
        y = 1 - j / n_lev * 0.93 - 0.03
        fig.add_artist(plt.Line2D([left, 0.99], [y, y],
                                  transform=fig.transFigure,
                                  color='black', linewidth=1.0))

    return _fig_to_bytes(fig, dpi=150)


def _draw_single_column_cell(ax, col, level: str, show_id: bool):
    ax.set_facecolor('white')
    ax.set_aspect('equal')
    ax.axis('off')

    w = col.width_cm
    d = col.depth_cm
    cov = 3.0
    bar_r = 0.9

    ax.add_patch(patches.Rectangle((0, 0), w, d,
                                   fill=False, edgecolor='black', linewidth=1.2))
    ax.add_patch(patches.Rectangle((cov, cov), w - 2 * cov, d - 2 * cov,
                                   fill=False, edgecolor='black', linewidth=0.7))

    if col.result and col.result.adopted_as_cm2 > 0:
        as_cm2 = col.result.adopted_as_cm2
        options = [(4, 12, 4.52), (4, 16, 8.04), (6, 12, 6.79),
                   (8, 12, 9.05), (4, 20, 12.57), (6, 16, 12.06)]
        chosen = options[0]
        for n_b, dia, area in options:
            if area >= as_cm2:
                chosen = (n_b, dia, area)
                break
        n_bars, bar_dia = chosen[0], chosen[1]
    else:
        n_bars, bar_dia = 4, 12

    stir_dia, stir_sp = 8, 20

    bar_positions = []
    if col.shape == 'circular':
        r = w / 2 - cov - bar_r
        for k in range(n_bars):
            angle = k * 2 * math.pi / n_bars - math.pi / 4
            bar_positions.append((w / 2 + r * math.cos(angle),
                                  d / 2 + r * math.sin(angle)))
    else:
        corners = [(cov, cov), (w - cov, cov),
                   (w - cov, d - cov), (cov, d - cov)]
        bar_positions = list(corners)
        extra = n_bars - 4
        if extra >= 2:
            bar_positions += [(w / 2, cov), (w / 2, d - cov)]
        if extra >= 4:
            bar_positions += [(cov, d / 2), (w - cov, d / 2)]

    for bx, by in bar_positions:
        ax.add_patch(patches.Circle((bx, by), bar_r,
                                    fill=True, facecolor='black', zorder=3))

    pad = 7
    text_h = 14
    ax.set_xlim(-pad, w + pad)
    ax.set_ylim(-text_h, d + pad)

    if show_id:
        ax.text(w / 2, d + pad * 0.7, col.id,
                ha='center', va='center', fontsize=7, fontweight='bold')

    dim_label = f'Ø{int(w)}' if col.shape == 'circular' else f'{int(w)}×{int(d)}'

    y0, dh = -1.5, 3.8
    lines = [
        f'Arm. Long. {n_bars}Ø{bar_dia}',
        f'Arranque {n_bars}Ø{bar_dia}',
        f'Arm. Trans. Ø{stir_dia} a/{stir_sp}',
    ]
    for k, txt in enumerate(lines):
        ax.text(w / 2, y0 - k * dh, txt, ha='center', va='top', fontsize=5.2)

    ax.text(w + 1, d + 1, dim_label,
            ha='left', va='bottom', fontsize=5.5, color='#555555')


# ── 4. Quadro de Sapatas ──────────────────────────────────────────────────────

def draw_footing_schedule(project: Project) -> bytes:
    footings = project.footings
    if not footings:
        return b""

    col_map = {c.id: c for c in project.columns}

    n = len(footings)
    cell_w = 2.4   # inches
    cell_h = 3.0   # inches
    label_w = 0.8
    fig_w = label_w + n * cell_w + 0.3
    fig_h = cell_h + 0.9

    fig = plt.figure(figsize=(fig_w, fig_h), facecolor='white')
    fig.text(0.5, 0.99, f'QUADRO DE SAPATAS — {project.name}',
             ha='center', va='top', fontsize=10, fontweight='bold')

    gs = GridSpec(1, n, figure=fig,
                  left=label_w / fig_w + 0.01, right=0.99,
                  top=0.91, bottom=0.01,
                  hspace=0.0, wspace=0.08)

    for i, footing in enumerate(footings):
        col = col_map.get(footing.related_column_id)
        ax = fig.add_subplot(gs[0, i])
        _draw_single_footing_cell(ax, footing, col)

    # Outer border
    fig.add_artist(plt.Line2D(
        [label_w / fig_w, 0.99], [0.91, 0.91],
        transform=fig.transFigure, color='black', linewidth=1.0))
    fig.add_artist(plt.Line2D(
        [label_w / fig_w, 0.99], [0.01, 0.01],
        transform=fig.transFigure, color='black', linewidth=1.0))

    return _fig_to_bytes(fig, dpi=150)


def _footing_bars(footing):
    """Return (n_bars_x, dia_x, spacing_x_cm, n_bars_y, dia_y, spacing_y_cm)."""
    as_cm2_m = 0.0
    if footing.result:
        as_cm2_m = footing.result.required_as_cm2

    # Bar options: (diameter mm, area cm²/bar)
    bar_opts = [(12, 1.131), (16, 2.011), (20, 3.142)]

    def _pick_bars(width_cm, as_req_cm2_m):
        as_total = max(as_req_cm2_m * width_cm / 100.0, 2.0)
        for dia, a_bar in bar_opts:
            n = max(math.ceil(as_total / a_bar), 4)
            spacing = width_cm / (n - 1) if n > 1 else width_cm
            if spacing >= 9.0:
                return n, dia, round(spacing / 5.0) * 5
        dia, a_bar = bar_opts[-1]
        n = max(math.ceil(as_total / a_bar), 4)
        return n, dia, max(round(width_cm / (n - 1) / 5.0) * 5, 10) if n > 1 else 10

    nx, dx, sx = _pick_bars(footing.width_a_cm, as_cm2_m)
    ny, dy, sy = _pick_bars(footing.width_b_cm, as_cm2_m)
    return nx, dx, sx, ny, dy, sy


def _draw_single_footing_cell(ax, footing, col):
    ax.set_facecolor('white')
    ax.set_aspect('equal')
    ax.axis('off')

    fa = footing.width_a_cm   # footing X dimension
    fb = footing.width_b_cm   # footing Y dimension
    cover = 5.0               # cm

    # Scale: draw footing in cm coordinate space
    # Footing outline
    ax.add_patch(patches.Rectangle(
        (0, 0), fa, fb,
        fill=True, facecolor='#f5f5f5', edgecolor='black', linewidth=1.2))

    # Reinforcement bars (plan view)
    nx, dx, sx, ny, dy, sy = _footing_bars(footing)

    bar_lw = 0.7
    bar_color = '#222222'

    # Bars in X direction (horizontal lines)
    y_step = (fb - 2 * cover) / max(ny - 1, 1)
    for k in range(ny):
        yb = cover + k * y_step
        ax.plot([cover, fa - cover], [yb, yb],
                color=bar_color, linewidth=bar_lw, zorder=2)

    # Bars in Y direction (vertical lines)
    x_step = (fa - 2 * cover) / max(nx - 1, 1)
    for k in range(nx):
        xb = cover + k * x_step
        ax.plot([xb, xb], [cover, fb - cover],
                color=bar_color, linewidth=bar_lw, zorder=2)

    # Column stub (filled)
    if col:
        cw = col.width_cm
        cd = col.depth_cm
        cx = fa / 2 - cw / 2
        cy = fb / 2 - cd / 2
        ax.add_patch(patches.Rectangle(
            (cx, cy), cw, cd,
            fill=True, facecolor='black', edgecolor='black',
            linewidth=0.8, zorder=3))

    # Axis limits with margin for text
    text_h = fb * 0.55
    pad = fa * 0.1
    ax.set_xlim(-pad, fa + pad)
    ax.set_ylim(-text_h, fb + pad * 0.5)

    # Header
    ax.text(fa / 2, fb + pad * 0.3, footing.id,
            ha='center', va='bottom', fontsize=7, fontweight='bold')

    # Column ID reference
    if col:
        ax.text(fa / 2, fb + pad * 0.3 - 4,
                f'({col.id})',
                ha='center', va='bottom', fontsize=5.5, color='#555555')

    # Dimension label
    ax.text(fa / 2, -2,
            f'{int(fa)}×{int(fb)}×{int(footing.height_cm)} cm',
            ha='center', va='top', fontsize=6.0, fontweight='bold')

    # Reinforcement text
    lines = [
        f'As_x: {nx}Ø{dx} a/{sx}',
        f'As_y: {ny}Ø{dy} a/{sy}',
    ]
    if footing.result:
        soil_u = footing.result.soil_utilization
        lines.append(f'σ solo: {footing.result.soil_stress_mpa * 1000:.0f}/{int(footing.result.soil_stress_mpa / footing.result.soil_utilization * 1000) if soil_u else "—"} kPa')

    y0 = -6
    for k, txt in enumerate(lines):
        ax.text(fa / 2, y0 - k * 5.5, txt,
                ha='center', va='top', fontsize=5.5)
