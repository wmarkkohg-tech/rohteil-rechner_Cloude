import streamlit as st
import cadquery as cq
import os
import base64
import tempfile
from streamlit_stl import stl_from_file

# --- Liste der gängigen DIN-Blechstärken in Europa (in mm) ---
DIN_STAERKEN = [0.5, 0.7, 0.8, 1.0, 1.2, 1.5, 2.0, 2.5, 3.0, 4.0, 5.0, 6.0, 8.0, 10.0, 12.0, 15.0, 20.0, 25.0, 30.0, 40.0, 50.0]

def finde_norm_dicke(berechnet):
    if berechnet <= 0:
        return 0.0
    return min(DIN_STAERKEN, key=lambda x: abs(x - berechnet))

st.set_page_config(page_title="Rohteil-Rechner", layout="wide")

# --- MAGISCHES CSS FÜR DRUCK (EXAKT 1 SEITE GARANTIERT) ---
st.markdown("""
<style>
iframe[height="600"] {
    background-color: #334155 !important;
    border: 2px solid #0f172a;
    border-radius: 8px;
}

@media print {
    @page { 
        size: A4 landscape; 
        margin: 5mm; 
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
        overflow: hidden !important; 
        background-color: white !important;
        margin: 0 !important;
        padding: 0 !important;
    }
    
    div[data-testid="stHorizontalBlock"] {
        display: flex !important;
        flex-direction: row !important;
        flex-wrap: nowrap !important; 
        align-items: flex-start !important;
        gap: 15px !important;
        max-height: 18cm !important;
    }
    div[data-testid="column"]:nth-of-type(1) {
        width: 35% !important;
        flex: 0 0 35% !important;
    }
    div[data-testid="column"]:nth-of-type(2) {
        width: 65% !important;
        flex: 0 0 65% !important;
    }

    h3 {
        font-size: 14pt !important;
        margin-top: 0 !important;
        margin-bottom: 5px !important;
    }

    img {
        max-height: 13cm !important; 
        width: auto !important;
        max-width: 100% !important;
        object-fit: contain !important;
        border: 2px solid #000 !important;
        background-color: white !important;
    }

    .mass-box {
        display: block !important;
        -webkit-print-color-adjust: exact !important;
        print-color-adjust: exact !important;
        padding: 10px !important; 
        margin-bottom: 5px !important;
    }
}
</style>
""", unsafe_allow_html=True)

st.title("📦 Rohteil-Maße ermitteln")
st.write("Ziehe eine STEP-Datei in das Feld unten. Das Programm liest automatisch die äußersten Kanten aus und erstellt eine isometrische 2D-Zeichnung zum Ausdrucken.")

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
            with st.spinner("Lese 3D-Daten aus und generiere Zeichnung..."):
                baugruppe = cq.importers.importStep(dateiname)
                teile = baugruppe.solids().vals()
                
                if len(teile) == 0:
                    st.warning("⚠️ Die Datei konnte gelesen werden, enthält aber keine Volumenkörper.")
                else:
                    st.success(f"Erfolgreich! Es wurden {len(teile)} Bauteil(e) gefunden.")
                    
                    col1, col2 = st.columns([1, 2])
                    
                    with col1:
                        st.markdown("### 📐 Rohteil-Maße")
                        for i, teil in enumerate(teile):
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
                                
                            if len(teile) == 1:
                                teil_name = file_basename
                            else:
                                teil_name = f"{file_basename} (Teil {i+1})"
                            
                            html_masse = f"""
                            <div class="mass-box" style="background-color: #eff6ff; border-left: 5px solid #3b82f6; border-radius: 5px; font-family: sans-serif; color: #000;">
                                <h4 style="margin-top:0; margin-bottom:5px; color: #1e3a8a; word-wrap: break-word;">{teil_name}</h4>
                                <strong>Außenmaß:</strong> {L} x {B} x {D} mm<br><br>
                                <strong>Materialstärke (DIN):</strong> {norm_staerke} mm<br>
                                <span style="font-size: 0.9em; color: #555;"><em>(Rechnerisch: {round(roh_staerke, 2)} mm)</em></span>
                            </div>
                            """
                            st.markdown(html_masse, unsafe_allow_html=True)
                            
                        st.write("") 
                        st.components.v1.html('<button onclick="window.parent.print()" style="padding:10px 20px; font-size:18px; cursor:pointer; background-color:#f0f2f6; border:1px solid #ccc; border-radius:5px; width: 100%; box-shadow: 2px 2px 5px rgba(0,0,0,0.1);">🖨️ Datenblatt drucken</button>')
                        
                    with col2:
                        st.markdown("### 🖍️ Technische Zeichnung")
                        
                        compound = cq.Compound.makeCompound(teile)
                        
                        opt = {
                            "width": 1000,
                            "height": 800,
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
                        html_img = f'<img src="data:image/svg+xml;base64,{b64}" style="width: 100%; max-height: 800px; border: 1px solid #ddd; padding: 10px; background-color: white;" />'
                        st.markdown(html_img, unsafe_allow_html=True)
                        
                        st.write("---")
                        
                        if st.checkbox("🔄 Interaktive 3D-Ansicht anzeigen (Drehen & Zoomen)"):
                            st.info("💡 Tipp: Mit gedrückter linker Maustaste drehen, mit dem Mausrad zoomen.")
                            
                            bbox = compound.BoundingBox()
                            dx = -(bbox.xmin + bbox.xmax) / 2
                            dy = -(bbox.ymin + bbox.ymax) / 2
                            dz = -(bbox.zmin + bbox.zmax) / 2
                            
                            c_centered = compound.translate((dx, dy, dz))
                            
                            max_dim = max(bbox.xlen, bbox.ylen, bbox.zlen)
                            if max_dim > 150:
                                scale_factor = 100.0 / max_dim
                                c_export = c_centered.scale(scale_factor)
                            else:
                                c_export = c_centered
                                
                            cq.exporters.export(c_export, stl_name, tolerance=0.5, angularTolerance=0.5)
                            stl_from_file(file_path=stl_name, color="#ff8c00", height=600)
                    
        except Exception as e:
            st.error(f"Es gab ein technisches Problem beim Lesen der Datei. Fehler: {e}")
