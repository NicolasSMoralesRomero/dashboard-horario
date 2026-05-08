import streamlit as st
import pandas as pd
from streamlit_gsheets import GSheetsConnection
from datetime import datetime, time
import re

# Configuración de página
st.set_page_config(page_title="WFM Dashboard", layout="wide")

# --- LÓGICA DE NEGOCIO Y PROCESAMIENTO ---

def parse_schedule(horario_str):
    """Extrae horas de inicio y fin de strings como '9 a 16' o '18 a 01'."""
    try:
        # Buscar números en el string
        horas = re.findall(r'\d+', str(horario_str))
        if len(horas) < 2:
            return None, None
        
        h_inicio = int(horas[0])
        h_fin = int(horas[1])
        
        return h_inicio, h_fin
    except:
        return None, None

def is_agent_active(h_inicio, h_fin, hora_actual):
    """Determina si un agente está activo, manejando turnos nocturnos."""
    actual = hora_actual.hour
    
    if h_inicio < h_fin:
        # Turno normal (ej. 9 a 17)
        return h_inicio <= actual < h_fin
    else:
        # Turno que cruza medianoche (ej. 18 a 01)
        return actual >= h_inicio or actual < h_fin

@st.cache_data(ttl=600)  # 10 minutos de caché
def get_data():
    conn = st.connection("gsheets", type=GSheetsConnection)
    # Leer desde la fila 2 para capturar encabezados de días (Fila 3 de la hoja)
    df = conn.read(spreadsheet=st.secrets["spreadsheet"]["url"], worksheet="Calendario", header=2)
    return df

# --- INTERFAZ DE USUARIO ---

st.title("📊 WFM - Control de Turnos en Tiempo Real")

try:
    raw_df = get_data()
    
    # Limpieza inicial
    # La columna A es 'Rango', B es 'Agente'. Renombramos para facilitar
    df = raw_df.copy()
    df.columns.values[0] = "Horario"
    df.columns.values[1] = "Agente"
    
    # Sidebar
    st.sidebar.header("Configuración")
    fecha_seleccionada = st.sidebar.date_input("Seleccionar Fecha", datetime.now())
    dia_str = str(fecha_seleccionada.day)
    hora_sistema = datetime.now().time()
    
    if dia_str not in df.columns:
        st.error(f"El día {dia_str} no se encuentra en la base de datos.")
        st.stop()

    # Filtrar solo agentes que trabajan el día seleccionado (celda no vacía)
    # Y limpiar filas que no son turnos (como separadores 'MAÑANA')
    df_dia = df[df[dia_str].notna() & df['Horario'].str.contains('a', na=False)].copy()
    
    # Parsing de horas
    df_dia['h_start'], df_dia['h_end'] = zip(*df_dia['Horario'].map(parse_schedule))
    df_dia = df_dia.dropna(subset=['h_start'])

    # --- SECCIÓN 1: ESTADO ACTUAL ---
    st.subheader(f"🕒 Estado Actual - {hora_sistema.strftime('%H:%M')}")
    
    activos = df_dia[df_dia.apply(lambda x: is_agent_active(x['h_start'], x['h_end'], hora_sistema), axis=1)]
    
    col1, col2 = st.columns([1, 3])
    col1.metric("Agentes Online", len(activos))
    col2.dataframe(activos[['Agente', 'Horario']], use_container_width=True, hide_index=True)

    st.divider()

    # --- SECCIÓN 2: PRÓXIMOS INGRESOS ---
    st.subheader("🚀 Próximos Ingresos")
    
    # Definimos 'próximos' como los que entran en la siguiente hora
    proxima_hora = (hora_sistema.hour + 1) % 24
    proximos = df_dia[df_dia['h_start'] == proxima_hora]
    
    if not proximos.empty:
        st.success(f"Ingresan a las {proxima_hora}:00 hs:")
        st.table(proximos[['Agente', 'Horario']])
    else:
        st.info("No hay ingresos programados para la próxima hora.")

    # --- SECCIÓN 3: RESUMEN DEL DÍA ---
    st.divider()
    st.subheader(f"📅 Planificación del Día: {fecha_seleccionada.strftime('%d/%m/%Y')}")
    
    resumen = df_dia.groupby('Horario')['Agente'].count().reset_index()
    resumen.columns = ['Rango Horario', 'Cantidad de Agentes']
    
    st.bar_chart(resumen.set_index('Rango Horario'))
    st.dataframe(df_dia[['Agente', 'Horario']].sort_values(by='h_start'), use_container_width=True, hide_index=True)

except Exception as e:
    st.error("Error al conectar con Google Sheets. Verifica las credenciales y la estructura de la hoja.")
    st.exception(e)
