import streamlit as st
import pandas as pd
import gspread
from google.oauth2.service_account import Credentials
import datetime
import pytz
import re

# --- CONFIGURACIÓN DE PÁGINA ---
st.set_page_config(page_title="WFM Dashboard", page_icon="⏱️", layout="wide")

TZ = pytz.timezone('America/Argentina/Buenos_Aires')

# --- CONEXIÓN A GOOGLE SHEETS ---
@st.cache_resource
def get_gspread_client():
    scopes = [
        "https://www.googleapis.com/auth/spreadsheets.readonly",
        "https://www.googleapis.com/auth/drive.readonly"
    ]
    creds_dict = st.secrets["gcp_service_account"]
    creds = Credentials.from_service_account_info(creds_dict, scopes=scopes)
    return gspread.authorize(creds)

@st.cache_data(ttl=600)
def load_wfm_data(sheet_url):
    client = get_gspread_client()
    try:
        sheet = client.open_by_url(sheet_url).worksheet("Calendario")
        all_values = sheet.get_all_values()
    except Exception as e:
        st.error(f"Error al conectar con Google Sheets: {e}")
        return pd.DataFrame()

    if len(all_values) < 3:
        return pd.DataFrame()

    # Mapear fechas
    dates_mapping = {}
    fila_fechas = all_values[1] 
    for col_idx in range(3, len(fila_fechas)):
        val = str(fila_fechas[col_idx]).strip()
        if re.match(r'\d{2}-\d{2}', val):
            dia = int(val.split('-')[0])
            dates_mapping[col_idx] = dia
            
    parsed_data = []
    turno_actual_memoria = ""
    
    for row_idx in range(2, len(all_values)):
        row = all_values[row_idx]
        if len(row) < 3:
            continue
            
        col_b_turno = str(row[1]).strip()
        col_c_agente_base = str(row[2]).strip()
        
        if "a" in col_b_turno and re.search(r'\d+', col_b_turno):
            turno_actual_memoria = col_b_turno
            
        if not turno_actual_memoria:
            continue
            
        match = re.search(r'(\d+)\s*a\s*(\d+)', turno_actual_memoria.lower())
        if not match:
            continue
            
        hora_inicio = int(match.group(1))
        hora_fin = int(match.group(2))
        cruza_medianoche = hora_fin <= hora_inicio
        
        agente_data = {
            "Turno": turno_actual_memoria,
            "Agente_Base": col_c_agente_base,
            "Hora_Inicio": hora_inicio,
            "Hora_Fin": hora_fin,
            "Cruza_Medianoche": cruza_medianoche
        }
        
        for col_idx, day_num in dates_mapping.items():
            if col_idx < len(row):
                val = str(row[col_idx]).strip()
                val_lower = val.lower()
                
                # --- FILTRO ANTI-BASURA ---
                # Detecta días, fechas y números para no confundirlos con personas
                es_basura = (
                    val_lower in ["lunes", "martes", "miercoles", "jueves", "viernes", "sabado", "domingo", "agente"] or
                    bool(re.match(r'^\d{2}-\d{2}$', val)) or
                    val.isdigit()
                )
                
                if es_basura:
                    agente_data[f"Dia_{day_num}"] = ""
                else:
                    agente_data[f"Dia_{day_num}"] = val
            else:
                agente_data[f"Dia_{day_num}"] = ""
                
        parsed_data.append(agente_data)
        
    return pd.DataFrame(parsed_data)

def get_status_agente(hora_inicio, hora_fin, cruza_medianoche, hora_actual):
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

def main():
    st.title("📊 Dashboard WFM - Control de Turnos")
    
    try:
        SHEET_URL = st.secrets["SHEET_URL"]
    except KeyError:
        st.warning("⚠️ Configura la SHEET_URL en los Secrets de Streamlit.")
        return

    df = load_wfm_data(SHEET_URL)
    
    if df.empty:
        st.info("No se pudieron cargar datos. Verifica el formato del Sheet.")
        st.stop()

    st.sidebar.header("Filtros")
    fecha_hoy = datetime.datetime.now(TZ).date()
    fecha_seleccionada = st.sidebar.date_input("Seleccionar Fecha", fecha_hoy)
    dia_seleccionado = fecha_seleccionada.day
    
    col_dia = f"Dia_{dia_seleccionado}"
    if col_dia not in df.columns:
        st.sidebar.warning(f"No hay datos cargados para el día {dia_seleccionado} en este mes.")
        return

    # 1. Filtramos vacíos y francos
    df_dia = df[
        (df[col_dia].astype(str).str.len() > 1) & 
        (~df[col_dia].astype(str).str.lower().isin(['f', 'franco', 'vac', 'vacaciones', 'licencia', 'ausente']))
    ].copy()

    # 2. Asignamos el agente
    df_dia['Agente'] = df_dia[col_dia]

    ahora = datetime.datetime.now(TZ)
    hora_actual = ahora.hour
    
    st.markdown(f"### 🕒 Estado Actual: `{ahora.strftime('%H:%M')} hrs` - {fecha_seleccionada.strftime('%d/%m/%Y')}")

    df_dia['En_Turno'] = False
    df_dia['Proximo'] = False
    
    for idx, row in df_dia.iterrows():
        en_turno, proximo = get_status_agente(
            row['Hora_Inicio'], row['Hora_Fin'], row['Cruza_Medianoche'], hora_actual
        )
        df_dia.at[idx, 'En_Turno'] = en_turno
        df_dia.at[idx, 'Proximo'] = proximo

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

    st.subheader(f"📈 Resumen de Dotación Programada ({fecha_seleccionada.strftime('%d/%m/%Y')})")
    
    if not df_dia.empty:
        resumen = df_dia.groupby('Turno').size().reset_index(name='Agentes Programados')
        resumen['Hora_Orden'] = resumen['Turno'].apply(lambda x: int(re.search(r'(\d+)', x).group(1)) if re.search(r'(\d+)', x) else 0)
        resumen = resumen.sort_values('Hora_Orden').drop(columns=['Hora_Orden']).reset_index(drop=True)

        col3, col4 = st.columns([2, 1])
        with col3:
            st.dataframe(resumen, use_container_width=True, hide_index=True)
        with col4:
            st.metric(label="Total de Agentes (Día)", value=resumen['Agentes Programados'].sum())
    else:
        st.info("No hay dotación programada para este día.")

if __name__ == "__main__":
    main()
