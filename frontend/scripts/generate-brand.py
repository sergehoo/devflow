"""
Identité DevFlow — générateur unique du logo « ampoule & engrenage ».

Source : le logo officiel (PSD « devflow LOGO ») exporté en
``scripts/brand/devflow-logo-master.png`` (symbole + « DEV » + « flow » manuscrit).

- Le symbole (ampoule jaune, rayons, engrenage) est redessiné en vecteur sur la
  géométrie mesurée du dessin source (repère 1143 × 1262, traits de 37) : net à
  toutes les tailles, engrenage en ``currentColor`` (noir en clair, crème en sombre).
  Trois niveaux : détaillé (≥ 56 px), compact (24–48 px, traits épaissis) et
  favicon (16–32 px : ampoule seule, engrenage 6 dents, moyeu plein).
- Le logo complet (avec « flow » manuscrit) reste l'image du PSD, déclinée en
  clair et en sombre (noir → crème).

Produit : public/brand/*.svg|png, public/favicon.svg, les PNG d'icônes (16, 32,
180, 192, 512, maskable), src/components/brand/geometry.ts et le partiel Django
templates/partials/_devflow_mark.html.

    cd frontend && ../venv/bin/python scripts/generate-brand.py     # PNG : rsvg-convert (librsvg) + Pillow
"""
import json
import math
import os
import shutil
import subprocess

YELLOW, INK, CREAM = "#FFD119", "#000000", "#F5F1E8"

# ─── Géométrie mesurée sur le dessin source (repère 1143 × 1262) ─────────────
CX, CY, R = 571.5, 584.5, 376.5          # ampoule : cercle, axe de symétrie x = CX
GY = 612.0                               # centre de l'engrenage (x = CX)
STROKE = 37
GAP = (225.9, 237.1)                     # ouverture du verre en haut à gauche (degrés, y vers le bas)
DEPART, K1, K2 = 126.3, 42.0, 48.0       # raccord cercle → culot (courbe de Bézier)
NECK_X, NECK_Y, BASE_Y, CORNER = 405.0, 990.0, 1164.0, 62.0
BAND = (583.5, 658.5)                    # bague du culot : interruption centrale
CAP = (98.0, 79.0)                       # demi-ellipse sous le culot
GEAR = dict(r_tip=252.0, w_tip=38.0, r_base=191.0, w_base=45.0)
RING = 101.0
OFFSET = (0.5, 0.5)
LEFT_RAYS = [((571.5, 18.5), (571.5, 125.5)), ((394.5, 118.8), (409.3, 156.8)), ((180.8, 180.3), (256.7, 256.2)),
             ((120.2, 393.9), (157.3, 408.5)), ((19.5, 570.9), (126.5, 570.9))]


def num(v):
    return f"{v:.1f}".rstrip("0").rstrip(".")


def pt(p):
    return f"{num(p[0] + OFFSET[0])} {num(p[1] + OFFSET[1])}"


def mirror(p):
    return (2 * CX - p[0], p[1])


def polar(deg, r=R):
    t = math.radians(deg)
    return CX + r * math.cos(t), CY + r * math.sin(t)


def rays_d(keep=None):
    out = []
    for i, (a, b) in enumerate(LEFT_RAYS):
        if keep is not None and i not in keep:
            continue
        out.append(f"M{pt(a)}L{pt(b)}")
        if a[0] != CX:
            out.append(f"M{pt(mirror(a))}L{pt(mirror(b))}")
    return "".join(out)


def bulb_d():
    """Verre (arc ouvert en haut à gauche), raccords, culot arrondi, bague et demi-ellipse."""
    xl, xr = NECK_X, 2 * CX - NECK_X
    a1 = polar(DEPART)
    t = math.radians(DEPART)
    c1 = (a1[0] + K1 * math.sin(t), a1[1] - K1 * math.cos(t))
    c2 = (xl, NECK_Y - K2)
    outline = (f"M{pt(polar(GAP[0]))}A{num(R)} {num(R)} 0 0 0 {pt(a1)}C{pt(c1)} {pt(c2)} {pt((xl, NECK_Y))}"
               f"L{pt((xl, BASE_Y - CORNER))}A{num(CORNER)} {num(CORNER)} 0 0 0 {pt((xl + CORNER, BASE_Y))}"
               f"L{pt((xr - CORNER, BASE_Y))}A{num(CORNER)} {num(CORNER)} 0 0 0 {pt((xr, BASE_Y - CORNER))}"
               f"L{pt((xr, NECK_Y))}C{pt(mirror(c2))} {pt(mirror(c1))} {pt(mirror(a1))}"
               f"A{num(R)} {num(R)} 0 0 0 {pt(polar(GAP[1]))}")
    band = f"M{pt((xl, NECK_Y))}L{pt((BAND[0], NECK_Y))}M{pt((BAND[1], NECK_Y))}L{pt((xr, NECK_Y))}"
    cap = f"M{pt((CX - CAP[0], BASE_Y))}A{num(CAP[0])} {num(CAP[1])} 0 0 0 {pt((CX + CAP[0], BASE_Y))}"
    return outline + band + cap


def gear_d(teeth=8):
    """Engrenage : dents à sommet plat, creux en arc de cercle. Moins de dents = dents élargies."""
    widen = 8 / teeth * (1.15 if teeth != 8 else 1)
    r_tip, w_tip, r_base, w_base = GEAR["r_tip"], GEAR["w_tip"] * widen, GEAR["r_base"], GEAR["w_base"] * widen
    rv = math.hypot(w_base, r_base)
    teeth_pts = []
    for k in range(teeth):
        a = math.radians(-90 + 360 * k / teeth)
        ux, uy, vx, vy = math.cos(a), math.sin(a), -math.sin(a), math.cos(a)
        p = lambda rad, tan: (CX + rad * ux + tan * vx, GY + rad * uy + tan * vy)  # noqa: E731
        teeth_pts.append((p(r_base, -w_base), p(r_tip, -w_tip), p(r_tip, w_tip), p(r_base, w_base)))
    d = [f"M{pt(teeth_pts[0][0])}"]
    for k, (_bl, tl, tr, br) in enumerate(teeth_pts):
        d.append(f"L{pt(tl)}L{pt(tr)}L{pt(br)}A{num(rv)} {num(rv)} 0 0 1 {pt(teeth_pts[(k + 1) % teeth][0])}")
    return "".join(d) + "Z"


# Niveaux de détail : épaisseur des traits, rayons conservés, dents, moyeu (anneau ou disque plein).
LEVELS = {
    "detailed": dict(stroke=STROKE, rays=None, teeth=8, hub=("ring", RING)),
    "compact": dict(stroke=60, rays=None, teeth=8, hub=("ring", RING)),
    "tiny": dict(stroke=95, rays=(), teeth=6, hub=("dot", 60)),
}


def view_box(level):
    """Cadre carré centré sur le symbole (rayons compris, ou ampoule seule pour le favicon)."""
    spec = LEVELS[level]
    half = spec["stroke"] / 2
    top = (18.5 if spec["rays"] is None else 208.0) - half - 20
    bottom = 1243 + half + 20
    size = bottom - top
    return f"{num(CX + OFFSET[0] - size / 2)} {num(top + OFFSET[1])} {num(size)} {num(size)}"


def geometry(level):
    spec = LEVELS[level]
    kind, radius = spec["hub"]
    return {
        "viewBox": view_box(level), "stroke": spec["stroke"],
        "yellow": rays_d(spec["rays"]) + bulb_d(), "gear": gear_d(spec["teeth"]),
        "hub": {"cx": CX + OFFSET[0], "cy": GY + OFFSET[1], "r": radius, "filled": kind == "dot"},
    }


def mark_inner(level, ink=INK, ink_attr=None):
    g = geometry(level)
    ink_paint = ink_attr or f'stroke="{ink}"'
    line = f'fill="none" stroke-linecap="round" stroke-linejoin="round" stroke-width="{g["stroke"]}"'
    hub = g["hub"]
    hub_svg = (f'<circle cx="{num(hub["cx"])}" cy="{num(hub["cy"])}" r="{num(hub["r"])}" {ink_paint.replace("stroke", "fill")}/>'
               if hub["filled"] else
               f'<circle cx="{num(hub["cx"])}" cy="{num(hub["cy"])}" r="{num(hub["r"])}" {ink_paint} {line}/>')
    return (f'<path d="{g["yellow"]}" stroke="{YELLOW}" {line}/>'
            f'<path d="{g["gear"]}" {ink_paint} {line}/>{hub_svg}')


def file_svg(level, ink=INK, title="DevFlow", extra=""):
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="{view_box(level)}" width="64" height="64" role="img" '
            f'aria-label="{title}"><title>{title}</title>{extra}{mark_inner(level, ink)}</svg>\n')


def favicon():
    """Favicon adaptatif : engrenage noir en clair, crème en sombre (règle CSS, pas de var() en attribut)."""
    style = f"<style>.ink{{stroke:{INK};fill:{INK}}}@media (prefers-color-scheme:dark){{.ink{{stroke:{CREAM};fill:{CREAM}}}}}</style>"
    inner = mark_inner("tiny", ink_attr='class="ink"').replace('class="ink" fill="none"', 'class="ink" style="fill:none"')
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="{view_box("tiny")}" width="64" height="64">'
            f"{style}{inner}</svg>\n")


def on_background(level, pad_ratio):
    """Icône pleine (fond crème) : ``pad_ratio`` = marge autour du symbole (zone sûre des icônes masquables)."""
    x, y, size, _ = (float(v) for v in view_box(level).split())
    pad = size * pad_ratio
    vb = f"{num(x - pad)} {num(y - pad)} {num(size + 2 * pad)} {num(size + 2 * pad)}"
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="{vb}"><rect x="{num(x - pad)}" y="{num(y - pad)}" '
            f'width="{num(size + 2 * pad)}" height="{num(size + 2 * pad)}" fill="{CREAM}"/>{mark_inner(level)}</svg>')


def ts_module():
    """Géométrie du symbole pour le composant React (même source que les fichiers SVG)."""
    levels = {name: geometry(name) for name in LEVELS}
    return ("/* Généré par frontend/scripts/generate-brand.py (logo « ampoule & engrenage ») — ne pas éditer à la main. */\n"
            f'export const BRAND_COLORS = {{ yellow: "{YELLOW}", ink: "{INK}", cream: "{CREAM}" }} as const;\n'
            "/** Symbole : chemins jaunes (rayons + ampoule), engrenage et moyeu (encre = currentColor). */\n"
            f"export const MARK = {json.dumps(levels)} as const;\n"
            "export type MarkLevel = keyof typeof MARK;\n"
            "/** Logo complet (image du PSD) : largeur / hauteur. */\n"
            f"export const FULL_LOGO_RATIO = {FULL_RATIO};\n")


def django_partial():
    """Symbole compact en SVG inline pour les gabarits Django historiques (engrenage en currentColor)."""
    return ('{# Symbole DevFlow (généré par frontend/scripts/generate-brand.py). Usage : {% include "partials/_devflow_mark.html" with size=28 %} #}\n'
            f'<svg class="devflow-mark" viewBox="{view_box("compact")}" width="{{{{ size|default:28 }}}}" height="{{{{ size|default:28 }}}}" '
            f'aria-hidden="true" focusable="false" style="flex-shrink:0">{mark_inner("compact", "currentColor")}</svg>\n')


FULL_RATIO = 1.0


def full_logos(public):
    """Logo complet clair / sombre depuis l'image maîtresse (noir → crème, jaune conservé)."""
    global FULL_RATIO
    from PIL import Image

    master = Image.open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "brand", "devflow-logo-master.png")).convert("RGBA")
    FULL_RATIO = round(master.width / master.height, 4)
    width = 720  # ≥ 3 × la plus grande largeur affichée
    light = master.resize((width, round(width / FULL_RATIO)), Image.LANCZOS)
    cream = tuple(int(CREAM[i:i + 2], 16) for i in (1, 3, 5))
    # Part de noir d'un pixel = 1 - max(r, g, b) : le noir devient crème, le jaune ne bouge pas.
    pixels = light.load()
    dark = Image.new("RGBA", light.size)
    out = dark.load()
    for y in range(light.height):
        for x in range(light.width):
            pr, pg, pb, pa = pixels[x, y]
            k = 1 - max(pr, pg, pb) / 255
            out[x, y] = (min(255, round(pr + k * cream[0])), min(255, round(pg + k * cream[1])),
                         min(255, round(pb + k * cream[2])), pa)
    for image, name in ((light, "devflow-logo.png"), (dark, "devflow-logo-dark.png")):
        # Deux teintes + transparence : une palette de 256 couleurs suffit (fichier ~4 × plus léger).
        image.quantize(colors=256, method=Image.Quantize.FASTOCTREE).save(os.path.join(public, "brand", name), optimize=True)


def main():
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # frontend/
    public = os.path.join(root, "public")
    brand = os.path.join(public, "brand")
    os.makedirs(brand, exist_ok=True)
    for old in ("logo.svg", "logo-dark.svg"):  # ancien logo « flux binaire »
        if os.path.exists(os.path.join(brand, old)):
            os.remove(os.path.join(brand, old))
    full_logos(public)
    files = {
        "brand/logo-mark.svg": file_svg("detailed"),
        "brand/logo-mark-dark.svg": file_svg("detailed", CREAM),
        "brand/logo-mark-compact.svg": file_svg("compact"),
        "brand/logo-mark-compact-dark.svg": file_svg("compact", CREAM),
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
    tiny = file_svg("tiny")
    for source, size, target in ((tiny, 16, "favicon-16.png"), (tiny, 32, "favicon-32.png"),
                                 (on_background("compact", 0.10), 180, "apple-touch-icon.png"),
                                 # Fond crème : l'engrenage reste lisible sur les écrans d'accueil sombres.
                                 (on_background("compact", 0.08), 192, "icon-192.png"),
                                 (on_background("detailed", 0.08), 512, "icon-512.png"),
                                 (on_background("detailed", 0.16), 512, "icon-maskable-512.png")):
        subprocess.run([rsvg, "-w", str(size), "-h", str(size), "-o", os.path.join(public, target), "-"],
                       input=source.encode(), check=True)
    print("Identité DevFlow régénérée.")


if __name__ == "__main__":
    main()
