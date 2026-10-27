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

# --- DRUCK-CSS: LINKS STÜCKLISTE, RECHTS ZEICHNUNG (NEBENEINANDER IM QUERFORMAT) ---
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
    margin-bottom: 10px;
    color: #000000;
}
table.excel-table th, table.excel-table td {
    border: 1px solid #94a3b8;
    padding: 4px 5px;
    text-align: left;
    font-size: 9.5px;
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
    padding: 8px;
    font-family: sans-serif;
    font-size: 11px;
    color: #000;
    margin-top: 8px;
    margin-bottom: 10px;
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
        height: auto !important;
        overflow: visible !important;
    }
    
    div[data-testid="stHorizontalBlock"] {
        display: flex !important;
        flex-direction: row !important;
        flex-wrap: nowrap !important;
        gap: 15px !important;
        align-items: flex-start !important;
        width: 100% !important;
    }
    
    div[data-testid="column"]:nth-of-type(1) {
        width: 54% !important;
        flex: 0 0 54% !important;
        display: block !important;
    }
    
    div[data-testid="column"]:nth-of-type(2) {
        width: 46% !important;
        flex: 0 0 46% !important;
        display: block !important;
    }

    img {
        width: 100% !important;
        max-height: 16cm !important;
        object-fit: contain !important;
        border: 1px solid #000 !important;
        background-color: white !important;
    }

    table.excel-table {
        font-size: 7.5pt !important;
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

st.title("📦 Rohteil- & Stücklisten-Rechner (Multi-Datei)")
st.write("Wähle Material, definiere den Verschnitt in % und ziehe **eine oder mehrere STEP-Dateien gleichzeitig** hinein.")

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

# --- MULTI-UPLOAD AKTIVIERT ---
uploaded_files = st.file_uploader("STEP-Datei(en) auswählen oder hier ablegen (Mehrfachauswahl möglich)", type=["step", "stp"], accept_multiple_files=True)

if uploaded_files:
    with tempfile.TemporaryDirectory() as tmpdir:
        svg_name = os.path.join(tmpdir, "temp_vorschau.svg")
        stl_name = os.path.join(tmpdir, "temp_3d.stl")
        
        alle_positionen = []
        alle_teile_verschoben = []
        aktueller_x_offset = 0.0
        
        try:
            with st.spinner(f"Analysiere {len(uploaded_files)} STEP-Datei(en), benenne Bauteile und berechne Preise..."):
                for i, uploaded_file in enumerate(uploaded_files):
                    file_basename = os.path.splitext(uploaded_file.name)[0]
                    dateiname = os.path.join(tmpdir, f"temp_bauteil_{i}.step")
                    
                    with open(dateiname, "wb") as f:
                        f.write(uploaded_file.getbuffer())
                    
                    baugruppe = cq.importers.importStep(dateiname)
                    teile = baugruppe.solids().vals()
                    
                    if len(teile) > 0:
                        # Für die Gesamtzeichnung: Dateien nebeneinander anordnen
                        file_compound = cq.Compound.makeCompound(teile)
                        bbox_file = file_compound.BoundingBox()
                        
                        dx = -bbox_file.xmin + aktueller_x_offset
                        dy = -bbox_file.ymin
                        dz = -bbox_file.zmin
                        
                        verschobenes_compound = file_compound.translate((dx, dy, dz))
                        alle_teile_verschoben.append(verschobenes_compound)
                        
                        abstand = max(bbox_file.xlen * 0.2, 50.0)
                        aktueller_x_offset += bbox_file.xlen + abstand
                        
                        # Teile innerhalb dieser STEP-Datei analysieren
                        datei_rohteile = []
                        for teil in teile:
                            box = teil.BoundingBox()
                            abmessungen = sorted([round(box.xlen, 2), round(box.ylen, 2), round(box.zlen, 2)], reverse=True)
                            L, B, D = abmessungen[0], abmessungen[1], abmessungen[2]
                            
                            volumen_mm3 = teil.Volume()
                            volumen_dm3 = volumen_mm3 / 1_000_000.0
                            einzel_gewicht = volumen_dm3 * dichte
                            
                            oberflaeche = teil.Area()
                            if oberflaeche > 0:
                                roh_staerke = (volumen_mm3 / oberflaeche) * 2
                                norm_staerke = finde_norm_dicke(roh_staerke)
                            else:
                                roh_staerke = 0.0
                                norm_staerke = 0.0
                                
                            datei_rohteile.append({
                                "Laenge": L,
                                "Breite": B,
                                "Dicke": D,
                                "NormStaerke": norm_staerke,
                                "EinzelGewicht": einzel_gewicht
                            })
                        
                        # Gleiche Teile innerhalb derselben STEP-Datei gruppieren
                        df_file = pd.DataFrame(datei_rohteile)
                        df_file_grouped = df_file.groupby(["Laenge", "Breite", "Dicke", "NormStaerke"]).agg(
                            Anzahl=("Laenge", "count"),
                            EinzelGewicht=("EinzelGewicht", "first")
                        ).reset_index()
                        
                        # Sortieren nach Häufigkeit/Größe für logische Nummerierung
                        df_file_grouped = df_file_grouped.sort_values(by=["Anzahl", "Laenge"], ascending=[False, False]).reset_index(drop=True)
                        
                        # NAMENSVERGABE:
                        # 1 Bauteil-Typ in der STEP -> heißt genau wie die STEP-Datei
                        # Mehrere verschiedene Bauteile in der STEP -> Dateiname_1, Dateiname_2, ...
                        anzahl_unterschiedliche_teile = len(df_file_grouped)
                        for idx_f, row_f in df_file_grouped.iterrows():
                            if anzahl_unterschiedliche_teile == 1:
                                bauteil_name = file_basename
                            else:
                                bauteil_name = f"{file_basename}_{idx_f + 1}"
                                
                            alle_positionen.append({
                                "BauteilName": bauteil_name,
                                "Anzahl": row_f["Anzahl"],
                                "Laenge": row_f["Laenge"],
                                "Breite": row_f["Breite"],
                                "Dicke": row_f["Dicke"],
                                "NormStaerke": row_f["NormStaerke"],
                                "EinzelGewicht": row_f["EinzelGewicht"]
                            })
                
                if len(alle_positionen) == 0:
                    st.warning("⚠️ Die hochgeladenen Dateien enthielten keine gültigen 3D-Volumenkörper.")
                else:
                    df_grouped = pd.DataFrame(alle_positionen)
                    gesamt_bauteile_anzahl = int(df_grouped["Anzahl"].sum())
                    st.success(f"Erfolgreich! Aus {len(uploaded_files)} Datei(en) wurden insgesamt {gesamt_bauteile_anzahl} Bauteile ({len(df_grouped)} Positionen) analysiert.")
                    
                    # Berechnungen pro Position
                    df_grouped["GesamtGewichtNetto"] = df_grouped["EinzelGewicht"] * df_grouped["Anzahl"]
                    df_grouped["VerschnittGewicht"] = df_grouped["GesamtGewichtNetto"] * faktor_verschnitt
                    df_grouped["GesamtGewichtBrutto"] = df_grouped["GesamtGewichtNetto"] + df_grouped["VerschnittGewicht"]
                    
                    df_grouped["EinzelPreis"] = df_grouped["EinzelGewicht"] * preis_pro_kg
                    df_grouped["GesamtPreisBrutto"] = df_grouped["GesamtGewichtBrutto"] * preis_pro_kg
                    
                    # Gesamtsummen für die Box unten
                    netto_ges_gew = df_grouped["GesamtGewichtNetto"].sum()
                    verschnitt_ges_gew = df_grouped["VerschnittGewicht"].sum()
                    brutto_ges_gew = df_grouped["GesamtGewichtBrutto"].sum()
                    netto_ges_preis = netto_ges_gew * preis_pro_kg
                    verschnitt_ges_preis = verschnitt_ges_gew * preis_pro_kg
                    brutto_ges_preis = df_grouped["GesamtPreisBrutto"].sum()
                    
                    col1, col2 = st.columns([1.15, 0.85])
                    
                    with col1:
                        if len(uploaded_files) == 1:
                            titel_text = f"📋 Stückliste: {os.path.splitext(uploaded_files[0].name)[0]}"
                        else:
                            titel_text = f"📋 Gesamt-Stückliste ({len(uploaded_files)} Dateien)"
                        st.markdown(f"### {titel_text}")
                        
                        html_table = '<table class="excel-table">'
                        html_table += '<thead><tr><th>Pos.</th><th>Bauteil / Benennung</th><th>Menge</th><th>Maße (L x B x D)</th><th>DIN-Stärke</th><th>Einz.-Gew.</th><th>Ges.-Gew.</th><th>Einz.-Preis</th><th>Ges.-Preis</th></tr></thead>'
                        html_table += '<tbody>'
                        
                        for idx, row in df_grouped.iterrows():
                            pos = idx + 1
                            bauteil_str = row["BauteilName"]
                            anzahl = int(row["Anzahl"])
                            mass_str = f"{row['Laenge']}x{row['Breite']}x{row['Dicke']}mm"
                            norm_str = f"{row['NormStaerke']} mm"
                            einzel_gew_str = f"{round(row['EinzelGewicht'], 2)} kg"
                            gesamt_gew_str = f"{round(row['GesamtGewichtBrutto'], 2)} kg"
                            einzel_preis_str = f"{round(row['EinzelPreis'], 2)} Fr."
                            preis_brutto_str = f"{round(row['GesamtPreisBrutto'], 2)} Fr."
                            
                            html_table += '<tr>'
                            html_table += f'<td><b>{pos}</b></td>'
                            html_table += f'<td><b>{bauteil_str}</b></td>'
                            html_table += f'<td><b>{anzahl}x</b></td>'
                            html_table += f'<td>{mass_str}</td>'
                            html_table += f'<td><b>{norm_str}</b></td>'
                            html_table += f'<td>{einzel_gew_str}</td>'
                            html_table += f'<td><b>{gesamt_gew_str}</b></td>'
                            html_table += f'<td>{einzel_preis_str}</td>'
                            html_table += f'<td><b>{preis_brutto_str}</b></td>'
                            html_table += '</tr>'
                            
                        html_table += '</tbody></table>'
                        st.markdown(html_table, unsafe_allow_html=True)
                        
                        # --- SEPARATE ZUSAMMENFASSUNG UNTEN ---
                        summary_html = f'''
                        <div class="summary-box">
                            <b>📊 Gesamtauswertung ({selected_material} | Total {gesamt_bauteile_anzahl} Teile):</b><br>
                            • Netto-Gewicht: <b>{round(netto_ges_gew, 2)} kg</b> ({round(netto_ges_preis, 2)} Fr.)<br>
                            • Verschnitt ({int(verschnitt_prozent)}%): <b>{round(verschnitt_ges_gew, 2)} kg</b> ({round(verschnitt_ges_preis, 2)} Fr.)<br>
                            <hr style="margin: 3px 0; border-top: 1px solid #94a3b8;">
                            • <b>TOTAL (Brutto inkl. Verschnitt):</b> <b>{round(brutto_ges_gew, 2)} kg</b> | <b>{round(brutto_ges_preis, 2)} Fr.</b>
                        </div>
                        '''
                        st.markdown(summary_html, unsafe_allow_html=True)
                        
                        st.write("") 
                        st.components.v1.html('<button onclick="window.parent.print()" style="padding:10px 20px; font-size:15px; font-weight:bold; cursor:pointer; background-color:#2563eb; color:white; border:none; border-radius:6px; width: 100%; box-shadow: 0 4px 6px rgba(0,0,0,0.1);">🖨️ Stückliste & Zeichnung drucken</button>', height=55)
                        
                    with col2:
                        st.markdown("### 🖍️ Technische Gesamt-Zeichnung")
                        
                        gesamt_compound = cq.Compound.makeCompound(alle_teile_verschoben)
                        
                        opt = {
                            "width": 1200,
                            "height": 1000,
                            "showAxes": False,
                            "projectionDir": (1.2, -1.0, 1.0)
                        }
                        
                        try:
                            cq.exporters.export(gesamt_compound, svg_name, opt=opt)
                        except:
                            cq.exporters.export(gesamt_compound, svg_name)
                            
                        with open(svg_name, "r", encoding="utf-8") as f:
                            svg_data = f.read()
                            
                        b64 = base64.b64encode(svg_data.encode("utf-8") if isinstance(svg_data, str) else svg_data).decode("utf-8")
                        html_img = f'<img src="data:image/svg+xml;base64,{b64}" style="width: 100%; max-height: 720px; border: 1px solid #cbd5e1; border-radius: 6px; padding: 10px; background-color: white;" />'
                        st.markdown(html_img, unsafe_allow_html=True)
                        
                        st.write("---")
                        
                        if st.checkbox("🔄 Interaktive 3D-Ansicht anzeigen (Drehen & Zoomen)"):
                            st.info("💡 Tipp: Mit gedrückter linker Maustaste drehen, mit dem Mausrad zoomen.")
                            
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
                            stl_from_file(file_path=stl_name, color="#ff8c00", height=600)
                
        except Exception as e:
            st.error(f"Es gab ein technisches Problem beim Lesen der Dateien. Fehler: {e}")

st.markdown("---")
st.markdown(
    """
    <div style="text-align: center; margin-top: 20px; margin-bottom: 20px;">
        <a href="javascript:window.location.reload(true);" target="_blank" style="text-decoration: none;">
            <button style="padding: 12px 28px; font-size: 16px; font-weight: bold; cursor: pointer; background: linear-gradient(135deg, #10b981, #059669); color: white; border: none; border-radius: 8px; box-shadow: 0 4px 6px rgba(0,0,0,0.15); transition: 0.3s;">
                🌐 App im Browser öffnen / Link kopieren
            </button>
        </a>
    </div>
    """,
    unsafe_allow_html=True
)
