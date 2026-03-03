# ============================================================
# ARCHIVO: app.py
# Dashboard Ambiental — GAD Municipalidad de Ambato
# Módulos: Monitoreo Pasivo Aire + Calidad del Agua
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
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib.units import cm
import warnings
warnings.filterwarnings('ignore')

# ── CONFIGURACIÓN ─────────────────────────────────────────────
st.set_page_config(
    page_title="Dashboard Ambiental — GAD Ambato",
    page_icon="🌿",
    layout="wide",
    initial_sidebar_state="expanded"
)

st.markdown("""
<style>
  .main-header {
    background: linear-gradient(135deg, #1a5276, #2980b9);
    padding: 20px 30px; border-radius: 12px;
    color: white; margin-bottom: 20px;
  }
</style>
""", unsafe_allow_html=True)

# ── CONSTANTES ────────────────────────────────────────────────
ORDEN_MESES = ["ENERO","FEBRERO","MARZO","ABRIL","MAYO","JUNIO",
               "JULIO","AGOSTO","SEPTIEMBRE","OCTUBRE","NOVIEMBRE","DICIEMBRE"]

LIMITES_AIRE = {
    'MPS_mg_cm2':  1.0,
    'Ozono_ug_m3': 100.0,
    'NO2_ug_m3':   40.0,
}
NOMBRES_AIRE = {
    'MPS_mg_cm2':  'Material Particulado Sedimentable (mg/cm²)',
    'Ozono_ug_m3': 'Ozono (µg/m³)',
    'NO2_ug_m3':   'Dióxido de Nitrógeno (µg/m³)',
}

LIMITES_AGUA = {
    'pH':             9.0,
    'DQO_mg_l':       40.0,
    'Cromo_mg_l':     0.032,
    'Cobre_mg_l':     0.005,
    'Plomo_mg_l':     0.001,
    'OD_pct':         80.0,
    'DBO5_mg_l':      20.0,
    'SST_mg_l':       550.0,
    'AceGrasas_mg_l': 0.3,
}
NOMBRES_AGUA = {
    'pH':             'Potencial de Hidrógeno (pH)',
    'DQO_mg_l':       'DQO (mg/l)',
    'Cromo_mg_l':     'Cromo Total (mg/l)',
    'Cobre_mg_l':     'Cobre (mg/l)',
    'Plomo_mg_l':     'Plomo (mg/l)',
    'OD_pct':         'Oxígeno Disuelto (%)',
    'DBO5_mg_l':      'DBO5 (mg/l)',
    'SST_mg_l':       'Sólidos Suspendidos Totales (mg/l)',
    'AceGrasas_mg_l': 'Aceites y Grasas (mg/l)',
}

# ── FUNCIONES COMPARTIDAS ─────────────────────────────────────
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

def utm_a_latlon(x, y):
    try:
        tr = Transformer.from_crs("EPSG:32717", "EPSG:4326", always_xy=True)
        lon, lat = tr.transform(x, y)
        if -5 < lat < 2 and -81 < lon < -75:
            return lat, lon
    except: pass
    return None, None

# ── FUNCIÓN LEER MONITOREO PASIVO AIRE ───────────────────────
def leer_excel_pasivo(archivo_bytes, nombre):
    df_raw = pd.read_excel(io.BytesIO(archivo_bytes),
                           sheet_name='MONITOREO PASIVO', header=None)
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

# ── FUNCIÓN LEER CALIDAD DEL AGUA ─────────────────────────────
def leer_excel_agua(archivo_bytes, nombre):
    df_raw = pd.read_excel(io.BytesIO(archivo_bytes),
                           sheet_name='DATOS FISICO QUIMICOS', header=None)

    titulo = str(df_raw.iloc[1, 0])
    mes = next((m for m in ORDEN_MESES if m in titulo.upper()), None)
    if not mes:
        mes = next((m for m in ORDEN_MESES if m in nombre.upper()), 'DESCONOCIDO')

    # Detectar columnas de estaciones
    fila_header = df_raw.iloc[2]
    estaciones = []
    for i, val in enumerate(fila_header):
        v = str(val).strip()
        if v not in ['nan','PARAMETROS','unidades','NaN',''] \
           and 'mites' not in v and 'Afectaci' not in v:
            estaciones.append((i, v))

    params_map = {
        'Potencial de Hidrógeno':      'pH',
        'DQO':                          'DQO_mg_l',
        'Cromo Total':                  'Cromo_mg_l',
        'Cobre':                        'Cobre_mg_l',
        'Plomo':                        'Plomo_mg_l',
        'Oxígeno Disuelto':             'OD_pct',
        'DBO5':                         'DBO5_mg_l',
        'Sólitos Suapendidos Totales':  'SST_mg_l',
        'Aceites y grasas':             'AceGrasas_mg_l',
    }

    filas = []
    for row_i in range(3, 12):
        if row_i >= len(df_raw): break
        row = df_raw.iloc[row_i]
        param_key = params_map.get(str(row[0]).strip())
        if not param_key: continue
        for col_i, estacion in estaciones:
            filas.append({
                'Mes':      mes,
                'Estacion': estacion,
                'Parametro':param_key,
                'Valor':    pd.to_numeric(row[col_i], errors='coerce'),
                'Archivo':  nombre
            })

    df_params = pd.DataFrame(filas)

    # ICA
    df_ica_raw = pd.read_excel(io.BytesIO(archivo_bytes), sheet_name='ICA', header=None)
    filas_ica = []
    for row_i in range(4, 20):
        if row_i >= len(df_ica_raw): break
        row = df_ica_raw.iloc[row_i]
        sitio   = str(row[0]).strip()
        codigo  = str(row[1]).strip()
        ica_val = pd.to_numeric(row[2], errors='coerce')
        interp  = str(row[3]).strip() if not pd.isna(row[3]) else ''
        if sitio in ['nan','NaN',''] or pd.isna(ica_val): continue
        filas_ica.append({
            'Mes':           mes,
            'Sitio':         sitio,
            'Codigo':        codigo,
            'ICA':           ica_val,
            'Interpretacion':interp,
            'Archivo':       nombre
        })

    df_ica = pd.DataFrame(filas_ica)
    return df_params, df_ica

def color_ica_estado(valor):
    if pd.isna(valor):  return '⚪ Sin dato'
    if valor >= 91:     return '🟢 Aceptable'
    if valor >= 66:     return '🟡 Indicios de contaminación'
    if valor >= 51:     return '🟠 Requiere atención inmediata'
    return '🔴 Ecosistema fuertemente contaminado'

def color_ica_hex(valor):
    if pd.isna(valor):  return '#95a5a6'
    if valor >= 91:     return '#27ae60'
    if valor >= 66:     return '#f1c40f'
    if valor >= 51:     return '#e67e22'
    return '#e74c3c'

# ── FUNCIÓN PDF ────────────────────────────────────────────────
def generar_pdf(df_data, mes, titulo_seccion, col_params, nombres_params):
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4,
                            leftMargin=2*cm, rightMargin=2*cm,
                            topMargin=2*cm, bottomMargin=2*cm)
    styles = getSampleStyleSheet()
    story  = []

    titulo_style = ParagraphStyle('titulo', parent=styles['Title'],
                                  textColor=colors.HexColor('#1a5276'), fontSize=16)
    story.append(Paragraph("GAD Municipalidad de Ambato", titulo_style))
    story.append(Paragraph(f"{titulo_seccion} — {mes}", styles['Heading2']))
    story.append(Spacer(1, 0.5*cm))

    header = ['Punto/Estación'] + [nombres_params.get(c, c)[:20] for c in col_params]
    datos  = [header]
    for _, row in df_data.iterrows():
        fila = [str(row.get('Punto', row.get('Estacion','')))]
        for c in col_params:
            v = row.get(c, '')
            fila.append(f"{v:.3f}" if isinstance(v, float) and not pd.isna(v) else str(v))
        datos.append(fila)

    col_w = [5*cm] + [2.5*cm]*len(col_params)
    tabla = Table(datos, colWidths=col_w)
    tabla.setStyle(TableStyle([
        ('BACKGROUND',    (0,0), (-1,0),  colors.HexColor('#1a5276')),
        ('TEXTCOLOR',     (0,0), (-1,0),  colors.white),
        ('FONTNAME',      (0,0), (-1,0),  'Helvetica-Bold'),
        ('FONTSIZE',      (0,0), (-1,-1), 8),
        ('ROWBACKGROUNDS',(0,1), (-1,-1), [colors.white, colors.HexColor('#f2f3f4')]),
        ('GRID',          (0,0), (-1,-1), 0.5, colors.HexColor('#cccccc')),
        ('ALIGN',         (1,0), (-1,-1), 'CENTER'),
    ]))
    story.append(tabla)
    doc.build(story)
    buffer.seek(0)
    return buffer

# ── FUNCIÓN ALERTAS EMAIL ─────────────────────────────────────
def enviar_alerta(destinatarios, mes, descripcion, df_excede, smtp_user, smtp_pass):
    msg = MIMEMultipart('alternative')
    msg['Subject'] = f"⚠️ Alerta Ambiental GAD Ambato — {mes}"
    msg['From']    = smtp_user
    msg['To']      = ", ".join(destinatarios)
    filas_html = "".join([
        f"<tr><td>{r.get('Punto', r.get('Sitio',''))}</td>"
        f"<td style='color:red'><b>{descripcion}</b></td></tr>"
        for _, r in df_excede.iterrows()
    ])
    html = f"""<html><body>
    <h2 style='color:#1a5276'>⚠️ Alerta Ambiental — GAD Ambato</h2>
    <p>Se detectaron valores que exceden límites normativos en <b>{mes}</b>.</p>
    <p><b>Módulo:</b> {descripcion}</p>
    <table border='1' cellpadding='6' style='border-collapse:collapse;'>
      <tr style='background:#1a5276;color:white'><th>Punto</th><th>Parámetro</th></tr>
      {filas_html}
    </table>
    <br><p style='color:gray;font-size:12px'>Sistema de Monitoreo Ambiental — GAD Ambato</p>
    </body></html>"""
    msg.attach(MIMEText(html, 'html'))
    with smtplib.SMTP_SSL('smtp.gmail.com', 465) as s:
        s.login(smtp_user, smtp_pass)
        s.sendmail(smtp_user, destinatarios, msg.as_string())

# ════════════════════════════════════════════════════════════
# INTERFAZ PRINCIPAL
# ════════════════════════════════════════════════════════════

st.markdown("""
<div class="main-header">
  <h2 style="margin:0">🌿 Dashboard Ambiental — GAD Municipalidad de Ambato</h2>
  <p style="margin:4px 0 0 0; opacity:0.85;">
    Sistema Integrado de Monitoreo Ambiental · Aire y Agua
  </p>
</div>
""", unsafe_allow_html=True)

# ── SIDEBAR ───────────────────────────────────────────────────
with st.sidebar:
    st.image("https://upload.wikimedia.org/wikipedia/commons/thumb/f/f4/Escudo_de_Ambato.svg/200px-Escudo_de_Ambato.svg.png", width=90)
    st.title("⚙️ Configuración")

    st.subheader("💨 Archivos Monitoreo Aire")
    archivos_aire = st.file_uploader(
        "Excel mensuales Monitoreo Pasivo",
        type=['xlsx'], accept_multiple_files=True, key='aire'
    )

    st.subheader("💧 Archivos Calidad del Agua")
    archivos_agua = st.file_uploader(
        "Excel mensuales Calidad del Agua",
        type=['xlsx'], accept_multiple_files=True, key='agua'
    )

    st.markdown("---")
    st.subheader("📧 Alertas por correo")
    smtp_user = st.text_input("Correo Gmail remitente", placeholder="tu@gmail.com")
    smtp_pass = st.text_input("Contraseña de aplicación", type="password")
    destinatarios_str = st.text_input("Destinatarios (separados por coma)")

# ── MÓDULOS PRINCIPALES ───────────────────────────────────────
modulo = st.radio("", ["💨 Monitoreo Pasivo — Calidad del Aire",
                        "💧 Calidad del Agua"],
                  horizontal=True, label_visibility="collapsed")

st.markdown("---")

# ════════════════════════════════════════════════════════════
# MÓDULO 1: CALIDAD DEL AIRE
# ════════════════════════════════════════════════════════════
if "Aire" in modulo:

    if not archivos_aire:
        st.info("👈 Sube los archivos Excel de Monitoreo Pasivo en el panel izquierdo.")
        st.stop()

    @st.cache_data
    def cargar_aire(info):
        lista = []
        for nombre, contenido in info:
            df_m = leer_excel_pasivo(contenido, nombre)
            if df_m is not None and len(df_m) > 0:
                lista.append(df_m)
        df = pd.concat(lista, ignore_index=True)
        df = df[df['Mes'] != 'DESCONOCIDO'].dropna(subset=['MPS_mg_cm2','Ozono_ug_m3','NO2_ug_m3'])
        df['Punto'] = df['Punto'].str.replace(r'\s+', ' ', regex=True).str.strip()
        df['Mes']   = pd.Categorical(df['Mes'], categories=ORDEN_MESES, ordered=True)
        df = df.sort_values(['Mes','Punto']).reset_index(drop=True)
        for p, lim in LIMITES_AIRE.items():
            df[f'Estado_{p}'] = df[p].apply(lambda v: semaforo(v, lim))
        df['lat'], df['lon'] = zip(*df.apply(
            lambda r: utm_a_latlon(r['X_UTM'], r['Y_UTM']), axis=1))
        return df

    info_aire = [(f.name, f.read()) for f in archivos_aire]
    df_aire = cargar_aire(info_aire)

    # Filtros
    c1, c2, c3 = st.columns([2,2,2])
    with c1:
        meses_a = st.multiselect("📅 Meses", ORDEN_MESES,
                                  default=df_aire['Mes'].unique().tolist(), key='ma')
    with c2:
        param_a = st.selectbox("🧪 Parámetro", list(LIMITES_AIRE.keys()),
                                format_func=lambda x: NOMBRES_AIRE[x], key='pa')
    with c3:
        puntos_a = st.multiselect("📍 Puntos", sorted(df_aire['Punto'].unique()),
                                   default=sorted(df_aire['Punto'].unique()), key='pua')

    df_af = df_aire[df_aire['Mes'].isin(meses_a) & df_aire['Punto'].isin(puntos_a)]
    lim_a = LIMITES_AIRE[param_a]

    # KPIs
    k1,k2,k3,k4,k5 = st.columns(5)
    pct_a = (df_af[param_a] > lim_a).mean() * 100
    k1.metric("Promedio",         f"{df_af[param_a].mean():.2f}")
    k2.metric("Máximo",           f"{df_af[param_a].max():.2f}")
    k3.metric("Mínimo",           f"{df_af[param_a].min():.2f}")
    k4.metric("Exceden límite",   f"{(df_af[param_a]>lim_a).sum()} registros",
               delta=f"{pct_a:.1f}%", delta_color="inverse")
    k5.metric("Límite normativo", f"{lim_a}")

    st.markdown("---")

    tab1,tab2,tab3,tab4,tab5,tab6 = st.tabs([
        "📈 Tendencia","🗺️ Mapa","🔥 Heatmap","📦 Boxplot","🏆 Ranking","📋 Tabla & PDF"])

    with tab1:
        df_t = df_af.groupby('Mes', observed=True)[param_a].agg(['mean','max','min']).reset_index()
        fig = go.Figure()
        fig.add_trace(go.Scatter(x=df_t['Mes'], y=df_t['max'], fill=None,
                                  mode='lines', line_color='rgba(231,76,60,0.3)', name='Máximo'))
        fig.add_trace(go.Scatter(x=df_t['Mes'], y=df_t['min'], fill='tonexty',
                                  mode='lines', line_color='rgba(39,174,96,0.3)',
                                  fillcolor='rgba(130,202,157,0.2)', name='Mínimo'))
        fig.add_trace(go.Scatter(x=df_t['Mes'], y=df_t['mean'], mode='lines+markers',
                                  name='Promedio', line=dict(color='#2980b9', width=3),
                                  marker=dict(size=9)))
        fig.add_hline(y=lim_a, line_dash='dash', line_color='red',
                      annotation_text=f'Límite: {lim_a}')
        fig.update_layout(title=f'Tendencia mensual — {NOMBRES_AIRE[param_a]}',
                          height=420, hovermode='x unified', plot_bgcolor='#f9f9f9')
        st.plotly_chart(fig, use_container_width=True)

    with tab2:
        mes_mapa = st.selectbox("Mes", meses_a, index=len(meses_a)-1, key='mma')
        df_mapa  = df_af[df_af['Mes'] == mes_mapa].dropna(subset=['lat','lon'])
        mapa = folium.Map(location=[-1.2490,-78.6163], zoom_start=13, tiles='CartoDB positron')
        for _, row in df_mapa.iterrows():
            val = row[param_a]
            folium.Marker(
                [row['lat'], row['lon']],
                popup=folium.Popup(
                    f"<b>{row['Punto']}</b><br>"
                    f"{NOMBRES_AIRE[param_a]}: <b>{val:.2f}</b><br>"
                    f"Ozono: {row['Ozono_ug_m3']:.2f} µg/m³<br>"
                    f"NO₂: {row['NO2_ug_m3']:.2f} µg/m³<br>"
                    f"Estado: {row[f'Estado_{param_a}']}", max_width=220),
                tooltip=f"{row['Punto']} | {val:.2f}",
                icon=folium.Icon(color=color_folium(val, lim_a), icon='cloud', prefix='fa')
            ).add_to(mapa)
        st_folium(mapa, width=None, height=480)
        df_excede_a = df_mapa[df_mapa[param_a] > lim_a]
        if len(df_excede_a) > 0:
            st.warning(f"⚠️ {len(df_excede_a)} punto(s) exceden el límite en {mes_mapa}")
            if smtp_user and smtp_pass and destinatarios_str:
                if st.button("📧 Enviar alerta correo — Aire"):
                    try:
                        enviar_alerta([d.strip() for d in destinatarios_str.split(',')],
                                      mes_mapa, NOMBRES_AIRE[param_a], df_excede_a,
                                      smtp_user, smtp_pass)
                        st.success("✅ Alerta enviada")
                    except Exception as e:
                        st.error(f"Error: {e}")

    with tab3:
        pivot = df_af.pivot_table(index='Punto', columns='Mes', values=param_a,
                                   aggfunc='mean', observed=True)
        pivot.index = [p[:28]+'…' if len(p)>28 else p for p in pivot.index]
        fig = px.imshow(pivot, color_continuous_scale=['#2ecc71','#f1c40f','#e74c3c'],
                        title=f'Heatmap — {NOMBRES_AIRE[param_a]}',
                        labels=dict(color=NOMBRES_AIRE[param_a]),
                        aspect='auto', zmin=0, zmax=lim_a*2)
        fig.update_layout(height=580)
        st.plotly_chart(fig, use_container_width=True)

    with tab4:
        df_bp = df_af.copy()
        df_bp['PuntoCorto'] = df_bp['Punto'].str[:28]
        fig = px.box(df_bp, x='PuntoCorto', y=param_a, color='PuntoCorto',
                     title=f'Distribución por punto — {NOMBRES_AIRE[param_a]}',
                     color_discrete_sequence=px.colors.qualitative.Safe)
        fig.add_hline(y=lim_a, line_dash='dash', line_color='red',
                      annotation_text=f'Límite: {lim_a}')
        fig.update_layout(height=500, showlegend=False, xaxis_tickangle=-40)
        st.plotly_chart(fig, use_container_width=True)

    with tab5:
        df_r = df_af.groupby('Punto', observed=True)[param_a].mean().reset_index()
        df_r = df_r.sort_values(param_a, ascending=True)
        df_r['Color'] = df_r[param_a].apply(
            lambda v: '#e74c3c' if v > lim_a else ('#f39c12' if v > lim_a*0.75 else '#27ae60'))
        df_r['PuntoCorto'] = df_r['Punto'].str[:30]
        fig = go.Figure(go.Bar(
            x=df_r[param_a], y=df_r['PuntoCorto'], orientation='h',
            marker_color=df_r['Color'], text=df_r[param_a].round(2), textposition='outside'))
        fig.add_vline(x=lim_a, line_dash='dash', line_color='red',
                      annotation_text=f'Límite: {lim_a}')
        fig.update_layout(title=f'Ranking — {NOMBRES_AIRE[param_a]}',
                          height=580, plot_bgcolor='#f9f9f9', margin=dict(l=220))
        st.plotly_chart(fig, use_container_width=True)

    with tab6:
        ca, cb = st.columns(2)
        with ca: mes_pdf_a = st.selectbox("Mes", meses_a, key='mpda')
        with cb: param_pdf_a = st.selectbox("Parámetro", list(LIMITES_AIRE.keys()),
                                              format_func=lambda x: NOMBRES_AIRE[x], key='ppda')
        df_tabla_a = df_af[df_af['Mes']==mes_pdf_a][
            ['Punto','MPS_mg_cm2','Ozono_ug_m3','NO2_ug_m3',f'Estado_{param_a}']].copy()
        df_tabla_a.columns = ['Punto','MPS (mg/cm²)','Ozono (µg/m³)','NO₂ (µg/m³)','Estado']
        st.dataframe(df_tabla_a, use_container_width=True, hide_index=True)
        if st.button("📄 Generar PDF — Aire"):
            df_pdf = df_af[df_af['Mes']==mes_pdf_a]
            if len(df_pdf) > 0:
                buf = generar_pdf(df_pdf, mes_pdf_a, "Monitoreo Pasivo Calidad del Aire",
                                  ['MPS_mg_cm2','Ozono_ug_m3','NO2_ug_m3'], NOMBRES_AIRE)
                st.download_button("⬇️ Descargar PDF", data=buf,
                                   file_name=f"Informe_Aire_{mes_pdf_a}.pdf",
                                   mime="application/pdf")

# ════════════════════════════════════════════════════════════
# MÓDULO 2: CALIDAD DEL AGUA
# ════════════════════════════════════════════════════════════
elif "Agua" in modulo:

    if not archivos_agua:
        st.info("👈 Sube los archivos Excel de Calidad del Agua en el panel izquierdo.")
        st.stop()

    @st.cache_data
    def cargar_agua(info):
        params_list, ica_list = [], []
        for nombre, contenido in info:
            try:
                df_p, df_i = leer_excel_agua(contenido, nombre)
                if df_p is not None and len(df_p) > 0:
                    params_list.append(df_p)
                if df_i is not None and len(df_i) > 0:
                    ica_list.append(df_i)
            except Exception as e:
                st.warning(f"Error leyendo {nombre}: {e}")
        df_params = pd.concat(params_list, ignore_index=True) if params_list else pd.DataFrame()
        df_ica    = pd.concat(ica_list,    ignore_index=True) if ica_list    else pd.DataFrame()
        for df in [df_params, df_ica]:
            if 'Mes' in df.columns:
                df['Mes'] = pd.Categorical(df['Mes'], categories=ORDEN_MESES, ordered=True)
        return df_params, df_ica

    info_agua = [(f.name, f.read()) for f in archivos_agua]
    df_params, df_ica = cargar_agua(info_agua)

    # Filtros
    meses_agua_disp = [m for m in ORDEN_MESES
                       if m in df_params['Mes'].unique().tolist()]
    c1, c2 = st.columns([2, 2])
    with c1:
        meses_w = st.multiselect("📅 Meses", meses_agua_disp,
                                  default=meses_agua_disp, key='mw')
    with c2:
        param_w = st.selectbox("🧪 Parámetro", list(LIMITES_AGUA.keys()),
                                format_func=lambda x: NOMBRES_AGUA[x], key='pw')

    df_pf = df_params[(df_params['Mes'].isin(meses_w)) &
                      (df_params['Parametro'] == param_w)].copy()
    df_if = df_ica[df_ica['Mes'].isin(meses_w)].copy() if len(df_ica) > 0 else pd.DataFrame()

    lim_w = LIMITES_AGUA[param_w]

    # KPIs
    if len(df_pf) > 0:
        k1,k2,k3,k4 = st.columns(4)
        pct_w = (df_pf['Valor'] > lim_w).mean() * 100
        k1.metric("Promedio",         f"{df_pf['Valor'].mean():.3f}")
        k2.metric("Máximo",           f"{df_pf['Valor'].max():.3f}")
        k3.metric("Mínimo",           f"{df_pf['Valor'].min():.3f}")
        k4.metric("Exceden límite",   f"{(df_pf['Valor']>lim_w).sum()} registros",
                   delta=f"{pct_w:.1f}%", delta_color="inverse")

    st.markdown("---")

    tab_w1,tab_w2,tab_w3,tab_w4,tab_w5 = st.tabs([
        "📈 Tendencia", "🌊 ICA por punto", "🔥 Heatmap",
        "🏆 Ranking estaciones", "📋 Tabla & PDF"])

    with tab_w1:
        if len(df_pf) > 0:
            df_tw = df_pf.groupby('Mes', observed=True)['Valor'].agg(
                ['mean','max','min']).reset_index()
            fig = go.Figure()
            fig.add_trace(go.Scatter(x=df_tw['Mes'], y=df_tw['max'], fill=None,
                                      mode='lines', line_color='rgba(231,76,60,0.3)', name='Máximo'))
            fig.add_trace(go.Scatter(x=df_tw['Mes'], y=df_tw['min'], fill='tonexty',
                                      mode='lines', fillcolor='rgba(41,128,185,0.15)',
                                      line_color='rgba(41,128,185,0.3)', name='Mínimo'))
            fig.add_trace(go.Scatter(x=df_tw['Mes'], y=df_tw['mean'], mode='lines+markers',
                                      name='Promedio', line=dict(color='#2980b9', width=3),
                                      marker=dict(size=9)))
            fig.add_hline(y=lim_w, line_dash='dash', line_color='red',
                          annotation_text=f'Límite: {lim_w}')
            fig.update_layout(title=f'Tendencia — {NOMBRES_AGUA[param_w]}',
                              height=420, hovermode='x unified', plot_bgcolor='#f9f9f9')
            st.plotly_chart(fig, use_container_width=True)

    with tab_w2:
        if len(df_if) > 0:
            df_if['Estado'] = df_if['ICA'].apply(color_ica_estado)
            df_if['Color']  = df_if['ICA'].apply(color_ica_hex)

            mes_ica = st.selectbox("Mes", meses_w, index=len(meses_w)-1, key='mica')
            df_ica_mes = df_if[df_if['Mes'] == mes_ica]

            fig = go.Figure(go.Bar(
                x=df_ica_mes['ICA'],
                y=df_ica_mes['Sitio'].str[:35],
                orientation='h',
                marker_color=df_ica_mes['Color'],
                text=df_ica_mes['ICA'].round(1),
                textposition='outside',
                customdata=df_ica_mes[['Codigo','Interpretacion']],
                hovertemplate='<b>%{y}</b><br>ICA: %{x}<br>%{customdata[1]}<extra></extra>'
            ))
            fig.add_vline(x=91, line_dash='dot', line_color='green',
                          annotation_text='Aceptable (91)')
            fig.add_vline(x=66, line_dash='dot', line_color='orange',
                          annotation_text='Indicios (66)')
            fig.add_vline(x=51, line_dash='dot', line_color='red',
                          annotation_text='Crítico (51)')
            fig.update_layout(
                title=f'🌊 Índice de Calidad del Agua (ICA) — {mes_ica}',
                height=500, plot_bgcolor='#f9f9f9',
                xaxis=dict(range=[0,100], title='ICA'),
                margin=dict(l=250)
            )
            st.plotly_chart(fig, use_container_width=True)

            # Tabla ICA con semáforo
            df_show = df_ica_mes[['Sitio','Codigo','ICA','Estado','Interpretacion']].copy()
            df_show.columns = ['Sitio','Código','ICA','Estado','Interpretación']
            st.dataframe(df_show, use_container_width=True, hide_index=True)

            # Alerta
            df_criticos = df_ica_mes[df_ica_mes['ICA'] < 51]
            if len(df_criticos) > 0:
                st.error(f"🔴 {len(df_criticos)} punto(s) con ecosistema fuertemente contaminado")
                if smtp_user and smtp_pass and destinatarios_str:
                    if st.button("📧 Enviar alerta correo — Agua"):
                        try:
                            df_alerta = df_criticos.rename(columns={'Sitio':'Punto'})
                            enviar_alerta([d.strip() for d in destinatarios_str.split(',')],
                                          mes_ica, "ICA Calidad del Agua — Ecosistema crítico",
                                          df_alerta, smtp_user, smtp_pass)
                            st.success("✅ Alerta enviada")
                        except Exception as e:
                            st.error(f"Error: {e}")

    with tab_w3:
        if len(df_pf) > 0:
            pivot_w = df_pf.pivot_table(index='Estacion', columns='Mes',
                                         values='Valor', aggfunc='mean', observed=True)
            fig = px.imshow(pivot_w,
                            color_continuous_scale=['#2ecc71','#f1c40f','#e74c3c'],
                            title=f'Heatmap — {NOMBRES_AGUA[param_w]}',
                            labels=dict(color=NOMBRES_AGUA[param_w]),
                            aspect='auto', zmin=0, zmax=lim_w*2)
            fig.update_layout(height=480)
            st.plotly_chart(fig, use_container_width=True)

    with tab_w4:
        if len(df_pf) > 0:
            df_rw = df_pf.groupby('Estacion', observed=True)['Valor'].mean().reset_index()
            df_rw = df_rw.sort_values('Valor', ascending=True)
            df_rw['Color'] = df_rw['Valor'].apply(
                lambda v: '#e74c3c' if v > lim_w else
                          ('#f39c12' if v > lim_w*0.75 else '#27ae60'))
            fig = go.Figure(go.Bar(
                x=df_rw['Valor'], y=df_rw['Estacion'], orientation='h',
                marker_color=df_rw['Color'],
                text=df_rw['Valor'].round(3), textposition='outside'))
            fig.add_vline(x=lim_w, line_dash='dash', line_color='red',
                          annotation_text=f'Límite: {lim_w}')
            fig.update_layout(title=f'Ranking de estaciones — {NOMBRES_AGUA[param_w]}',
                              height=500, plot_bgcolor='#f9f9f9', margin=dict(l=220))
            st.plotly_chart(fig, use_container_width=True)

    with tab_w5:
        if len(df_pf) > 0:
            mes_pdf_w = st.selectbox("Mes para PDF", meses_w, key='mpdw')
            df_tabla_w = df_pf[df_pf['Mes']==mes_pdf_w].pivot_table(
                index='Estacion', columns='Parametro', values='Valor',
                aggfunc='mean', observed=True).reset_index()
            df_tabla_w.columns.name = None
            st.dataframe(df_tabla_w, use_container_width=True, hide_index=True)
            if st.button("📄 Generar PDF — Agua"):
                buf = generar_pdf(
                    df_tabla_w.rename(columns={'Estacion':'Punto'}),
                    mes_pdf_w, "Calidad del Agua — Parámetros Físico-Químicos",
                    [c for c in df_tabla_w.columns if c != 'Estacion'],
                    NOMBRES_AGUA
                )
                st.download_button("⬇️ Descargar PDF", data=buf,
                                   file_name=f"Informe_Agua_{mes_pdf_w}.pdf",
                                   mime="application/pdf")
