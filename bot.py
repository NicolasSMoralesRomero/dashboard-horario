import os
import pandas as pd
import gspread
from google.oauth2.service_account import Credentials
import datetime
import pytz
import re
import requests
import json

# Zona Horaria
TZ = pytz.timezone('America/Argentina/Buenos_Aires')

def get_gspread_client():
    scopes = ["https://www.googleapis.com/auth/spreadsheets.readonly", "https://www.googleapis.com/auth/drive.readonly"]
    creds_info = json.loads(os.environ['GCP_SERVICE_ACCOUNT'])
    creds = Credentials.from_service_account_info(creds_info, scopes=scopes)
    return gspread.authorize(creds)

def notify_slack(agentes, turno_prox, webhook):
    if not agentes: return
    nombres = ", ".join(agentes)
    mensaje = {
        "text": f"⚠️ *ALERTA DE INGRESO (Próximos 5 min)*\nEn breve ingresan para el turno *{turno_prox}*:\n👥 {nombres}\nFavor validar conexión."
    }
    requests.post(webhook, json=mensaje)

def run_bot():
    url = os.environ['SHEET_URL']
    webhook = os.environ['SLACK_WEBHOOK_URL']
    
    client = get_gspread_client()
    sheet = client.open_by_url(url).worksheet("Calendario")
    all_values = sheet.get_all_values()

    dates_mapping = {}
    for col_idx, val in enumerate(all_values[1]):
        if re.match(r'\d{2}-\d{2}', str(val)):
            dates_mapping[col_idx] = int(val.split('-')[0])

    ahora = datetime.datetime.now(TZ)
    h_proxima = (ahora.hour + 1) % 24
    dia_hoy = ahora.day
    
    turno_memoria = ""
    agentes_notificar = []
    nombre_turno = ""

    for row in all_values[2:]:
        if len(row) < 3: continue
        
        celda_a = str(row[0]).strip().lower()
        celda_b = str(row[1]).strip().lower()
        patron_turno = r'(\d{1,2})\s*[a\-]\s*(\d{1,2})'
        
        match_b = re.search(patron_turno, celda_b)
        match_a = re.search(patron_turno, celda_a)
        
        if match_b:
            turno_memoria = f"de {match_b.group(1)} a {match_b.group(2)}"
        elif match_a:
            turno_memoria = f"de {match_a.group(1)} a {match_a.group(2)}"
            
        if not turno_memoria: continue
        
        h_ini = int(re.search(r'(\d+)', turno_memoria).group(1))
        
        if h_ini == h_proxima:
            for col_idx, d_num in dates_mapping.items():
                if d_num == dia_hoy and col_idx < len(row):
                    nombre_agente = str(row[col_idx]).strip()
                    if len(nombre_agente) > 1 and nombre_agente.lower() not in ['f','franco','vac','lic','martes','lunes','miercoles','jueves','viernes','sabado','domingo', 'agente', 'mañana/tarde', 'tarde/noche'] and not nombre_agente.isdigit():
                        agentes_notificar.append(nombre_agente)
                        nombre_turno = turno_memoria
    
    if agentes_notificar:
        notify_slack(agentes_notificar, nombre_turno, webhook)
        print(f"Éxito: Notificación enviada para {agentes_notificar}")
    else:
        print("Operación terminada: No hay ingresos en la próxima hora.")

if __name__ == "__main__":
    run_bot()
