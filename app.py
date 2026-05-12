import streamlit as st
import pandas as pd
import gspread
from google.oauth2.service_account import Credentials
import datetime
import pytz
import re

# --- CONFIGURACIÓN DE PÁGINA ---
st.set_page_config(page_title="WFM Dashboard", page_icon="⏱️", layout="wide")

# Zona horaria local (Ajusta según tu país, ej: 'America/Argentina/Buenos_Aires')
TZ = pytz.timezone('America/Argentina/Buenos_Aires')

# --- CONEXIÓN A GOOGLE SHEETS ---
@st.cache_resource
def get_gspread_client():
    """Autentica y devuelve el cliente de gspread usando st.secrets."""
    scopes = [
        "https://www.googleapis.com/auth/spreadsheets.readonly",
        "https://www.googleapis.com/auth/drive.readonly"
    ]
    # Extraer credenciales del secrets.toml
    creds_dict = st.secrets["gcp_service_account"]
    creds = Credentials.from_service_account_info(creds_dict, scopes=scopes)
    return gspread.authorize(creds)

@st.cache_data(ttl=600) # TTL de 10 minutos para frescura vs cuota API
def load_wfm_data(sheet_url):
    """Descarga y procesa la matriz visual de Google Sheets a un formato estructurado."""
    client = get_gspread_client()
    try:
        sheet = client.open_by_url(sheet_url).worksheet("Calendario")
        # Traer todo de una vez (minimiza llamadas a la API)
        all_values = sheet.get_all_values()
    except Exception as e:
        st.error(f"Error al conectar con Google Sheets: {e}")
        return pd.DataFrame()

    if len(all_values) < 3:
        return pd.DataFrame()

    # Fila 3 (índice 2) contiene los días del mes (1, 2, 3...)
    days_row = all_values[2]
    
    # Extraemos filas de datos (de la 4 en adelante)
    data_rows = all_values[3:]
    
    parsed_data = []
    
    for row in data_rows:
        # Validar longitud mínima de fila
        if len(row) < 3:
            continue
            
        rango_turno = str(row[0]).strip()
        agente = str(row[1]).strip()
        
        # Filtro 1: Ignorar filas vacías o títulos (MAÑANA, TARDE)
        # Usamos regex para buscar el patrón "numero a numero"
        match = re.match(r'(\d+)\s*a\s*(\d+)', rango_turno.lower())
        if not match or not agente:
            continue
            
        hora_inicio = int(match.group(1))
        hora_fin = int(match.group(2))
        
        # Lógica para turnos que cruzan la medianoche
        cruza_medianoche = hora_fin <= hora_inicio
        
        # Construir diccionario para este agente
        agente_data = {
            "Turno": rango_turno,
            "Agente": agente,
            "Hora_Inicio": hora_inicio,
            "Hora_Fin": hora_fin,
            "Cruza_Medianoche": cruza_medianoche
        }
        
        # Mapear los días laborables (Columna C en adelante, índice 2+)
        for col_idx in range(2, len(row)):
            if col_idx < len(days_row):
                dia_str = str(days_row[col_idx]).strip()
                if dia_str.isdigit():
                    dia_num = int(dia_str)
                    celda_valor = str(row[col_idx]).strip()
                    # Condición: si el valor contiene el nombre u otra marca de presencia
                    trabaja = len(celda_valor) > 1 and celda_valor.lower() != "f" 
                    agente_data[f"Dia_{dia_num}"] = trabaja
                    
        parsed_data.append(agente_data)
        
    return pd.DataFrame(parsed_data)

def get_status_agente(hora_inicio, hora_fin, cruza_medianoche, hora_actual):
    """Determina si un agente está actualmente en turno o si entra en la próxima banda."""
    en_turno = False
    proximo = False
    
    if not cruza_medianoche:
        if hora_inicio <= hora_actual < hora_fin:
            en_turno = True
        elif hora_inicio == hora_actual + 1 or hora_inicio == hora_actual + 2:
            proximo = True
    else:
        if hora_actual >= hora_inicio or hora_actual < hora_fin:
            en_turno = True
        elif hora_inicio == hora_actual + 1 or hora_inicio == hora_actual + 2:
            proximo = True
            
    return en_turno, proximo

# --- UI Y LÓGICA DE LA APLICACIÓN ---
def main():
    st.title("📊 Dashboard WFM - Control de Turnos")
    
    # Intenta obtener la URL desde st.secrets
    try:
        SHEET_URL = st.secrets["SHEET_URL"]
    except KeyError:
        st.warning("⚠️ Configura la SHEET_URL en los Secrets de Streamlit.")
        return

    df = load_wfm_data(SHEET_URL)
    
    if df.empty:
        st.stop()

    # --- SIDEBAR ---
    st.sidebar.header("Filtros")
    fecha_hoy = datetime.datetime.now(TZ).date()
    fecha_seleccionada = st.sidebar.date_input("Seleccionar Fecha", fecha_hoy)
    dia_seleccionado = fecha_seleccionada.day
    
    col_dia = f"Dia_{dia_seleccionado}"
    if col_dia not in df.columns:
        st.sidebar.error(f"El día {dia_seleccionado} no se encuentra en el calendario o no hay datos cargados.")
        return

    # Filtrar solo agentes que trabajan el día seleccionado
    df_dia = df[df[col_dia] == True].copy()

    # --- TIEMPO ACTUAL ---
    ahora = datetime.datetime.now(TZ)
    hora_actual = ahora.hour
    
    st.markdown(f"### 🕒 Estado Actual: `{ahora.strftime('%H:%M')} hrs` - {fecha_seleccionada.strftime('%d/%m/%Y')}")

    # Lógica de cálculo de estado
    df_dia['En_Turno'] = False
    df_dia['Proximo'] = False
    
    for idx, row in df_dia.iterrows():
        en_turno, proximo = get_status_agente(
            row['Hora_Inicio'], row['Hora_Fin'], row['Cruza_Medianoche'], hora_actual
        )
        df_dia.at[idx, 'En_Turno'] = en_turno
        df_dia.at[idx, 'Proximo'] = proximo

    # --- SECCIÓN 1 Y 2: ACTUALES Y PRÓXIMOS ---
    col1, col2 = st.columns(2)
    
    with col1:
        st.success("🟢 Agentes en Turno Actual")
        en_turno_df = df_dia[df_dia['En_Turno']][['Agente', 'Turno']].reset_index(drop=True)
        if not en_turno_df.empty:
            st.dataframe(en_turno_df, use_container_width=True, hide_index=True)
        else:
            st.info("No hay agentes programados en esta banda horaria.")

    with col2:
        st.warning("🟡 Próximos Ingresos (Próx. 1-2 hs)")
        proximos_df = df_dia[df_dia['Proximo']][['Agente', 'Turno']].reset_index(drop=True)
        if not proximos_df.empty:
            st.dataframe(proximos_df, use_container_width=True, hide_index=True)
        else:
            st.info("No hay ingresos programados a corto plazo.")

    st.markdown("---")

    # --- SECCIÓN 3: RESUMEN DEL DÍA ---
    st.subheader(f"📈 Resumen de Dotación: {fecha_seleccionada.strftime('%d/%m/%Y')}")
    
    resumen = df_dia.groupby('Turno').size().reset_index(name='Agentes Programados')
    resumen['Hora_Orden'] = resumen['Turno'].apply(lambda x: int(re.match(r'(\d+)', x).group(1)) if re.match(r'(\d+)', x) else 0)
    resumen = resumen.sort_values('Hora_Orden').drop(columns=['Hora_Orden']).reset_index(drop=True)

    col3, col4 = st.columns([2, 1])
    with col3:
        st.dataframe(resumen, use_container_width=True, hide_index=True)
    with col4:
        st.metric(label="Total de Agentes (Día)", value=resumen['Agentes Programados'].sum())

if __name__ == "__main__":
    main()
