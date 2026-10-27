import streamlit as st
import cadquery as cq
import os
import base64
import tempfile
import pandas as pd
from streamlit_stl import stl_from_file

# --- Dichten in g/cm³ und Richtpreise (CHF/kg) ---
MATERIALIEN = {
    "Stahl (1.0037 / S235)": {"dichte": 7.85, "preis_markt": 2.40},
    "Aluminium (AlMg3 / AlCuMg)": {"dichte": 2.70, "preis_markt": 4.50},
    "CNS / Edelstahl (1.4301)": {"dichte": 7.90, "preis_markt": 7.80}
}

DIN_STAERKEN = [0.5, 0.7, 0.8, 1.0, 1.2, 1.5, 2.0, 2.5, 3.0, 4.0, 5.0, 6.0, 8.0, 10.0, 12.0, 15.0, 20.0, 25.0, 30.0, 40.0, 50.0]

def finde_norm_dicke(berechnet):
    if berechnet <= 0:
        return 0.0
    return min(DIN_STAERKEN, key=lambda x: abs(x - berechnet))

st.set_page_config(page_title="Rohteil- & Stücklisten-Rechner", layout="wide")

# --- DRUCK-CSS: SAUBERE EINSEITIGE QUERFORMAT-ANSICHT ---
st.markdown('''
<style>
iframe[height="600"] {
    background-color: #334155 !important;
    border: 2px solid #0f172a;
    border-radius: 8px;
}

table.excel-table {
    width: 100%;
    border-collapse: collapse;
    font-family: sans-serif;
    margin-top: 10px;
    margin-bottom: 15px;
    color: #000000;
}
table.excel-table th, table.excel-table td {
    border: 1px solid #94a3b8;
    padding: 5px 7px;
    text-align: left;
    font-size: 11px;
    color: #000000;
}
table.excel-table th {
    background-color: #e2e8f0 !important;
    color: #000000 !important;
    font-weight: bold;
}
table.excel-table tr:nth-child(even) {
    background-color: #f8fafc;
}

.summary-box {
    background-color: #f1f5f9;
    border: 1px solid #cbd5e1;
    border-radius: 6px;
    padding: 10px;
    font-family: sans-serif;
    font-size: 12px;
    color: #000;
    margin-top: 10px;
    margin-bottom: 15px;
}

@media print {
    @page { 
        size: A4 landscape; 
        margin: 8mm; 
    }
    
    header, footer, [data-testid="stToolbar"], [data-testid="stSidebar"], 
    [data-testid="stFileUploader"], button, .stCheckbox, iframe,
    h1, div[data-testid="stAlert"] { 
        display: none !important; 
    }

    html, body, .stApp, main, .block-container {
        background-color: white !important;
        color: black !important;
        margin: 0 !important;
        padding: 0 !important;
        height: 100% !important;
        overflow: hidden !important;
    }
    
    div[data-testid="stHorizontalBlock"] {
        display: flex !important;
        flex-direction: row !important;
        gap: 15px !important;
        align-items: flex-start !important;
    }
    
    div[data-testid="column"]:nth-of-type(1) {
        width: 48% !important;
        flex: 0 0 48% !important;
    }
    
    div[data-testid="column"]:nth-of-type(2) {
        width: 52% !important;
        flex: 0 0 52% !important;
    }

    img {
        width: 100% !important;
        max-height: 17cm !important;
        object-fit: contain !important;
        border: 1px solid #000 !important;
        background-color: white !important;
    }

    table.excel-table {
        font-size: 9pt !important;
        border: 1px solid #000 !important;
    }
    table.excel-table th, table.excel-table td {
        border: 1px solid #000 !important;
        color: #000 !important;
    }
    
    .summary-box {
        border: 1px solid #000 !important;
        background-color: #fff !important;
    }
}
</style>
''', unsafe_allow_html=True)

st.title("📦 Rohteil- & Stücklisten-Rechner")
st.write("Wähle Material, definiere den Verschnitt in % und erhalte die komplette Aufschlüsselung inklusive Einzelpreisen und Gesamtsummen.")

# --- EINSTELLUNGEN ---
col_m1, col_m2, col_m3 = st.columns([2, 1, 1])
with col_m1:
    selected_material = st.selectbox("🪨 Material auswählen:", list(MATERIALIEN.keys()))
with col_m2:
    markt_preis = MATERIALIEN[selected_material]["preis_markt"]
    preis_pro_kg = st.number_input("💰 Preis/kg (CHF)", min_value=0.0, value=markt_preis, step=0.10, format="%.2f")
with col_m3:
    verschnitt_prozent = st.number_input("✂️ Verschnitt (%)", min_value=0.0, max_value=100.0, value=10.0, step=1.0, format="%.1f")

dichte = MATERIALIEN[selected_material]["dichte"]
faktor_verschnitt = verschnitt_prozent / 100.0

uploaded_file = st.file_uploader("STEP-Datei auswählen oder hier ablegen", type=["step", "stp"])

if uploaded_file is not None:
    file_basename = os.path.splitext(uploaded_file.name)[0]
    
    with tempfile.TemporaryDirectory() as tmpdir:
        dateiname = os.path.join(tmpdir, "temp_bauteil.step")
        svg_name = os.path.join(tmpdir, "temp_vorschau.svg")
        stl_name = os.path.join(tmpdir, "temp_3d.stl")
        
        with open(dateiname, "wb") as f:
            f.write(uploaded_file.getbuffer())
        
        try:
            with st.spinner("Analysiere 3D-Daten, berechne Gewichte, Verschnitt und Preise..."):
                baugruppe = cq.importers.importStep(dateiname)
                teile = baugruppe.solids().vals()
                
                if len(teile) == 0:
                    st.warning("⚠️ Die Datei konnte gelesen werden, enthält aber keine Volumenkörper.")
                else:
                    st.success(f"Erfolgreich! Insgesamt {len(teile)} Volumenkörper gefunden.")
                    
                    rohteile_liste = []
                    for teil in teile:
                        box = teil.BoundingBox()
                        L = round(box.xlen, 2)
                        B = round(box.ylen, 2)
                        D = round(box.zlen, 2)
                        
                        volumen_mm3 = teil.Volume()
                        volumen_dm3 = volumen_mm3 / 1_000_000.0  # mm³ in dm³
                        einzel_gewicht = volumen_dm3 * dichte     # Gewicht in kg pro Stück
                        
                        oberflaeche = teil.Area()
                        if oberflaeche > 0:
                            roh_staerke = (volumen_mm3 / oberflaeche) * 2
                            norm_staerke = finde_norm_dicke(roh_staerke)
                        else:
                            roh_staerke = 0.0
                            norm_staerke = 0.0
                            
                        rohteile_liste.append({
                            "Laenge": L,
                            "Breite": B,
                            "Dicke": D,
                            "NormStaerke": norm_staerke,
                            "EinzelGewicht": einzel_gewicht
                        })
                    
                    df = pd.DataFrame(rohteile_liste)
                    
                    # Gruppieren nach gleichen Abmessungen
                    df_grouped = df.groupby(["Laenge", "Breite", "Dicke", "NormStaerke"]).agg(
                        Anzahl=("Laenge", "count"),
                        EinzelGewicht=("EinzelGewicht", "first")
                    ).reset_index()
                    
                    # Berechnungen pro Position
                    df_grouped["GesamtGewichtNetto"] = df_grouped["EinzelGewicht"] * df_grouped["Anzahl"]
                    df_grouped["VerschnittGewicht"] = df_grouped["GesamtGewichtNetto"] * faktor_verschnitt
                    df_grouped["GesamtGewichtBrutto"] = df_grouped["GesamtGewichtNetto"] + df_grouped["VerschnittGewicht"]
                    
                    df_grouped["EinzelPreis"] = df_grouped["EinzelGewicht"] * preis_pro_kg
                    df_grouped["VerschnittPreis"] = df_grouped["VerschnittGewicht"] * preis_pro_kg
                    df_grouped["GesamtPreisBrutto"] = df_grouped["GesamtGewichtBrutto"] * preis_pro_kg
                    
                    df_grouped = df_grouped.sort_values(by="Anzahl", ascending=False).reset_index(drop=True)
                    
                    # Gesamtsummen für die Box unten
                    netto_ges_gew = df_grouped["GesamtGewichtNetto"].sum()
                    verschnitt_ges_gew = df_grouped["VerschnittGewicht"].sum()
                    brutto_ges_gew = df_grouped["GesamtGewichtBrutto"].sum()
                    netto_ges_preis = netto_ges_gew * preis_pro_kg
                    verschnitt_ges_preis = verschnitt_ges_gew * preis_pro_kg
                    brutto_ges_preis = df_grouped["GesamtPreisBrutto"].sum()
                    
                    col1, col2 = st.columns([1, 1])
                    
                    with col1:
                        st.markdown(f"### 📋 Stückliste: {file_basename}")
                        
                        html_table = '<table class="excel-table">'
                        html_table += '<thead><tr><th>Pos.</th><th>Menge</th><th>Maße (L x B x D)</th><th>Einz.-Gew.</th><th>Einz.-Preis</th><th>Ges.-Preis (Brutto)</th></tr></thead>'
                        html_table += '<tbody>'
                        
                        for idx, row in df_grouped.iterrows():
                            pos = idx + 1
                            anzahl = int(row["Anzahl"])
                            mass_str = f"{row['Laenge']}x{row['Breite']}x{row['Dicke']}mm"
                            einzel_gew_str = f"{round(row['EinzelGewicht'], 2)} kg"
                            einzel_preis_str = f"{round(row['EinzelPreis'], 2)} Fr."
                            preis_brutto_str = f"{round(row['GesamtPreisBrutto'], 2)} Fr."
                            
                            html_table += f'<tr>'
                            html_table += f'<td><b>{pos}</b></td>'
                            html_table += f'<td><b>{anzahl}x</b></td>'
                            html_table += f'<td>{mass_str}</td>'
                            html_table += f'<td>{einzel_gew_str}</td>'
                            html_table += f'<td>{einzel_preis_str}</td>'
                            html_table += f'<td><b>{preis_brutto_str}</b></td>'
                            html_table += f'</tr>'
                            
                        html_table += '</tbody></table>'
                        st.markdown(html_table, unsafe_allow_html=True)
                        
                        # --- SEPARATE ZUSAMMENFASSUNG UNTEN ---
                        summary_html = f'''
                        <div class="summary-box">
                            <b>📊 Gesamtauswertung ({selected_material}):</b><br>
                            • Netto-Gewicht: <b>{round(netto_ges_gew, 2)} kg</b> ({round(netto_ges_preis, 2)} Fr.)<br>
                            • Verschnitt ({int(verschnitt_prozent)}%): <b>{round(verschnitt_ges_gew, 2)} kg</b> ({round(verschnitt_ges_preis, 2)} Fr.)<br>
                            <hr style="margin: 5px 0; border-top: 1px solid #94a3b8;">
                            • <b>TOTAL (Brutto inkl. Verschnitt):</b> <b>{round(brutto_ges_gew, 2)} kg</b> | <b>{round(brutto_ges_preis, 2)} Fr.</b>
                        </div>
                        '''
                        st.markdown(summary_html, unsafe_allow_html=True)
                        
                        st.write("") 
                        st.components.v1.html('<button onclick="window.parent.print()" style="padding:10px 20px; font-size:15px; font-weight:bold; cursor:pointer; background-color:#2563eb; color:white; border:none; border-radius:6px; width: 100%; box-shadow: 0 4px 6px rgba(0,0,0,0.1);">🖨️ Stückliste & Zeichnung drucken (1 Seite)</button>', height=55)
                        
                    with col2:
                        st.markdown("### 🖍️ Technische Zeichnung")
                        
                        compound = cq.Compound.makeCompound(teile)
                        
                        opt = {
                            "width": 1200,
                            "height": 1000,
                            "showAxes": False,
                            "projectionDir": (1.2, -1.0, 1.0)
                        }
                        
                        try:
                            cq.exporters.export(compound, svg_name, opt=opt)
                        except:
                            cq.exporters.export(compound, svg_name)
                            
                        with open(svg_name, "r", encoding="utf-8") as f:
                            svg_data = f.read()
                            
                        b64 = base64.b64encode(svg_data.encode("utf-8") if isinstance(svg_data, str) else svg_data).decode("utf-8")
                        html_img = f'<img src="data:image/svg+xml;base64,{b64}" style="width: 100%; max-height: 750px; border: 1px solid #cbd5e1; border-radius: 6px; padding: 10px; background-color: white;" />'
                        st.markdown(html_img, unsafe_allow_html=True)
                        
                        st.write("---")
                        
                        if st.checkbox("🔄 Interaktive 3D-Ansicht anzeigen (Drehen & Zoomen)"):
                            st.info("💡 Tipp: Mit gedrückter linker Maustaste drehen, mit dem Mausrad zoomen.")
                            
                            bbox = compound.BoundingBox()
                            dx = -(bbox.xmin + bbox.xmax) / 2
                            dy = -(bbox.ymin + bbox.ymax) / 2
                            dz = -(bbox.zmin + bbox.zmax) / 2
                            
                            c_centered = compound.translate((dx, dy, dz))
                            cfg_max_dim = max(bbox.xlen, bbox.ylen, bbox.zlen)
                            if cfg_max_dim > 150:
                                scale_factor = 100.0 / cfg_max_dim
                                c_export = c_centered.scale(scale_factor)
                            else:
                                c_export = c_centered
                                
                            cq.exporters.export(c_export, stl_name, tolerance=0.5, angularTolerance=0.5)
                            stl_from_file(file_path=stl_name, color="#ff8c00", height=600)
                
        except Exception as e:
            st.error(f"Es gab ein technisches Problem beim Lesen der Datei. Fehler: {e}")

st.markdown("---")
col_b1, col_b2, col_b3 = st.columns([1, 2, 1])
with col_b2:
    st.markdown(
        '<div style="text-align: center;">'
        '<a href="" target="_self" style="text-decoration: none;">'
        '<button style="padding: 10px 20px; font-size: 15px; font-weight: bold; cursor: pointer; background-color: #10b981; color: white; border: none; border-radius: 6px; box-shadow: 0 4px 6px rgba(0,0,0,0.1); width: 100%;">🌐 App-Link für das Team teilen</button>'
        '</a>'
        '</div>',
        unsafe_allow_html=True
    )
