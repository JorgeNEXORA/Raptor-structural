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
        _draw_tarugo_lines(ax, x1, y1, x2, y2, span_dir)
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


def _draw_tarugo_lines(ax, x1, y1, x2, y2, span_dir, spacing=0.80):
    """Tarugos — short perpendicular bands at regular intervals along the span.

    Tarugos run perpendicular to vigotas and are drawn as slightly thicker
    semi-transparent bands to distinguish them from the vigota lines.
    Typical spacing: 0.80 m for spans ≤ 5 m; one at mid-span for shorter spans.
    """
    color = '#888888'
    lw = 1.8
    margin = 0.04
    band_half = 0.06  # half-width of the tarugo band in metres
    if span_dir == 'x':
        # Tarugos run in Y direction, placed along X at intervals
        span_len = x2 - x1
        n_tar = max(1, round(span_len / spacing))
        positions = [x1 + span_len * (k + 1) / (n_tar + 1) for k in range(n_tar)]
        for xp in positions:
            ax.add_patch(patches.Rectangle(
                (xp - band_half, y1 + margin), band_half * 2, y2 - y1 - 2 * margin,
                fill=True, facecolor='#cccccc', edgecolor='#888888',
                linewidth=lw * 0.4, zorder=3, alpha=0.65))
    else:
        # Tarugos run in X direction, placed along Y at intervals
        span_len = y2 - y1
        n_tar = max(1, round(span_len / spacing))
        positions = [y1 + span_len * (k + 1) / (n_tar + 1) for k in range(n_tar)]
        for yp in positions:
            ax.add_patch(patches.Rectangle(
                (x1 + margin, yp - band_half), x2 - x1 - 2 * margin, band_half * 2,
                fill=True, facecolor='#cccccc', edgecolor='#888888',
                linewidth=lw * 0.4, zorder=3, alpha=0.65))


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
            sv = _slab_val(slab.slab_type)
            hatch, fc = hatch_map.get(sv, ('', '#eeeeee'))
            ax.add_patch(patches.Polygon(pts, closed=True,
                                         fill=True, facecolor=fc, edgecolor='#888888',
                                         linewidth=0.6, hatch=hatch, zorder=1, alpha=0.7))
            # Vigota + tarugo lines for ribbed slabs (using bounding box of polygon)
            if sv == _ST_RIBBED:
                px = [p[0] for p in pts]; py = [p[1] for p in pts]
                bx1, bx2 = min(px), max(px); by1, by2 = min(py), max(py)
                bw, bh = bx2 - bx1, by2 - by1
                span_dir = 'x' if bw <= bh else 'y'
                # Clip vigota/tarugo lines to polygon using matplotlib clip path
                from matplotlib.patches import PathPatch
                from matplotlib.path import Path as MPath
                clip_patch = patches.Polygon(pts, closed=True, transform=ax.transData)
                # Draw vigota lines (will be clipped)
                color = '#aaaaaa'; margin = 0.05; lw = 0.45; sp = 0.42
                if span_dir == 'x':
                    y = by1 + sp
                    while y < by2 - margin:
                        ln, = ax.plot([bx1+margin, bx2-margin], [y, y],
                                      color=color, linewidth=lw, zorder=2)
                        ln.set_clip_path(clip_patch)
                        y += sp
                else:
                    x = bx1 + sp
                    while x < bx2 - margin:
                        ln, = ax.plot([x, x], [by1+margin, by2-margin],
                                      color=color, linewidth=lw, zorder=2)
                        ln.set_clip_path(clip_patch)
                        x += sp
                # Draw tarugo bands
                span_len = bw if span_dir == 'x' else bh
                n_tar = max(1, round(span_len / 0.80))
                band_half = 0.06
                for k in range(n_tar):
                    pos = (bx1 if span_dir=='x' else by1) + span_len * (k+1) / (n_tar+1)
                    if span_dir == 'x':
                        rect = patches.Rectangle((pos-band_half, by1+margin),
                                                  band_half*2, bh-2*margin,
                                                  fill=True, facecolor='#cccccc',
                                                  edgecolor='#888888', linewidth=0.3,
                                                  zorder=3, alpha=0.65)
                    else:
                        rect = patches.Rectangle((bx1+margin, pos-band_half),
                                                  bw-2*margin, band_half*2,
                                                  fill=True, facecolor='#cccccc',
                                                  edgecolor='#888888', linewidth=0.3,
                                                  zorder=3, alpha=0.65)
                    rect.set_clip_path(clip_patch)
                    ax.add_patch(rect)
                _draw_span_arrow(ax, bx1, by1, bx2, by2, span_dir)
            cx = sum(p[0] for p in pts) / len(pts)
            cy = sum(p[1] for p in pts) / len(pts)
            sv_label = {'one_way':'1D','two_way':'2D','ribbed':'Alig.','cantilever':'Cons.'}.get(sv,'')
            cat = f'[{slab.catalog_id}]' if getattr(slab,'catalog_id',None) else ''
            ax.text(cx, cy + 0.10, slab.id,
                    ha='center', va='center', fontsize=6.5, fontweight='bold', zorder=5)
            ax.text(cx, cy - 0.20,
                    f'{sv_label} h={slab.thickness_cm:.0f}cm L={slab.span_m:.1f}m {cat}'.strip(),
                    ha='center', va='top', fontsize=5.0, color='#333333', zorder=5)
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
        pid = getattr(b, 'portico_id', '') or ''
        beam_label = f"{pid}\n{b.id}" if pid else b.id
        ax.text(mx, my, beam_label, ha='center', va='center', fontsize=5.5,
                rotation=rot, zorder=6, linespacing=1.2,
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
                      label='Aligeirada (vigotas+tarugos)'),
        patches.Patch(facecolor='#ddeeff', hatch='///', edgecolor='#aaaaaa',
                      label='Laje 1 Dir.'),
        patches.Patch(facecolor='#eeddff', hatch='xxx', edgecolor='#aaaaaa',
                      label='Laje 2 Dir.'),
        patches.Patch(facecolor='#ffeedd', hatch='---', edgecolor='#aaaaaa',
                      label='Consola'),
        patches.Patch(facecolor='#cccccc', edgecolor='#888888', label='Tarugo'),
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
            # Column that stops at piso: show grey "não aplicável" for Cobertura row
            if level == 'Cobertura' and getattr(col, 'stops_at', 'cobertura') == 'piso':
                ax.set_facecolor('#e0e0e0')
                ax.axis('off')
                ax.text(0.5, 0.5, '—', ha='center', va='center',
                        transform=ax.transAxes, fontsize=10, color='#666666')
                if j == 0:
                    ax.text(0.5, 0.95, col.id, ha='center', va='top',
                            transform=ax.transAxes, fontsize=7, fontweight='bold')
            else:
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


def _beam_frame_direction(beams, col_map) -> str:
    """Return 'X' or 'Y' for the primary axis of a beam group."""
    dx_tot = dy_tot = 0.0
    for b in beams:
        c1, c2 = col_map.get(b.start_node), col_map.get(b.end_node)
        if c1 and c2:
            dx_tot += abs(c2.x - c1.x)
            dy_tot += abs(c2.y - c1.y)
    return 'X' if dx_tot >= dy_tot else 'Y'


def _group_beams_into_frames(beams, col_map):
    """Group beams into frames (pórticos).
    Uses portico_id if set, otherwise groups by collinear alignment.
    Returns list of (label, direction, sorted_beam_list).
    """
    beams_with_pid = [b for b in beams if getattr(b, 'portico_id', '')]
    if beams_with_pid:
        pid_groups: dict = {}
        for b in beams:
            pid = getattr(b, 'portico_id', '') or '_auto'
            pid_groups.setdefault(pid, []).append(b)
        result = []
        for pid in sorted(pid_groups.keys()):
            grp = pid_groups[pid]
            d = _beam_frame_direction(grp, col_map)
            def _bsort(b, _d=d):
                c = col_map.get(b.start_node)
                return (c.x if _d == 'X' else c.y) if c else 0
            result.append((pid, d, sorted(grp, key=_bsort)))
        return result

    TOL_DEG = 20
    TOL_POS = 0.5

    def beam_angle_deg(b):
        c1 = col_map.get(b.start_node)
        c2 = col_map.get(b.end_node)
        if not c1 or not c2:
            return 0.0
        dx = abs(c2.x - c1.x)
        dy = abs(c2.y - c1.y)
        return math.degrees(math.atan2(dy, dx + 1e-9))

    x_beams = [b for b in beams if beam_angle_deg(b) <= TOL_DEG]
    y_beams = [b for b in beams if beam_angle_deg(b) > TOL_DEG]

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
            # label is auto-generated; direction is explicit
            result.append((direction, direction, sorted(groups[key], key=sort_key)))
        return result

    return group_by_transverse(x_beams, 'X') + group_by_transverse(y_beams, 'Y')


def _draw_beam_cross_section(ax, beam, n_bot, dia_bot, x_c, y_bot, width, height):
    """Draw a beam cross-section at (x_c, y_bot) with given drawn width/height."""
    cov = width * 0.09
    bar_r = width * 0.05
    # Outer box
    ax.add_patch(patches.Rectangle(
        (x_c - width / 2, y_bot), width, height,
        fill=True, facecolor='#f0f0f0', edgecolor='black',
        linewidth=0.8, zorder=5))
    # Stirrup inner outline (dashed)
    ax.add_patch(patches.Rectangle(
        (x_c - width / 2 + cov, y_bot + cov),
        width - 2 * cov, height - 2 * cov,
        fill=False, edgecolor='black', linewidth=0.45,
        linestyle='--', zorder=5))
    # Bottom bars
    for k in range(n_bot):
        bx = (x_c - width / 2 + cov + k * (width - 2 * cov) / max(n_bot - 1, 1)
              if n_bot > 1 else x_c)
        ax.add_patch(patches.Circle(
            (bx, y_bot + cov + bar_r), bar_r,
            fill=True, facecolor='black', zorder=6))
    # Top hanger bars (2)
    for bx in [x_c - width / 2 + cov, x_c + width / 2 - cov]:
        ax.add_patch(patches.Circle(
            (bx, y_bot + height - cov - bar_r * 0.7), bar_r * 0.75,
            fill=True, facecolor='black', zorder=6))


def _draw_frame_elevation(ax, direction, beams, col_map, frame_num, label=None):
    """Draw full pórtico: longitudinal elevation + cross-sections above each span."""
    ax.set_facecolor('white')
    ax.axis('off')

    # ── column positions ─────────────────────────────────────────────
    col_pos = {}
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

    # ── span list (x_left, x_right, beam, left_col_id, right_col_id) ──
    span_list = []
    for b in beams:
        p1, p2 = col_pos.get(b.start_node), col_pos.get(b.end_node)
        if p1 is None or p2 is None:
            continue
        if p1 <= p2:
            lid, rid = b.start_node, b.end_node
        else:
            p1, p2 = p2, p1
            lid, rid = b.end_node, b.start_node
        span_list.append((p1, p2, b, lid, rid))
    span_list.sort(key=lambda t: t[0])
    if not span_list:
        return

    # ── geometry ─────────────────────────────────────────────────────
    bh = beams[0].height_cm / 100    # beam height (m)
    bw = beams[0].width_cm / 100     # beam width (m)
    cover = 0.025                     # rebar cover (m)
    col_h = col_obj[sorted_col_ids[0]].height_m   # floor height (~3m)
    col_stub_top = col_h * 0.50
    col_stub_bot = col_h * 0.40
    beam_top = 0.0
    beam_bot = -bh

    # cross-section drawn size (at 3× magnification relative to meters)
    cs_scale = 3.0
    cs_w = bw * cs_scale
    cs_h = bh * cs_scale
    cs_gap = col_stub_top * 0.08
    cs_y_bot = beam_top + col_stub_top + cs_gap
    cs_y_top = cs_y_bot + cs_h

    # ── DRAW EACH SPAN ──────────────────────────────────────────────
    for x_l, x_r, beam, lid, rid in span_list:
        span = x_r - x_l
        mid  = (x_l + x_r) / 2
        rr   = beam.reinforcement_result or {}
        vsd  = beam.result.vsd_kn        if beam.result else 0.0
        msd  = beam.result.msd_knm       if beam.result else 0.0
        as_r = beam.result.required_as_cm2 if beam.result else 2.0
        d_cm = beam.effective_depth_cm

        n_bot, dia_bot, _ = _beam_bottom_bars(as_r)
        phi_e, s_e = _beam_stirrup_design(vsd, d_cm)   # end-zone stirrups
        # Mid-zone: one step lighter (max s = min(d/2, 20cm))
        phi_m = max(phi_e - 2, 6)
        s_m   = min(int(s_e * 1.5 / 5) * 5, 20)
        s_m   = max(s_m, s_e)

        col_w_l = (col_obj[lid].width_cm if direction == 'X'
                   else col_obj[lid].depth_cm) if lid in col_obj else 25
        col_w_r = (col_obj[rid].width_cm if direction == 'X'
                   else col_obj[rid].depth_cm) if rid in col_obj else 25

        # ── Beam body ──────────────────────────────────────────────
        ax.add_patch(patches.Rectangle(
            (x_l, beam_bot), span, bh,
            fill=True, facecolor='#f8f8f8',
            edgecolor='black', linewidth=1.0, zorder=2))

        # ── Stirrups in 3 zones ────────────────────────────────────
        zone = span / 4.0
        s_e_m = s_e / 100.0
        s_m_m = s_m / 100.0
        lw_e, lw_m = 0.45, 0.30

        def draw_stirs(x_start, x_end, spacing, lw):
            xs = x_start
            n = 0
            while xs <= x_end + 1e-4:
                ax.plot([xs, xs], [beam_bot + cover, beam_top - cover],
                        color='#666', linewidth=lw, alpha=0.75, zorder=2)
                xs += spacing
                n += 1
            return n

        n_el = draw_stirs(x_l + cover, x_l + zone, s_e_m, lw_e)
        n_mi = draw_stirs(x_l + zone, x_r - zone, s_m_m, lw_m)
        n_er = draw_stirs(x_r - zone, x_r - cover, s_e_m, lw_e)

        # zone boundary marks
        for xz in [x_l + zone, x_r - zone]:
            ax.plot([xz, xz], [beam_bot, beam_top],
                    color='#aaa', linewidth=0.5, linestyle=':', zorder=2)

        # ── BOTTOM bars ────────────────────────────────────────────
        inset_l = col_w_l / 200
        inset_r = col_w_r / 200
        y_b1 = beam_bot + cover + 0.006
        ax.plot([x_l + inset_l, x_r - inset_r], [y_b1, y_b1],
                color='black', linewidth=2.0, zorder=4, solid_capstyle='butt')

        c_bot = int(span * 100 - col_w_l / 2 - col_w_r / 2 + 15)
        bot_txt = rr.get("bottom_text") or f"{n_bot}Ø{dia_bot}"
        ax.text(mid, y_b1 + 0.015,
                f'{bot_txt}  C={c_bot}',
                ha='center', va='bottom',
                fontsize=7.0, fontweight='bold', zorder=5)

        # ── BOTTOM 2nd layer if n_bot > 4 ──────────────────────────
        if n_bot > 4:
            y_b2 = y_b1 + 0.022
            n2 = n_bot - 4
            ax.plot([x_l + inset_l + 0.1, x_r - inset_r - 0.1], [y_b2, y_b2],
                    color='black', linewidth=1.6, zorder=4, solid_capstyle='butt')
            c_b2 = int(c_bot * 0.7)
            ax.text(mid, y_b2 + 0.012,
                    f'{n2}Ø{dia_bot}  C={c_b2}  2ª camada',
                    ha='center', va='bottom', fontsize=6.0, zorder=5)

        # ── TOP HANGER bars (2Ø12 full span, dashed) ───────────────
        y_h = beam_top - cover - 0.010
        c_hang = int(span * 100 - col_w_l / 2 - col_w_r / 2 + 15)
        ax.plot([x_l + inset_l, x_r - inset_r], [y_h, y_h],
                color='black', linewidth=1.2, zorder=4,
                linestyle='--', dashes=(5, 3))
        ax.text(mid, y_h + 0.012,
                f'2Ø12  C={c_hang}  (m.)',
                ha='center', va='bottom',
                fontsize=6.0, style='italic', color='#444', zorder=5)

        # ── Stirrup labels (below beam) ─────────────────────────────
        y_sl = beam_bot - 0.08
        ax.text(x_l + zone * 0.5, y_sl,
                f'{n_el}xØ{phi_e} a/{s_e}',
                ha='center', va='top', fontsize=6.5)
        if n_mi > 0:
            ax.text(mid, y_sl,
                    f'{n_mi}xØ{phi_m} a/{s_m}',
                    ha='center', va='top', fontsize=6.5)
        ax.text(x_r - zone * 0.5, y_sl,
                f'{n_er}xØ{phi_e} a/{s_e}',
                ha='center', va='top', fontsize=6.5)

        # ── Msd/Vsd label inside beam ───────────────────────────────
        ax.text(mid, -bh * 0.62,
                f'Msd={msd:.1f}kNm  Vsd={vsd:.1f}kN',
                ha='center', va='center', fontsize=6.0, color='#444', zorder=3)

        # ── Beam label ──────────────────────────────────────────────
        ax.text(mid, -bh * 0.22,
                f'{beam.id}  ({int(bw*100)}×{int(bh*100)})',
                ha='center', va='center',
                fontsize=7.0, color='#222', style='italic', zorder=3)

        # ── Span dimension arrow ────────────────────────────────────
        y_arr = beam_top + col_stub_top * 0.60
        ax.annotate('', xy=(x_r, y_arr), xytext=(x_l, y_arr),
                    arrowprops=dict(arrowstyle='<->', color='black',
                                   lw=1.0, mutation_scale=8), zorder=5)
        ax.text(mid, y_arr + 0.05, f'{span:.3f} m',
                ha='center', va='bottom', fontsize=9.0, fontweight='bold')

        # ── Cross-section above this span ────────────────────────────
        _draw_beam_cross_section(ax, beam, n_bot, dia_bot,
                                 mid, cs_y_bot, cs_w, cs_h)
        ax.text(mid, cs_y_top + 0.05,
                f'{int(bw*100)}×{int(bh*100)} cm  [{n_bot}Ø{dia_bot}]',
                ha='center', va='bottom',
                fontsize=7.0, fontweight='bold')

    # ── COLUMN STUBS ─────────────────────────────────────────────────
    for cid in sorted_col_ids:
        col = col_obj[cid]
        pos = col_pos[cid]
        cw = (col.width_cm if direction == 'X' else col.depth_cm) / 100

        for (y0, h, hatch) in [
            (beam_top, col_stub_top, '///'),
            (beam_bot - col_stub_bot, col_stub_bot, '///'),
        ]:
            ax.add_patch(patches.Rectangle(
                (pos - cw / 2, y0), cw, h,
                fill=True, facecolor='#d0d0d0',
                edgecolor='black', linewidth=0.9, zorder=3))
            ax.add_patch(patches.Rectangle(
                (pos - cw / 2, y0), cw, h,
                fill=False, edgecolor='#999', linewidth=0.3,
                hatch=hatch, zorder=3))

        # Column label
        ax.text(pos, beam_top + col_stub_top + 0.03, cid,
                ha='center', va='bottom', fontsize=8, fontweight='bold')
        ax.text(pos, beam_bot - col_stub_bot - 0.04,
                f'{int(col.width_cm)}×{int(col.depth_cm)}',
                ha='center', va='top', fontsize=7.0, color='#444')

    # ── TOP SUPPORT BARS at each column (2Ø12, extends L/4 each side) ──
    for cid in sorted_col_ids:
        pos = col_pos[cid]
        lefts  = [(xl, xr, b) for xl, xr, b, l, r in span_list if abs(xr - pos) < 0.02]
        rights = [(xl, xr, b) for xl, xr, b, l, r in span_list if abs(xl - pos) < 0.02]
        if not lefts and not rights:
            continue
        x_ext_l = pos - (lefts[0][1]  - lefts[0][0])  / 4 if lefts  else pos
        x_ext_r = pos + (rights[0][1] - rights[0][0]) / 4 if rights else pos
        if x_ext_l >= x_ext_r:
            continue
        y_ts = beam_top - cover - 0.008
        ax.plot([x_ext_l, x_ext_r], [y_ts - 0.012, y_ts - 0.012],
                color='black', linewidth=1.3, zorder=6, solid_capstyle='butt')
        c_sup = int((x_ext_r - x_ext_l) * 100)
        ax.text(pos, y_ts - 0.024,
                f'2Ø12  C={c_sup}',
                ha='center', va='top',
                fontsize=5.0, fontweight='bold', zorder=7)

    # ── Frame title ───────────────────────────────────────────────────
    c0 = col_obj[sorted_col_ids[0]]
    cv = c0.y if direction == 'X' else c0.x
    al = 'Y' if direction == 'X' else 'X'
    msds = [f'{(b.result.msd_knm if b.result else 0):.0f}' for b in beams]
    pid_part = label if (label and label not in ('X', 'Y')) else f'Pórtico {frame_num}'
    title = (f'{pid_part}    ({al}={cv:.2f}m)    Escala 1:50    '
             f'Vigas {int(beams[0].width_cm)}×{int(beams[0].height_cm)} cm    '
             f'Msd=[{", ".join(msds)}] kNm')
    ax.set_title(title, fontsize=8.5, fontweight='bold', loc='left', pad=6)

    # ── Axis bounds (no equal aspect — let x dominate) ────────────────
    x0 = col_pos[sorted_col_ids[0]]
    x1 = col_pos[sorted_col_ids[-1]]
    tot = x1 - x0
    mg  = max(tot * 0.05, bw * 0.8)
    ax.set_xlim(x0 - mg - bw / 2, x1 + mg + bw / 2)
    ax.set_ylim(beam_bot - col_stub_bot - 0.40,
                cs_y_top + 0.25)


def draw_beam_schedule(project: Project) -> bytes:
    """Draw pormenores de vigas: longitudinal frame elevation + cross-sections."""
    beams_with_results = [b for b in project.beams if b.result]
    if not beams_with_results:
        return b""

    col_map = {c.id: c for c in project.columns}
    frames = _group_beams_into_frames(beams_with_results, col_map)
    if not frames:
        return b""

    fig_w = 22.0   # inches

    # Each frame gets a fixed row height (enough to read labels clearly)
    row_h = 5.5   # inches per frame
    fig_h = len(frames) * row_h + 1.0
    fig = plt.figure(figsize=(fig_w, fig_h), facecolor='white')
    fig.suptitle(f'PORMENORES DE VIGAS — {project.name}',
                 fontsize=14, fontweight='bold', y=0.999)

    from matplotlib.gridspec import GridSpec
    gs = GridSpec(len(frames), 1, figure=fig,
                  left=0.01, right=0.99,
                  top=0.97, bottom=0.01,
                  hspace=0.35)

    for idx, (label, direction, bms) in enumerate(frames):
        ax = fig.add_subplot(gs[idx, 0])
        _draw_frame_elevation(ax, direction, bms, col_map, idx + 1, label=label)

    return _fig_to_bytes(fig, dpi=180)


# ═══════════════════════════════════════════════════════════════════════════════
# DXF export — Pormenores de Vigas
# ═══════════════════════════════════════════════════════════════════════════════

def _dxf_rect(msp, x0, y0, w, h, layer, lw=25, close=True):
    pts = [(x0, y0), (x0+w, y0), (x0+w, y0+h), (x0, y0+h)]
    msp.add_lwpolyline(pts, close=close, dxfattribs={'layer': layer, 'lineweight': lw})


def _dxf_hatch(msp, x0, y0, w, h, layer, pattern='ANSI31', scale=0.04):
    hatch = msp.add_hatch(dxfattribs={'layer': layer})
    hatch.set_pattern_fill(pattern, scale=scale, angle=45)
    hatch.paths.add_polyline_path(
        [(x0,y0),(x0+w,y0),(x0+w,y0+h),(x0,y0+h)], is_closed=True)


def _dxf_text(msp, txt, x, y, h, layer, align='LEFT', color=None):
    from ezdxf.enums import TextEntityAlignment
    align_map = {
        'LEFT':   TextEntityAlignment.LEFT,
        'CENTER': TextEntityAlignment.MIDDLE_CENTER,
        'RIGHT':  TextEntityAlignment.RIGHT,
        'ML':     TextEntityAlignment.MIDDLE_LEFT,
        'MR':     TextEntityAlignment.MIDDLE_RIGHT,
    }
    attribs = {'height': h, 'layer': layer}
    if color is not None:
        attribs['color'] = color
    t = msp.add_text(txt, dxfattribs=attribs)
    t.set_placement((x, y), align=align_map.get(align, TextEntityAlignment.LEFT))


def _dxf_dim_linear(msp, x0, x1, y_dim, tick_h, txt, layer, h_txt):
    """Horizontal dimension line from x0 to x1 at y=y_dim."""
    # Main dimension line
    msp.add_line((x0, y_dim), (x1, y_dim), dxfattribs={'layer': layer, 'lineweight': 13})
    # Ticks
    for xd in [x0, x1]:
        msp.add_line((xd, y_dim - tick_h*0.5), (xd, y_dim + tick_h*0.5),
                     dxfattribs={'layer': layer, 'lineweight': 13})
    # Arrow-like serifs
    for xd, sign in [(x0, 1), (x1, -1)]:
        msp.add_line((xd, y_dim),
                     (xd + sign * tick_h * 0.8, y_dim + tick_h * 0.4),
                     dxfattribs={'layer': layer, 'lineweight': 13})
        msp.add_line((xd, y_dim),
                     (xd + sign * tick_h * 0.8, y_dim - tick_h * 0.4),
                     dxfattribs={'layer': layer, 'lineweight': 13})
    _dxf_text(msp, txt, (x0+x1)/2, y_dim + tick_h*0.7, h_txt, layer, 'CENTER')


def _dxf_frame_elevation(msp, direction, beams, col_map, frame_num, y_off, label=None):
    """Draw one pórtico frame into DXF model space at vertical offset y_off."""
    # ── column positions ──────────────────────────────────────────────────────
    col_pos, col_obj = {}, {}
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

    # ── span list ─────────────────────────────────────────────────────────────
    span_list = []
    for b in beams:
        p1, p2 = col_pos.get(b.start_node), col_pos.get(b.end_node)
        if p1 is None or p2 is None:
            continue
        if p1 <= p2:
            lid, rid = b.start_node, b.end_node
        else:
            p1, p2 = p2, p1
            lid, rid = b.end_node, b.start_node
        span_list.append((p1, p2, b, lid, rid))
    span_list.sort(key=lambda t: t[0])
    if not span_list:
        return

    # ── geometry (model-space metres) ─────────────────────────────────────────
    bh       = beams[0].height_cm / 100
    bw       = beams[0].width_cm  / 100
    cover    = 0.025
    col_h    = col_obj[sorted_col_ids[0]].height_m
    cst      = col_h * 0.45       # col stub top
    csb      = col_h * 0.35       # col stub bottom
    beam_top = y_off
    beam_bot = y_off - bh

    cs_scale = 3.5
    cs_w     = bw  * cs_scale
    cs_h_d   = bh  * cs_scale
    cs_gap   = cst * 0.15
    cs_y_bot = beam_top + cst + cs_gap

    # text heights (appear correctly at 1:50 on paper)
    TH_LG  = 0.175   # large: span dimension  (3.5mm @1:50)
    TH_MD  = 0.125   # medium: bar labels      (2.5mm)
    TH_SM  = 0.100   # small: secondary text   (2.0mm)
    TH_XS  = 0.085   # extra-small: Msd/Vsd    (1.7mm)

    # ── EACH SPAN ─────────────────────────────────────────────────────────────
    for x_l, x_r, beam, lid, rid in span_list:
        span = x_r - x_l
        mid  = (x_l + x_r) / 2
        rr   = beam.reinforcement_result or {}
        vsd  = beam.result.vsd_kn          if beam.result else 0.0
        msd  = beam.result.msd_knm         if beam.result else 0.0
        as_r = beam.result.required_as_cm2 if beam.result else 2.0
        d_cm = beam.effective_depth_cm

        n_bot, dia_bot, _ = _beam_bottom_bars(as_r)
        phi_e, s_e = _beam_stirrup_design(vsd, d_cm)
        phi_m = max(phi_e - 2, 6)
        s_m   = min(int(s_e * 1.5 / 5) * 5, 20)
        s_m   = max(s_m, s_e)

        col_w_l = (col_obj[lid].width_cm if direction == 'X'
                   else col_obj[lid].depth_cm) if lid in col_obj else 25
        col_w_r = (col_obj[rid].width_cm if direction == 'X'
                   else col_obj[rid].depth_cm) if rid in col_obj else 25

        # Beam rectangle
        _dxf_rect(msp, x_l, beam_bot, span, bh, 'VIGAS', lw=35)

        # Stirrups – 3 zones
        zone   = span / 4.0
        s_e_m  = s_e / 100.0
        s_m_m  = s_m / 100.0

        def draw_stirs_dxf(x_start, x_end, spacing, lw=13):
            xs = x_start
            n  = 0
            while xs <= x_end + 1e-4:
                msp.add_line((xs, beam_bot + cover), (xs, beam_top - cover),
                             dxfattribs={'layer': 'ESTRIBOS', 'lineweight': lw, 'color': 8})
                xs += spacing
                n  += 1
            return n

        n_el = draw_stirs_dxf(x_l + cover, x_l + zone, s_e_m, 18)
        n_mi = draw_stirs_dxf(x_l + zone,  x_r - zone, s_m_m, 13)
        n_er = draw_stirs_dxf(x_r - zone,  x_r - cover, s_e_m, 18)

        # zone boundary
        for xz in [x_l + zone, x_r - zone]:
            msp.add_line((xz, beam_bot), (xz, beam_top),
                         dxfattribs={'layer': 'ESTRIBOS', 'linetype': 'DASHED',
                                     'lineweight': 9, 'color': 8})

        # Bottom bars
        inset_l = col_w_l / 200
        inset_r = col_w_r / 200
        y_b = beam_bot + cover + 0.008
        msp.add_line((x_l + inset_l, y_b), (x_r - inset_r, y_b),
                     dxfattribs={'layer': 'ARMADURA_INF', 'lineweight': 50, 'color': 1})

        c_bot   = int(span * 100 - col_w_l/2 - col_w_r/2 + 15)
        bot_txt = rr.get('bottom_text') or f'{n_bot}Ø{dia_bot}'
        _dxf_text(msp, f'{bot_txt}  C={c_bot}', mid, y_b + TH_SM*0.6, TH_MD, 'TEXTO',
                  'CENTER', color=1)

        # Top hanger bars (dashed)
        y_h = beam_top - cover - 0.010
        msp.add_line((x_l + inset_l, y_h), (x_r - inset_r, y_h),
                     dxfattribs={'layer': 'ARMADURA_SUP', 'lineweight': 25,
                                 'linetype': 'DASHED', 'color': 2})
        c_hang = c_bot
        _dxf_text(msp, f'2Ø12  C={c_hang} (m.)', mid, y_h + TH_XS*0.5,
                  TH_SM, 'TEXTO', 'CENTER', color=2)

        # Stirrup labels (below beam)
        y_sl = beam_bot - TH_SM * 0.6
        _dxf_text(msp, f'{n_el}xØ{phi_e} a/{s_e}',
                  x_l + zone*0.5, y_sl, TH_SM, 'TEXTO', 'CENTER')
        if n_mi > 0:
            _dxf_text(msp, f'{n_mi}xØ{phi_m} a/{s_m}',
                      mid, y_sl, TH_SM, 'TEXTO', 'CENTER')
        _dxf_text(msp, f'{n_er}xØ{phi_e} a/{s_e}',
                  x_r - zone*0.5, y_sl, TH_SM, 'TEXTO', 'CENTER')

        # Msd / Vsd inside beam
        _dxf_text(msp, f'Msd={msd:.1f}kNm  Vsd={vsd:.1f}kN',
                  mid, beam_bot + bh*0.3, TH_XS, 'TEXTO', 'CENTER', color=9)

        # Beam ID
        _dxf_text(msp, f'{beam.id}  ({int(bw*100)}x{int(bh*100)})',
                  mid, beam_bot + bh*0.65, TH_SM, 'TEXTO', 'CENTER', color=8)

        # Span dimension
        y_arr = beam_top + cst * 0.55
        _dxf_dim_linear(msp, x_l, x_r, y_arr, TH_LG * 0.7,
                        f'{span:.3f} m', 'COTAS', TH_LG)

        # ── Cross-section above span ──────────────────────────────────────────
        cx    = mid
        cy_b  = cs_y_bot
        # rectangle
        _dxf_rect(msp, cx - cs_w/2, cy_b, cs_w, cs_h_d, 'CORTES', lw=25)
        # stirrup inner
        cov_s = cs_w * 0.10
        _dxf_rect(msp, cx - cs_w/2 + cov_s, cy_b + cov_s,
                  cs_w - 2*cov_s, cs_h_d - 2*cov_s, 'ESTRIBOS', lw=13)
        # bottom bar circles
        bar_r = cs_w * 0.055
        for k in range(n_bot):
            bx = (cx - cs_w/2 + cov_s + k*(cs_w - 2*cov_s)/max(n_bot-1, 1)
                  if n_bot > 1 else cx)
            msp.add_circle((bx, cy_b + cov_s + bar_r),
                           bar_r, dxfattribs={'layer': 'ARMADURA_INF', 'color': 1})
        # top hanger bar circles
        for bxh in [cx - cs_w/2 + cov_s, cx + cs_w/2 - cov_s]:
            msp.add_circle((bxh, cy_b + cs_h_d - cov_s - bar_r*0.8),
                           bar_r*0.75, dxfattribs={'layer': 'ARMADURA_SUP', 'color': 2})
        # label
        _dxf_text(msp, f'{int(bw*100)}x{int(bh*100)} cm  [{n_bot}Ø{dia_bot}]',
                  cx, cs_y_bot + cs_h_d + TH_SM*0.6, TH_SM, 'TEXTO', 'CENTER')

    # ── COLUMN STUBS ──────────────────────────────────────────────────────────
    for cid in sorted_col_ids:
        col = col_obj[cid]
        pos = col_pos[cid]
        cw  = (col.width_cm if direction == 'X' else col.depth_cm) / 100

        for y0s, hs in [(beam_top, cst), (beam_bot - csb, csb)]:
            _dxf_rect(msp, pos - cw/2, y0s, cw, hs, 'PILARES', lw=35)
            _dxf_hatch(msp, pos - cw/2, y0s, cw, hs, 'PILARES')

        _dxf_text(msp, cid, pos, beam_top + cst + TH_MD*0.3, TH_MD,
                  'TEXTO', 'CENTER', color=7)
        _dxf_text(msp, f'{int(col.width_cm)}x{int(col.depth_cm)}',
                  pos, beam_bot - csb - TH_SM*0.6, TH_SM, 'TEXTO', 'CENTER', color=8)

    # ── TOP SUPPORT BARS at columns ────────────────────────────────────────────
    for cid in sorted_col_ids:
        pos = col_pos[cid]
        lefts  = [(xl,xr) for xl,xr,b,l,r in span_list if abs(xr-pos) < 0.02]
        rights = [(xl,xr) for xl,xr,b,l,r in span_list if abs(xl-pos) < 0.02]
        if not lefts and not rights:
            continue
        x_ext_l = pos - (lefts[0][1]  - lefts[0][0]) / 4 if lefts  else pos
        x_ext_r = pos + (rights[0][1] - rights[0][0]) / 4 if rights else pos
        if x_ext_l >= x_ext_r:
            continue
        y_ts = beam_top - cover - 0.012
        msp.add_line((x_ext_l, y_ts), (x_ext_r, y_ts),
                     dxfattribs={'layer': 'ARMADURA_SUP', 'lineweight': 35, 'color': 2})
        c_sup = int((x_ext_r - x_ext_l) * 100)
        _dxf_text(msp, f'2Ø12  C={c_sup}',
                  pos, y_ts - TH_SM*0.6, TH_SM, 'TEXTO', 'CENTER', color=2)

    # ── Frame title ────────────────────────────────────────────────────────────
    c0 = col_obj[sorted_col_ids[0]]
    cv = c0.y if direction == 'X' else c0.x
    al = 'Y' if direction == 'X' else 'X'
    x0_fr = col_pos[sorted_col_ids[0]]
    msds  = [f'{(b.result.msd_knm if b.result else 0):.0f}' for b in beams]
    pid_part = label if (label and label not in ('X', 'Y')) else f'PORTICO {frame_num}'
    title = (f'{pid_part}  ({al}={cv:.2f}m)  1:50  '
             f'Vigas {int(beams[0].width_cm)}x{int(beams[0].height_cm)} cm  '
             f'Msd=[{", ".join(msds)}] kNm')
    _dxf_text(msp, title, x0_fr, beam_top + cst + TH_LG*1.2, TH_LG,
              'TEXTO', 'LEFT', color=7)


def draw_beam_schedule_dxf(project: 'Project') -> bytes:
    """Generate DXF file with pormenores de vigas for all frames."""
    try:
        import ezdxf
    except ImportError:
        return b""

    beams_with_results = [b for b in project.beams if b.result]
    if not beams_with_results:
        return b""

    col_map = {c.id: c for c in project.columns}
    frames  = _group_beams_into_frames(beams_with_results, col_map)
    if not frames:
        return b""

    doc = ezdxf.new('R2010')
    doc.header['$INSUNITS'] = 6   # metres
    doc.header['$MEASUREMENT'] = 1  # metric

    # Ensure DASHED linetype
    if 'DASHED' not in doc.linetypes:
        doc.linetypes.add('DASHED', pattern=[0.3, -0.15])

    # Layers
    for lname, color in [
        ('VIGAS',        7),
        ('PILARES',      8),
        ('ARMADURA_INF', 1),
        ('ARMADURA_SUP', 2),
        ('ESTRIBOS',     3),
        ('CORTES',       5),
        ('COTAS',        1),
        ('TEXTO',        7),
    ]:
        if lname not in doc.layers:
            doc.layers.add(lname, color=color)

    msp = doc.modelspace()

    # Title block text
    _dxf_text(msp, f'PORMENORES DE VIGAS — {project.name}',
              0, 0, 0.25, 'TEXTO', 'LEFT', color=7)

    # Compute Y-offset per frame (stack downward, starting at y=-1.5)
    y_cursor = -1.5
    for idx, (label, direction, bms) in enumerate(frames):
        bh_i  = bms[0].height_cm / 100
        ch_i  = bh_i * 4   # fallback
        # Get actual col height
        for b in bms:
            for nid in [b.start_node, b.end_node]:
                if nid in col_map:
                    ch_i = col_map[nid].height_m
                    break
            else:
                continue
            break

        cst_i = ch_i * 0.45
        csb_i = ch_i * 0.35
        cs_h_i = bh_i * 3.5
        frame_h = cst_i + bh_i + csb_i + cs_h_i + 0.60   # total Y extent

        _dxf_frame_elevation(msp, direction, bms, col_map, idx + 1, y_cursor, label=label)
        y_cursor -= (frame_h + 2.0)   # 2m spacing between frames

    out = io.StringIO()
    doc.write(out)
    return out.getvalue().encode('utf-8')


# ── shared DXF setup helper ──────────────────────────────────────────────────

def _dxf_new_doc():
    """Create standard DXF document with engineering layers."""
    import ezdxf
    doc = ezdxf.new('R2010')
    doc.header['$INSUNITS'] = 6    # metres
    doc.header['$MEASUREMENT'] = 1
    if 'DASHED' not in doc.linetypes:
        doc.linetypes.add('DASHED', pattern=[0.3, -0.15])
    for lname, color in [
        ('VIGAS', 7), ('PILARES', 8), ('LAJES', 5),
        ('SAPATAS', 6), ('ARMADURA_INF', 1), ('ARMADURA_SUP', 2),
        ('ESTRIBOS', 3), ('CORTES', 5), ('COTAS', 1), ('TEXTO', 7),
        ('GRELHA', 9), ('LEGENDA', 7),
    ]:
        if lname not in doc.layers:
            doc.layers.add(lname, color=color)
    return doc, doc.modelspace()


def _dxf_title_block(msp, project, drawing_title: str, scale: str, x0=0.0, y0=-2.0):
    """Draw a simple title block at (x0, y0)."""
    TH = 0.18
    lines = [
        f'OBRA: {getattr(project, "name", "")}',
        f'REQUERENTE: {getattr(project, "owner", "")}',
        f'LOCALIZAÇÃO: {getattr(project, "location", "")}',
        f'TIPO: {getattr(project, "building_type", "")}',
        f'PEÇA: {drawing_title}',
        f'ESCALA: {scale}',
        f'PROJECTISTA: {getattr(project, "designer", "")}',
    ]
    for k, line in enumerate(lines):
        _dxf_text(msp, line, x0, y0 - k * TH * 1.4, TH, 'TEXTO', 'LEFT', color=7)


def _dxf_col_square(msp, col, x_c, y_c, scale=1.0):
    """Draw a filled column square at (x_c, y_c) in DXF. scale=pixels per cm."""
    w = col.width_cm  * scale
    d = col.depth_cm  * scale
    _dxf_rect(msp, x_c - w/2, y_c - d/2, w, d, 'PILARES', lw=50)
    # Solid hatch
    hatch = msp.add_hatch(dxfattribs={'layer': 'PILARES', 'color': 254})
    hatch.set_solid_fill()
    hatch.paths.add_polyline_path(
        [(x_c-w/2, y_c-d/2),(x_c+w/2, y_c-d/2),
         (x_c+w/2, y_c+d/2),(x_c-w/2, y_c+d/2)], is_closed=True)


# ── A. Planta de Fundações DXF ───────────────────────────────────────────────

def draw_foundation_plan_dxf(project: 'Project') -> bytes:
    """DXF foundation plan: footings, tie beams, columns."""
    try:
        doc, msp = _dxf_new_doc()
    except ImportError:
        return b""

    TH_LG, TH_MD, TH_SM = 0.175, 0.125, 0.100
    col_lookup   = {c.id: c for c in project.columns}
    footing_map  = {f.related_column_id: f for f in project.footings}

    # Footings (dashed)
    for col in project.columns:
        f = footing_map.get(col.id)
        if not f:
            continue
        fw = f.width_a_cm / 100
        fh = f.width_b_cm / 100
        pts = [(col.x-fw/2, col.y-fh/2),(col.x+fw/2, col.y-fh/2),
               (col.x+fw/2, col.y+fh/2),(col.x-fw/2, col.y+fh/2)]
        msp.add_lwpolyline(pts, close=True, dxfattribs={
            'layer': 'SAPATAS', 'lineweight': 18, 'linetype': 'DASHED'})
        _dxf_text(msp, f'{int(f.width_a_cm)}x{int(f.width_b_cm)}x{int(f.height_cm)}',
                  col.x, col.y - fh/2 - TH_SM*0.8, TH_SM, 'TEXTO', 'CENTER', color=6)
        _dxf_text(msp, f.id,
                  col.x + fw/2 + 0.05, col.y, TH_SM, 'TEXTO', 'LEFT', color=6)

    # Tie beams
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
        nx, ny = -dy/length*bw/2, dx/length*bw/2
        pts = [(c1.x+nx, c1.y+ny),(c2.x+nx, c2.y+ny),
               (c2.x-nx, c2.y-ny),(c1.x-nx, c1.y-ny)]
        msp.add_lwpolyline(pts, close=True, dxfattribs={'layer': 'VIGAS', 'lineweight': 25})
        hatch = msp.add_hatch(dxfattribs={'layer': 'VIGAS', 'color': 8})
        hatch.set_solid_fill()
        hatch.paths.add_polyline_path(pts, is_closed=True)
        mx, my = (c1.x+c2.x)/2, (c1.y+c2.y)/2
        _dxf_text(msp, tb.id, mx, my, TH_SM, 'TEXTO', 'CENTER')

    # Columns (solid)
    for col in project.columns:
        _dxf_col_square(msp, col, col.x, col.y, scale=0.01)
        _dxf_text(msp, col.id, col.x, col.y + col.depth_cm/200 + TH_MD*0.4,
                  TH_MD, 'TEXTO', 'CENTER', color=7)

    _dxf_title_block(msp, project, 'PLANTA DE FUNDAÇÕES', '1:50')
    out = io.StringIO(); doc.write(out)
    return out.getvalue().encode('utf-8')


# ── B. Planta da Laje DXF ───────────────────────────────────────────────────

def draw_slab_plan_dxf(project: 'Project', title: str = 'PLANTA DA LAJE DE PISO') -> bytes:
    """DXF slab plan: bays with hatch, beams, columns."""
    try:
        doc, msp = _dxf_new_doc()
    except ImportError:
        return b""

    TH_LG, TH_MD, TH_SM = 0.175, 0.125, 0.100
    col_lookup = {c.id: c for c in project.columns}

    # Slab bays from polygon_points
    hatch_patterns = {
        'one_way':    ('ANSI31', 0.08),
        'two_way':    ('ANSI37', 0.08),
        'ribbed':     ('ANSI32', 0.10),
        'cantilever': ('ANSI33', 0.10),
    }
    for slab in project.slabs:
        pts = slab.polygon_points
        if not pts or len(pts) < 3:
            continue
        msp.add_lwpolyline(pts, close=True, dxfattribs={'layer': 'LAJES', 'lineweight': 18})
        st = str(getattr(slab.slab_type, 'value', slab.slab_type)).lower()
        pat, sc = hatch_patterns.get(st, ('ANSI31', 0.08))
        hatch = msp.add_hatch(dxfattribs={'layer': 'LAJES', 'color': 5})
        hatch.set_pattern_fill(pat, scale=sc)
        hatch.paths.add_polyline_path(pts, is_closed=True)
        cx = sum(p[0] for p in pts) / len(pts)
        cy = sum(p[1] for p in pts) / len(pts)
        _dxf_text(msp, slab.id, cx, cy, TH_MD, 'TEXTO', 'CENTER', color=5)

    # Beams
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
        nx, ny = -dy/length*bw/2, dx/length*bw/2
        pts = [(c1.x+nx, c1.y+ny),(c2.x+nx, c2.y+ny),
               (c2.x-nx, c2.y-ny),(c1.x-nx, c1.y-ny)]
        msp.add_lwpolyline(pts, close=True, dxfattribs={'layer': 'VIGAS', 'lineweight': 35})
        hatch = msp.add_hatch(dxfattribs={'layer': 'VIGAS', 'color': 8})
        hatch.set_solid_fill()
        hatch.paths.add_polyline_path(pts, is_closed=True)
        mx, my = (c1.x+c2.x)/2, (c1.y+c2.y)/2
        pid = getattr(b, 'portico_id', '') or ''
        blabel = f"{pid}\\P{b.id}" if pid else b.id  # ezdxf MTEXT newline
        _dxf_text(msp, blabel, mx, my, TH_SM, 'TEXTO', 'CENTER', color=7)

    # Columns
    for col in project.columns:
        _dxf_col_square(msp, col, col.x, col.y, scale=0.01)
        _dxf_text(msp, col.id, col.x, col.y + col.depth_cm/200 + TH_SM*0.4,
                  TH_SM, 'TEXTO', 'CENTER', color=7)

    _dxf_title_block(msp, project, title, '1:50')
    out = io.StringIO(); doc.write(out)
    return out.getvalue().encode('utf-8')


# ── C. Quadro de Pilares DXF ─────────────────────────────────────────────────

def draw_column_schedule_dxf(project: 'Project') -> bytes:
    """DXF column schedule: cross-sections in a grid (3 rows × N cols)."""
    try:
        doc, msp = _dxf_new_doc()
    except ImportError:
        return b""
    if not project.columns:
        return b""

    TH_MD, TH_SM, TH_XS = 0.125, 0.100, 0.085
    CS = 1/35.0    # scale: 1cm column = 1/35 m in DXF  (≈1:35)
    CELL_W = 1.60  # m per column cell
    CELL_H = 2.20  # m per level row
    LABEL_W = 0.6

    levels = ['Cobertura', 'Piso 1', 'Fundação']

    # Title
    _dxf_text(msp, f'QUADRO DE PILARES — {project.name}',
              0, 0.3, 0.22, 'TEXTO', 'LEFT', color=7)

    for j, level in enumerate(levels):
        y_row = -(j * CELL_H) - 0.6   # top of this row

        # Level label (vertical)
        _dxf_text(msp, level, -LABEL_W + 0.05, y_row - CELL_H/2, TH_MD,
                  'TEXTO', 'LEFT', color=8)

        # Row border line
        total_w = len(project.columns) * CELL_W
        msp.add_line((-LABEL_W, y_row), (total_w, y_row),
                     dxfattribs={'layer': 'GRELHA', 'lineweight': 18})

        for i, col in enumerate(project.columns):
            x_cell = i * CELL_W
            y_bot  = y_row - CELL_H

            # Cell border
            _dxf_rect(msp, x_cell, y_bot, CELL_W, CELL_H, 'GRELHA', lw=9)

            # Column cross-section centred in upper 60% of cell
            w = col.width_cm  * CS
            d = col.depth_cm  * CS
            cx = x_cell + CELL_W/2
            cy = y_row - CELL_H*0.30   # centre at 30% from top

            # Outer rectangle
            _dxf_rect(msp, cx-w/2, cy-d/2, w, d, 'PILARES', lw=35)
            # Stirrup inner
            cov = col.width_cm * 0.10 * CS
            _dxf_rect(msp, cx-w/2+cov, cy-d/2+cov, w-2*cov, d-2*cov, 'ESTRIBOS', lw=13)

            # Bars
            if col.result and col.result.adopted_as_cm2 > 0:
                as_cm2 = col.result.adopted_as_cm2
                opts = [(4,12,4.52),(4,16,8.04),(6,12,6.79),(8,12,9.05),(4,20,12.57)]
                n_bars, bar_dia = 4, 12
                for nb, bd, area in opts:
                    if area >= as_cm2:
                        n_bars, bar_dia = nb, bd
                        break
            else:
                n_bars, bar_dia = 4, 12

            bar_r = w * 0.07
            if col.shape == 'circular':
                r = w/2 - cov - bar_r
                for k in range(n_bars):
                    ang = k * 2 * math.pi / n_bars
                    bx = cx + r * math.cos(ang)
                    by = cy + r * math.sin(ang)
                    msp.add_circle((bx, by), bar_r, dxfattribs={'layer': 'ARMADURA_INF', 'color': 1})
            else:
                bar_pos = [(cx-w/2+cov, cy-d/2+cov),(cx+w/2-cov, cy-d/2+cov),
                           (cx+w/2-cov, cy+d/2-cov),(cx-w/2+cov, cy+d/2-cov)]
                if n_bars >= 6:
                    bar_pos += [(cx, cy-d/2+cov),(cx, cy+d/2-cov)]
                if n_bars >= 8:
                    bar_pos += [(cx-w/2+cov, cy),(cx+w/2-cov, cy)]
                for bx, by in bar_pos[:n_bars]:
                    msp.add_circle((bx, by), bar_r, dxfattribs={'layer': 'ARMADURA_INF', 'color': 1})

            # Text below section
            dim_lbl = f'Ø{int(col.width_cm)}' if col.shape=='circular' else f'{int(col.width_cm)}x{int(col.depth_cm)}'
            y_txt = cy - d/2 - TH_SM*0.6
            _dxf_text(msp, dim_lbl, cx, y_txt, TH_MD, 'TEXTO', 'CENTER', color=8)
            _dxf_text(msp, f'{n_bars}Ø{bar_dia}', cx, y_txt - TH_SM*1.3, TH_SM, 'TEXTO', 'CENTER', color=1)
            _dxf_text(msp, 'Ø8 a/20', cx, y_txt - TH_SM*2.5, TH_SM, 'TEXTO', 'CENTER', color=3)

            # Column ID (only on first row)
            if j == 0:
                _dxf_text(msp, col.id, cx, y_row + TH_MD*0.3, TH_MD, 'TEXTO', 'CENTER', color=7)

    # Bottom border
    y_bot_all = -(len(levels) * CELL_H) - 0.6
    total_w   = len(project.columns) * CELL_W
    msp.add_line((-LABEL_W, y_bot_all), (total_w, y_bot_all),
                 dxfattribs={'layer': 'GRELHA', 'lineweight': 18})

    _dxf_title_block(msp, project, 'QUADRO DE PILARES', '1:35', 0, y_bot_all - 0.3)
    out = io.StringIO(); doc.write(out)
    return out.getvalue().encode('utf-8')


# ── D. Quadro de Sapatas DXF ─────────────────────────────────────────────────

def draw_footing_schedule_dxf(project: 'Project') -> bytes:
    """DXF footing schedule: plan + cross-section per footing."""
    try:
        doc, msp = _dxf_new_doc()
    except ImportError:
        return b""
    if not project.footings:
        return b""

    TH_MD, TH_SM, TH_XS = 0.125, 0.100, 0.085
    FS = 1/50.0   # scale: 1cm footing = 1/50 m in DXF (≈1:50)
    CELL_W = 2.20
    CELL_H = 3.40
    col_map = {c.id: c for c in project.columns}

    _dxf_text(msp, f'QUADRO DE SAPATAS — {project.name}',
              0, 0.3, 0.22, 'TEXTO', 'LEFT', color=7)

    for i, ft in enumerate(project.footings):
        x0 = i * CELL_W
        y0 = -0.6
        _dxf_rect(msp, x0, y0 - CELL_H, CELL_W, CELL_H, 'GRELHA', lw=9)

        fw = ft.width_a_cm * FS
        fh = ft.width_b_cm * FS
        fhgt = ft.height_cm * FS
        cx = x0 + CELL_W/2
        # Plan view (top 45% of cell)
        plan_cy = y0 - CELL_H*0.22
        _dxf_rect(msp, cx-fw/2, plan_cy-fh/2, fw, fh, 'SAPATAS', lw=25)
        _dxf_hatch(msp, cx-fw/2, plan_cy-fh/2, fw, fh, 'SAPATAS', 'ANSI31', 0.05)

        # Column stub on plan
        col = col_map.get(ft.related_column_id)
        if col:
            cw = col.width_cm * FS
            cd = col.depth_cm * FS
            _dxf_rect(msp, cx-cw/2, plan_cy-cd/2, cw, cd, 'PILARES', lw=35)
            hatch = msp.add_hatch(dxfattribs={'layer': 'PILARES', 'color': 254})
            hatch.set_solid_fill()
            hatch.paths.add_polyline_path(
                [(cx-cw/2, plan_cy-cd/2),(cx+cw/2, plan_cy-cd/2),
                 (cx+cw/2, plan_cy+cd/2),(cx-cw/2, plan_cy+cd/2)], is_closed=True)

        # Cross-section view (middle 30% of cell)
        sec_cy = y0 - CELL_H*0.58
        _dxf_rect(msp, cx-fw/2, sec_cy, fw, fhgt, 'SAPATAS', lw=25)
        if col:
            _dxf_rect(msp, cx-col.width_cm*FS/2, sec_cy+fhgt, col.width_cm*FS, fhgt*0.5, 'PILARES', lw=25)

        # Reinforcement bars (bottom of footing cross-section)
        rr = ft.reinforcement_result or {}
        as_x = ft.result.required_as_cm2 if ft.result else 0
        as_y = ft.result.required_as_cm2 if ft.result else 0
        bar_y = sec_cy + fhgt*0.12
        msp.add_line((cx-fw/2*0.8, bar_y), (cx+fw/2*0.8, bar_y),
                     dxfattribs={'layer': 'ARMADURA_INF', 'lineweight': 35, 'color': 1})

        # Labels
        y_lbl = y0 - CELL_H*0.72
        _dxf_text(msp, ft.id, cx, y0 + TH_MD*0.3, TH_MD, 'TEXTO', 'CENTER', color=7)
        _dxf_text(msp, f'{int(ft.width_a_cm)}x{int(ft.width_b_cm)}x{int(ft.height_cm)} cm',
                  cx, y_lbl, TH_SM, 'TEXTO', 'CENTER', color=8)
        if ft.result:
            sigma = getattr(ft.result, 'sigma_soil_mpa', 0) * 1000
            _dxf_text(msp, f'σ={sigma:.0f} kPa',
                      cx, y_lbl - TH_SM*1.4, TH_SM, 'TEXTO', 'CENTER', color=8)
        if as_x > 0:
            _dxf_text(msp, f'As_x={as_x:.1f} cm²',
                      cx, y_lbl - TH_SM*2.7, TH_SM, 'TEXTO', 'CENTER', color=1)
        if as_y > 0:
            _dxf_text(msp, f'As_y={as_y:.1f} cm²',
                      cx, y_lbl - TH_SM*3.9, TH_SM, 'TEXTO', 'CENTER', color=1)

    y_bot = -0.6 - CELL_H
    _dxf_title_block(msp, project, 'QUADRO DE SAPATAS', '1:50',
                     0, y_bot - 0.3)
    out = io.StringIO(); doc.write(out)
    return out.getvalue().encode('utf-8')


# ── Quadro de Lajes ───────────────────────────────────────────────────────────

def _slab_schedule_rows(slabs, project):
    """Build rows list for the slab schedule table (PAVINORTE format)."""
    _TYPE_PT = {
        "one_way": "Vigotada 1 dir.", "ribbed": "Aligeirada",
        "two_way": "Maciça 2 dir.", "cantilever": "Consola",
    }
    fyk = getattr(project, 'fyk_mpa', 500.0)
    fck = getattr(project, 'fck_mpa', 25.0)
    fyd = min(fyk / 1.15, 435.0)
    fcd = fck / 1.5
    rows = []
    for s in slabs:
        tp = _TYPE_PT.get(_slab_val(s.slab_type), _slab_val(s.slab_type))
        r = s.result
        As_str = "-"
        if r:
            d_m = s.effective_depth_cm / 100
            mu = r.msd_knm_m * 1000 / max(d_m**2 * fcd * 1e6, 1e-6)
            mu = min(mu, 0.295)
            omega = 1.0 - math.sqrt(max(1 - 2*mu, 0.0))
            As = omega * d_m * fcd * 1e6 / (fyd * 1e6) * 10000
            As = max(As, 0.0013 * 100 * s.effective_depth_cm)
            As_str = f"{As:.2f}"
        cat = s.catalog_id or "-"
        # h notation: thickness_cm = h1 + 5cm capping for ribbed, else plain
        sv = _slab_val(s.slab_type)
        if sv in (_ST_RIBBED, _ST_ONE_WAY) and s.thickness_cm > 5:
            h_str = f"{int(s.thickness_cm - 5)}+5"
        else:
            h_str = f"{s.thickness_cm:.0f}"
        # Maciçamento: solid band at supports for ribbed/one_way
        macic = "Apoios" if sv in (_ST_RIBBED, _ST_ONE_WAY) else "-"
        rows.append([
            s.id, tp, (s.direction or "-").upper(), cat,
            f"{s.span_m:.2f}", h_str, f"{s.effective_depth_cm:.0f}",
            f"{s.gk_kn_m2:.2f}", f"{s.qk_kn_m2:.2f}",
            f"{r.msd_knm_m:.2f}" if r else "-",
            As_str, macic,
            f"{getattr(r,'deflection_utilization',0):.2f}" if r else "-",
            f"{getattr(r,'crack_utilization',0):.2f}" if r else "-",
        ])
    return rows


def _draw_slab_table(ax, rows, headers, hdr_color='#2c3e50', col_widths=None):
    """Render a slab schedule table on the given Axes."""
    if col_widths is None:
        col_widths = [0.05, 0.12, 0.04, 0.10, 0.06, 0.06, 0.05,
                      0.07, 0.07, 0.07, 0.08, 0.07, 0.08, 0.08]
    ax.axis('off')
    if not rows:
        ax.text(0.5, 0.5, 'Sem lajes', ha='center', va='center', transform=ax.transAxes)
        return
    tbl = ax.table(cellText=rows, colLabels=headers,
                   cellLoc='center', loc='center', colWidths=col_widths)
    tbl.auto_set_font_size(False)
    tbl.set_fontsize(7.5)
    tbl.scale(1, 1.45)
    for j in range(len(headers)):
        tbl[0, j].set_facecolor(hdr_color)
        tbl[0, j].set_text_props(color='white', fontweight='bold')
    n_util_cols = 2  # last 2 columns are utilization
    n_cols = len(headers)
    for i, row in enumerate(rows):
        for j in range(n_cols):
            tbl[i+1, j].set_facecolor('#f8f9fa' if i % 2 == 0 else 'white')
        for jj in range(n_cols - n_util_cols, n_cols):
            try:
                v = float(row[jj])
                c = '#c0392b' if v >= 1.0 else ('#e67e22' if v >= 0.80 else '#27ae60')
                tbl[i+1, jj].set_facecolor(c)
                tbl[i+1, jj].set_text_props(color='white', fontweight='bold')
            except Exception:
                pass


def draw_slab_schedule(project: Project) -> bytes:
    """PNG slab schedule — split into Piso and Cobertura sections."""
    slabs = project.slabs
    if not slabs:
        fig, ax = plt.subplots(figsize=(10, 2))
        ax.text(0.5, 0.5, 'Sem lajes', ha='center', va='center', transform=ax.transAxes)
        buf = io.BytesIO(); fig.savefig(buf, format='png', dpi=150, bbox_inches='tight')
        plt.close(fig); return buf.getvalue()

    headers = ["ID", "Tipo", "Dir.", "Catálogo/Vigota", "Vão (m)", "h1+h2",
               "d (cm)", "gk (kN/m²)", "qk (kN/m²)", "Msd (kNm/m)",
               "As (cm²/m)", "Maciçamento", "U.Flecha", "U.Fissura"]

    piso_slabs  = [s for s in slabs if getattr(s, 'level', 'piso') != 'cobertura']
    cob_slabs   = [s for s in slabs if getattr(s, 'level', 'piso') == 'cobertura']

    rows_piso = _slab_schedule_rows(piso_slabs, project)
    rows_cob  = _slab_schedule_rows(cob_slabs,  project)

    n_piso = max(len(rows_piso), 1)
    n_cob  = max(len(rows_cob), 1)
    row_h  = 0.42
    hdr_h  = 0.6
    fig_h  = (n_piso + n_cob) * row_h + hdr_h * 2 + 2.0
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(17, max(4.0, fig_h)))
    fig.suptitle(f'QUADRO DE LAJES — {project.name}', fontsize=13, fontweight='bold', y=1.01)

    ax1.set_title('LAJE DE PISO', fontsize=11, fontweight='bold',
                  color='white', pad=4,
                  bbox=dict(facecolor='#2980b9', edgecolor='none', pad=4))
    _draw_slab_table(ax1, rows_piso, headers, hdr_color='#2980b9')

    ax2.set_title('LAJE DE COBERTURA', fontsize=11, fontweight='bold',
                  color='white', pad=4,
                  bbox=dict(facecolor='#16a085', edgecolor='none', pad=4))
    _draw_slab_table(ax2, rows_cob, headers, hdr_color='#16a085')

    fig.tight_layout()
    buf = io.BytesIO()
    fig.savefig(buf, format='png', dpi=150, bbox_inches='tight')
    plt.close(fig)
    return buf.getvalue()


def draw_slab_schedule_dxf(project: Project) -> bytes:
    """DXF slab schedule table."""
    slabs = project.slabs
    doc, msp = _dxf_new_doc()

    _TYPE_PT = {
        "one_way": "Vigotada 1 dir.", "ribbed": "Aligeirada",
        "two_way": "Maciça 2 dir.", "cantilever": "Consola",
    }

    COLS = ["ID", "Tipo", "Dir", "Vão(m)", "h(cm)", "gk", "qk", "Msd", "As(cm²/m)", "Util.Flex"]
    WIDTHS = [1.2, 3.0, 0.8, 1.5, 1.2, 1.2, 1.2, 1.5, 2.0, 1.8]
    ROW_H = 0.6
    TH = 0.100  # text height (same as TH_SM)

    # Header row
    x0 = 0.0; y0 = 0.0
    total_w = sum(WIDTHS)
    _dxf_rect(msp, x0, y0 - ROW_H, total_w, ROW_H, 'GRELHA', lw=35)
    xc = x0
    for i, (hdr, w) in enumerate(zip(COLS, WIDTHS)):
        _dxf_text(msp, hdr, xc + w/2, y0 - ROW_H/2, TH, 'TEXTO', 'CENTER', color=7)
        xc += w

    rows_y = y0 - ROW_H
    for si, s in enumerate(slabs):
        tp = _TYPE_PT.get(_slab_val(s.slab_type), _slab_val(s.slab_type))
        r = s.result
        fyd = min(getattr(project,'fyk_mpa',500)/1.15, 435.0)
        fcd = getattr(project,'fck_mpa',25)/1.5
        d_m = s.effective_depth_cm/100
        As = 0.0
        if r:
            mu = r.msd_knm_m*1000/max(d_m**2*fcd*1e6,1e-6)
            mu = min(mu,0.295)
            omega = 1-math.sqrt(max(1-2*mu,0))
            As = max(omega*d_m*fcd*1e6/(fyd*1e6)*10000, 0.0013*100*s.effective_depth_cm)
        vals = [
            s.id, tp[:18], (s.direction or "-").upper(),
            f"{s.span_m:.2f}", f"{s.thickness_cm:.0f}",
            f"{s.gk_kn_m2:.2f}", f"{s.qk_kn_m2:.2f}",
            f"{r.msd_knm_m:.2f}" if r else "-",
            f"{As:.2f}",
            f"{getattr(r,'deflection_utilization',0):.2f}" if r else "-",
        ]
        ry = rows_y - ROW_H
        _dxf_rect(msp, x0, ry, total_w, ROW_H, 'GRELHA', lw=13)
        xc = x0
        for val, w in zip(vals, WIDTHS):
            _dxf_text(msp, str(val), xc + w/2, ry + ROW_H/2, TH, 'TEXTO', 'CENTER', color=8)
            xc += w
        rows_y = ry

    y_bot = rows_y
    _dxf_title_block(msp, project, 'QUADRO DE LAJES', 'S/Escala', 0, y_bot - 0.3)
    out = io.StringIO(); doc.write(out)
    return out.getvalue().encode('utf-8')


# ── Retaining Wall Schedule ───────────────────────────────────────────────────

def draw_retaining_wall_schedule(project: Project) -> bytes:
    """PNG schedule for retaining walls and their continuous footings."""
    walls = getattr(project, 'retaining_walls', [])
    cfs   = getattr(project, 'continuous_footings', [])

    fig, axes = plt.subplots(2, 1, figsize=(14, max(4, len(walls)*1.2 + len(cfs)*1.2 + 2)))

    # ── Muros de betão ────────────────────────────────────────────────────────
    ax1 = axes[0]; ax1.axis('off')
    if not walls:
        ax1.text(0.5, 0.5, 'Sem muros de betão', ha='center', va='center', transform=ax1.transAxes)
    else:
        hdrs = ["ID", "H (m)", "e base (cm)", "Largura base (m)", "γ solo (kN/m³)",
                "φ (°)", "q sob. (kN/m²)", "SF Desliز.", "SF Derrub.", "σ solo (MPa)", "OK"]
        rows = []
        for w in walls:
            r = w.result
            ok = "✓" if r and r.sliding_ok and r.overturning_ok and r.bearing_ok else "✗"
            rows.append([
                w.id, f"{w.height_m:.1f}", f"{w.stem_thickness_cm:.0f}",
                f"{w.base_width_m:.2f}", f"{w.gamma_soil_kn_m3:.0f}", f"{w.phi_deg:.0f}",
                f"{w.surcharge_kn_m2:.1f}",
                f"{r.sliding_safety:.2f}" if r else "-",
                f"{r.overturning_safety:.2f}" if r else "-",
                f"{r.bearing_stress_mpa*1000:.0f}" if r else "-",
                ok,
            ])
        tbl = ax1.table(cellText=rows, colLabels=hdrs, cellLoc='center', loc='center')
        tbl.auto_set_font_size(False); tbl.set_fontsize(8.5); tbl.scale(1, 1.5)
        for j in range(len(hdrs)):
            tbl[0, j].set_facecolor('#2c3e50')
            tbl[0, j].set_text_props(color='white', fontweight='bold')
        for i, row in enumerate(rows):
            for j in range(len(hdrs)):
                tbl[i+1, j].set_facecolor('#f8f9fa' if i%2==0 else 'white')
            ok_val = row[-1]
            tbl[i+1, len(hdrs)-1].set_facecolor('#27ae60' if ok_val == "✓" else '#c0392b')
            tbl[i+1, len(hdrs)-1].set_text_props(color='white', fontweight='bold')
    ax1.set_title('MUROS DE BETÃO DE SUPORTE', fontsize=12, fontweight='bold', pad=8)

    # ── Sapatas corridas ──────────────────────────────────────────────────────
    ax2 = axes[1]; ax2.axis('off')
    if not cfs:
        ax2.text(0.5, 0.5, 'Sem sapatas corridas', ha='center', va='center', transform=ax2.transAxes)
    else:
        hdrs2 = ["ID", "Muro", "Largura (cm)", "Altura (cm)", "Comp. (m)",
                 "σ solo (MPa)", "Util. Solo", "As req. (cm²/m)", "Util. Flex."]
        rows2 = []
        for cf in cfs:
            r = cf.result
            rows2.append([
                cf.id, cf.related_wall_id,
                f"{cf.width_cm:.0f}", f"{cf.height_cm:.0f}", f"{cf.length_m:.1f}",
                f"{r.soil_stress_mpa*1000:.0f} kPa" if r else "-",
                f"{r.soil_utilization:.2f}" if r else "-",
                f"{r.required_as_cm2_m:.2f}" if r else "-",
                f"{r.bending_utilization:.2f}" if r else "-",
            ])
        tbl2 = ax2.table(cellText=rows2, colLabels=hdrs2, cellLoc='center', loc='center')
        tbl2.auto_set_font_size(False); tbl2.set_fontsize(8.5); tbl2.scale(1, 1.5)
        for j in range(len(hdrs2)):
            tbl2[0, j].set_facecolor('#16a085')
            tbl2[0, j].set_text_props(color='white', fontweight='bold')
        for i, row in enumerate(rows2):
            for j in range(len(hdrs2)):
                tbl2[i+1, j].set_facecolor('#f8f9fa' if i%2==0 else 'white')
    ax2.set_title('SAPATAS CORRIDAS', fontsize=12, fontweight='bold', pad=8)

    fig.suptitle(f'{project.name} — Muros e Sapatas Corridas', fontsize=13, fontweight='bold', y=1.01)
    fig.tight_layout()
    buf = io.BytesIO()
    fig.savefig(buf, format='png', dpi=150, bbox_inches='tight')
    plt.close(fig)
    return buf.getvalue()
