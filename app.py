import streamlit as st
import cadquery as cq
from OCP.BRepAdaptor import BRepAdaptor_Surface
from OCP.GeomAbs import GeomAbs_Plane, GeomAbs_Cylinder
import ezdxf
from ezdxf import bbox as dxf_bbox
from ezdxf.addons.drawing import Frontend, RenderContext, svg as dxf_svg, layout as dxf_layout, config as dxf_config
import os
import math
import base64
import tempfile
from collections import Counter
import pandas as pd
from streamlit_stl import stl_from_file

# --- Dichten in g/cm³ und Richtpreise (CHF/kg) ---
MATERIALIEN = {
    "Stahl (1.0037 / S235)": {"dichte": 7.85, "preis_markt": 2.40, "icon": "🔩", "kurz": "S235"},
    "Aluminium (AlMg3 / AlCuMg)": {"dichte": 2.70, "preis_markt": 4.50, "icon": "🪶", "kurz": "Alu"},
    "CNS / Edelstahl (1.4301)": {"dichte": 7.90, "preis_markt": 7.80, "icon": "✨", "kurz": "CNS 1.4301"}
}

DIN_STAERKEN = [
    0.5, 0.7, 0.8, 1.0, 1.2, 1.5, 2.0, 2.5, 3.0,
    4.0, 5.0, 6.0, 8.0, 10.0, 12.0, 15.0, 20.0,
    25.0, 30.0, 40.0, 50.0
]

DXF_STAERKE_PLATZHALTER = "— Stärke wählen —"


def format_din_staerke(val) -> str:
    """Formatiert eine DIN-Blechstärke als reinen String ohne Sonderzeichen/Bulletpoints."""
    if val is None or val == "" or str(val) == DXF_STAERKE_PLATZHALTER:
        return DXF_STAERKE_PLATZHALTER
    try:
        v = float(val)
        if v <= 0:
            return DXF_STAERKE_PLATZHALTER
        if v.is_integer():
            return f"{int(v)} mm"
        return f"{v:.1f} mm"
    except (ValueError, TypeError):
        return DXF_STAERKE_PLATZHALTER


def parse_din_staerke_auswahl(val) -> float | None:
    """
    Liest den numerischen DIN-Stärkewert aus einer Selectbox-Option (z. B. '5 mm' -> 5.0).
    Gibt None zurück, solange noch keine DIN-Stärke ausgewählt wurde.
    """
    if val is None:
        return None
    if isinstance(val, (int, float)):
        if math.isnan(val) or float(val) <= 0:
            return None
        return float(val)
    s = str(val).strip()
    if not s or s == DXF_STAERKE_PLATZHALTER or "wählen" in s:
        return None
    s_clean = s.replace("mm", "").strip()
    try:
        v = float(s_clean)
        return v if v > 0 else None
    except ValueError:
        return None


DIN_STAERKEN_OPTIONEN = [DXF_STAERKE_PLATZHALTER] + [format_din_staerke(s) for s in DIN_STAERKEN]


def formatiere_bohrungs_statistik(durchmesser_liste: list[float]) -> str:
    """
    Erstellt aus einer Liste erkannter Bohrungs-Durchmesser eine nach Durchmesser
    sortierte Zusammenfassung, z. B.: '4× ⌀12 mm, 1× ⌀50 mm (Total: 5 Stk.)'
    """
    if not durchmesser_liste:
        return "—"
    gerundet = [round(float(d), 1) for d in durchmesser_liste if d > 0]
    if not gerundet:
        return "—"
    zaehler = Counter(gerundet)
    teile_str = []
    for d in sorted(zaehler.keys()):
        anz = zaehler[d]
        d_str = f"{int(d)}" if float(d).is_integer() else f"{d:.1f}"
        teile_str.append(f"{anz}× ⌀{d_str} mm")
    total = sum(zaehler.values())
    return f"{', '.join(teile_str)} (Total: {total} Stk.)"


def ermittle_step_bohrungen(teil) -> str:
    """
    Erkennt zylindrische Vollbohrungen in einem 3D-STEP-Bauteil und gibt die
    formatierte Bohrungs-Statistik zurück.
    """
    try:
        durchmesser = []
        gesehene_achsen = []
        for f in teil.Faces():
            adaptor = BRepAdaptor_Surface(f.wrapped)
            if adaptor.GetType() == GeomAbs_Cylinder:
                u_span = abs(adaptor.LastUParameter() - adaptor.FirstUParameter())
                # Vollkreis-Bohrung (360°): U-Spanne >= 350° (ca. 6.10 rad)
                if u_span >= 6.10:
                    cyl = adaptor.Cylinder()
                    d = round(2.0 * cyl.Radius(), 1)
                    loc = cyl.Axis().Location()
                    pos_key = (round(loc.X(), 1), round(loc.Y(), 1), round(loc.Z(), 1), d)
                    if pos_key not in gesehene_achsen:
                        gesehene_achsen.append(pos_key)
                        durchmesser.append(d)
        return formatiere_bohrungs_statistik(durchmesser)
    except Exception:
        return "—"


def zaehle_biegungen(solid) -> int:
    """
    Erkennt automatisch die Anzahl der Abkantungen / Biegungen in einem 3D-STEP-Volumenkörper:
    - Durchläuft alle Faces (`solid.Faces()`) und filtert Zylinderflächen (`f.geomType() == "CYLINDER"`).
    - Schließt 360°-Vollzylinder (Bohrungen/Löcher) aus (prüft auf Teilwinkel < 360°).
    - Da jede Biegung eine Innen- und eine Außenfläche besitzt, ergibt sich:
      `anzahl_biegungen = len(biegeflaechen) // 2`
    """
    try:
        teilzylinder = []
        for f in solid.Faces():
            if f.geomType() == "CYLINDER":
                adaptor = BRepAdaptor_Surface(f.wrapped)
                u_span_deg = math.degrees(abs(adaptor.LastUParameter() - adaptor.FirstUParameter()))
                # Schließe 360°-Vollbohrungen aus; berücksichtige nur Teilzylinderflächen (< 350°)
                if 5.0 <= u_span_deg < 350.0:
                    cyl = adaptor.Cylinder()
                    r = round(cyl.Radius(), 2)
                    ax = cyl.Axis().Direction()
                    loc = cyl.Axis().Location()
                    teilzylinder.append({
                        "face": f,
                        "r": r,
                        "dir": (ax.X(), ax.Y(), ax.Z()),
                        "loc": (loc.X(), loc.Y(), loc.Z()),
                    })

        # Filtere echte Biegeflächen (besitzen eine koaxiale Gegenfläche mit anderem Radius: Innen- & Außenradius)
        # und dedupliziere entlang derselben Biegeachse geteilte Teilflächen
        biegeflaechen = []
        gesehene_biegeflaechen = []
        for i, c1 in enumerate(teilzylinder):
            hat_gegenflaeche = False
            for j, c2 in enumerate(teilzylinder):
                if i == j:
                    continue
                dot = (
                    c1["dir"][0] * c2["dir"][0]
                    + c1["dir"][1] * c2["dir"][1]
                    + c1["dir"][2] * c2["dir"][2]
                )
                if abs(dot) > 0.995:
                    dx = c2["loc"][0] - c1["loc"][0]
                    dy = c2["loc"][1] - c1["loc"][1]
                    dz = c2["loc"][2] - c1["loc"][2]
                    proj = dx * c1["dir"][0] + dy * c1["dir"][1] + dz * c1["dir"][2]
                    px = dx - proj * c1["dir"][0]
                    py = dy - proj * c1["dir"][1]
                    pz = dz - proj * c1["dir"][2]
                    achsen_abstand = math.sqrt(px * px + py * py + pz * pz)
                    radien_diff = abs(c1["r"] - c2["r"])
                    if achsen_abstand < 0.5 and 0.3 <= radien_diff <= 55.0:
                        hat_gegenflaeche = True
                        break

            if hat_gegenflaeche:
                # Prüfe ob exakt diese Zylinderfläche (gleiche Biegeachse + gleicher Radius) schon gezählt wurde
                schon_vorhanden = False
                for g in gesehene_biegeflaechen:
                    dot_g = (
                        c1["dir"][0] * g["dir"][0]
                        + c1["dir"][1] * g["dir"][1]
                        + c1["dir"][2] * g["dir"][2]
                    )
                    if abs(dot_g) > 0.995 and abs(c1["r"] - g["r"]) < 0.15:
                        dx = g["loc"][0] - c1["loc"][0]
                        dy = g["loc"][1] - c1["loc"][1]
                        dz = g["loc"][2] - c1["loc"][2]
                        proj = dx * c1["dir"][0] + dy * c1["dir"][1] + dz * c1["dir"][2]
                        px = dx - proj * c1["dir"][0]
                        py = dy - proj * c1["dir"][1]
                        pz = dz - proj * c1["dir"][2]
                        if math.sqrt(px * px + py * py + pz * pz) < 0.5:
                            schon_vorhanden = True
                            break
                if not schon_vorhanden:
                    gesehene_biegeflaechen.append(c1)
                    biegeflaechen.append(c1["face"])

        anzahl_biegungen = len(biegeflaechen) // 2
        return anzahl_biegungen
    except Exception:
        return 0


def map_auf_din_staerke(rohwert_mm: float, ist_volumen_schaetzung: bool = False) -> float:
    """
    Ordnet einen gemessenen oder berechneten Stärkewert todsicher einer
    genormten DIN-Blechstärke zu.
    """
    if rohwert_mm <= DIN_STAERKEN[0]:
        return DIN_STAERKEN[0]
    if rohwert_mm >= DIN_STAERKEN[-1]:
        return DIN_STAERKEN[-1]

    schwellen_faktor = 0.22 if ist_volumen_schaetzung else 0.38

    for idx in range(len(DIN_STAERKEN) - 1):
        untere = DIN_STAERKEN[idx]
        obere = DIN_STAERKEN[idx + 1]
        schwelle = untere + (obere - untere) * schwellen_faktor
        if rohwert_mm < schwelle:
            return untere

    return DIN_STAERKEN[-1]


def ermittle_exakte_blechstaerke(teil) -> float:
    """
    Mehrstufige, todsichere Blechstärken-Erkennung für 3D-STEP-Volumenkörper:
    1. Direkte geometrische B-Rep-Analyse gegenüberliegender paralleler Ebenen (exakter Wandabstand).
    2. Physikalische Volumen/Oberflächen-Bilanz mit asymmetrischer Intervall-Schwelle.
    3. Fallback über BoundingBox-Minimalmaß.
    """
    try:
        ebenen = []
        for f in teil.Faces():
            adaptor = BRepAdaptor_Surface(f.wrapped)
            if adaptor.GetType() == GeomAbs_Plane:
                flaeche = f.Area()
                if flaeche > 1e-2:
                    pln = adaptor.Plane()
                    ax = pln.Axis().Direction()
                    loc = pln.Location()
                    ebenen.append((
                        flaeche,
                        (ax.X(), ax.Y(), ax.Z()),
                        (loc.X(), loc.Y(), loc.Z()),
                    ))

        if len(ebenen) >= 2:
            ebenen.sort(key=lambda x: x[0], reverse=True)
            max_flaeche = ebenen[0][0]
            relevante = [e for e in ebenen if e[0] >= max_flaeche * 0.05][:25]

            kandidaten = {}
            for i in range(len(relevante)):
                a1, n1, p1 = relevante[i]
                for j in range(i + 1, len(relevante)):
                    a2, n2, p2 = relevante[j]
                    dot = n1[0] * n2[0] + n1[1] * n2[1] + n1[2] * n2[2]
                    if abs(dot) > 0.998:
                        dx = p2[0] - p1[0]
                        dy = p2[1] - p1[1]
                        dz = p2[2] - p1[2]
                        abstand = abs(dx * n1[0] + dy * n1[1] + dz * n1[2])

                        if 0.35 <= abstand <= 55.0:
                            naechste_din = min(DIN_STAERKEN, key=lambda d: abs(d - abstand))
                            rel_abw = abs(abstand - naechste_din) / naechste_din
                            if rel_abw <= 0.06:
                                paar_gewicht = min(a1, a2)
                                kandidaten[naechste_din] = kandidaten.get(naechste_din, 0.0) + paar_gewicht

            if kandidaten:
                beste_din = max(kandidaten.items(), key=lambda item: item[1])[0]
                return beste_din
    except Exception:
        pass

    try:
        volumen_mm3 = teil.Volume()
        oberflaeche_mm2 = teil.Area()
        if oberflaeche_mm2 > 0:
            berechnete_staerke = (2.0 * volumen_mm3) / oberflaeche_mm2
            korrigierte_staerke = berechnete_staerke * 1.09
            return map_auf_din_staerke(korrigierte_staerke, ist_volumen_schaetzung=True)
    except Exception:
        pass

    box = teil.BoundingBox()
    dims = sorted([box.xlen, box.ylen, box.zlen])
    return map_auf_din_staerke(dims[0], ist_volumen_schaetzung=False)


def analysiere_dxf_datei(dxf_pfad: str) -> dict | None:
    """
    Multi-Part-DXF-Analyse:
    1. Erkennt alle separaten Außenkonturen über räumliches Bounding-Box-Clustering.
    2. Ordnet alle CIRCLE-Elemente innerhalb jeder Außenkontur als Bohrungen dem jeweiligen Teil zu.
    3. Setzt KEINE Blind-Dicke (NormStaerke = None) und Biegungen = 0.
    """
    doc = ezdxf.readfile(dxf_pfad)
    msp = doc.modelspace()
    gesamt_ext = dxf_bbox.extents(msp)
    if not gesamt_ext.has_data:
        return None

    kreise = []
    kontur_boxen = []

    for entity in msp:
        etype = entity.dxftype()
        if etype in ("TEXT", "MTEXT", "DIMENSION", "LEADER", "ATTDEF", "ATTRIB", "VIEWPORT", "POINT"):
            continue
        try:
            e_box = dxf_bbox.extents([entity])
            if not e_box.has_data:
                continue
        except Exception:
            continue

        xmin, ymin = float(e_box.extmin.x), float(e_box.extmin.y)
        xmax, ymax = float(e_box.extmax.x), float(e_box.extmax.y)

        if etype == "CIRCLE":
            r = float(entity.dxf.radius)
            cx = float(entity.dxf.center.x)
            cy = float(entity.dxf.center.y)
            kreise.append({
                "cx": cx,
                "cy": cy,
                "r": r,
                "d": round(2.0 * r, 1),
                "xmin": xmin,
                "ymin": ymin,
                "xmax": xmax,
                "ymax": ymax,
                "area": (xmax - xmin) * (ymax - ymin),
            })
        else:
            kontur_boxen.append([xmin, ymin, xmax, ymax])

    if not kontur_boxen and kreise:
        kreise_sortiert = sorted(kreise, key=lambda k: k["area"], reverse=True)
        verbleibende_kreise = []
        for k in kreise_sortiert:
            ist_innen = False
            for b in kontur_boxen:
                if b[0] - 0.5 <= k["cx"] <= b[2] + 0.5 and b[1] - 0.5 <= k["cy"] <= b[3] + 0.5:
                    ist_innen = True
                    break
            if not ist_innen:
                kontur_boxen.append([k["xmin"], k["ymin"], k["xmax"], k["ymax"]])
            else:
                verbleibende_kreise.append(k)
        kreise = verbleibende_kreise

    tol = 1.5
    geaendert = True
    while geaendert:
        geaendert = False
        neue_boxen = []
        benutzt = [False] * len(kontur_boxen)
        for i in range(len(kontur_boxen)):
            if benutzt[i]:
                continue
            bx1, by1, bx2, by2 = kontur_boxen[i]
            benutzt[i] = True
            for j in range(i + 1, len(kontur_boxen)):
                if benutzt[j]:
                    continue
                ox1, oy1, ox2, oy2 = kontur_boxen[j]
                if not (ox2 < bx1 - tol or ox1 > bx2 + tol or oy2 < by1 - tol or oy1 > by2 + tol):
                    bx1 = min(bx1, ox1)
                    by1 = min(by1, oy1)
                    bx2 = max(bx2, ox2)
                    by2 = max(by2, oy2)
                    benutzt[j] = True
                    geaendert = True
            neue_boxen.append([bx1, by1, bx2, by2])
        kontur_boxen = neue_boxen

    gueltige_boxen = [
        b for b in kontur_boxen
        if (b[2] - b[0]) >= 2.0 and (b[3] - b[1]) >= 2.0
    ]
    gueltige_boxen.sort(key=lambda b: (round(b[0], 1), round(b[1], 1)))

    bauteile = []
    for b in gueltige_boxen:
        bx1, by1, bx2, by2 = b
        w = bx2 - bx1
        h = by2 - by1
        dims_2d = sorted([w, h], reverse=True)
        laenge = round(dims_2d[0], 2)
        breite = round(dims_2d[1], 2)

        teil_bohrungen = []
        for k in kreise:
            if (bx1 - tol) <= k["cx"] <= (bx2 + tol) and (by1 - tol) <= k["cy"] <= (by2 + tol):
                if abs(k["d"] - laenge) < 0.2 and abs(k["d"] - breite) < 0.2:
                    continue
                teil_bohrungen.append(k["d"])

        bauteile.append({
            "Laenge": laenge,
            "Breite": breite,
            "Dicke": None,
            "NormStaerke": None,
            "Biegungen": 0,
            "Volumen_dm3": 0.0,
            "Bohrungen": formatiere_bohrungs_statistik(teil_bohrungen),
        })

    backend = dxf_svg.SVGBackend()
    cfg = dxf_config.Configuration(
        background_policy=dxf_config.BackgroundPolicy.WHITE,
        color_policy=dxf_config.ColorPolicy.BLACK,
    )
    frontend = Frontend(RenderContext(doc), backend, config=cfg)
    frontend.draw_layout(msp, finalize=True)

    ges_w = max(float(gesamt_ext.size.x), 100.0)
    ges_h = max(float(gesamt_ext.size.y), 80.0)
    svg_str = backend.get_string(
        dxf_layout.Page(ges_w, ges_h, dxf_layout.Units.mm, margins=dxf_layout.Margins.all(8))
    )
    b64_dxf_svg = base64.b64encode(svg_str.encode("utf-8")).decode("utf-8")

    return {
        "bauteile": bauteile,
        "b64_svg": b64_dxf_svg,
    }


st.set_page_config(page_title="Rohteil- & Stücklisten-Rechner", page_icon="⚙️", layout="wide")

# --- UI- & DRUCK-CSS (Blechlager-Hintergrund + Blur-Overlay, Dark-Mode-sicher & A4-Querformat 58%/40%) ---
st.markdown('''
<style>
:root {
    --card-bg: rgba(22, 27, 34, 0.94);
    --card-border: #3b4452;
    --table-header-bg: #0f172a;
    --table-header-text: #f8fafc;
    --table-row-odd: #161b22;
    --table-row-even: #1f2631;
    --table-row-hover: #293241;
    --text-main: #f8fafc;
    --text-muted: #cbd5e1;
    --accent-blue: #3b82f6;
    --badge-bg: #1e3a8a;
    --badge-text: #eff6ff;
    --badge-border: #60a5fa;
    --badge-warn-bg: #78350f;
    --badge-warn-text: #fef3c7;
    --badge-warn-border: #f59e0b;
    --price-highlight: #34d399;
}

/* Atmosphärisches Blechlager-/Industrie-Hintergrundbild mit abgedunkeltem Blur-Overlay */
.stApp {
    background-image:
        linear-gradient(rgba(14, 17, 23, 0.88), rgba(14, 17, 23, 0.88)),
        url("https://images.unsplash.com/photo-1581091226825-a6a2a5aee158?q=80&w=1920&auto=format&fit=crop") !important;
    background-size: cover !important;
    background-position: center !important;
    background-attachment: fixed !important;
    color: var(--text-main) !important;
}

.stApp > [data-testid="stAppViewContainer"] {
    backdrop-filter: blur(4px);
    -webkit-backdrop-filter: blur(4px);
    background: rgba(14, 17, 23, 0.45);
}

/* Garantierte Lesbarkeit für alle Texte, Labels & Überschriften */
.stApp label,
.stApp h1,
.stApp h2,
.stApp h3,
.stApp p,
[data-testid="stWidgetLabel"] p,
[data-testid="stFileUploader"] label,
[data-testid="stCheckbox"] label span {
    color: #f8fafc !important;
}

iframe[height="600"] {
    background-color: #161b22 !important;
    border: 1px solid var(--card-border);
    border-radius: 8px;
}

/* Werkstatt-Header */
.workshop-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 12px 18px;
    background: var(--card-bg);
    backdrop-filter: blur(6px);
    border: 1px solid var(--card-border);
    border-left: 5px solid var(--accent-blue);
    border-radius: 8px;
    margin-bottom: 14px;
    box-shadow: 0 4px 12px rgba(0, 0, 0, 0.25);
}
.workshop-title {
    font-size: 1.38rem;
    font-weight: 700;
    color: var(--text-main) !important;
    margin: 0;
}
.workshop-subtitle {
    font-size: 0.84rem;
    color: var(--text-muted) !important;
    margin: 2px 0 0 0;
}

/* KPI-Metrik-Karten (nur Bildschirm) */
.kpi-grid {
    display: grid;
    grid-template-columns: repeat(4, 1fr);
    gap: 10px;
    margin-top: 8px;
    margin-bottom: 12px;
}
.kpi-card {
    background: var(--card-bg);
    backdrop-filter: blur(6px);
    border: 1px solid var(--card-border);
    border-radius: 8px;
    padding: 9px 12px;
}
.kpi-label {
    font-size: 0.73rem;
    text-transform: uppercase;
    letter-spacing: 0.04em;
    color: var(--text-muted) !important;
    font-weight: 600;
}
.kpi-value {
    font-size: 1.12rem;
    font-weight: 700;
    color: var(--text-main) !important;
    margin-top: 2px;
}
.kpi-sub {
    font-size: 0.76rem;
    color: var(--text-muted) !important;
}

/* Stücklisten-Tabelle (Hochkontrast auf jedem System) */
table.excel-table {
    width: 100%;
    border-collapse: collapse;
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
    margin-top: 8px;
    margin-bottom: 10px;
    background-color: var(--table-row-odd) !important;
    color: var(--text-main) !important;
    border: 1px solid var(--card-border);
}
table.excel-table th {
    background-color: var(--table-header-bg) !important;
    color: var(--table-header-text) !important;
    font-weight: 700;
    font-size: 10.2px;
    padding: 6px 6px;
    text-align: left;
    border: 1px solid var(--card-border);
    white-space: nowrap;
}
table.excel-table td {
    border: 1px solid var(--card-border);
    padding: 5px 6px;
    text-align: left;
    font-size: 10.2px;
    background-color: var(--table-row-odd) !important;
    color: var(--text-main) !important;
}
table.excel-table td b {
    color: var(--text-main) !important;
}
table.excel-table tr:nth-child(even) td {
    background-color: var(--table-row-even) !important;
    color: var(--text-main) !important;
}
table.excel-table tr:hover td {
    background-color: var(--table-row-hover) !important;
}

/* DIN-Stärke Badge (reiner String ohne Minus-Striche) */
.din-badge {
    display: inline-block;
    padding: 2px 6px;
    border-radius: 4px;
    font-weight: 700;
    font-size: 10px;
    background-color: var(--badge-bg) !important;
    color: var(--badge-text) !important;
    border: 1px solid var(--badge-border);
    white-space: nowrap;
}
.din-badge-pending {
    display: inline-block;
    padding: 2px 6px;
    border-radius: 4px;
    font-weight: 700;
    font-size: 10px;
    background-color: var(--badge-warn-bg) !important;
    color: var(--badge-warn-text) !important;
    border: 1px solid var(--badge-warn-border);
    white-space: nowrap;
}

.price-strong {
    font-weight: 700;
    color: var(--price-highlight) !important;
}

/* Gesamtauswertungs-Box */
.summary-box {
    background: var(--card-bg) !important;
    backdrop-filter: blur(6px);
    border: 1px solid var(--card-border);
    border-left: 4px solid var(--accent-blue);
    border-radius: 6px;
    padding: 10px 14px;
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
    font-size: 11.5px;
    color: var(--text-main) !important;
    margin-top: 8px;
    margin-bottom: 10px;
    line-height: 1.5;
}
.summary-box b, .summary-box span {
    color: var(--text-main) !important;
}
.summary-box .price-strong {
    color: var(--price-highlight) !important;
}
.summary-box hr {
    margin: 5px 0;
    border: 0;
    border-top: 1px solid var(--card-border);
}

/* Technische Zeichnung Box (Bildschirm – kompakt & ausgewogen) */
.drawing-frame {
    width: 100%;
    max-height: 420px;
    object-fit: contain;
    border: 1px solid var(--card-border);
    border-radius: 8px;
    padding: 8px;
    background-color: #ffffff !important;
    display: block;
    box-sizing: border-box;
    margin-bottom: 8px;
}

/* Dedizierter Druck-Container: Auf dem Bildschirm ausgeblendet */
.print-only-sheet {
    display: none;
}

/* =========================================================================
   DRUCK-MODUS (A4 QUERFORMAT): 68% STÜCKLISTE / 30% ZEICHNUNG (MAX 4.0 CM HÖHE)
   ========================================================================= */
@media print {
    @page {
        size: A4 landscape;
        margin: 6mm;
    }

    html, body, .stApp, main, [data-testid="stAppViewContainer"], .block-container {
        background: #ffffff !important;
        background-color: #ffffff !important;
        background-image: none !important;
        backdrop-filter: none !important;
        -webkit-backdrop-filter: none !important;
        color: #000000 !important;
        margin: 0 !important;
        padding: 0 !important;
        max-width: 100% !important;
        width: 100% !important;
        overflow: visible !important;
    }

    /* Alle interaktiven Streamlit-Widgets & Screen-Container beim Drucken ausblenden */
    header, footer,
    [data-testid="stToolbar"],
    [data-testid="stHeader"],
    [data-testid="stSidebar"],
    [data-testid="stFileUploader"],
    [data-testid="stDataFrame"],
    [data-testid="stNumberInput"],
    [data-testid="stSelectbox"],
    [data-testid="stCheckbox"],
    [data-testid="stExpander"],
    div[data-testid="stAlert"],
    div[data-testid="stHorizontalBlock"],
    button, iframe,
    .workshop-header, .kpi-grid, .screen-only-view {
        display: none !important;
    }

    /* Dediziertes A4-Querformat-Druckblatt: 68% Links (Stückliste + Auswertung) / 30% Rechts (Zeichnungen) */
    .print-only-sheet {
        display: flex !important;
        flex-direction: row !important;
        flex-wrap: nowrap !important;
        justify-content: space-between !important;
        align-items: flex-start !important;
        width: 100% !important;
        max-width: 100% !important;
        box-sizing: border-box !important;
        page-break-inside: avoid !important;
        break-inside: avoid !important;
    }

    .print-col-left {
        width: 68% !important;
        max-width: 68% !important;
        flex: 0 0 68% !important;
        box-sizing: border-box !important;
        overflow: visible !important;
    }

    .print-col-right {
        width: 30% !important;
        max-width: 30% !important;
        flex: 0 0 30% !important;
        box-sizing: border-box !important;
        overflow: hidden !important;
        display: flex !important;
        flex-direction: column !important;
        flex-wrap: nowrap !important;
        align-items: center !important;
        gap: 8px !important;
    }

    .print-title {
        font-family: sans-serif !important;
        font-size: 9pt !important;
        font-weight: bold !important;
        color: #000000 !important;
        margin: 0 0 3px 0 !important;
        padding: 0 !important;
        width: 100% !important;
        text-align: left !important;
    }

    /* Jedes einzelne Bild (3D-STEP oder 2D-DXF) kompakt untereinander in der rechten Spalte */
    .print-col-right img, .print-drawing-img {
        width: 100% !important;
        max-width: 260px !important;
        max-height: 3.2cm !important;
        height: auto !important;
        object-fit: contain !important;
        border: 1px solid #000000 !important;
        background-color: #ffffff !important;
        padding: 2px !important;
        margin: 0 auto 6px auto !important;
        box-sizing: border-box !important;
        display: block !important;
        page-break-inside: avoid !important;
        break-inside: avoid !important;
    }

    /* Tabelle im Druck: Gestochen scharf Schwarz auf Weiß, alle 10 Spalten garantiert sichtbar */
    table.excel-table {
        width: 100% !important;
        table-layout: auto !important;
        font-size: 7pt !important;
        border: 1px solid #000000 !important;
        background-color: #ffffff !important;
        margin-top: 2px !important;
        margin-bottom: 5px !important;
    }
    table.excel-table th {
        background-color: #e2e8f0 !important;
        color: #000000 !important;
        border: 1px solid #000000 !important;
        padding: 2px 3px !important;
        font-size: 7pt !important;
        white-space: nowrap !important;
    }
    table.excel-table td, table.excel-table td b {
        border: 1px solid #000000 !important;
        color: #000000 !important;
        background-color: #ffffff !important;
        padding: 2px 3px !important;
        font-size: 7pt !important;
        word-break: break-word !important;
    }
    /* Preis- und Gewichts-Spalten niemals abschneiden */
    table.excel-table td:nth-child(1),
    table.excel-table td:nth-child(3),
    table.excel-table td:nth-child(5),
    table.excel-table td:nth-child(7),
    table.excel-table td:nth-child(8),
    table.excel-table td:nth-child(9),
    table.excel-table td:nth-child(10) {
        white-space: nowrap !important;
    }
    .din-badge, .din-badge-pending, .price-strong {
        border: none !important;
        padding: 0 !important;
        color: #000000 !important;
        background: transparent !important;
        font-size: 7pt !important;
    }
    .summary-box, .summary-box b, .summary-box span, .summary-box .price-strong {
        border-color: #000000 !important;
        background-color: #ffffff !important;
        color: #000000 !important;
        font-size: 7.8pt !important;
    }
    .summary-box {
        border: 1px solid #000000 !important;
        padding: 4px 7px !important;
        margin-top: 4px !important;
        width: 100% !important;
        box-sizing: border-box !important;
    }
}
</style>
''', unsafe_allow_html=True)

# --- WERKSTATT-HEADER ---
st.markdown('''
<div class="workshop-header">
    <div>
        <div class="workshop-title">⚙️ Rohteil- & Stücklisten-Rechner</div>
        <div class="workshop-subtitle">3D-STEP & 2D-DXF Analyse · Automatische Biegekantenerkennung · Bohrungs-Statistik & Kalkulation (CHF)</div>
    </div>
</div>
''', unsafe_allow_html=True)

col_m1, col_m2, col_m3, col_m4 = st.columns([2.0, 1.0, 1.0, 1.0])
with col_m1:
    selected_material = st.selectbox("🪨 Werkstoff / Materialgüte", list(MATERIALIEN.keys()))
with col_m2:
    markt_preis = MATERIALIEN[selected_material]["preis_markt"]
    preis_pro_kg = st.number_input("💰 Materialpreis (CHF/kg)", min_value=0.0, value=markt_preis, step=0.10, format="%.2f")
with col_m3:
    verschnitt_prozent = st.number_input("✂️ Verschnitt-Zuschlag (%)", min_value=0.0, max_value=100.0, value=30.0, step=1.0, format="%.1f")
with col_m4:
    kosten_pro_biegung = st.number_input("📐 Kosten pro Biegung (CHF)", min_value=0.0, value=1.50, step=0.25, format="%.2f")

dichte = MATERIALIEN[selected_material]["dichte"]
mat_icon = MATERIALIEN[selected_material]["icon"]
mat_kurz = MATERIALIEN[selected_material]["kurz"]
faktor_verschnitt = verschnitt_prozent / 100.0

uploaded_files = st.file_uploader(
    "📂 STEP- oder DXF-Datei(en) auswählen oder per Drag & Drop ablegen (.step, .stp, .dxf)",
    type=["step", "stp", "dxf"],
    accept_multiple_files=True
)

if uploaded_files:
    current_file_sig = [(f.name, f.size) for f in uploaded_files]

    if st.session_state.get("file_sig") != current_file_sig:
        with tempfile.TemporaryDirectory() as tmpdir:
            svg_name = os.path.join(tmpdir, "temp_vorschau.svg")
            stl_name = os.path.join(tmpdir, "temp_3d.stl")

            alle_positionen = []
            alle_teile_verschoben = []
            dxf_svg_liste = []
            aktueller_x_offset = 0.0

            try:
                with st.spinner("Analysiere CAD-Dateien (STEP / DXF, Biegekanten & Bohrungen)..."):
                    for i, uploaded_file in enumerate(uploaded_files):
                        file_basename, file_ext = os.path.splitext(uploaded_file.name)
                        ext_lower = file_ext.lower()

                        # --- PFAD A: 2D-DXF-ZUSCHNITT (Multi-Teile-Erkennung + Bohrungs-Statistik) ---
                        if ext_lower == ".dxf":
                            dxf_dateiname = os.path.join(tmpdir, f"temp_zuschnitt_{i}.dxf")
                            with open(dxf_dateiname, "wb") as f:
                                f.write(uploaded_file.getbuffer())

                            dxf_ergebnis = analysiere_dxf_datei(dxf_dateiname)
                            if dxf_ergebnis is not None and len(dxf_ergebnis["bauteile"]) > 0:
                                gefundene_teile = dxf_ergebnis["bauteile"]
                                anzahl_dxf_teile = len(gefundene_teile)
                                for idx_d, dxf_teil in enumerate(gefundene_teile):
                                    if anzahl_dxf_teile == 1:
                                        bauteil_name = file_basename
                                    else:
                                        bauteil_name = f"{file_basename}_{idx_d + 1}"

                                    alle_positionen.append({
                                        "Pos": len(alle_positionen) + 1,
                                        "BauteilName": bauteil_name,
                                        "Dateityp": "DXF",
                                        "BasisAnzahl": 1,
                                        "Laenge": dxf_teil["Laenge"],
                                        "Breite": dxf_teil["Breite"],
                                        "Dicke": None,
                                        "NormStaerke": None,
                                        "Biegungen": 0,
                                        "Bohrungen": dxf_teil["Bohrungen"],
                                        "Volumen_dm3": 0.0
                                    })
                                dxf_svg_liste.append((file_basename, dxf_ergebnis["b64_svg"]))

                        # --- PFAD B: 3D-STEP-BAUTEIL ---
                        else:
                            dateiname = os.path.join(tmpdir, f"temp_bauteil_{i}.step")
                            with open(dateiname, "wb") as f:
                                f.write(uploaded_file.getbuffer())

                            baugruppe = cq.importers.importStep(dateiname)
                            teile = baugruppe.solids().vals()

                            if len(teile) > 0:
                                file_compound = cq.Compound.makeCompound(teile)
                                bbox_file = file_compound.BoundingBox()

                                dx = -bbox_file.xmin + aktueller_x_offset
                                dy = -bbox_file.ymin
                                dz = -bbox_file.zmin

                                verschobenes_compound = file_compound.translate((dx, dy, dz))
                                alle_teile_verschoben.append(verschobenes_compound)

                                abstand = max(bbox_file.xlen * 0.2, 50.0)
                                aktueller_x_offset += bbox_file.xlen + abstand

                                datei_rohteile = []
                                for teil in teile:
                                    box = teil.BoundingBox()
                                    dim = sorted([box.xlen, box.ylen, box.zlen], reverse=True)
                                    L = round(dim[0], 2)
                                    B = round(dim[1], 2)

                                    norm_staerke = ermittle_exakte_blechstaerke(teil)
                                    D = norm_staerke
                                    volumen_dm3 = (L * B * D) / 1_000_000.0
                                    bohrungen_str = ermittle_step_bohrungen(teil)
                                    anz_biegungen = zaehle_biegungen(teil)

                                    datei_rohteile.append({
                                        "Laenge": L,
                                        "Breite": B,
                                        "Dicke": D,
                                        "NormStaerke": norm_staerke,
                                        "Biegungen": anz_biegungen,
                                        "Bohrungen": bohrungen_str,
                                        "Volumen_dm3": volumen_dm3
                                    })

                                df_file = pd.DataFrame(datei_rohteile)
                                df_file_grouped = df_file.groupby(
                                    ["Laenge", "Breite", "Dicke", "NormStaerke", "Biegungen", "Bohrungen"]
                                ).agg(
                                    BasisAnzahl=("Laenge", "count"),
                                    Volumen_dm3=("Volumen_dm3", "first")
                                ).reset_index()

                                df_file_grouped = df_file_grouped.sort_values(
                                    by=["BasisAnzahl", "Laenge"], ascending=[False, False]
                                ).reset_index(drop=True)

                                anzahl_unterschiedliche_teile = len(df_file_grouped)
                                for idx_f, row_f in df_file_grouped.iterrows():
                                    if anzahl_unterschiedliche_teile == 1:
                                        bauteil_name = file_basename
                                    else:
                                        bauteil_name = f"{file_basename}_{idx_f + 1}"

                                    alle_positionen.append({
                                        "Pos": len(alle_positionen) + 1,
                                        "BauteilName": bauteil_name,
                                        "Dateityp": "STEP",
                                        "BasisAnzahl": int(row_f["BasisAnzahl"]),
                                        "Laenge": row_f["Laenge"],
                                        "Breite": row_f["Breite"],
                                        "Dicke": row_f["Dicke"],
                                        "NormStaerke": row_f["NormStaerke"],
                                        "Biegungen": int(row_f["Biegungen"]),
                                        "Bohrungen": row_f["Bohrungen"],
                                        "Volumen_dm3": row_f["Volumen_dm3"]
                                    })

                    # 3D-STEP-Gesamtzeichnung & STL erzeugen (falls STEP-Teile vorhanden sind)
                    b64_svg = ""
                    stl_bytes = None
                    if len(alle_teile_verschoben) > 0:
                        gesamt_compound = cq.Compound.makeCompound(alle_teile_verschoben)
                        opt = {
                            "width": 1200,
                            "height": 1000,
                            "showAxes": False,
                            "projectionDir": (1.2, -1.0, 1.0)
                        }
                        try:
                            cq.exporters.export(gesamt_compound, svg_name, opt=opt)
                        except Exception:
                            cq.exporters.export(gesamt_compound, svg_name)

                        with open(svg_name, "r", encoding="utf-8") as f:
                            svg_data = f.read()
                        b64_svg = base64.b64encode(
                            svg_data.encode("utf-8") if isinstance(svg_data, str) else svg_data
                        ).decode("utf-8")

                        bbox = gesamt_compound.BoundingBox()
                        dx = -(bbox.xmin + bbox.xmax) / 2
                        dy = -(bbox.ymin + bbox.ymax) / 2
                        dz = -(bbox.zmin + bbox.zmax) / 2
                        c_centered = gesamt_compound.translate((dx, dy, dz))
                        cfg_max_dim = max(bbox.xlen, bbox.ylen, bbox.zlen)
                        if cfg_max_dim > 150:
                            scale_factor = 100.0 / cfg_max_dim
                            c_export = c_centered.scale(scale_factor)
                        else:
                            c_export = c_centered
                        cq.exporters.export(c_export, stl_name, tolerance=0.5, angularTolerance=0.5)
                        with open(stl_name, "rb") as f_stl:
                            stl_bytes = f_stl.read()

                    st.session_state["file_sig"] = current_file_sig
                    st.session_state["basis_daten"] = alle_positionen
                    st.session_state["b64_svg"] = b64_svg
                    st.session_state["dxf_svg_liste"] = dxf_svg_liste
                    st.session_state["stl_bytes"] = stl_bytes
            except Exception as e:
                st.error(f"Fehler beim Lesen der Dateien: {e}")
                st.session_state["basis_daten"] = []

    basis_daten = st.session_state.get("basis_daten", [])
    if len(basis_daten) == 0:
        st.warning("⚠️ Keine gültigen Bauteile oder 2D-Konturen gefunden.")
    else:
        df_base = pd.DataFrame(basis_daten)
        b64_svg = st.session_state.get("b64_svg", "")
        dxf_svg_liste = st.session_state.get("dxf_svg_liste", [])
        stl_bytes = st.session_state.get("stl_bytes", None)
        hat_dxf_dateien = bool((df_base["Dateityp"] == "DXF").any())

        if len(uploaded_files) == 1:
            titel_text = f"📋 Stückliste: {os.path.splitext(uploaded_files[0].name)[0]}"
        else:
            titel_text = f"📋 Gesamt-Stückliste ({len(uploaded_files)} Dateien)"

        col1, col2 = st.columns([1.22, 0.78])

        with col1:
            st.markdown(f"### {titel_text}")

            def baue_mass_anzeige(r) -> str:
                if r["NormStaerke"] is None or pd.isna(r["NormStaerke"]):
                    return f"{r['Laenge']} × {r['Breite']} mm"
                d_fmt = int(r["NormStaerke"]) if float(r["NormStaerke"]).is_integer() else r["NormStaerke"]
                return f"{r['Laenge']} × {r['Breite']} × {d_fmt}"

            edit_input_df = pd.DataFrame({
                "Pos.": df_base["Pos"],
                "Bauteil / Benennung": df_base["BauteilName"],
                "Menge (Stk.)": df_base["BasisAnzahl"],
                "Maße (mm)": df_base.apply(baue_mass_anzeige, axis=1),
                "Biegungen": df_base["Biegungen"].apply(lambda b: f"{int(b)}x"),
                "Bohrungen": df_base["Bohrungen"],
                "DIN-Stärke (mm)": df_base["NormStaerke"].apply(format_din_staerke)
            })

            gesperrte_spalten = ["Pos.", "Bauteil / Benennung", "Maße (mm)", "Biegungen", "Bohrungen"]
            if not hat_dxf_dateien:
                gesperrte_spalten.append("DIN-Stärke (mm)")

            edited_df = st.data_editor(
                edit_input_df,
                disabled=gesperrte_spalten,
                hide_index=True,
                use_container_width=True,
                column_config={
                    "Pos.": st.column_config.NumberColumn("Pos.", format="%d"),
                    "Bauteil / Benennung": st.column_config.TextColumn("🔩 Bauteil / Benennung"),
                    "Menge (Stk.)": st.column_config.NumberColumn(
                        "🔢 Menge ✏️", min_value=0, max_value=100000, step=1, format="%d"
                    ),
                    "Maße (mm)": st.column_config.TextColumn("📐 Rohmaß (mm)"),
                    "Biegungen": st.column_config.TextColumn("📐 Biegungen"),
                    "Bohrungen": st.column_config.TextColumn("🕳️ Bohrungen"),
                    "DIN-Stärke (mm)": (
                        st.column_config.SelectboxColumn(
                            "📏 DIN-Stärke ✏️",
                            options=DIN_STAERKEN_OPTIONEN,
                            required=True
                        )
                        if hat_dxf_dateien
                        else st.column_config.TextColumn("📏 DIN-Stärke")
                    )
                },
                key="main_qty_editor"
            )

            df_calc = df_base.copy()
            df_calc["Anzahl"] = edited_df["Menge (Stk.)"].astype(int)
            df_calc["Biegungen"] = df_calc["Biegungen"].fillna(0).astype(int)

            # Für DXF-Positionen wird die gewählte DIN-Stärke übernommen.
            # Solange "— Stärke wählen —" aktiv ist (None), bleiben Volumen, Gewicht und Preis exakt 0.0!
            gewaehlte_staerken = edited_df["DIN-Stärke (mm)"].apply(parse_din_staerke_auswahl)
            for idx_c in df_calc.index:
                if df_calc.loc[idx_c, "Dateityp"] == "DXF":
                    st_val = gewaehlte_staerken.loc[idx_c]
                    df_calc.loc[idx_c, "NormStaerke"] = st_val
                    df_calc.loc[idx_c, "Dicke"] = st_val
                    if st_val is not None and st_val > 0:
                        df_calc.loc[idx_c, "Volumen_dm3"] = (
                            float(df_calc.loc[idx_c, "Laenge"])
                            * float(df_calc.loc[idx_c, "Breite"])
                            * float(st_val)
                        ) / 1_000_000.0
                    else:
                        df_calc.loc[idx_c, "Volumen_dm3"] = 0.0
                else:
                    # 3D-STEP: Gewicht rein über das rechteckige Rohmaß (L x B x Dicke)
                    df_calc.loc[idx_c, "Volumen_dm3"] = (
                        float(df_calc.loc[idx_c, "Laenge"])
                        * float(df_calc.loc[idx_c, "Breite"])
                        * float(df_calc.loc[idx_c, "NormStaerke"])
                    ) / 1_000_000.0

            df_calc["EinzelGewicht"] = df_calc["Volumen_dm3"] * dichte
            df_calc["GesamtGewichtNetto"] = df_calc["EinzelGewicht"] * df_calc["Anzahl"]
            df_calc["VerschnittGewicht"] = df_calc["GesamtGewichtNetto"] * faktor_verschnitt
            df_calc["GesamtGewichtBrutto"] = df_calc["GesamtGewichtNetto"] + df_calc["VerschnittGewicht"]

            # Biegekosten pro Stück und Position
            hat_gueltige_staerke = df_calc["NormStaerke"].notna()
            df_calc["BiegekostenEinzel"] = (
                df_calc["Biegungen"] * kosten_pro_biegung
            ).where(hat_gueltige_staerke, 0.0)
            df_calc["BiegekostenGesamt"] = df_calc["BiegekostenEinzel"] * df_calc["Anzahl"]

            # Einzelpreis (Material Netto + Biegekosten pro Stück) & Gesamtpreis (Material Brutto + Biegekosten Gesamt)
            df_calc["EinzelPreis"] = (df_calc["EinzelGewicht"] * preis_pro_kg) + df_calc["BiegekostenEinzel"]
            df_calc["GesamtPreisMaterialBrutto"] = df_calc["GesamtGewichtBrutto"] * preis_pro_kg
            df_calc["GesamtPreisBrutto"] = df_calc["GesamtPreisMaterialBrutto"] + df_calc["BiegekostenGesamt"]

            offene_dxf_staerken = int(
                df_calc[df_calc["Dateityp"] == "DXF"]["NormStaerke"].isna().sum()
            )
            if offene_dxf_staerken > 0:
                st.warning(
                    f"⚠️ Bitte für {offene_dxf_staerken} DXF-Position(en) in der Spalte **📏 DIN-Stärke ✏️** "
                    f"die gewünschte Blechstärke auswählen, um Gewicht und Preis zu berechnen."
                )

            gesamt_bauteile_anzahl = int(df_calc["Anzahl"].sum())
            gesamt_biegungen = sum(
                int(row_b["Biegungen"]) * int(row_b["Anzahl"])
                for _, row_b in df_calc.iterrows()
            )
            gesamt_biege_kosten = float(gesamt_biegungen) * float(kosten_pro_biegung)
            netto_ges_gew = df_calc["GesamtGewichtNetto"].sum()
            verschnitt_ges_gew = df_calc["VerschnittGewicht"].sum()
            brutto_ges_gew = df_calc["GesamtGewichtBrutto"].sum()
            netto_ges_preis = netto_ges_gew * preis_pro_kg
            verschnitt_ges_preis = verschnitt_ges_gew * preis_pro_kg
            brutto_ges_preis = df_calc["GesamtPreisMaterialBrutto"].sum() + gesamt_biege_kosten

            kpi_html = (
                f'<div class="kpi-grid">'
                f'<div class="kpi-card"><div class="kpi-label">📦 Menge & Biegungen</div>'
                f'<div class="kpi-value">{gesamt_bauteile_anzahl} Stk.</div>'
                f'<div class="kpi-sub">{len(df_calc)} Pos. · {gesamt_biegungen}x Biegungen total</div></div>'
                f'<div class="kpi-card"><div class="kpi-label">⚖️ Netto-Gewicht</div>'
                f'<div class="kpi-value">{netto_ges_gew:.2f} kg</div>'
                f'<div class="kpi-sub">{mat_icon} {mat_kurz} ({dichte} g/cm³)</div></div>'
                f'<div class="kpi-card"><div class="kpi-label">🏋️ Brutto-Gewicht</div>'
                f'<div class="kpi-value">{brutto_ges_gew:.2f} kg</div>'
                f'<div class="kpi-sub">inkl. {verschnitt_prozent:.0f}% Verschnitt (+{verschnitt_ges_gew:.2f} kg)</div></div>'
                f'<div class="kpi-card"><div class="kpi-label">🇨🇭 Kalkulation Total</div>'
                f'<div class="kpi-value" style="color: var(--price-highlight);">{brutto_ges_preis:.2f} CHF</div>'
                f'<div class="kpi-sub">Mat. + Abkanten ({gesamt_biege_kosten:.2f} Fr.)</div></div>'
                f'</div>'
            )
            st.markdown(kpi_html, unsafe_allow_html=True)

            html_table = '<table class="excel-table">'
            html_table += (
                '<thead><tr>'
                '<th>Pos.</th>'
                '<th>🔩 Bauteil / Benennung</th>'
                '<th>🔢 Menge</th>'
                '<th>📐 Maße (L × B × D)</th>'
                '<th>📐 Biegungen</th>'
                '<th>🕳️ Bohrungen</th>'
                '<th>📏 DIN-Stärke</th>'
                '<th>⚖️ Einz.-Gew.</th>'
                '<th>🏋️ Ges.-Gew.</th>'
                '<th>💰 Einz.-Preis</th>'
                '<th>🇨🇭 Ges.-Preis</th>'
                '</tr></thead><tbody>'
            )

            for idx, row in df_calc.iterrows():
                pos = int(row["Pos"])
                bauteil_str = row["BauteilName"]
                anzahl = int(row["Anzahl"])
                biegungen_int = int(row["Biegungen"])
                biegungen_str = f"{biegungen_int}x"
                bohrungen_str = row["Bohrungen"]
                hat_staerke = row["NormStaerke"] is not None and not pd.isna(row["NormStaerke"])

                if hat_staerke:
                    d_val = float(row["NormStaerke"])
                    dicke_fmt = int(d_val) if d_val.is_integer() else d_val
                    mass_str = f"{row['Laenge']} × {row['Breite']} × {dicke_fmt} mm"
                    norm_str = format_din_staerke(d_val)
                    badge_cls = "din-badge"
                    einzel_gew_str = f"{row['EinzelGewicht']:.2f} kg"
                    gesamt_gew_str = f"{row['GesamtGewichtBrutto']:.2f} kg"
                    einzel_preis_str = f"{row['EinzelPreis']:.2f} Fr."
                    preis_brutto_str = f"{row['GesamtPreisBrutto']:.2f} Fr."
                else:
                    mass_str = f"{row['Laenge']} × {row['Breite']} × ? mm"
                    norm_str = "Stärke wählen"
                    badge_cls = "din-badge-pending"
                    einzel_gew_str = "—"
                    gesamt_gew_str = "—"
                    einzel_preis_str = "—"
                    preis_brutto_str = "—"

                html_table += (
                    f'<tr>'
                    f'<td><b>{pos}</b></td>'
                    f'<td><b>{bauteil_str}</b></td>'
                    f'<td><b>{anzahl}×</b></td>'
                    f'<td>{mass_str}</td>'
                    f'<td><b>{biegungen_str}</b></td>'
                    f'<td>{bohrungen_str}</td>'
                    f'<td><span class="{badge_cls}">{norm_str}</span></td>'
                    f'<td>{einzel_gew_str}</td>'
                    f'<td><b>{gesamt_gew_str}</b></td>'
                    f'<td>{einzel_preis_str}</td>'
                    f'<td><span class="price-strong">{preis_brutto_str}</span></td>'
                    f'</tr>'
                )

            html_table += '</tbody></table>'
            st.markdown(html_table, unsafe_allow_html=True)

            summary_html = (
                f'<div class="summary-box">'
                f'<b>📊 Gesamtauswertung ({mat_icon} {selected_material} | Total Menge: {gesamt_bauteile_anzahl} Stk.):</b><br>'
                f'• Netto-Gewicht (Rohmaß L×B×D): <b>{netto_ges_gew:.2f} kg</b> ({netto_ges_preis:.2f} Fr.)<br>'
                f'• Verschnitt ({verschnitt_prozent:.0f}%): <b>{verschnitt_ges_gew:.2f} kg</b> ({verschnitt_ges_preis:.2f} Fr.)<br>'
                f'• Abkanten / Biegungen: <b>{gesamt_biegungen}x</b> (@ {kosten_pro_biegung:.2f} Fr.) = <b>{gesamt_biege_kosten:.2f} CHF</b>'
                f'<hr>'
                f'• <b>TOTAL (Brutto inkl. Verschnitt & Abkanten):</b> <b>{gesamt_bauteile_anzahl} Stk.</b> &nbsp;|&nbsp; '
                f'<b>{brutto_ges_gew:.2f} kg</b> &nbsp;|&nbsp; <span class="price-strong">{brutto_ges_preis:.2f} CHF</span>'
                f'</div>'
            )
            st.markdown(summary_html, unsafe_allow_html=True)

            st.components.v1.html(
                '<button onclick="window.parent.print()" '
                'style="padding:10px 20px; font-size:15px; font-weight:bold; cursor:pointer; '
                'background-color:#2563eb; color:white; border:none; border-radius:6px; width: 100%; '
                'box-shadow: 0 4px 6px rgba(0,0,0,0.15);">'
                '🖨️ Stückliste & Technische Zeichnung drucken (A4 Querformat)</button>',
                height=55
            )

        with col2:
            st.markdown("### 📐 Technische Gesamt-Zeichnung")

            if b64_svg:
                html_img = (
                    f'<img class="drawing-frame" src="data:image/svg+xml;base64,{b64_svg}" />'
                )
                st.markdown(html_img, unsafe_allow_html=True)

            for dxf_name, b64_dxf in dxf_svg_liste:
                html_dxf_img = (
                    f'<img class="drawing-frame" src="data:image/svg+xml;base64,{b64_dxf}" />'
                )
                st.markdown(html_dxf_img, unsafe_allow_html=True)

            # 3D-Ansicht Checkbox wird nur eingeblendet, wenn echte 3D-STEP-Daten vorliegen
            if stl_bytes is not None:
                if st.checkbox("🔄 Interaktive 3D-Ansicht einblenden"):
                    with tempfile.NamedTemporaryFile(delete=False, suffix=".stl") as tmp_stl:
                        tmp_stl.write(stl_bytes)
                        tmp_stl_path = tmp_stl.name
                    stl_from_file(file_path=tmp_stl_path, color="#ff8c00", height=600)

        # Dedizierter A4-Querformat-Druckblock (68% Stückliste / 30% Zeichnung, Bilder strikt untereinander)
        print_imgs = []
        if b64_svg:
            print_imgs.append(f'<img class="print-drawing-img" src="data:image/svg+xml;base64,{b64_svg}" />')
        for _, b64_dxf in dxf_svg_liste:
            print_imgs.append(f'<img class="print-drawing-img" src="data:image/svg+xml;base64,{b64_dxf}" />')
        print_img_html = "".join(print_imgs)

        print_sheet_html = (
            f'<div class="print-only-sheet">'
            f'<div class="print-col-left">'
            f'<div class="print-title">{titel_text}</div>'
            f'{html_table}'
            f'{summary_html}'
            f'</div>'
            f'<div class="print-col-right">'
            f'<div class="print-title">📐 Technische Gesamt-Zeichnung</div>'
            f'{print_img_html}'
            f'</div>'
            f'</div>'
        )
        st.markdown(print_sheet_html, unsafe_allow_html=True)
