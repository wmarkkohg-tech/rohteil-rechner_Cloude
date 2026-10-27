import streamlit as st
import cadquery as cq
import os
import base64
import tempfile
import pandas as pd
from streamlit_stl import stl_from_file

# --- Liste der gängigen DIN-Blechstärken in Europa (in mm) ---
DIN_STAERKEN = [0.5, 0.7, 0.8, 1.0, 1.2, 1.5, 2.0, 2.5, 3.0, 4.0, 5.0, 6.0, 8.0, 10.0, 12.0, 15.0, 20.0, 25.0, 30.0, 40.0, 50.0]

def finde_norm_dicke(berechnet):
    if berechnet <= 0:
        return 0.0
    return min(DIN_STAERKEN, key=lambda x: abs(x - berechnet))

st.set_page_config(page_title="Rohteil- & Stücklisten-Rechner", layout="wide")

# --- MAGISCHES CSS FÜR DRUCK (EXAKT 1 SEITE ALS EXCEL-STÜCKLISTE) ---
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
    margin-bottom: 20px;
}
table.excel-table th, table.excel-table td {
    border: 1px solid #cbd5e1;
    padding: 10px 12px;
    text-align: left;
    font-size: 14px;
}
table.excel-table th {
    background-color: #f1f5f9;
    color: #1e293b;
    font-weight: bold;
}
table.excel-table tr:nth-child(even) {
    background-color: #f8fafc;
}

@media print {
    @page { 
        size: A4 landscape; 
        margin: 10mm; 
    }
    
    header, footer, [data-testid="stToolbar"], [data-testid="stSidebar"], 
    [data-testid="stFileUploader"], button, .stCheckbox, iframe,
    h1, div[data-testid="stAlert"] { 
        display: none !important; 
    }

    div[data-testid="stMarkdownContainer"] > p {
        display: none !important;
    }

    html, body, .stApp, main, .block-container {
        height: 100vh !important;
        max-height: 100vh !important;
        background-color: white !important;
        margin: 0 !important;
        padding: 0 !important;
    }
    
    div[data-testid="stHorizontalBlock"] {
        display: flex !important;
        flex-direction: row !important;
        flex-wrap: nowrap !important; 
        align-items: flex-start !important;
        gap: 20mm !important;
    }
    div[data-testid="column"]:nth-of-type(1) {
        width: 48% !important;
        flex: 0 0 48% !important;
    }
    div[data-testid="column"]:nth-of-type(2) {
        width: 48% !important;
        flex: 0 0 48% !important;
    }

    h3 {
        font-size: 14pt !important;
        margin-top: 0 !important;
        margin-bottom: 5px !important;
    }

    img {
        max-height: 12cm !important; 
        width: auto !important;
        max-width: 100% !important;
        object-fit: contain !important;
        border: 1px solid #000 !important;
        background-color: white !important;
    }

    table.excel-table {
        font-size: 11pt !important;
        border: 1px solid #000 !important;
    }
    table.excel-table th, table.excel-table td {
        border: 1px solid #000 !important;
        padding: 6px 8px !important;
    }
}
</style>
''', unsafe_allow_html=True)

st.title("📦 Rohteil- & Stücklisten-Rechner")
st.write("Ziehe eine STEP-Datei hinein. Das System erkennt identische Teile automatisch, fasst sie in einer Stückliste zusammen und generiert eine saubere Druckansicht.")

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
            with st.spinner("Lese 3D-Daten aus, analysiere Bauteile und erstelle Stückliste..."):
                baugruppe = cq.importers.importStep(dateiname)
                teile = baugruppe.solids().vals()
                
                if len(teile) == 0:
                    st.warning("⚠️ Die Datei konnte gelesen werden, enthält aber keine Volumenkörper.")
                else:
                    st.success(f"Erfolgreich! Es wurden insgesamt {len(teile)} Volumenkörper gefunden.")
                    
                    rohteile_liste = []
                    for teil in teile:
                        box = teil.BoundingBox()
                        L = round(box.xlen, 2)
                        B = round(box.ylen, 2)
                        D = round(box.zlen, 2)
                        
                        volumen = teil.Volume()
                        oberflaeche = teil.Area()
                        
                        if oberflaeche > 0:
                            roh_staerke = (volumen / oberflaeche) * 2
                            norm_staerke = finde_norm_dicke(roh_staerke)
                        else:
                            roh_staerke = 0.0
                            norm_staerke = 0.0
                            
                        rohteile_liste.append({
                            "Laenge": L,
                            "Breite": B,
                            "Dicke": D,
                            "NormStaerke": norm_staerke
                        })
                    
                    df = pd.DataFrame(rohteile_liste)
                    df_grouped = df.groupby(["Laenge", "Breite", "Dicke", "NormStaerke"]).size().reset_index(name="Anzahl")
                    df_grouped = df_grouped.sort_values(by="Anzahl", ascending=False).reset_index(drop=True)
                    
                    col1, col2 = st.columns([1, 1])
                    
                    with col1:
                        st.markdown(f"### 📋 Stückliste: {file_basename}")
                        
                        html_table = '<table class="excel-table">'
                        html_table += '<thead><tr><th>Pos.</th><th>Anzahl</th><th>Außenmaß (L x B x D)</th><th>DIN-Stärke</th></tr></thead>'
                        html_table += '<tbody>'
                        
                        for idx, row in df_grouped.iterrows():
                            pos = idx + 1
                            anzahl = row["Anzahl"]
                            mass_str = f"{row['Laenge']} x {row['Breite']} x {row['Dicke']} mm"
                            norm_str = f"{row['NormStaerke']} mm"
                            
                            html_table += f'<tr>'
                            html_table += f'<td><b>{pos}</b></td>'
                            html_table += f'<td><b>{anzahl} Stk.</b></td>'
                            html_table += f'<td>{mass_str}</td>'
                            html_table += f'<td>{norm_str}</td>'
                            html_table += f'</tr>'
                            
                        html_table += '</tbody></table>'
                        
                        st.markdown(html_table, unsafe_allow_html=True)
                        st.write("") 
                        st.components.v1.html('<button onclick="window.parent.print()" style="padding:12px 20px; font-size:16px; font-weight:bold; cursor:pointer; background-color:#2563eb; color:white; border:none; border-radius:6px; width: 100%; box-shadow: 0 4px 6px rgba(0,0,0,0.1);">🖨️ Stückliste & Zeichnung drucken</button>', height=60)
                        
                    with col2:
                        st.markdown("### 🖍️ Technische Zeichnung")
                        
                        compound = cq.Compound.makeCompound(teile)
                        
                        opt = {
                            "width": 900,
                            "height": 750,
                            "showAxes": False,
                            "projectionDir": (1.2, -1.0, 1.0)
                        }
                        
                        try:
                            cq.exporters.export(compound, svg_name, opt=opt)
                        except:
                            cq.exporters.export(compound, svg_name)
                            
                        with open(svg_name, "r", encoding="utf-8") as f:
                            svg_data = f.read()
                            
                        b64 = base64.b64encode(svg_data.encode("utf-8")).decode("utf-8")
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
