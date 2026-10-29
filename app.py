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

def ermittle_exakte_blechstaerke(teil):
    """
    Ermittelt die exakte Blechstärke über Volumen und Oberfläche 
    inkl. Biegeradius-Kompensation für gekantete Blechteile.
    """
    try:
        volumen_mm3 = teil.Volume()
        oberflaeche_mm2 = teil.Area()
        if oberflaeche_mm2 > 0:
            berechnete_staerke = (2.0 * volumen_mm3) / oberflaeche_mm2
            # CAD-Korrekturfaktor für Biegeradien (verhindert Abwärtsrundung auf 2.5mm bei echten 3mm Blechen)
            korrigierte_staerke = berechnete_staerke * 1.08
            return min(DIN_STAERKEN, key=lambda x: abs(x - korrigierte_staerke))
    except:
        pass
    
    box = teil.BoundingBox()
    dims = sorted([box.xlen, box.ylen, box.zlen])
    return min(DIN_STAERKEN, key=lambda x: abs(x - dims[0]))

st.set_page_config(page_title="Rohteil- & Stücklisten-Rechner", layout="wide")

# --- DRUCK-CSS ---
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
    margin-top: 8px;
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
    h1, div[data-testid="stAlert"], [data-testid="stDataFrame"], 
    div[data-testid="stNumberInput"], div[data-testid="stSelectbox"],
    div[data-testid="stExpander"] { 
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

st.title("📦 Rohteil- & Stücklisten-Rechner")

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

uploaded_files = st.file_uploader("STEP-Datei(en) auswählen oder hier ablegen", type=["step", "stp"], accept_multiple_files=True)

if uploaded_files:
    current_file_sig = [(f.name, f.size) for f in uploaded_files]
    
    if st.session_state.get("file_sig") != current_file_sig:
        with tempfile.TemporaryDirectory() as tmpdir:
            svg_name = os.path.join(tmpdir, "temp_vorschau.svg")
            stl_name = os.path.join(tmpdir, "temp_3d.stl")
            
            alle_positionen = []
            alle_teile_verschoben = []
            aktueller_x_offset = 0.0
            
            try:
                with st.spinner("Analysiere STEP-Dateien..."):
                    for i, uploaded_file in enumerate(uploaded_files):
                        file_basename = os.path.splitext(uploaded_file.name)[0]
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
                                
                                volumen_mm3 = teil.Volume()
                                volumen_dm3 = volumen_mm3 / 1_000_000.0
                                norm_staerke = ermittle_exakte_blechstaerke(teil)
                                D = norm_staerke
                                    
                                datei_rohteile.append({
                                    "Laenge": L,
                                    "Breite": B,
                                    "Dicke": D,
                                    "NormStaerke": norm_staerke,
                                    "Volumen_dm3": volumen_dm3
                                })
                            
                            df_file = pd.DataFrame(datei_rohteile)
                            df_file_grouped = df_file.groupby(["Laenge", "Breite", "Dicke", "NormStaerke"]).agg(
                                BasisAnzahl=("Laenge", "count"),
                                Volumen_dm3=("Volumen_dm3", "first")
                            ).reset_index()
                            
                            df_file_grouped = df_file_grouped.sort_values(by=["BasisAnzahl", "Laenge"], ascending=[False, False]).reset_index(drop=True)
                            
                            anzahl_unterschiedliche_teile = len(df_file_grouped)
                            for idx_f, row_f in df_file_grouped.iterrows():
                                if anzahl_unterschiedliche_teile == 1:
                                    bauteil_name = file_basename
                                else:
                                    bauteil_name = f"{file_basename}_{idx_f + 1}"
                                    
                                alle_positionen.append({
                                    "Pos": len(alle_positionen) + 1,
                                    "BauteilName": bauteil_name,
                                    "BasisAnzahl": int(row_f["BasisAnzahl"]),
                                    "Laenge": row_f["Laenge"],
                                    "Breite": row_f["Breite"],
                                    "Dicke": row_f["Dicke"],
                                    "NormStaerke": row_f["NormStaerke"],
                                    "Volumen_dm3": row_f["Volumen_dm3"]
                                })
                    
                    if len(alle_positionen) > 0:
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
                        b64_svg = base64.b64encode(svg_data.encode("utf-8") if isinstance(svg_data, str) else svg_data).decode("utf-8")
                        
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
                        st.session_state["stl_bytes"] = stl_bytes
                    else:
                        st.session_state["basis_daten"] = []
            except Exception as e:
                st.error(f"Fehler beim Lesen der Dateien: {e}")
                st.session_state["basis_daten"] = []

    basis_daten = st.session_state.get("basis_daten", [])
    if len(basis_daten) == 0:
        st.warning("⚠️ Keine gültigen Volumenkörper gefunden.")
    else:
        df_base = pd.DataFrame(basis_daten)
        
        col1, col2 = st.columns([1.15, 0.85])
        
        with col1:
            if len(uploaded_files) == 1:
                titel_text = f"📋 Stückliste: {os.path.splitext(uploaded_files[0].name)[0]}"
            else:
                titel_text = f"📋 Gesamt-Stückliste ({len(uploaded_files)} Dateien)"
            st.markdown(f"### {titel_text}")
            
            edit_input_df = pd.DataFrame({
                "Pos.": df_base["Pos"],
                "Bauteil / Benennung": df_base["BauteilName"],
                "Menge (Stk.)": df_base["BasisAnzahl"],
                "Maße (mm)": df_base.apply(lambda r: f"{r['Laenge']}x{r['Breite']}x{r['Dicke']}", axis=1),
                "DIN-Stärke (mm)": df_base["NormStaerke"]
            })
            
            edited_df = st.data_editor(
                edit_input_df,
                disabled=["Pos.", "Bauteil / Benennung", "Maße (mm)", "DIN-Stärke (mm)"],
                hide_index=True,
                use_container_width=True,
                column_config={
                    "Menge (Stk.)": st.column_config.NumberColumn(
                        "Menge ✏️", min_value=0, max_value=100000, step=1, format="%d"
                    )
                },
                key="main_qty_editor"
            )
            
            df_calc = df_base.copy()
            df_calc["Anzahl"] = edited_df["Menge (Stk.)"].astype(int)
            
            df_calc["EinzelGewicht"] = df_calc["Volumen_dm3"] * dichte
            df_calc["GesamtGewichtNetto"] = df_calc["EinzelGewicht"] * df_calc["Anzahl"]
            df_calc["VerschnittGewicht"] = df_calc["GesamtGewichtNetto"] * faktor_verschnitt
            df_calc["GesamtGewichtBrutto"] = df_calc["GesamtGewichtNetto"] + df_calc["VerschnittGewicht"]
            
            df_calc["EinzelPreis"] = df_calc["EinzelGewicht"] * preis_pro_kg
            df_calc["GesamtPreisBrutto"] = df_calc["GesamtGewichtBrutto"] * preis_pro_kg
            
            gesamt_bauteile_anzahl = int(df_calc["Anzahl"].sum())
            netto_ges_gew = df_calc["GesamtGewichtNetto"].sum()
            verschnitt_ges_gew = df_calc["VerschnittGewicht"].sum()
            brutto_ges_gew = df_calc["GesamtGewichtBrutto"].sum()
            netto_ges_preis = netto_ges_gew * preis_pro_kg
            verschnitt_ges_preis = verschnitt_ges_gew * preis_pro_kg
            brutto_ges_preis = df_calc["GesamtPreisBrutto"].sum()
            
            html_table = '<table class="excel-table">'
            html_table += '<thead><tr><th>Pos.</th><th>Bauteil / Benennung</th><th>Menge</th><th>Maße (L x B x D)</th><th>DIN-Stärke</th><th>Einz.-Gew.</th><th>Ges.-Gew.</th><th>Einz.-Preis</th><th>Ges.-Preis</th></tr></thead>'
            html_table += '<tbody>'
            
            for idx, row in df_calc.iterrows():
                pos = int(row["Pos"])
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
            
            summary_html = f'''
            <div class="summary-box">
                <b>📊 Gesamtauswertung ({selected_material} | Total Menge: {gesamt_bauteile_anzahl} Stk.):</b><br>
                • Netto-Gewicht: <b>{round(netto_ges_gew, 2)} kg</b> ({round(netto_ges_preis, 2)} Fr.)<br>
                • Verschnitt ({int(verschnitt_prozent)}%): <b>{round(verschnitt_ges_gew, 2)} kg</b> ({round(verschnitt_ges_preis, 2)} Fr.)<br>
                <hr style="margin: 3px 0; border-top: 1px solid #94a3b8;">
                • <b>TOTAL (Brutto inkl. Verschnitt):</b> <b>{gesamt_bauteile_anzahl} Stk.</b> | <b>{round(brutto_ges_gew, 2)} kg</b> | <b>{round(brutto_ges_preis, 2)} Fr.</b>
            </div>
            '''
            st.markdown(summary_html, unsafe_allow_html=True)
            
            st.write("") 
            st.components.v1.html('<button onclick="window.parent.print()" style="padding:10px 20px; font-size:15px; font-weight:bold; cursor:pointer; background-color:#2563eb; color:white; border:none; border-radius:6px; width: 100%; box-shadow: 0 4px 6px rgba(0,0,0,0.1);">🖨️ Stückliste & Zeichnung drucken</button>', height=55)
            
        with col2:
            st.markdown("### 🖍️ Technische Gesamt-Zeichnung")
            
            b64_svg = st.session_state.get("b64_svg", "")
            if b64_svg:
                html_img = f'<img src="data:image/svg+xml;base64,{b64_svg}" style="width: 100%; max-height: 720px; border: 1px solid #cbd5e1; border-radius: 6px; padding: 10px; background-color: white;" />'
                st.markdown(html_img, unsafe_allow_html=True)
            
            st.write("---")
            
            if st.checkbox("🔄 Interaktive 3D-Ansicht anzeigen (Drehen & Zoomen)"):
                st.info("💡 Tipp: Mit gedrückter linker Maustaste drehen, mit dem Mausrad zoomen.")
                stl_bytes = st.session_state.get("stl_bytes", None)
                if stl_bytes:
                    with tempfile.NamedTemporaryFile(delete=False, suffix=".stl") as tmp_stl:
                        tmp_stl.write(stl_bytes)
                        tmp_stl_path = tmp_stl.name
                    stl_from_file(file_path=tmp_stl_path, color="#ff8c00", height=600)
