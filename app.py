# ============================================================
# ARCHIVO: app.py
# Dashboard Ambiental — GAD Municipalidad de Ambato
# Ejecutar con: streamlit run app.py
# ============================================================

import streamlit as st
import pandas as pd
import numpy as np
import plotly.express as px
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import folium
from streamlit_folium import st_folium
from pyproj import Transformer
import io
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, Image
from reportlab.lib.units import cm
import warnings
warnings.filterwarnings('ignore')

# ── CONFIGURACIÓN DE PÁGINA ──────────────────────────────────
st.set_page_config(
    page_title="Dashboard Ambiental — GAD Ambato",
    page_icon="🌿",
    layout="wide",
    initial_sidebar_state="expanded"
)

# ── ESTILOS CSS ──────────────────────────────────────────────
st.markdown("""
<style>
  .main-header {
    background: linear-gradient(135deg, #1a5276, #2980b9);
    padding: 20px 30px; border-radius: 12px;
    color: white; margin-bottom: 20px;
  }
  .kpi-card {
    background: #f0f7ff; border-radius: 10px;
    padding: 15px; text-align: center;
    border-left: 4px solid #2980b9;
  }
  .alerta-roja  { border-left-color: #e74c3c !important; background: #fdf0ef !important; }
  .alerta-ambar { border-left-color: #f39c12 !important; background: #fef9e7 !important; }
  .alerta-verde { border-left-color: #27ae60 !important; background: #eafaf1 !important; }
</style>
""", unsafe_allow_html=True)

# ── CONSTANTES ───────────────────────────────────────────────
ORDEN_MESES = ["ENERO","FEBRERO","MARZO","ABRIL","MAYO","JUNIO",
               "JULIO","AGOSTO","SEPTIEMBRE","OCTUBRE","NOVIEMBRE","DICIEMBRE"]

LIMITES = {
    'MPS_mg_cm2':  1.0,
    'Ozono_ug_m3': 100.0,
    'NO2_ug_m3':   40.0,
}
NOMBRES = {
    'MPS_mg_cm2':  'Material Particulado Sedimentable (mg/cm²)',
    'Ozono_ug_m3': 'Ozono (µg/m³)',
    'NO2_ug_m3':   'Dióxido de Nitrógeno (µg/m³)',
}

# ── FUNCIONES ────────────────────────────────────────────────
def semaforo(v, lim):
    if   v <= lim * 0.75: return '🟢 Bueno'
    elif v <= lim:         return '🟡 Moderado'
    else:                  return '🔴 Excede límite'

def color_folium(v, lim):
    if pd.isna(v):         return 'gray'
    elif v <= lim * 0.75:  return 'green'
    elif v <= lim:         return 'orange'
    else:                  return 'red'

def corregir_mes(mes, archivo):
    if str(mes) in ORDEN_MESES: return mes
    for m in ORDEN_MESES:
        if m in archivo.upper(): return m
    return "DESCONOCIDO"

def leer_excel_pasivo(archivo_bytes, nombre):
    df_raw = pd.read_excel(io.BytesIO(archivo_bytes), sheet_name='MONITOREO PASIVO', header=None)
    titulo = str(df_raw.iloc[3, 0])
    mes = next((m for m in ORDEN_MESES if m in titulo.upper()), None)

    fila_inicio = None
    for i, row in df_raw.iterrows():
        if str(row[0]).strip().lower() == 'código':
            fila_inicio = i + 2
            break
    if fila_inicio is None: return None

    filas = []
    for i in range(fila_inicio, len(df_raw)):
        row = df_raw.iloc[i]
        if pd.isna(row[0]) and pd.isna(row[2]): break
        filas.append({
            'Mes':        mes or corregir_mes('', nombre),
            'Codigo':     str(row[0]).strip(),
            'Punto':      str(row[1]).strip(),
            'X_UTM':      pd.to_numeric(row[2], errors='coerce'),
            'Y_UTM':      pd.to_numeric(row[3], errors='coerce'),
            'MPS_mg_cm2': pd.to_numeric(row[4], errors='coerce'),
            'Ozono_ug_m3':pd.to_numeric(row[5], errors='coerce'),
            'NO2_ug_m3':  pd.to_numeric(row[6], errors='coerce'),
            'Archivo':    nombre
        })
    df = pd.DataFrame(filas).dropna(subset=['X_UTM'])
    df['Mes'] = df.apply(lambda r: corregir_mes(r['Mes'], r['Archivo']), axis=1)
    return df

def utm_a_latlon(x, y):
    try:
        tr = Transformer.from_crs("EPSG:32717", "EPSG:4326", always_xy=True)
        lon, lat = tr.transform(x, y)
        if -5 < lat < 2 and -81 < lon < -75:
            return lat, lon
    except: pass
    return None, None

def generar_pdf(df_mes, mes, param):
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4,
                            leftMargin=2*cm, rightMargin=2*cm,
                            topMargin=2*cm, bottomMargin=2*cm)
    styles = getSampleStyleSheet()
    story  = []

    # Título
    titulo_style = ParagraphStyle('titulo', parent=styles['Title'],
                                  textColor=colors.HexColor('#1a5276'), fontSize=16)
    story.append(Paragraph("GAD Municipalidad de Ambato", titulo_style))
    story.append(Paragraph(f"Informe de Monitoreo Pasivo — {mes}", styles['Heading2']))
    story.append(Paragraph(f"Parámetro: {NOMBRES[param]}", styles['Normal']))
    story.append(Spacer(1, 0.5*cm))

    # Tabla de datos
    lim   = LIMITES[param]
    cols  = ['Punto', param, f'Estado_{param}']
    datos = [['Punto de muestreo', NOMBRES[param][:30], 'Estado']]
    for _, row in df_mes[cols].iterrows():
        datos.append([row['Punto'][:40], f"{row[param]:.2f}", row[f'Estado_{param}']])

    tabla = Table(datos, colWidths=[9*cm, 4*cm, 4*cm])
    tabla.setStyle(TableStyle([
        ('BACKGROUND',    (0,0), (-1,0),  colors.HexColor('#1a5276')),
        ('TEXTCOLOR',     (0,0), (-1,0),  colors.white),
        ('FONTNAME',      (0,0), (-1,0),  'Helvetica-Bold'),
        ('FONTSIZE',      (0,0), (-1,-1), 9),
        ('ROWBACKGROUNDS',(0,1), (-1,-1), [colors.white, colors.HexColor('#f2f3f4')]),
        ('GRID',          (0,0), (-1,-1), 0.5, colors.HexColor('#cccccc')),
        ('ALIGN',         (1,0), (-1,-1), 'CENTER'),
    ]))
    story.append(tabla)
    story.append(Spacer(1, 0.5*cm))

    # Resumen estadístico
    story.append(Paragraph("Resumen estadístico", styles['Heading3']))
    resumen = [
        ['Promedio', f"{df_mes[param].mean():.2f}"],
        ['Máximo',   f"{df_mes[param].max():.2f}"],
        ['Mínimo',   f"{df_mes[param].min():.2f}"],
        ['Límite normativo', f"{lim}"],
        ['Puntos que exceden', f"{(df_mes[param] > lim).sum()} de {len(df_mes)}"],
    ]
    t2 = Table(resumen, colWidths=[6*cm, 4*cm])
    t2.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (0,-1), colors.HexColor('#eaf4fb')),
        ('FONTNAME',   (0,0), (0,-1), 'Helvetica-Bold'),
        ('FONTSIZE',   (0,0), (-1,-1), 10),
        ('GRID',       (0,0), (-1,-1), 0.5, colors.HexColor('#cccccc')),
    ]))
    story.append(t2)
    doc.build(story)
    buffer.seek(0)
    return buffer

def enviar_alerta(destinatarios, mes, param, df_excede, smtp_user, smtp_pass):
    msg = MIMEMultipart('alternative')
    msg['Subject'] = f"⚠️ Alerta Ambiental GAD Ambato — {mes}"
    msg['From']    = smtp_user
    msg['To']      = ", ".join(destinatarios)

    lim   = LIMITES[param]
    filas = "".join([
        f"<tr><td>{r['Punto']}</td><td style='color:red'><b>{r[param]:.2f}</b></td>"
        f"<td>{lim}</td></tr>"
        for _, r in df_excede.iterrows()
    ])
    html = f"""
    <html><body>
    <h2 style='color:#1a5276'>⚠️ Alerta de Calidad del Aire — GAD Ambato</h2>
    <p>Se detectaron <b>{len(df_excede)} puntos</b> que exceden el límite normativo
       en el monitoreo de <b>{mes}</b>.</p>
    <p><b>Parámetro:</b> {NOMBRES[param]} | <b>Límite:</b> {lim}</p>
    <table border='1' cellpadding='6' style='border-collapse:collapse;'>
      <tr style='background:#1a5276;color:white'>
        <th>Punto</th><th>Valor medido</th><th>Límite</th>
      </tr>{filas}
    </table>
    <br><p style='color:gray;font-size:12px'>
      Sistema de Monitoreo Ambiental — GAD Municipalidad de Ambato
    </p></body></html>
    """
    msg.attach(MIMEText(html, 'html'))
    with smtplib.SMTP_SSL('smtp.gmail.com', 465) as s:
        s.login(smtp_user, smtp_pass)
        s.sendmail(smtp_user, destinatarios, msg.as_string())

# ════════════════════════════════════════════════════════════
# INTERFAZ PRINCIPAL
# ════════════════════════════════════════════════════════════

# ── HEADER ──────────────────────────────────────────────────
st.markdown("""
<div class="main-header">
  <h2 style="margin:0">🌿 Dashboard Ambiental — GAD Municipalidad de Ambato</h2>
  <p style="margin:4px 0 0 0; opacity:0.85;">
    Monitoreo Pasivo de Calidad del Aire · Sistema de Gestión Ambiental
  </p>
</div>
""", unsafe_allow_html=True)

# ── SIDEBAR ──────────────────────────────────────────────────
with st.sidebar:
    st.image("https://upload.wikimedia.org/wikipedia/commons/thumb/f/f4/Escudo_de_Ambato.svg/200px-Escudo_de_Ambato.svg.png", width=100)
    st.title("⚙️ Configuración")

    archivos = st.file_uploader(
        "📂 Subir archivos Excel mensuales",
        type=['xlsx'], accept_multiple_files=True,
        help="Sube todos los archivos de Monitoreo Pasivo"
    )

    st.markdown("---")
    st.subheader("📧 Alertas por correo")
    smtp_user   = st.text_input("Correo Gmail remitente", placeholder="tu@gmail.com")
    smtp_pass   = st.text_input("Contraseña de aplicación", type="password")
    destinatarios_str = st.text_input("Destinatarios (separados por coma)",
                                       placeholder="jefe@gad.gob.ec, otro@gad.gob.ec")
    st.caption("⚠️ Usa contraseña de aplicación de Gmail, no tu contraseña normal")

# ── CARGA Y PROCESAMIENTO ─────────────────────────────────────
if not archivos:
    st.info("👈 Sube los archivos Excel de monitoreo en el panel izquierdo para comenzar.")
    st.stop()

@st.cache_data
def cargar_datos(archivos_info):
    lista = []
    for nombre, contenido in archivos_info:
        df_m = leer_excel_pasivo(contenido, nombre)
        if df_m is not None and len(df_m) > 0:
            lista.append(df_m)
    df = pd.concat(lista, ignore_index=True)
    df = df[df['Mes'] != 'DESCONOCIDO'].dropna(subset=['MPS_mg_cm2','Ozono_ug_m3','NO2_ug_m3'])
    df['Punto'] = df['Punto'].str.replace(r'\s+', ' ', regex=True).str.strip()
    df['Mes']   = pd.Categorical(df['Mes'], categories=ORDEN_MESES, ordered=True)
    df          = df.sort_values(['Mes','Punto']).reset_index(drop=True)
    for p, lim in LIMITES.items():
        df[f'Estado_{p}'] = df[p].apply(lambda v: semaforo(v, lim))
    df['lat'], df['lon'] = zip(*df.apply(lambda r: utm_a_latlon(r['X_UTM'], r['Y_UTM']), axis=1))
    return df

archivos_info = [(f.name, f.read()) for f in archivos]
df = cargar_datos(archivos_info)

# ── FILTROS PRINCIPALES ──────────────────────────────────────
col1, col2, col3 = st.columns([2, 2, 2])
with col1:
    meses_sel = st.multiselect("📅 Meses", ORDEN_MESES,
                                default=df['Mes'].unique().tolist())
with col2:
    param = st.selectbox("🧪 Parámetro", list(LIMITES.keys()),
                          format_func=lambda x: NOMBRES[x])
with col3:
    puntos_sel = st.multiselect("📍 Puntos",
                                 sorted(df['Punto'].unique()),
                                 default=sorted(df['Punto'].unique()))

df_f = df[df['Mes'].isin(meses_sel) & df['Punto'].isin(puntos_sel)]
lim  = LIMITES[param]

# ── KPIs ─────────────────────────────────────────────────────
st.markdown("### 📊 Indicadores clave")
k1, k2, k3, k4, k5 = st.columns(5)
pct = (df_f[param] > lim).mean() * 100
exceden = (df_f[param] > lim).sum()

k1.metric("Promedio",        f"{df_f[param].mean():.2f}")
k2.metric("Máximo",          f"{df_f[param].max():.2f}")
k3.metric("Mínimo",          f"{df_f[param].min():.2f}")
k4.metric("Exceden límite",  f"{exceden} registros",   delta=f"{pct:.1f}%",
           delta_color="inverse")
k5.metric("Límite normativo", f"{lim}")

st.markdown("---")

# ── PESTAÑAS ─────────────────────────────────────────────────
tab1, tab2, tab3, tab4, tab5, tab6 = st.tabs([
    "📈 Tendencia", "🗺️ Mapa", "🔥 Heatmap",
    "📦 Boxplot", "🏆 Ranking", "📋 Tabla & PDF"
])

# PESTAÑA 1 — Tendencia
with tab1:
    df_t = df_f.groupby('Mes', observed=True)[param].agg(['mean','max','min']).reset_index()
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=df_t['Mes'], y=df_t['max'], fill=None,
                              mode='lines', line_color='rgba(231,76,60,0.3)', name='Máximo'))
    fig.add_trace(go.Scatter(x=df_t['Mes'], y=df_t['min'], fill='tonexty',
                              mode='lines', line_color='rgba(39,174,96,0.3)',
                              fillcolor='rgba(130,202,157,0.2)', name='Mínimo'))
    fig.add_trace(go.Scatter(x=df_t['Mes'], y=df_t['mean'], mode='lines+markers',
                              name='Promedio', line=dict(color='#2980b9', width=3),
                              marker=dict(size=9)))
    fig.add_hline(y=lim, line_dash='dash', line_color='red',
                  annotation_text=f'Límite: {lim}')
    fig.update_layout(title=f'Tendencia mensual — {NOMBRES[param]}',
                      height=420, hovermode='x unified', plot_bgcolor='#f9f9f9')
    st.plotly_chart(fig, use_container_width=True)

# PESTAÑA 2 — Mapa
with tab2:
    mes_mapa = st.selectbox("Mes para el mapa", meses_sel,
                             index=len(meses_sel)-1, key='mes_mapa')
    df_mapa  = df_f[df_f['Mes'] == mes_mapa].dropna(subset=['lat','lon'])

    mapa = folium.Map(location=[-1.2490, -78.6163], zoom_start=13,
                      tiles='CartoDB positron')
    for _, row in df_mapa.iterrows():
        val   = row[param]
        color = color_folium(val, lim)
        popup = folium.Popup(f"""
            <b>{row['Punto']}</b><br>
            {NOMBRES[param]}: <b style='color:{"red" if color=="red" else "green"}'>{val:.2f}</b><br>
            Ozono: {row['Ozono_ug_m3']:.2f} µg/m³<br>
            NO₂: {row['NO2_ug_m3']:.2f} µg/m³<br>
            Estado: {row[f'Estado_{param}']}
        """, max_width=220)
        folium.Marker(
            [row['lat'], row['lon']], popup=popup,
            tooltip=f"{row['Punto']} | {val:.2f}",
            icon=folium.Icon(color=color, icon='cloud', prefix='fa')
        ).add_to(mapa)
    st_folium(mapa, width=None, height=500)

    # Botón alerta
    df_excede = df_mapa[df_mapa[param] > lim]
    if len(df_excede) > 0:
        st.warning(f"⚠️ {len(df_excede)} punto(s) exceden el límite en {mes_mapa}")
        if smtp_user and smtp_pass and destinatarios_str:
            if st.button("📧 Enviar alerta por correo"):
                try:
                    destinatarios = [d.strip() for d in destinatarios_str.split(',')]
                    enviar_alerta(destinatarios, mes_mapa, param,
                                  df_excede, smtp_user, smtp_pass)
                    st.success("✅ Alerta enviada correctamente")
                except Exception as e:
                    st.error(f"Error al enviar: {e}")

# PESTAÑA 3 — Heatmap
with tab3:
    pivot = df_f.pivot_table(index='Punto', columns='Mes',
                              values=param, aggfunc='mean', observed=True)
    pivot.index = [p[:28]+'…' if len(p)>28 else p for p in pivot.index]
    fig = px.imshow(pivot, color_continuous_scale=['#2ecc71','#f1c40f','#e74c3c'],
                    title=f'Heatmap — {NOMBRES[param]}',
                    labels=dict(color=NOMBRES[param]),
                    aspect='auto', zmin=0, zmax=lim*2)
    fig.update_layout(height=600)
    st.plotly_chart(fig, use_container_width=True)

# PESTAÑA 4 — Boxplot
with tab4:
    df_bp = df_f.copy()
    df_bp['PuntoCorto'] = df_bp['Punto'].str[:28]
    fig = px.box(df_bp, x='PuntoCorto', y=param, color='PuntoCorto',
                 title=f'Distribución por punto — {NOMBRES[param]}',
                 labels={param: NOMBRES[param], 'PuntoCorto': ''},
                 color_discrete_sequence=px.colors.qualitative.Safe)
    fig.add_hline(y=lim, line_dash='dash', line_color='red',
                  annotation_text=f'Límite: {lim}')
    fig.update_layout(height=500, showlegend=False, xaxis_tickangle=-40)
    st.plotly_chart(fig, use_container_width=True)

# PESTAÑA 5 — Ranking
with tab5:
    df_r = df_f.groupby('Punto', observed=True)[param].mean().reset_index()
    df_r = df_r.sort_values(param, ascending=True)
    df_r['Color'] = df_r[param].apply(
        lambda v: '#e74c3c' if v > lim else ('#f39c12' if v > lim*0.75 else '#27ae60'))
    df_r['PuntoCorto'] = df_r['Punto'].str[:30]
    fig = go.Figure(go.Bar(
        x=df_r[param], y=df_r['PuntoCorto'], orientation='h',
        marker_color=df_r['Color'],
        text=df_r[param].round(2), textposition='outside'
    ))
    fig.add_vline(x=lim, line_dash='dash', line_color='red',
                  annotation_text=f'Límite: {lim}')
    fig.update_layout(title=f'Ranking de puntos — {NOMBRES[param]}',
                      height=580, plot_bgcolor='#f9f9f9', margin=dict(l=220))
    st.plotly_chart(fig, use_container_width=True)

# PESTAÑA 6 — Tabla y PDF
with tab6:
    col_a, col_b = st.columns([1, 1])
    with col_a:
        mes_pdf = st.selectbox("Mes para PDF", meses_sel, key='mes_pdf')
    with col_b:
        param_pdf = st.selectbox("Parámetro para PDF", list(LIMITES.keys()),
                                  format_func=lambda x: NOMBRES[x], key='param_pdf')

    df_tabla = df_f[df_f['Mes'] == mes_pdf][[
        'Punto','MPS_mg_cm2','Ozono_ug_m3','NO2_ug_m3', f'Estado_{param}']].copy()
    df_tabla.columns = ['Punto','MPS (mg/cm²)','Ozono (µg/m³)','NO₂ (µg/m³)','Estado']
    st.dataframe(df_tabla, use_container_width=True, hide_index=True)

    # Botón descargar PDF
    if st.button("📄 Generar y descargar PDF"):
        df_mes_pdf = df_f[df_f['Mes'] == mes_pdf]
        if len(df_mes_pdf) > 0:
            pdf_buffer = generar_pdf(df_mes_pdf, mes_pdf, param_pdf)
            st.download_button(
                label="⬇️ Descargar PDF",
                data=pdf_buffer,
                file_name=f"Informe_MonitoreoAire_{mes_pdf}.pdf",
                mime="application/pdf"
            )
        else:
            st.warning("No hay datos para el mes seleccionado")
