# ============================================================
# ARCHIVO: app.py
# Dashboard Ambiental — GAD Municipalidad de Ambato
# Módulos: Resumen General | Monitoreo Pasivo | Agua | Partículas
# ============================================================

import streamlit as st
import pandas as pd
import numpy as np
import plotly.express as px
import plotly.graph_objects as go
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

# ── CONFIG ─────────────────────────────────────────────────────
st.set_page_config(
    page_title="Dashboard Ambiental — GAD Ambato",
    page_icon="🌿", layout="wide",
    initial_sidebar_state="expanded"
)
st.markdown("""
<style>
.main-header {
  background: linear-gradient(135deg,#1a5276,#2980b9);
  padding:18px 28px; border-radius:12px; color:white; margin-bottom:16px;
}
.semaforo-box {
  border-radius:10px; padding:12px; text-align:center;
  color:white; font-weight:bold;
}
</style>
""", unsafe_allow_html=True)

# ── CONSTANTES ──────────────────────────────────────────────────
ORDEN_MESES = ["ENERO","FEBRERO","MARZO","ABRIL","MAYO","JUNIO",
               "JULIO","AGOSTO","SEPTIEMBRE","OCTUBRE","NOVIEMBRE","DICIEMBRE"]

LIM_PASIVO = {'MPS_mg_cm2':1.0, 'Ozono_ug_m3':100.0, 'NO2_ug_m3':40.0}
NOM_PASIVO = {
    'MPS_mg_cm2':'MPS (mg/cm²)',
    'Ozono_ug_m3':'Ozono (µg/m³)',
    'NO2_ug_m3':'NO₂ (µg/m³)',
}
LIM_AGUA = {
    'pH':9.0,'DQO_mg_l':40.0,'Cromo_mg_l':0.032,
    'Cobre_mg_l':0.005,'Plomo_mg_l':0.001,'OD_pct':80.0,
    'DBO5_mg_l':20.0,'SST_mg_l':550.0,'AceGrasas_mg_l':0.3,
}
NOM_AGUA = {
    'pH':'pH','DQO_mg_l':'DQO (mg/l)','Cromo_mg_l':'Cromo (mg/l)',
    'Cobre_mg_l':'Cobre (mg/l)','Plomo_mg_l':'Plomo (mg/l)',
    'OD_pct':'Oxígeno Disuelto (%)','DBO5_mg_l':'DBO5 (mg/l)',
    'SST_mg_l':'SST (mg/l)','AceGrasas_mg_l':'Aceites/Grasas (mg/l)',
}
LIM_PART = {
    'CO_ug_m3':10000.0,'NO2_ug_m3':200.0,'O3_ug_m3':100.0,
    'PM10_ug_m3':100.0,'PM25_ug_m3':50.0,'SO2_ug_m3':125.0,
}
NOM_PART = {
    'CO_ug_m3':'CO (µg/m³)','NO2_ug_m3':'NO₂ (µg/m³)',
    'O3_ug_m3':'Ozono (µg/m³)','PM10_ug_m3':'PM10 (µg/m³)',
    'PM25_ug_m3':'PM2.5 (µg/m³)','SO2_ug_m3':'SO₂ (µg/m³)',
}

# ── UTILIDADES ──────────────────────────────────────────────────
def semaforo(v, lim):
    if   v <= lim*0.75: return '🟢 Bueno'
    elif v <= lim:       return '🟡 Moderado'
    else:                return '🔴 Excede'

def color_hex(v, lim):
    if pd.isna(v):        return '#95a5a6'
    if v <= lim*0.75:     return '#27ae60'
    if v <= lim:          return '#f39c12'
    return '#e74c3c'

def color_folium_fn(v, lim):
    if pd.isna(v):        return 'gray'
    if v <= lim*0.75:     return 'green'
    if v <= lim:          return 'orange'
    return 'red'

def mes_from(texto, nombre):
    t = str(texto).upper()
    for m in ORDEN_MESES:
        if m in t: return m
    for m in ORDEN_MESES:
        if m in nombre.upper(): return m
    return 'DESCONOCIDO'

def utm_latlon(x, y):
    try:
        tr = Transformer.from_crs("EPSG:32717","EPSG:4326",always_xy=True)
        lon, lat = tr.transform(x, y)
        if -5<lat<2 and -81<lon<-75: return lat, lon
    except: pass
    return None, None

def ica_aire_estado(v):
    if pd.isna(v): return '⚪ Sin dato'
    if v<=50:  return '🟢 Deseable'
    if v<=100: return '🟡 Aceptable'
    if v<=150: return '🟠 Precaución'
    if v<=200: return '🔴 Alerta'
    if v<=300: return '🔴 Alarma'
    return '🔴 Emergencia'

def ica_aire_color(v):
    if pd.isna(v): return '#95a5a6'
    if v<=50:  return '#27ae60'
    if v<=100: return '#f1c40f'
    if v<=150: return '#e67e22'
    if v<=200: return '#e74c3c'
    return '#8e44ad'

# ── LECTORES ────────────────────────────────────────────────────
def leer_pasivo(b, nombre):
    df = pd.read_excel(io.BytesIO(b), sheet_name='MONITOREO PASIVO', header=None)
    mes = mes_from(df.iloc[3,0], nombre)
    fi = None
    for i,row in df.iterrows():
        if str(row[0]).strip().lower()=='código': fi=i+2; break
    if fi is None: return None
    rows=[]
    for i in range(fi, len(df)):
        r=df.iloc[i]
        if pd.isna(r[0]) and pd.isna(r[2]): break
        rows.append({
            'Mes':mes,'Codigo':str(r[0]).strip(),'Punto':str(r[1]).strip(),
            'X_UTM':pd.to_numeric(r[2],errors='coerce'),
            'Y_UTM':pd.to_numeric(r[3],errors='coerce'),
            'MPS_mg_cm2':pd.to_numeric(r[4],errors='coerce'),
            'Ozono_ug_m3':pd.to_numeric(r[5],errors='coerce'),
            'NO2_ug_m3':pd.to_numeric(r[6],errors='coerce'),
            'Archivo':nombre
        })
    out=pd.DataFrame(rows).dropna(subset=['X_UTM'])
    out['Mes']=out.apply(lambda r: mes_from(r['Mes'],r['Archivo']),axis=1)
    return out

def leer_agua(b, nombre):
    df=pd.read_excel(io.BytesIO(b), sheet_name='DATOS FISICO QUIMICOS', header=None)
    mes=mes_from(df.iloc[1,0], nombre)
    estaciones=[(i,str(v).strip()) for i,v in enumerate(df.iloc[2])
                if str(v).strip() not in ['nan','PARAMETROS','unidades','NaN','']
                and 'mites' not in str(v) and 'Afectaci' not in str(v)]
    pm={'Potencial de Hidrógeno':'pH','DQO':'DQO_mg_l','Cromo Total':'Cromo_mg_l',
        'Cobre':'Cobre_mg_l','Plomo':'Plomo_mg_l','Oxígeno Disuelto':'OD_pct',
        'DBO5':'DBO5_mg_l','Sólitos Suapendidos Totales':'SST_mg_l',
        'Aceites y grasas':'AceGrasas_mg_l'}
    rows=[]
    for ri in range(3,12):
        if ri>=len(df): break
        r=df.iloc[ri]; pk=pm.get(str(r[0]).strip())
        if not pk: continue
        for ci,est in estaciones:
            rows.append({'Mes':mes,'Estacion':est,'Parametro':pk,
                         'Valor':pd.to_numeric(r[ci],errors='coerce'),'Archivo':nombre})
    df_p=pd.DataFrame(rows)
    df_ica_raw=pd.read_excel(io.BytesIO(b), sheet_name='ICA', header=None)
    ica_rows=[]
    for ri in range(4,20):
        if ri>=len(df_ica_raw): break
        r=df_ica_raw.iloc[ri]
        s,c=str(r[0]).strip(),str(r[1]).strip()
        iv=pd.to_numeric(r[2],errors='coerce')
        interp=str(r[3]).strip() if not pd.isna(r[3]) else ''
        if s in ['nan','NaN',''] or pd.isna(iv): continue
        ica_rows.append({'Mes':mes,'Sitio':s,'Codigo':c,'ICA':iv,'Interpretacion':interp,'Archivo':nombre})
    return df_p, pd.DataFrame(ica_rows)

def leer_particulas(b, nombre):
    df=pd.read_excel(io.BytesIO(b), sheet_name='RESULTADOS ', header=None)
    mes='DESCONOCIDO'
    fila_datos=None
    for i in range(len(df)):
        cell=str(df.iloc[i,0])
        for m in ORDEN_MESES:
            if m in cell.upper(): mes=m; fila_datos=i; break
        if fila_datos is not None: break
    if fila_datos is None: return None, pd.DataFrame()
    r=df.iloc[fila_datos]
    resumen=pd.Series({
        'Mes':mes,
        'CO_ug_m3':   pd.to_numeric(r[1],errors='coerce'),
        'NO2_ug_m3':  pd.to_numeric(r[2],errors='coerce'),
        'O3_ug_m3':   pd.to_numeric(r[3],errors='coerce'),
        'PM10_ug_m3': pd.to_numeric(r[4],errors='coerce'),
        'PM25_ug_m3': pd.to_numeric(r[5],errors='coerce'),
        'SO2_ug_m3':  pd.to_numeric(r[6],errors='coerce'),
        'Lluvia_mm':  pd.to_numeric(r[7],errors='coerce'),
        'Temp_C':     pd.to_numeric(r[8],errors='coerce'),
        'ICA_max':    pd.to_numeric(r[9],errors='coerce'),
        'Archivo':nombre
    })
    try:
        df_ica=pd.read_excel(io.BytesIO(b), sheet_name='ICA', header=None)
        ica_rows=[]
        for i in range(12, len(df_ica)-1):
            ri=df_ica.iloc[i]
            fecha=pd.to_datetime(ri[0],errors='coerce')
            if pd.isna(fecha): continue
            vals=pd.to_numeric(df_ica.iloc[i,1:40],errors='coerce').dropna()
            ica_rows.append({'Fecha':fecha,'ICA':vals.mean() if len(vals)>0 else np.nan,'Mes':mes})
        df_ica_out=pd.DataFrame(ica_rows)
    except:
        df_ica_out=pd.DataFrame()
    return resumen, df_ica_out

# ── PDF ─────────────────────────────────────────────────────────
def generar_pdf(df, mes, titulo, cols, nombres):
    buf=io.BytesIO()
    doc=SimpleDocTemplate(buf,pagesize=A4,
                          leftMargin=2*cm,rightMargin=2*cm,
                          topMargin=2*cm,bottomMargin=2*cm)
    styles=getSampleStyleSheet()
    ts=ParagraphStyle('t',parent=styles['Title'],
                      textColor=colors.HexColor('#1a5276'),fontSize=14)
    story=[Paragraph("GAD Municipalidad de Ambato",ts),
           Paragraph(f"{titulo} — {mes}",styles['Heading2']),
           Spacer(1,0.4*cm)]
    col_p='Punto' if 'Punto' in df.columns else ('Estacion' if 'Estacion' in df.columns else df.columns[0])
    header=[col_p]+[nombres.get(c,c)[:16] for c in cols]
    data=[header]
    for _,row in df.iterrows():
        fila=[str(row.get(col_p,''))]
        for c in cols:
            v=row.get(c,'')
            fila.append(f"{v:.3f}" if isinstance(v,float) and not pd.isna(v) else str(v))
        data.append(fila)
    cw=[5*cm]+[2.2*cm]*len(cols)
    t=Table(data,colWidths=cw)
    t.setStyle(TableStyle([
        ('BACKGROUND',(0,0),(-1,0),colors.HexColor('#1a5276')),
        ('TEXTCOLOR',(0,0),(-1,0),colors.white),
        ('FONTNAME',(0,0),(-1,0),'Helvetica-Bold'),
        ('FONTSIZE',(0,0),(-1,-1),8),
        ('ROWBACKGROUNDS',(0,1),(-1,-1),[colors.white,colors.HexColor('#f2f3f4')]),
        ('GRID',(0,0),(-1,-1),0.5,colors.HexColor('#cccccc')),
        ('ALIGN',(1,0),(-1,-1),'CENTER'),
    ]))
    story.append(t)
    doc.build(story)
    buf.seek(0)
    return buf

# ── EMAIL ───────────────────────────────────────────────────────
def enviar_email(dest, asunto, html, user, pwd):
    msg=MIMEMultipart('alternative')
    msg['Subject']=asunto; msg['From']=user; msg['To']=", ".join(dest)
    msg.attach(MIMEText(html,'html'))
    with smtplib.SMTP_SSL('smtp.gmail.com',465) as s:
        s.login(user,pwd); s.sendmail(user,dest,msg.as_string())

# ════════════════════════════════════════════════════════════════
# HEADER
# ════════════════════════════════════════════════════════════════
st.markdown("""
<div class="main-header">
  <h2 style="margin:0">🌿 Dashboard Ambiental — GAD Municipalidad de Ambato</h2>
  <p style="margin:4px 0 0; opacity:.85">
    Sistema Integrado · Monitoreo Pasivo Aire · Calidad del Agua · Partículas y Gases
  </p>
</div>
""", unsafe_allow_html=True)

# ── SIDEBAR ─────────────────────────────────────────────────────
with st.sidebar:
    try:
        st.image("https://upload.wikimedia.org/wikipedia/commons/thumb/f/f4/Escudo_de_Ambato.svg/200px-Escudo_de_Ambato.svg.png",width=90)
    except: pass
    st.title("⚙️ Configuración")

    st.subheader("💨 Monitoreo Pasivo Aire")
    arch_pas=st.file_uploader("Excel mensuales Pasivo",type=['xlsx'],accept_multiple_files=True,key='kp')

    st.subheader("💧 Calidad del Agua")
    arch_agua=st.file_uploader("Excel mensuales Agua",type=['xlsx'],accept_multiple_files=True,key='ka')

    st.subheader("🏭 Partículas y Gases")
    arch_part=st.file_uploader("Excel mensuales Partículas",type=['xlsx'],accept_multiple_files=True,key='kg')

    st.markdown("---")
    st.subheader("📧 Alertas por correo")
    smtp_user=st.text_input("Gmail remitente",placeholder="tu@gmail.com")
    smtp_pass=st.text_input("Contraseña de app",type="password")
    dest_str =st.text_input("Destinatarios (coma)")

# ── MÓDULOS ──────────────────────────────────────────────────────
modulo=st.radio("",["📊 Resumen General","💨 Monitoreo Pasivo — Aire",
                     "💧 Calidad del Agua","🏭 Partículas y Gases"],
                horizontal=True,label_visibility="collapsed")
st.markdown("---")

# ════════════════════════════════════════════════════════════════
# MÓDULO 0 — RESUMEN GENERAL
# ════════════════════════════════════════════════════════════════
if "Resumen" in modulo:
    st.subheader("📊 Resumen Integrado de Cumplimiento Normativo")

    filas=[]

    # Pasivo
    for f in (arch_pas or []):
        try:
            df_m=leer_pasivo(f.read(),f.name)
            if df_m is None: continue
            for param,lim in LIM_PASIVO.items():
                vals=df_m[param].dropna()
                pct_exc=(vals>lim).mean()*100
                prom=vals.mean()
                filas.append({'Módulo':'💨 Monitoreo Pasivo','Mes':df_m['Mes'].iloc[0],
                              'Parámetro':NOM_PASIVO[param],'Promedio':round(prom,3),
                              'Límite':lim,'% Excede':round(pct_exc,1),
                              'Estado':semaforo(prom,lim)})
        except: pass

    # Agua
    for f in (arch_agua or []):
        try:
            dp,_=leer_agua(f.read(),f.name)
            if len(dp)==0: continue
            for param,lim in LIM_AGUA.items():
                sub=dp[dp['Parametro']==param]
                if len(sub)==0: continue
                vals=sub['Valor'].dropna()
                prom=vals.mean(); pct_exc=(vals>lim).mean()*100
                filas.append({'Módulo':'💧 Calidad del Agua','Mes':sub['Mes'].iloc[0],
                              'Parámetro':NOM_AGUA[param],'Promedio':round(prom,4),
                              'Límite':lim,'% Excede':round(pct_exc,1),
                              'Estado':semaforo(prom,lim)})
        except: pass

    # Partículas
    for f in (arch_part or []):
        try:
            res,_=leer_particulas(f.read(),f.name)
            if res is None: continue
            for param,lim in LIM_PART.items():
                val=res.get(param,np.nan)
                if pd.isna(val): continue
                fv=float(val)
                filas.append({'Módulo':'🏭 Partículas/Gases','Mes':res['Mes'],
                              'Parámetro':NOM_PART[param],'Promedio':round(fv,3),
                              'Límite':lim,'% Excede':100.0 if fv>lim else 0.0,
                              'Estado':semaforo(fv,lim)})
        except: pass

    if not filas:
        st.info("👈 Sube archivos en el panel lateral para ver el resumen integrado.")
        st.stop()

    df_res=pd.DataFrame(filas)
    df_res['Mes']=pd.Categorical(df_res['Mes'],categories=ORDEN_MESES,ordered=True)

    # ── KPIs
    total=len(df_res)
    buenos=(df_res['Estado']=='🟢 Bueno').sum()
    mods  =(df_res['Estado']=='🟡 Moderado').sum()
    malos =(df_res['Estado']=='🔴 Excede').sum()

    c1,c2,c3,c4=st.columns(4)
    c1.metric("Total indicadores",total)
    c2.metric("🟢 Dentro del límite",buenos,f"{buenos/total*100:.0f}%")
    c3.metric("🟡 Moderados",mods,f"{mods/total*100:.0f}%")
    c4.metric("🔴 Exceden límite",malos,f"{malos/total*100:.0f}%",delta_color="inverse")
    st.markdown("---")

    tr1,tr2,tr3,tr4=st.tabs([
        "🚨 Incumplimiento %","📊 Por módulo","📅 Evolución mensual","📋 Tabla completa"])

    with tr1:
        df_exc=df_res[df_res['% Excede']>0].copy()
        df_exc=df_exc.sort_values('% Excede',ascending=True)
        if len(df_exc)==0:
            st.success("✅ Ningún parámetro excede los límites normativos.")
        else:
            df_exc['Etiqueta']=df_exc['Módulo'].str[-20:]+' — '+df_exc['Parámetro']
            df_exc['Color']=df_exc['% Excede'].apply(
                lambda v:'#e74c3c' if v>50 else '#f39c12')
            fig=go.Figure(go.Bar(
                x=df_exc['% Excede'],y=df_exc['Etiqueta'],orientation='h',
                marker_color=df_exc['Color'],
                text=df_exc.apply(lambda r:f"{r['% Excede']:.0f}%  (prom: {r['Promedio']}  lím: {r['Límite']})",axis=1),
                textposition='outside'
            ))
            fig.add_vline(x=100,line_dash='dash',line_color='black',
                          annotation_text='100%')
            fig.update_layout(
                title='Parámetros con registros que exceden el límite normativo',
                height=max(420,len(df_exc)*35),
                xaxis=dict(title='% de registros que exceden el límite',range=[0,130]),
                plot_bgcolor='#f9f9f9',margin=dict(l=300,r=20,t=60,b=40)
            )
            st.plotly_chart(fig,use_container_width=True)

            # Tarjetas de alerta roja
            st.subheader("🔴 Parámetros críticos (>50% exceden el límite)")
            criticos=df_exc[df_exc['% Excede']>50]
            if len(criticos)==0:
                st.info("Ningún parámetro supera el 50% de excedencia.")
            else:
                cols_c=st.columns(min(len(criticos),4))
                for i,((_,r),col_c) in enumerate(zip(criticos.iterrows(),cols_c)):
                    col_c.markdown(f"""
                    <div style='background:#e74c3c;border-radius:10px;padding:14px;
                                text-align:center;color:white'>
                      <b>{r['Módulo']}</b><br>
                      <span style='font-size:13px'>{r['Parámetro']}</span><br>
                      <span style='font-size:28px;font-weight:bold'>{r['% Excede']:.0f}%</span><br>
                      <span style='font-size:11px'>Prom: {r['Promedio']} | Lím: {r['Límite']}</span>
                    </div>""",unsafe_allow_html=True)

    with tr2:
        # Barras apiladas por módulo
        df_mod=df_res.groupby(['Módulo','Estado']).size().reset_index(name='n')
        fig=px.bar(df_mod,x='Módulo',y='n',color='Estado',barmode='stack',
                   color_discrete_map={
                       '🟢 Bueno':'#27ae60','🟡 Moderado':'#f39c12','🔴 Excede':'#e74c3c'},
                   title='Distribución de estados por módulo de monitoreo')
        fig.update_layout(height=380,plot_bgcolor='#f9f9f9')
        st.plotly_chart(fig,use_container_width=True)

        # Donas
        col_a,col_b,col_c=st.columns(3)
        for col_ui,mod_n in zip([col_a,col_b,col_c],
                                 ['💨 Monitoreo Pasivo','💧 Calidad del Agua','🏭 Partículas/Gases']):
            sub=df_res[df_res['Módulo']==mod_n]
            if len(sub)==0: col_ui.info(f"Sin datos\n{mod_n}"); continue
            cnt=sub['Estado'].value_counts()
            fig_d=go.Figure(go.Pie(
                labels=cnt.index,values=cnt.values,hole=0.5,
                marker_colors=['#27ae60','#f39c12','#e74c3c'],
                textinfo='label+percent'
            ))
            fig_d.update_layout(title=mod_n.split('—')[0],height=260,
                                 showlegend=False,margin=dict(t=40,b=5,l=5,r=5))
            col_ui.plotly_chart(fig_d,use_container_width=True)

    with tr3:
        if df_res['Mes'].nunique()>1:
            param_ev=st.selectbox("Parámetro",df_res['Parámetro'].unique(),key='rev_p')
            df_ev=df_res[df_res['Parámetro']==param_ev].sort_values('Mes')
            fig=go.Figure()
            # Área de riesgo
            lim_ev=df_ev['Límite'].iloc[0] if len(df_ev)>0 else 1
            fig.add_trace(go.Scatter(
                x=df_ev['Mes'],y=df_ev['Promedio'],
                mode='lines+markers+text',name='Promedio mensual',
                line=dict(color='#2980b9',width=3),marker=dict(size=10),
                text=df_ev['Promedio'].round(3),textposition='top center'
            ))
            fig.add_hline(y=lim_ev,line_dash='dash',line_color='red',
                          annotation_text=f'Límite: {lim_ev}')
            fig.update_layout(title=f'Evolución — {param_ev}',
                              height=380,plot_bgcolor='#f9f9f9',hovermode='x unified')
            st.plotly_chart(fig,use_container_width=True)
        else:
            st.info("Carga más de un mes para ver la evolución temporal.")

    with tr4:
        st.dataframe(
            df_res.sort_values(['% Excede','Módulo'],ascending=[False,True]),
            use_container_width=True,hide_index=True
        )
        if st.button("📄 Exportar resumen PDF"):
            buf=generar_pdf(
                df_res.rename(columns={'Módulo':'Punto'}),
                'Todos los meses','Resumen General de Monitoreo Ambiental',
                ['Parámetro','Promedio','Límite','% Excede'],
                {'Parámetro':'Parámetro','Promedio':'Promedio',
                 'Límite':'Límite','% Excede':'% Excede'}
            )
            st.download_button("⬇️ Descargar PDF",data=buf,
                               file_name="Resumen_Ambiental_GAD_Ambato.pdf",
                               mime="application/pdf")

# ════════════════════════════════════════════════════════════════
# MÓDULO 1 — MONITOREO PASIVO AIRE
# ════════════════════════════════════════════════════════════════
elif "Pasivo" in modulo:
    if not arch_pas:
        st.info("👈 Sube archivos Excel de Monitoreo Pasivo."); st.stop()

    @st.cache_data
    def cargar_pasivo(info):
        lista=[]
        for n,c in info:
            d=leer_pasivo(c,n)
            if d is not None and len(d)>0: lista.append(d)
        df=pd.concat(lista,ignore_index=True)
        df=df[df['Mes']!='DESCONOCIDO'].dropna(subset=['MPS_mg_cm2','Ozono_ug_m3','NO2_ug_m3'])
        df['Punto']=df['Punto'].str.replace(r'\s+',' ',regex=True).str.strip()
        df['Mes']=pd.Categorical(df['Mes'],categories=ORDEN_MESES,ordered=True)
        df=df.sort_values(['Mes','Punto']).reset_index(drop=True)
        for p,l in LIM_PASIVO.items():
            df[f'Est_{p}']=df[p].apply(lambda v: semaforo(v,l))
        df['lat'],df['lon']=zip(*df.apply(lambda r: utm_latlon(r['X_UTM'],r['Y_UTM']),axis=1))
        return df

    info_p=[(f.name,f.read()) for f in arch_pas]
    df_pa=cargar_pasivo(info_p)

    c1,c2,c3=st.columns([2,2,2])
    with c1: meses_p=st.multiselect("📅 Meses",ORDEN_MESES,default=df_pa['Mes'].unique().tolist(),key='mp')
    with c2: param_p=st.selectbox("🧪 Parámetro",list(LIM_PASIVO.keys()),format_func=lambda x:NOM_PASIVO[x],key='pp')
    with c3: puntos_p=st.multiselect("📍 Puntos",sorted(df_pa['Punto'].unique()),default=sorted(df_pa['Punto'].unique()),key='pup')

    df_pf=df_pa[df_pa['Mes'].isin(meses_p)&df_pa['Punto'].isin(puntos_p)]
    lp=LIM_PASIVO[param_p]

    k1,k2,k3,k4,k5=st.columns(5)
    pct_p=(df_pf[param_p]>lp).mean()*100
    k1.metric("Promedio",f"{df_pf[param_p].mean():.2f}")
    k2.metric("Máximo",f"{df_pf[param_p].max():.2f}")
    k3.metric("Mínimo",f"{df_pf[param_p].min():.2f}")
    k4.metric("Exceden límite",f"{(df_pf[param_p]>lp).sum()} reg.",
               delta=f"{pct_p:.1f}%",delta_color="inverse")
    k5.metric("Límite",f"{lp}")
    st.markdown("---")

    t1,t2,t3,t4,t5,t6=st.tabs(["📈 Tendencia","🗺️ Mapa","🔥 Heatmap","📦 Boxplot","🏆 Ranking","📋 Tabla & PDF"])

    with t1:
        dt=df_pf.groupby('Mes',observed=True)[param_p].agg(['mean','max','min']).reset_index()
        fig=go.Figure()
        fig.add_trace(go.Scatter(x=dt['Mes'],y=dt['max'],fill=None,mode='lines',
                                  line_color='rgba(231,76,60,.3)',name='Máx'))
        fig.add_trace(go.Scatter(x=dt['Mes'],y=dt['min'],fill='tonexty',mode='lines',
                                  fillcolor='rgba(130,202,157,.2)',
                                  line_color='rgba(39,174,96,.3)',name='Mín'))
        fig.add_trace(go.Scatter(x=dt['Mes'],y=dt['mean'],mode='lines+markers',
                                  name='Promedio',line=dict(color='#2980b9',width=3),
                                  marker=dict(size=9)))
        fig.add_hline(y=lp,line_dash='dash',line_color='red',annotation_text=f'Límite:{lp}')
        fig.update_layout(title=f'Tendencia — {NOM_PASIVO[param_p]}',height=420,
                          hovermode='x unified',plot_bgcolor='#f9f9f9')
        st.plotly_chart(fig,use_container_width=True)

    with t2:
        mes_m=st.selectbox("Mes",meses_p,index=len(meses_p)-1,key='pm_m')
        df_mm=df_pf[df_pf['Mes']==mes_m].dropna(subset=['lat','lon'])
        mp=folium.Map(location=[-1.249,-78.616],zoom_start=13,tiles='CartoDB positron')
        for _,row in df_mm.iterrows():
            v=row[param_p]
            folium.Marker([row['lat'],row['lon']],
                popup=folium.Popup(
                    f"<b>{row['Punto']}</b><br>{NOM_PASIVO[param_p]}: <b>{v:.2f}</b><br>"
                    f"Ozono: {row['Ozono_ug_m3']:.2f} µg/m³<br>"
                    f"NO₂: {row['NO2_ug_m3']:.2f} µg/m³<br>"
                    f"Estado: {row[f'Est_{param_p}']}",max_width=220),
                tooltip=f"{row['Punto']} | {v:.2f}",
                icon=folium.Icon(color=color_folium_fn(v,lp),icon='cloud',prefix='fa')
            ).add_to(mp)
        st_folium(mp,width=None,height=480)
        df_exc_p=df_mm[df_mm[param_p]>lp]
        if len(df_exc_p)>0:
            st.warning(f"⚠️ {len(df_exc_p)} punto(s) exceden el límite en {mes_m}")
            if smtp_user and smtp_pass and dest_str:
                if st.button("📧 Enviar alerta — Pasivo"):
                    filas="".join([f"<tr><td>{r['Punto']}</td><td style='color:red'>{r[param_p]:.2f}</td><td>{lp}</td></tr>"
                                   for _,r in df_exc_p.iterrows()])
                    html_a=f"""<html><body>
                    <h2 style='color:#1a5276'>⚠️ Alerta Monitoreo Pasivo — GAD Ambato</h2>
                    <p><b>Mes:</b> {mes_m} | <b>Parámetro:</b> {NOM_PASIVO[param_p]}</p>
                    <table border='1' cellpadding='6' style='border-collapse:collapse'>
                    <tr style='background:#1a5276;color:white'><th>Punto</th><th>Valor</th><th>Límite</th></tr>
                    {filas}</table></body></html>"""
                    try:
                        enviar_email([d.strip() for d in dest_str.split(',')],
                            f"⚠️ Alerta Aire GAD Ambato — {mes_m}",html_a,smtp_user,smtp_pass)
                        st.success("✅ Alerta enviada")
                    except Exception as e: st.error(f"Error: {e}")

    with t3:
        piv=df_pf.pivot_table(index='Punto',columns='Mes',values=param_p,aggfunc='mean',observed=True)
        piv.index=[p[:28]+'…' if len(p)>28 else p for p in piv.index]
        fig=px.imshow(piv,color_continuous_scale=['#2ecc71','#f1c40f','#e74c3c'],
                      title=f'Heatmap — {NOM_PASIVO[param_p]}',aspect='auto',
                      zmin=0,zmax=lp*2)
        fig.update_layout(height=560)
        st.plotly_chart(fig,use_container_width=True)

    with t4:
        df_bp=df_pf.copy(); df_bp['PC']=df_bp['Punto'].str[:28]
        fig=px.box(df_bp,x='PC',y=param_p,color='PC',
                   title=f'Distribución — {NOM_PASIVO[param_p]}',
                   color_discrete_sequence=px.colors.qualitative.Safe)
        fig.add_hline(y=lp,line_dash='dash',line_color='red',annotation_text=f'Límite:{lp}')
        fig.update_layout(height=500,showlegend=False,xaxis_tickangle=-40)
        st.plotly_chart(fig,use_container_width=True)

    with t5:
        df_rk=df_pf.groupby('Punto',observed=True)[param_p].mean().reset_index()
        df_rk=df_rk.sort_values(param_p,ascending=True)
        df_rk['Color']=df_rk[param_p].apply(lambda v:color_hex(v,lp))
        df_rk['PC']=df_rk['Punto'].str[:30]
        fig=go.Figure(go.Bar(x=df_rk[param_p],y=df_rk['PC'],orientation='h',
                              marker_color=df_rk['Color'],
                              text=df_rk[param_p].round(2),textposition='outside'))
        fig.add_vline(x=lp,line_dash='dash',line_color='red',annotation_text=f'Límite:{lp}')
        fig.update_layout(title=f'Ranking — {NOM_PASIVO[param_p]}',
                          height=580,plot_bgcolor='#f9f9f9',margin=dict(l=230))
        st.plotly_chart(fig,use_container_width=True)

    with t6:
        ca,cb=st.columns(2)
        with ca: mp_pdf=st.selectbox("Mes",meses_p,key='mp_pdf')
        df_tab=df_pf[df_pf['Mes']==mp_pdf][['Punto','MPS_mg_cm2','Ozono_ug_m3','NO2_ug_m3',f'Est_{param_p}']].copy()
        df_tab.columns=['Punto','MPS (mg/cm²)','Ozono (µg/m³)','NO₂ (µg/m³)','Estado']
        st.dataframe(df_tab,use_container_width=True,hide_index=True)
        if st.button("📄 PDF — Monitoreo Pasivo"):
            df_pp=df_pf[df_pf['Mes']==mp_pdf]
            buf=generar_pdf(df_pp,mp_pdf,"Monitoreo Pasivo Calidad del Aire",
                            ['MPS_mg_cm2','Ozono_ug_m3','NO2_ug_m3'],NOM_PASIVO)
            st.download_button("⬇️ Descargar PDF",data=buf,
                               file_name=f"Informe_Pasivo_{mp_pdf}.pdf",mime="application/pdf")

# ════════════════════════════════════════════════════════════════
# MÓDULO 2 — CALIDAD DEL AGUA
# ════════════════════════════════════════════════════════════════
elif "Agua" in modulo:
    if not arch_agua:
        st.info("👈 Sube archivos Excel de Calidad del Agua."); st.stop()

    @st.cache_data
    def cargar_agua(info):
        pl,il=[],[]
        for n,c in info:
            try:
                dp,di=leer_agua(c,n)
                if len(dp)>0: pl.append(dp)
                if len(di)>0: il.append(di)
            except Exception as e: st.warning(f"Error {n}: {e}")
        dfp=pd.concat(pl,ignore_index=True) if pl else pd.DataFrame()
        dfi=pd.concat(il,ignore_index=True) if il else pd.DataFrame()
        for df in [dfp,dfi]:
            if 'Mes' in df.columns:
                df['Mes']=pd.Categorical(df['Mes'],categories=ORDEN_MESES,ordered=True)
        return dfp,dfi

    info_a=[(f.name,f.read()) for f in arch_agua]
    df_aw,df_ica_w=cargar_agua(info_a)

    meses_aw=[m for m in ORDEN_MESES if m in df_aw['Mes'].unique().tolist()]
    c1,c2=st.columns([2,2])
    with c1: meses_w=st.multiselect("📅 Meses",meses_aw,default=meses_aw,key='maw')
    with c2: param_w=st.selectbox("🧪 Parámetro",list(LIM_AGUA.keys()),format_func=lambda x:NOM_AGUA[x],key='paw')

    df_awf=df_aw[(df_aw['Mes'].isin(meses_w))&(df_aw['Parametro']==param_w)]
    df_if=df_ica_w[df_ica_w['Mes'].isin(meses_w)] if len(df_ica_w)>0 else pd.DataFrame()
    lw=LIM_AGUA[param_w]

    if len(df_awf)>0:
        k1,k2,k3,k4=st.columns(4)
        pct_w=(df_awf['Valor']>lw).mean()*100
        k1.metric("Promedio",f"{df_awf['Valor'].mean():.3f}")
        k2.metric("Máximo",f"{df_awf['Valor'].max():.3f}")
        k3.metric("Mínimo",f"{df_awf['Valor'].min():.3f}")
        k4.metric("Exceden límite",f"{(df_awf['Valor']>lw).sum()} reg.",
                   delta=f"{pct_w:.1f}%",delta_color="inverse")
    st.markdown("---")

    tw1,tw2,tw3,tw4,tw5=st.tabs(["📈 Tendencia","🌊 ICA por punto","🔥 Heatmap","🏆 Ranking","📋 Tabla & PDF"])

    with tw1:
        if len(df_awf)>0:
            dtw=df_awf.groupby('Mes',observed=True)['Valor'].agg(['mean','max','min']).reset_index()
            fig=go.Figure()
            fig.add_trace(go.Scatter(x=dtw['Mes'],y=dtw['max'],fill=None,mode='lines',
                                      line_color='rgba(231,76,60,.3)',name='Máx'))
            fig.add_trace(go.Scatter(x=dtw['Mes'],y=dtw['min'],fill='tonexty',mode='lines',
                                      fillcolor='rgba(41,128,185,.15)',
                                      line_color='rgba(41,128,185,.3)',name='Mín'))
            fig.add_trace(go.Scatter(x=dtw['Mes'],y=dtw['mean'],mode='lines+markers',
                                      name='Promedio',line=dict(color='#2980b9',width=3),
                                      marker=dict(size=9)))
            fig.add_hline(y=lw,line_dash='dash',line_color='red',annotation_text=f'Límite:{lw}')
            fig.update_layout(title=f'Tendencia — {NOM_AGUA[param_w]}',
                              height=420,hovermode='x unified',plot_bgcolor='#f9f9f9')
            st.plotly_chart(fig,use_container_width=True)

    with tw2:
        if len(df_if)>0:
            mes_ica=st.selectbox("Mes",meses_w,index=len(meses_w)-1,key='mica')
            df_im=df_if[df_if['Mes']==mes_ica].copy()
            df_im['Color']=df_im['ICA'].apply(lambda v:
                '#27ae60' if v>=91 else '#f1c40f' if v>=66 else '#e67e22' if v>=51 else '#e74c3c')
            df_im['Estado']=df_im['ICA'].apply(lambda v:
                '🟢 Aceptable' if v>=91 else '🟡 Indicios' if v>=66 else '🟠 Atención' if v>=51 else '🔴 Crítico')
            fig=go.Figure(go.Bar(
                x=df_im['ICA'],y=df_im['Sitio'].str[:35],orientation='h',
                marker_color=df_im['Color'],text=df_im['ICA'].round(1),textposition='outside'))
            for val,lbl,clr in [(91,'Aceptable','green'),(66,'Indicios','orange'),(51,'Crítico','red')]:
                fig.add_vline(x=val,line_dash='dot',line_color=clr,
                              annotation_text=lbl,annotation_position='top')
            fig.update_layout(title=f'ICA — {mes_ica}',height=460,plot_bgcolor='#f9f9f9',
                              xaxis=dict(range=[0,105]),margin=dict(l=250))
            st.plotly_chart(fig,use_container_width=True)
            st.dataframe(df_im[['Sitio','Codigo','ICA','Estado','Interpretacion']],
                         use_container_width=True,hide_index=True)
            criticos=df_im[df_im['ICA']<51]
            if len(criticos)>0:
                st.error(f"🔴 {len(criticos)} punto(s) con ecosistema fuertemente contaminado (ICA<50)")
                if smtp_user and smtp_pass and dest_str:
                    if st.button("📧 Enviar alerta — Agua"):
                        filas="".join([f"<tr><td>{r['Sitio']}</td><td style='color:red'>{r['ICA']:.1f}</td></tr>"
                                       for _,r in criticos.iterrows()])
                        html_a=f"""<html><body>
                        <h2>⚠️ Alerta Calidad del Agua — GAD Ambato</h2>
                        <p><b>Mes:</b> {mes_ica} — ICA crítico (&lt;50)</p>
                        <table border='1' cellpadding='6' style='border-collapse:collapse'>
                        <tr style='background:#1a5276;color:white'><th>Sitio</th><th>ICA</th></tr>
                        {filas}</table></body></html>"""
                        try:
                            enviar_email([d.strip() for d in dest_str.split(',')],
                                f"⚠️ Alerta Agua GAD Ambato — {mes_ica}",html_a,smtp_user,smtp_pass)
                            st.success("✅ Alerta enviada")
                        except Exception as e: st.error(f"Error: {e}")

    with tw3:
        if len(df_awf)>0:
            piv_w=df_awf.pivot_table(index='Estacion',columns='Mes',values='Valor',
                                      aggfunc='mean',observed=True)
            fig=px.imshow(piv_w,color_continuous_scale=['#2ecc71','#f1c40f','#e74c3c'],
                          title=f'Heatmap — {NOM_AGUA[param_w]}',aspect='auto',
                          zmin=0,zmax=lw*2)
            fig.update_layout(height=460)
            st.plotly_chart(fig,use_container_width=True)

    with tw4:
        if len(df_awf)>0:
            df_rw=df_awf.groupby('Estacion')['Valor'].mean().reset_index()
            df_rw=df_rw.sort_values('Valor',ascending=True)
            df_rw['Color']=df_rw['Valor'].apply(lambda v:color_hex(v,lw))
            fig=go.Figure(go.Bar(x=df_rw['Valor'],y=df_rw['Estacion'],orientation='h',
                                  marker_color=df_rw['Color'],
                                  text=df_rw['Valor'].round(3),textposition='outside'))
            fig.add_vline(x=lw,line_dash='dash',line_color='red',annotation_text=f'Límite:{lw}')
            fig.update_layout(title=f'Ranking — {NOM_AGUA[param_w]}',
                              height=500,plot_bgcolor='#f9f9f9',margin=dict(l=220))
            st.plotly_chart(fig,use_container_width=True)

    with tw5:
        if len(df_awf)>0:
            mp_pdf_w=st.selectbox("Mes",meses_w,key='mpdf_w')
            df_tw=df_awf[df_awf['Mes']==mp_pdf_w].pivot_table(
                index='Estacion',columns='Parametro',values='Valor',
                aggfunc='mean',observed=True).reset_index()
            df_tw.columns.name=None
            st.dataframe(df_tw,use_container_width=True,hide_index=True)
            if st.button("📄 PDF — Agua"):
                buf=generar_pdf(df_tw.rename(columns={'Estacion':'Punto'}),
                                mp_pdf_w,"Calidad del Agua",
                                [c for c in df_tw.columns if c!='Estacion'],NOM_AGUA)
                st.download_button("⬇️ Descargar PDF",data=buf,
                                   file_name=f"Informe_Agua_{mp_pdf_w}.pdf",mime="application/pdf")

# ════════════════════════════════════════════════════════════════
# MÓDULO 3 — PARTÍCULAS Y GASES
# ════════════════════════════════════════════════════════════════
elif "Partículas" in modulo:
    if not arch_part:
        st.info("👈 Sube archivos Excel de Calidad del Aire (Partículas)."); st.stop()

    @st.cache_data
    def cargar_particulas_all(info):
        rlist,ilist=[],[]
        for n,c in info:
            try:
                res,df_id=leer_particulas(c,n)
                if res is not None: rlist.append(res)
                if df_id is not None and len(df_id)>0: ilist.append(df_id)
            except Exception as e: st.warning(f"Error {n}: {e}")
        df_m=pd.DataFrame(rlist) if rlist else pd.DataFrame()
        df_i=pd.concat(ilist,ignore_index=True) if ilist else pd.DataFrame()
        if len(df_m)>0:
            df_m['Mes']=pd.Categorical(df_m['Mes'],categories=ORDEN_MESES,ordered=True)
            df_m=df_m.sort_values('Mes').reset_index(drop=True)
        return df_m,df_i

    info_pt=[(f.name,f.read()) for f in arch_part]
    df_mens,df_ica_d=cargar_particulas_all(info_pt)

    if len(df_mens)==0:
        st.error("No se pudieron leer los archivos. Verifica el formato."); st.stop()

    meses_pt=[m for m in ORDEN_MESES if m in df_mens['Mes'].tolist()]
    c1,c2=st.columns([2,2])
    with c1: meses_pt_sel=st.multiselect("📅 Meses",meses_pt,default=meses_pt,key='mpt')
    with c2: param_pt=st.selectbox("🧪 Parámetro",list(LIM_PART.keys()),
                                    format_func=lambda x:NOM_PART[x],key='ppt')

    df_mf=df_mens[df_mens['Mes'].isin(meses_pt_sel)]
    lpt=LIM_PART[param_pt]

    if len(df_mf)>0 and param_pt in df_mf.columns:
        vals_pt=df_mf[param_pt].dropna()
        k1,k2,k3,k4,k5=st.columns(5)
        k1.metric("Promedio",f"{vals_pt.mean():.2f}")
        k2.metric("Máximo",f"{vals_pt.max():.2f}")
        k3.metric("Mínimo",f"{vals_pt.min():.2f}")
        k4.metric("Exceden límite",f"{(vals_pt>lpt).sum()} meses",
                   delta=f"{(vals_pt>lpt).mean()*100:.0f}%",delta_color="inverse")
        k5.metric("Límite TULAS",f"{lpt}")
        if 'ICA_max' in df_mf.columns:
            ica_prom=df_mf['ICA_max'].mean()
            st.info(f"🌬️ ICA promedio del período: **{ica_prom:.0f}** — {ica_aire_estado(ica_prom)}")
    st.markdown("---")

    tp1,tp2,tp3,tp4,tp5=st.tabs([
        "📈 Tendencia + Semáforo","🌬️ ICA diario",
        "📊 Comparativa parámetros","📅 Resumen mensual","📋 Tabla & PDF"])

    with tp1:
        if param_pt in df_mf.columns:
            fig=go.Figure()
            fig.add_trace(go.Scatter(
                x=df_mf['Mes'],y=df_mf[param_pt],
                mode='lines+markers+text',name=NOM_PART[param_pt],
                line=dict(color='#2980b9',width=3),marker=dict(size=11),
                text=df_mf[param_pt].round(1),textposition='top center'
            ))
            fig.add_hline(y=lpt,line_dash='dash',line_color='red',
                          annotation_text=f'Límite TULAS: {lpt}')
            fig.update_layout(title=f'Tendencia mensual — {NOM_PART[param_pt]}',
                              height=400,plot_bgcolor='#f9f9f9',hovermode='x unified')
            st.plotly_chart(fig,use_container_width=True)

            # ── Semáforo visual mensual ──
            st.subheader("🚦 Semáforo mensual")
            n_cols=len(df_mf)
            if n_cols>0:
                cols_sem=st.columns(min(n_cols,12))
                for idx,((_,row),col_s) in enumerate(zip(df_mf.iterrows(),cols_sem)):
                    val=row.get(param_pt,np.nan)
                    if pd.isna(val): continue
                    fv=float(val)
                    if fv<=lpt*0.75: bg='#27ae60'; ico='🟢'
                    elif fv<=lpt:    bg='#f39c12'; ico='🟡'
                    else:            bg='#e74c3c'; ico='🔴'
                    pct_lim=min(fv/lpt*100,999)
                    col_s.markdown(f"""
                    <div style='background:{bg};border-radius:10px;padding:10px;
                                text-align:center;color:white;min-height:90px'>
                      <div style='font-size:10px;font-weight:bold'>{row['Mes'][:3]}</div>
                      <div style='font-size:20px'>{ico}</div>
                      <div style='font-size:14px;font-weight:bold'>{fv:.1f}</div>
                      <div style='font-size:10px'>{pct_lim:.0f}% lím.</div>
                    </div>""",unsafe_allow_html=True)

    with tp2:
        if len(df_ica_d)>0:
            df_id_f=df_ica_d[df_ica_d['Mes'].isin(meses_pt_sel)].copy()
            df_id_f['Color']=df_id_f['ICA'].apply(ica_aire_color)
            fig=go.Figure()
            fig.add_trace(go.Scatter(
                x=df_id_f['Fecha'],y=df_id_f['ICA'],mode='lines+markers',
                name='ICA diario',line=dict(color='#8e44ad',width=2),
                marker=dict(size=6,color=df_id_f['Color'])
            ))
            for val,lbl,clr in [(50,'Deseable','#27ae60'),(100,'Aceptable','#f39c12'),(150,'Precaución','#e74c3c')]:
                fig.add_hline(y=val,line_dash='dot',line_color=clr,
                              annotation_text=lbl,annotation_position='right')
            fig.update_layout(title='ICA Diario — Índice de Calidad del Aire',
                              height=420,plot_bgcolor='#f9f9f9',
                              xaxis_title='Fecha',yaxis_title='ICA')
            st.plotly_chart(fig,use_container_width=True)
            st.caption("Escala ICA: 🟢 0-50 Deseable | 🟡 51-100 Aceptable | 🟠 101-150 Precaución | 🔴 151-200 Alerta | >200 Emergencia")

            # Distribución de días por categoría
            df_id_f['Categoría']=df_id_f['ICA'].apply(ica_aire_estado)
            cnt=df_id_f['Categoría'].value_counts().reset_index()
            cnt.columns=['Categoría','Días']
            fig2=px.bar(cnt,x='Categoría',y='Días',
                        color='Categoría',
                        color_discrete_map={
                            '🟢 Deseable':'#27ae60','🟡 Aceptable':'#f1c40f',
                            '🟠 Precaución':'#e67e22','🔴 Alerta':'#e74c3c'},
                        title='Distribución de días por categoría ICA')
            fig2.update_layout(height=320,plot_bgcolor='#f9f9f9',showlegend=False)
            st.plotly_chart(fig2,use_container_width=True)
        else:
            st.info("No hay datos ICA diarios en los archivos cargados.")

    with tp3:
        params_r=[p for p in LIM_PART.keys() if p in df_mf.columns]
        if len(df_mf)>0 and len(params_r)>0:
            # Gráfica de barras agrupadas: % respecto al límite
            df_bar=[]
            for _,row in df_mf.iterrows():
                for p in params_r:
                    v=row.get(p,np.nan)
                    if pd.isna(v): continue
                    df_bar.append({'Mes':str(row['Mes']),'Parámetro':NOM_PART[p],
                                   'Valor':float(v),'Límite':LIM_PART[p],
                                   '% Límite':min(float(v)/LIM_PART[p]*100,200)})
            df_bar=pd.DataFrame(df_bar)
            fig=px.bar(df_bar,x='Parámetro',y='% Límite',color='Mes',
                       barmode='group',
                       title='% del valor respecto al límite normativo por parámetro y mes',
                       color_discrete_sequence=px.colors.qualitative.Set2,
                       hover_data=['Valor','Límite'])
            fig.add_hline(y=100,line_dash='dash',line_color='red',
                          annotation_text='100% = Límite normativo')
            fig.update_layout(height=430,plot_bgcolor='#f9f9f9',xaxis_tickangle=-20)
            st.plotly_chart(fig,use_container_width=True)

            # Radar chart
            if len(df_mf)>0:
                fig_r=go.Figure()
                for _,row in df_mf.iterrows():
                    vals_r=[min(float(row[p])/LIM_PART[p]*100,200)
                             if not pd.isna(row.get(p)) else 0 for p in params_r]
                    labels=[NOM_PART[p] for p in params_r]
                    fig_r.add_trace(go.Scatterpolar(
                        r=vals_r+[vals_r[0]],
                        theta=labels+[labels[0]],
                        fill='toself',name=str(row['Mes'])
                    ))
                fig_r.add_trace(go.Scatterpolar(
                    r=[100]*len(params_r)+[100],
                    theta=[NOM_PART[p] for p in params_r]+[NOM_PART[params_r[0]]],
                    mode='lines',name='Límite (100%)',
                    line=dict(color='red',dash='dash',width=2)
                ))
                fig_r.update_layout(
                    title='Radar de cumplimiento (100% = límite normativo)',
                    polar=dict(radialaxis=dict(visible=True,range=[0,150])),
                    height=500
                )
                st.plotly_chart(fig_r,use_container_width=True)

    with tp4:
        st.subheader("Resumen mensual con semáforo de colores")
        params_s=[p for p in LIM_PART.keys() if p in df_mf.columns]

        def highlight_row(row):
            out=['']*len(row)
            for i,col in enumerate(row.index):
                if col in LIM_PART:
                    v=row[col]
                    if pd.isna(v): continue
                    lim=LIM_PART[col]
                    if float(v)>lim:       out[i]='background-color:#f5c6cb'
                    elif float(v)>lim*.75: out[i]='background-color:#fff3cd'
                    else:                  out[i]='background-color:#d4edda'
            return out

        df_show=df_mf[['Mes']+params_s+(['ICA_max'] if 'ICA_max' in df_mf.columns else [])].copy()
        st.dataframe(df_show.style.apply(highlight_row,axis=1),
                     use_container_width=True,hide_index=True)

        # Alertas
        alertas=[]
        for _,row in df_mf.iterrows():
            for p in params_s:
                v=row.get(p,np.nan)
                if not pd.isna(v) and float(v)>LIM_PART[p]:
                    alertas.append({
                        'Mes':str(row['Mes']),'Parámetro':NOM_PART[p],
                        'Valor':round(float(v),2),'Límite':LIM_PART[p],
                        '% del límite':round(float(v)/LIM_PART[p]*100,1)
                    })
        if alertas:
            df_al=pd.DataFrame(alertas).sort_values('% del límite',ascending=False)
            st.error("🚨 Parámetros que exceden el límite normativo:")
            st.dataframe(df_al,use_container_width=True,hide_index=True)
            if smtp_user and smtp_pass and dest_str:
                if st.button("📧 Enviar alerta — Partículas"):
                    filas="".join([f"<tr><td>{r['Mes']}</td><td>{r['Parámetro']}</td>"
                                   f"<td style='color:red'>{r['Valor']}</td><td>{r['Límite']}</td>"
                                   f"<td>{r['% del límite']}%</td></tr>"
                                   for _,r in df_al.iterrows()])
                    html_a=f"""<html><body>
                    <h2 style='color:#1a5276'>⚠️ Alerta Partículas/Gases — GAD Ambato</h2>
                    <table border='1' cellpadding='6' style='border-collapse:collapse'>
                    <tr style='background:#1a5276;color:white'>
                    <th>Mes</th><th>Parámetro</th><th>Valor</th><th>Límite</th><th>% Límite</th></tr>
                    {filas}</table></body></html>"""
                    try:
                        enviar_email([d.strip() for d in dest_str.split(',')],
                            "⚠️ Alerta Partículas GAD Ambato",html_a,smtp_user,smtp_pass)
                        st.success("✅ Alerta enviada")
                    except Exception as e: st.error(f"Error: {e}")
        else:
            st.success("✅ Todos los parámetros dentro del límite normativo.")

    with tp5:
        params_pdf=[p for p in LIM_PART.keys() if p in df_mf.columns]
        st.dataframe(df_mf[['Mes']+params_pdf+(['ICA_max'] if 'ICA_max' in df_mf.columns else [])],
                     use_container_width=True,hide_index=True)
        if st.button("📄 PDF — Partículas"):
            buf=generar_pdf(df_mf.rename(columns={'Mes':'Punto'}),
                            'Resumen anual','Calidad del Aire — Partículas y Gases',
                            params_pdf,NOM_PART)
            st.download_button("⬇️ Descargar PDF",data=buf,
                               file_name="Informe_Particulas_GAD.pdf",mime="application/pdf")
