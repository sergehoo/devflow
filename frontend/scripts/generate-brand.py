"""
Identité DevFlow — générateur unique du symbole « flux binaire ».

Un flux en S (le « / » de </>) : voie centrale jaune (le workflow) encadrée de
deux voies de données composées de caractères 0 / 1 orientés le long de la
courbe. Trois niveaux de détail : détaillé (≥ 56 px), compact (1 = trait,
0 = point, 24–48 px), favicon (16–32 px, traits épaissis et resserrés).

Produit, depuis la même géométrie : public/brand/*.svg, public/favicon.svg,
les PNG (16, 32, 180, 192, 512, maskable), src/components/brand/geometry.ts et
le partiel Django templates/partials/_devflow_mark.html.

    cd frontend && python3 scripts/generate-brand.py      # PNG : rsvg-convert (librsvg)
"""
import math
import os
import shutil
import subprocess
import sys

YELLOW, INK, AMBER, CREAM = "#FFD54F", "#202020", "#B07A00", "#F5F1E8"
BITS = "1011001110100101101100101"

def bez(p, t):
    (x0, y0), (x1, y1), (x2, y2), (x3, y3) = p
    u = 1 - t
    x = u**3*x0 + 3*u*u*t*x1 + 3*u*t*t*x2 + t**3*x3
    y = u**3*y0 + 3*u*u*t*y1 + 3*u*t*t*y2 + t**3*y3
    dx = 3*u*u*(x1-x0) + 6*u*t*(x2-x1) + 3*t*t*(x3-x2)
    dy = 3*u*u*(y1-y0) + 6*u*t*(y2-y1) + 3*t*t*(y3-y2)
    n = math.hypot(dx, dy) or 1
    return x, y, dx/n, dy/n

def lane(p, offset, n=400, t0=0.0, t1=1.0):
    pts = []
    for i in range(n + 1):
        x, y, tx, ty = bez(p, t0 + (t1 - t0) * i / n)
        pts.append((x - ty*offset, y + tx*offset, tx, ty))
    return pts

def path_d(pts, every=10):
    """Polyligne allégée (1 point sur ``every``, 1 décimale) : quelques centaines d'octets par voie."""
    keep = pts[::every] + ([pts[-1]] if (len(pts) - 1) % every else [])
    return "M" + "L".join(f"{x:.1f} {y:.1f}" for x, y, *_ in keep)

def resample(pts, step, margin):
    out, acc = [], 0.0
    total = sum(math.hypot(b[0]-a[0], b[1]-a[1]) for a, b in zip(pts, pts[1:]))
    target = margin
    for a, b in zip(pts, pts[1:]):
        seg = math.hypot(b[0]-a[0], b[1]-a[1])
        while acc + seg >= target and target <= total - margin + 1e-6:
            r = (target - acc) / seg
            out.append((a[0] + (b[0]-a[0])*r, a[1] + (b[1]-a[1])*r, a[2], a[3]))
            target += step
        acc += seg
    return out

def glyphs(pts, color, step, h, start=0):
    out = []
    for i, (x, y, tx, ty) in enumerate(resample(pts, step, step * 0.5)):
        ang = math.degrees(math.atan2(ty, tx))
        bit = BITS[(start + i) % len(BITS)]
        if bit == "1":
            shape = f'<rect x="{-h*0.15:.2f}" y="{-h/2:.2f}" width="{h*0.3:.2f}" height="{h:.2f}" rx="{h*0.15:.2f}"/>'
        else:
            shape = f'<ellipse rx="{h*0.3:.2f}" ry="{h*0.42:.2f}" fill="none" stroke="{color}" stroke-width="{h*0.24:.2f}"/>'
        out.append(f'<g transform="translate({x:.1f} {y:.1f}) rotate({ang:.0f})">{shape}</g>')
    return f'<g fill="{color}">' + "".join(out) + "</g>"

CURVE = [(9, 50), (31, 51), (33, 13), (55, 14)]
GAP = 9

def mark(ink=INK, amber=AMBER, kind="detailed"):
    """detailed : caractères 0/1 (≥ 64 px) ; compact : trait/point (24–48 px) ; tiny : favicon 16–32 px."""
    if kind == "detailed":
        a, b, c = lane(CURVE, -GAP, t0=0.10, t1=1.0), lane(CURVE, 0), lane(CURVE, GAP, t0=0.0, t1=0.90)
        return (f'<path d="{path_d(b)}" fill="none" stroke="{YELLOW}" stroke-width="6.5" stroke-linecap="round"/>'
                + glyphs(a, ink, 5.5, 6.2) + glyphs(c, amber, 5.5, 6.2, start=7))
    gap, wc, wl, dash, k = (9.5, 8, 4.6, "0 7.5 6 7.5", 1.0) if kind == "compact" else (11, 10, 6.5, "0 9.5 8 9.5", 0.84)
    curve = [(32 + (x - 32) * k, 32 + (y - 32) * k) for x, y in CURVE]  # resserré : rien ne déborde du cadre
    a, b, c = lane(curve, -gap, t0=0.12, t1=1.0), lane(curve, 0), lane(curve, gap, t0=0.0, t1=0.88)
    out = [f'<path d="{path_d(b)}" fill="none" stroke="{YELLOW}" stroke-width="{wc}" stroke-linecap="round"/>']
    for pts, col in ((a, ink), (c, amber)):
        out.append(f'<path d="{path_d(pts)}" fill="none" stroke="{col}" stroke-width="{wl}" stroke-linecap="round" stroke-dasharray="{dash}"/>')
    return "".join(out)

def svg(inner, size=64):
    return f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64" width="{size}" height="{size}">{inner}</svg>'


WORD = ('<text x="78" y="43" font-family="Inter, \'Segoe UI\', system-ui, -apple-system, sans-serif" font-size="31" '
        'font-weight="800" letter-spacing="-0.8"><tspan fill="{ink}">Dev</tspan><tspan fill="{flow}">Flow</tspan></text>')


def file_svg(inner, w=64, title="DevFlow"):
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} 64" width="{w}" height="64" role="img" aria-label="{title}">'
            f'<title>{title}</title>{inner}</svg>\n')


def favicon():
    """Favicon adaptatif : encre anthracite en clair, crème en sombre (règle CSS, pas de var() en attribut)."""
    inner = mark(ink="INK", kind="tiny").replace('stroke="INK"', 'class="ink"')
    style = "<style>.ink{stroke:#202020}@media (prefers-color-scheme:dark){.ink{stroke:#F5F1E8}}</style>"
    return file_svg(style + inner)



def ts_module():
    """Géométrie du symbole pour le composant React (même source que les fichiers SVG)."""
    import json

    def glyph_list(pts, step, start):
        out = []
        for i, (x, y, tx, ty) in enumerate(resample(pts, step, step * 0.5)):
            out.append([round(x, 1), round(y, 1), round(math.degrees(math.atan2(ty, tx))), int(BITS[(start + i) % len(BITS)])])
        return out

    a, b, c = lane(CURVE, -GAP, t0=0.10, t1=1.0), lane(CURVE, 0), lane(CURVE, GAP, t0=0.0, t1=0.90)
    detailed = {"flow": path_d(b), "ink": glyph_list(a, 5.5, 0), "amber": glyph_list(c, 5.5, 7)}
    ca, cb, cc = lane(CURVE, -9.5, t0=0.12, t1=1.0), lane(CURVE, 0), lane(CURVE, 9.5, t0=0.0, t1=0.88)
    compact = {"flow": path_d(cb), "ink": path_d(ca), "amber": path_d(cc)}
    return ("/* Généré par frontend/scripts/generate-brand.py (symbole « flux binaire ») — ne pas éditer à la main. */\n"
            f"export const BRAND_COLORS = {{ yellow: \"{YELLOW}\", amber: \"{AMBER}\" }} as const;\n"
            "/** Glyphes : [x, y, angle (deg), bit 0|1] le long des voies de flux (repère 64 × 64). */\n"
            f"export const DETAILED = {json.dumps(detailed)} as const;\n"
            f"export const COMPACT = {json.dumps(compact)} as const;\n")



def django_partial():
    """Symbole compact en SVG inline pour les gabarits Django historiques (aucune dépendance aux statiques)."""
    inner = mark(ink="currentColor", kind="compact")
    return ("{# Symbole DevFlow (généré par frontend/scripts/generate-brand.py). Usage : {% include \"partials/_devflow_mark.html\" with size=28 %} #}\n"
            '<svg class="devflow-mark" viewBox="0 0 64 64" width="{{ size|default:28 }}" height="{{ size|default:28 }}" aria-hidden="true" focusable="false" '
            f'style="flex-shrink:0">{inner}</svg>\n')


def main():
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # frontend/
    public = os.path.join(root, "public")
    os.makedirs(os.path.join(public, "brand"), exist_ok=True)
    tiny = file_svg(mark(kind="tiny"))
    cream = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="-14 -14 92 92" width="92" height="92">'
             f'<rect x="-14" y="-14" width="92" height="92" fill="{CREAM}"/>{mark(kind="compact")}</svg>')
    maskable = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="-26 -26 116 116" width="116" height="116">'
                f'<rect x="-26" y="-26" width="116" height="116" fill="{CREAM}"/>{mark(kind="compact")}</svg>')
    files = {
        "brand/logo-mark.svg": file_svg(mark()),
        "brand/logo-mark-dark.svg": file_svg(mark(ink=CREAM)),
        "brand/logo-mark-compact.svg": file_svg(mark(kind="compact")),
        "brand/logo-mark-compact-dark.svg": file_svg(mark(ink=CREAM, kind="compact")),
        "brand/logo.svg": file_svg(mark() + WORD.format(ink=INK, flow=AMBER), w=228),
        "brand/logo-dark.svg": file_svg(mark(ink=CREAM) + WORD.format(ink=CREAM, flow=YELLOW), w=228),
        "favicon.svg": favicon(),
    }
    for name, content in files.items():
        with open(os.path.join(public, name), "w") as fh:
            fh.write(content)
    with open(os.path.join(root, "src", "components", "brand", "geometry.ts"), "w") as fh:
        fh.write(ts_module())
    with open(os.path.join(os.path.dirname(root), "templates", "partials", "_devflow_mark.html"), "w") as fh:
        fh.write(django_partial())
    rsvg = shutil.which("rsvg-convert")
    if not rsvg:
        print("rsvg-convert absent : PNG non régénérés (brew install librsvg / apt install librsvg2-bin).")
        return
    for source, size, target in ((tiny, 16, "favicon-16.png"), (tiny, 32, "favicon-32.png"), (cream, 180, "apple-touch-icon.png"),
                                 (files["brand/logo-mark-compact.svg"], 192, "icon-192.png"),
                                 (files["brand/logo-mark.svg"], 512, "icon-512.png"), (maskable, 512, "icon-maskable-512.png")):
        subprocess.run([rsvg, "-w", str(size), "-h", str(size), "-o", os.path.join(public, target), "-"], input=source.encode(), check=True)
    print("Identité DevFlow régénérée.")


if __name__ == "__main__":
    main()
