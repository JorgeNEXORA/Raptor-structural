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

# Use string values for comparison — SlabType is a str-Enum so these always
# match regardless of which enum members exist in the deployed model version.
_ST_RIBBED     = "ribbed"
_ST_ONE_WAY    = "one_way"
_ST_TWO_WAY    = "two_way"
_ST_CANTILEVER = "cantilever"


def _slab_val(slab_type) -> str:
    """Return the string value of a SlabType (or the value itself if already str)."""
    return slab_type.value if hasattr(slab_type, 'value') else str(slab_type)


def _is_cantilever(slab_type) -> bool:
    return _slab_val(slab_type) == _ST_CANTILEVER


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
    non_cant = [s for s in project.slabs if not _is_cantilever(s.slab_type)]
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

    sv = _slab_val(slab.slab_type) if slab else _ST_ONE_WAY

    color_map = {
        _ST_ONE_WAY:    '#ddeeff',
        _ST_TWO_WAY:    '#eeddff',
        _ST_RIBBED:     '#fff8e8',
        _ST_CANTILEVER: '#ffeedd',
    }
    bg_color = color_map.get(sv, '#f0f0f0')

    # Background rectangle
    ax.add_patch(patches.Rectangle(
        (x1, y1), w, h,
        fill=True, facecolor=bg_color, edgecolor='#555555',
        linewidth=0.9, zorder=1))

    if sv == _ST_RIBBED:
        _draw_vigota_lines(ax, x1, y1, x2, y2, span_dir)
        _draw_span_arrow(ax, x1, y1, x2, y2, span_dir)

    elif sv == _ST_TWO_WAY:
        ax.add_patch(patches.Rectangle(
            (x1, y1), w, h, fill=False,
            hatch='xxx', edgecolor='#aaaaaa', linewidth=0, zorder=2, alpha=0.7))

    elif sv == _ST_ONE_WAY:
        ax.add_patch(patches.Rectangle(
            (x1, y1), w, h, fill=False,
            hatch='///', edgecolor='#aaaaaa', linewidth=0, zorder=2, alpha=0.7))
        _draw_span_arrow(ax, x1, y1, x2, y2, span_dir)

    # Bay label
    cx, cy = (x1 + x2) / 2, (y1 + y2) / 2
    if slab:
        stype_label = {
            _ST_ONE_WAY:    '1D',
            _ST_TWO_WAY:    '2D',
            _ST_RIBBED:     'Alig.',
            _ST_CANTILEVER: 'Cons.',
        }
        stype_label = stype_label.get(sv, '')
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
        _ST_ONE_WAY:    ('///', '#ddeeff'),
        _ST_TWO_WAY:    ('xxx', '#eeddff'),
        _ST_RIBBED:     ('',    '#fff8e8'),
        _ST_CANTILEVER: ('---', '#ffeedd'),
    }
    drawn_slab_ids = set()
    for slab in project.slabs:
        pts = slab.polygon_points
        if pts and len(pts) >= 3:
            hatch, fc = hatch_map.get(_slab_val(slab.slab_type), ('', '#eeeeee'))
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


# ── 5. Quadro de Vigas ───────────────────────────────────────────────────────

def _beam_bottom_bars(as_req_cm2: float):
    """Return (n_bars, dia_mm, total_area_cm2) satisfying as_req_cm2."""
    as_min = max(as_req_cm2, 1.0)
    options = [
        (2, 10, 1.571), (2, 12, 2.262), (2, 16, 4.021), (3, 12, 3.393),
        (2, 20, 6.283), (3, 16, 6.032), (4, 12, 4.524), (3, 20, 9.425),
        (4, 16, 8.042), (5, 16, 10.053), (4, 20, 12.566), (5, 20, 15.708),
        (6, 20, 18.850),
    ]
    for n, phi, area in options:
        if area >= as_min:
            return n, phi, area
    return 6, 20, 18.850


def _beam_stirrup_design(vsd_kn: float, d_cm: float):
    """Return (phi_mm, s_cm) satisfying EC2 shear Vrd,s >= vsd_kn."""
    fyd_kn_cm2 = (500.0 / 1.15) * 0.1   # kN/cm²  (1 MPa = 0.1 kN/cm²)
    z_cm = 0.9 * d_cm
    options = [(6, 20), (6, 15), (6, 10), (8, 20), (8, 15), (8, 10),
               (10, 20), (10, 15), (10, 10)]
    for phi_mm, s_cm in options:
        phi_cm = phi_mm / 10.0
        asw_cm2 = 2 * math.pi * (phi_cm / 2) ** 2   # 2 legs
        vrd_s = (asw_cm2 / s_cm) * z_cm * fyd_kn_cm2
        if vrd_s >= vsd_kn:
            return phi_mm, s_cm
    return 10, 10


def _group_beams_into_frames(beams, col_map):
    """Group beams into frames (pórticos) by collinear alignment.
    Returns list of (direction, sorted_beam_list).
    """
    TOL_DEG = 20   # degrees: beam is 'X' if angle < 20°, else 'Y'
    TOL_POS = 0.5  # m: group frames within 0.5 m of same transverse coordinate

    def beam_angle_deg(b):
        c1 = col_map.get(b.start_node)
        c2 = col_map.get(b.end_node)
        if not c1 or not c2:
            return 0.0
        dx = abs(c2.x - c1.x)
        dy = abs(c2.y - c1.y)
        return math.degrees(math.atan2(dy, dx + 1e-9))

    x_beams = [b for b in beams if beam_angle_deg(b) <= TOL_DEG]
    y_beams = [b for b in beams if beam_angle_deg(b) >  TOL_DEG]

    def group_by_transverse(beam_list, direction):
        groups = {}
        for b in beam_list:
            c1 = col_map.get(b.start_node)
            c2 = col_map.get(b.end_node)
            if not c1 or not c2:
                continue
            transverse = ((c1.y + c2.y) / 2) if direction == 'X' else ((c1.x + c2.x) / 2)
            key = round(transverse / TOL_POS) * TOL_POS
            groups.setdefault(key, []).append(b)

        result = []
        for key in sorted(groups.keys()):
            def sort_key(b, d=direction):
                c1 = col_map[b.start_node]
                return c1.x if d == 'X' else c1.y
            result.append((direction, sorted(groups[key], key=sort_key)))
        return result

    frames = group_by_transverse(x_beams, 'X') + group_by_transverse(y_beams, 'Y')
    return frames


def _draw_frame_elevation(ax, direction, beams, col_map, frame_num):
    """Draw one frame elevation (pórtico) on ax."""
    ax.set_facecolor('white')
    ax.axis('off')

    # ── collect column positions along frame direction ──────────────
    col_pos = {}   # col_id → coordinate (m)
    col_obj = {}
    for b in beams:
        for nid in [b.start_node, b.end_node]:
            if nid not in col_pos:
                c = col_map.get(nid)
                if c:
                    col_pos[nid] = c.x if direction == 'X' else c.y
                    col_obj[nid] = c

    sorted_col_ids = sorted(col_pos, key=lambda cid: col_pos[cid])
    if len(sorted_col_ids) < 2:
        return

    # ── sort beams into spans ───────────────────────────────────────
    span_list = []   # (x_left, x_right, beam)
    for b in beams:
        p1 = col_pos.get(b.start_node)
        p2 = col_pos.get(b.end_node)
        if p1 is None or p2 is None:
            continue
        if p1 > p2:
            p1, p2 = p2, p1
        span_list.append((p1, p2, b))
    span_list.sort(key=lambda t: t[0])
    if not span_list:
        return

    # ── geometry ────────────────────────────────────────────────────
    bh = beams[0].height_cm / 100        # beam height (m)
    bw = beams[0].width_cm / 100         # beam width (m)
    cover = 0.025                         # rebar cover (m)
    beam_top = 0.0
    beam_bot = -bh
    col_stub_top = bh * 1.3              # column stub above beam
    col_stub_bot = bh * 0.6             # column stub below beam

    # ── draw each span ──────────────────────────────────────────────
    for x_l, x_r, beam in span_list:
        span = x_r - x_l
        rr = beam.reinforcement_result or {}
        vsd = beam.result.vsd_kn if beam.result else 0.0
        msd = beam.result.msd_knm if beam.result else 0.0
        as_req = beam.result.required_as_cm2 if beam.result else 2.0

        n_bot, dia_bot, _ = _beam_bottom_bars(as_req)
        phi_s, s_s = _beam_stirrup_design(vsd, beam.effective_depth_cm)
        s_m = s_s / 100.0

        # Beam outline
        ax.add_patch(patches.Rectangle(
            (x_l, beam_bot), span, bh,
            fill=True, facecolor='#f0f0f0',
            edgecolor='black', linewidth=0.9, zorder=2))

        # Stirrup hatching (vertical lines at spacing s_m)
        n_stir = max(1, int(span / s_m))
        actual_spacing = span / n_stir
        for k in range(n_stir + 1):
            xs = x_l + k * actual_spacing
            if xs > x_r + 1e-6:
                break
            ax.plot([xs, xs], [beam_bot + cover, beam_top - cover],
                    color='#999999', linewidth=0.35, zorder=2, alpha=0.7)

        # ── BOTTOM bars ─────────────────────────────────────────────
        inset = bw * 0.4
        y_bot = beam_bot + cover + 0.007
        ax.plot([x_l + inset, x_r - inset], [y_bot, y_bot],
                color='black', linewidth=1.8, zorder=4, solid_capstyle='butt')
        bot_label = rr.get("bottom_text") or f"{n_bot}Ø{dia_bot}"
        ax.text((x_l + x_r) / 2, y_bot - 0.010,
                bot_label, ha='center', va='top',
                fontsize=5.5, fontweight='bold', zorder=5)

        # Stirrups label at bottom (below beam)
        stir_label = f"{n_stir}×Ø{phi_s} a/{s_s}"
        ax.text((x_l + x_r) / 2, beam_bot - 0.04,
                stir_label, ha='center', va='top', fontsize=5.0, color='#222222')

        # ── TOP hanger bars (2Ø12) ──────────────────────────────────
        y_top = beam_top - cover - 0.007
        ax.plot([x_l + inset, x_r - inset], [y_top, y_top],
                color='black', linewidth=1.0, zorder=4,
                linestyle='--', dashes=(6, 3))
        ax.text((x_l + x_r) / 2, y_top + 0.010,
                '2Ø12', ha='center', va='bottom',
                fontsize=5.0, style='italic', color='#444444')

        # ── span label (double-headed arrow above column stub) ──────
        y_arr = col_stub_top + 0.06
        mid = (x_l + x_r) / 2
        ax.annotate('', xy=(x_r, y_arr), xytext=(x_l, y_arr),
                    arrowprops=dict(arrowstyle='<->', color='black',
                                   lw=0.8, mutation_scale=7), zorder=5)
        ax.text(mid, y_arr + 0.025, f'{span:.3f}',
                ha='center', va='bottom', fontsize=6.5)

        # ── Msd / Vsd annotation (small, below span) ────────────────
        ax.text(mid, beam_top - bh * 0.48,
                f'Msd={msd:.0f}kNm  Vsd={vsd:.0f}kN',
                ha='center', va='center', fontsize=4.5, color='#555555')

        # ── beam ID label (centred in span) ─────────────────────────
        ax.text(mid, beam_bot + bh * 0.80,
                beam.id, ha='center', va='center',
                fontsize=5.0, color='#666666', style='italic')

    # ── draw column stubs ───────────────────────────────────────────
    for cid in sorted_col_ids:
        col = col_obj[cid]
        pos = col_pos[cid]
        cw = (col.width_cm if direction == 'X' else col.depth_cm) / 100
        cd = (col.depth_cm if direction == 'X' else col.width_cm) / 100

        # Above beam
        ax.add_patch(patches.Rectangle(
            (pos - cw / 2, beam_top), cw, col_stub_top,
            fill=True, facecolor='#cccccc',
            edgecolor='black', linewidth=0.9, zorder=3))
        # Below beam
        ax.add_patch(patches.Rectangle(
            (pos - cw / 2, beam_bot - col_stub_bot), cw, col_stub_bot,
            fill=True, facecolor='#cccccc',
            edgecolor='black', linewidth=0.9, zorder=3))

        # Hatch column section to distinguish from beam
        ax.add_patch(patches.Rectangle(
            (pos - cw / 2, beam_top), cw, col_stub_top,
            fill=False, edgecolor='#888888', linewidth=0.3,
            hatch='///', zorder=3))

        # Column label above stub
        ax.text(pos, beam_top + col_stub_top + 0.025, cid,
                ha='center', va='bottom', fontsize=5.5, fontweight='bold')

        # Dimension tick at bottom
        y_tick = beam_bot - col_stub_bot
        ax.plot([pos, pos], [y_tick - 0.02, y_tick + 0.02],
                color='black', linewidth=0.8)
        ax.text(pos, y_tick - 0.03, f'{col.width_cm:.0f}×{col.depth_cm:.0f}',
                ha='center', va='top', fontsize=4.5, color='#555555')

    # ── frame title ─────────────────────────────────────────────────
    c_first = col_obj[sorted_col_ids[0]]
    coord_val = c_first.y if direction == 'X' else c_first.x
    axis_lbl = 'Y' if direction == 'X' else 'X'
    frame_title = (f'Pórtico {frame_num}    '
                   f'({axis_lbl}={coord_val:.2f}m)    '
                   f'Escala 1:50    '
                   f'Vigas {int(beams[0].width_cm)}×{int(beams[0].height_cm)} cm')
    ax.set_title(frame_title, fontsize=7, fontweight='bold', loc='left', pad=4)

    # ── axis bounds ─────────────────────────────────────────────────
    x_left_edge = col_pos[sorted_col_ids[0]]
    x_right_edge = col_pos[sorted_col_ids[-1]]
    total_span = x_right_edge - x_left_edge
    margin = max(total_span * 0.03, bw)

    ax.set_xlim(x_left_edge - margin - bw / 2,
                x_right_edge + margin + bw / 2)
    ax.set_ylim(beam_bot - col_stub_bot - 0.18,
                beam_top + col_stub_top + 0.22)
    ax.set_aspect('equal')


def draw_beam_schedule(project: Project) -> bytes:
    """Draw frame elevation drawings (pormenores de vigas / pórticos)."""
    beams_with_results = [b for b in project.beams if b.result]
    if not beams_with_results:
        return b""

    col_map = {c.id: c for c in project.columns}
    frames = _group_beams_into_frames(beams_with_results, col_map)
    if not frames:
        return b""

    n_frames = len(frames)
    fig_w = 18.0
    row_h = 4.8   # inches per frame row

    fig = plt.figure(figsize=(fig_w, n_frames * row_h + 1.0), facecolor='white')
    fig.suptitle(f'PORMENORES DE VIGAS — {project.name}',
                 fontsize=11, fontweight='bold', y=0.995)

    for idx, (direction, beams) in enumerate(frames):
        ax = fig.add_subplot(n_frames, 1, idx + 1)
        _draw_frame_elevation(ax, direction, beams, col_map, idx + 1)

    plt.tight_layout(rect=[0, 0, 1, 0.97])
    return _fig_to_bytes(fig, dpi=150)
