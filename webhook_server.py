#!/usr/bin/env python3
"""
WhatsApp Webhook Server — Control Correos James + Bot ASFIN
- Números conocidos (James personal): comandos de gestión
- Números desconocidos: flujo de captación ASFIN con Calendar
"""

import asyncio
import json
import logging
import os
import re
import smtplib
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Optional

import uvicorn
from fastapi import FastAPI, HTTPException, Request, Query
from fastapi.responses import PlainTextResponse

# ─── Google Calendar via Service Account ──────────────────────────────────────
try:
    from google.oauth2 import service_account
    from googleapiclient.discovery import build
    GCAL_AVAILABLE = True
except ImportError:
    GCAL_AVAILABLE = False

# ─── Configuración ─────────────────────────────────────────────────────────────
VERIFY_TOKEN      = os.getenv("VERIFY_TOKEN",      "james_control_correos_2026")
WA_TOKEN          = os.getenv("WA_TOKEN",          "")
PHONE_NUMBER_ID   = os.getenv("PHONE_NUMBER_ID",   "1017000174828335")
JAMES_WA_PERSONAL = os.getenv("JAMES_WA_PERSONAL", "51934284408")
JAMES_WA_BIZ      = os.getenv("JAMES_WA_BIZ",      "51968742772")
SHEET_ID          = os.getenv("SHEET_ID",          "1RSAc1hYS3utB13tK5VS3L-Qu2Kc8kaEHXiJnLk9BgHs")
WORKSHEET_ID      = int(os.getenv("WORKSHEET_ID",  "0"))
TASK_LIST_ID      = os.getenv("TASK_LIST_ID",      "MDY5MzE5MDc1NDA2NzkyNDA4ODQ6MDow")
CALLMEBOT_KEY     = os.getenv("CALLMEBOT_KEY",     "1235044")
JAMES_EMAIL       = os.getenv("JAMES_EMAIL",       "pabel.conga@gmail.com")
GMAIL_USER        = os.getenv("GMAIL_USER",        "")
GMAIL_APP_PASS    = os.getenv("GMAIL_APP_PASS",    "")

# Google Calendar Service Account
GCAL_CLIENT_EMAIL = os.getenv("GCAL_CLIENT_EMAIL", "asfin-calendar-bot@asfin-bot.iam.gserviceaccount.com")
GCAL_PRIVATE_KEY  = os.getenv("GCAL_PRIVATE_KEY",  "").replace("\\n", "\n")
GCAL_CALENDAR_ID  = os.getenv("GCAL_CALENDAR_ID",  "pabel.conga@gmail.com")  # calendario principal de James

LIMA_TZ = timezone(timedelta(hours=-5))

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("wa-webhook")

app = FastAPI(title="WA Webhook — Control Correos James + ASFIN")

# ─── Sesiones clientes externos ───────────────────────────────────────────────
CLIENT_SESSIONS: dict[str, dict] = {}
PENDING_CONFIRM: dict[str, dict] = {}  # código 4 dígitos → datos cliente

SERVICIOS = {
    "1": "Consultoría empresarial",
    "2": "Gestión financiera",
    "3": "Asesoría en contrataciones y arbitraje",
}

# ─── Google Calendar helpers ──────────────────────────────────────────────────

def get_calendar_service():
    """Construye el cliente de Google Calendar con Service Account."""
    if not GCAL_AVAILABLE or not GCAL_PRIVATE_KEY:
        return None
    try:
        creds = service_account.Credentials.from_service_account_info(
            {
                "type": "service_account",
                "client_email": GCAL_CLIENT_EMAIL,
                "private_key": GCAL_PRIVATE_KEY,
                "token_uri": "https://oauth2.googleapis.com/token",
                "private_key_id": "",
                "client_id": "",
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "project_id": "asfin-bot",
            },
            scopes=["https://www.googleapis.com/auth/calendar"],
        )
        return build("calendar", "v3", credentials=creds, cache_discovery=False)
    except Exception as e:
        log.error(f"Calendar service error: {e}")
        return None


def parse_dia_to_date(dia_str: str, now: datetime) -> Optional[datetime]:
    """
    Convierte texto del cliente a fecha concreta.
    Ej: "lunes", "viernes 20", "20 de marzo", "mañana"
    Retorna datetime en Lima TZ con hora 00:00.
    """
    dia_str = dia_str.lower().strip()
    dias_semana = {
        "lunes": 0, "martes": 1, "miércoles": 2, "miercoles": 2,
        "jueves": 3, "viernes": 4, "sábado": 5, "sabado": 5, "domingo": 6
    }
    meses = {
        "enero": 1, "febrero": 2, "marzo": 3, "abril": 4, "mayo": 5, "junio": 6,
        "julio": 7, "agosto": 8, "septiembre": 9, "octubre": 10, "noviembre": 11, "diciembre": 12
    }

    # "mañana"
    if "mañana" in dia_str or "manana" in dia_str:
        return (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)

    # "pasado mañana"
    if "pasado" in dia_str:
        return (now + timedelta(days=2)).replace(hour=0, minute=0, second=0, microsecond=0)

    # Día de la semana (próximo)
    for nombre, num in dias_semana.items():
        if nombre in dia_str:
            diff = (num - now.weekday()) % 7
            if diff == 0:
                diff = 7  # mismo día de la semana → próxima semana
            return (now + timedelta(days=diff)).replace(hour=0, minute=0, second=0, microsecond=0)

    # "20 de marzo" o "20 marzo"
    match = re.search(r"(\d{1,2})\s+(?:de\s+)?(\w+)", dia_str)
    if match:
        day = int(match.group(1))
        mes_str = match.group(2)
        mes = meses.get(mes_str)
        if mes:
            year = now.year if mes >= now.month else now.year + 1
            try:
                return datetime(year, mes, day, 0, 0, tzinfo=LIMA_TZ)
            except Exception:
                pass

    # Solo número de día
    match2 = re.search(r"(\d{1,2})", dia_str)
    if match2:
        day = int(match2.group(1))
        try:
            candidate = now.replace(day=day, hour=0, minute=0, second=0, microsecond=0)
            if candidate.date() < now.date():
                # mes siguiente
                if now.month == 12:
                    candidate = candidate.replace(year=now.year + 1, month=1)
                else:
                    candidate = candidate.replace(month=now.month + 1)
            return candidate
        except Exception:
            pass

    return None


def is_blocked_slot(dt: datetime) -> bool:
    """
    Devuelve True si la fecha/hora está en bloque de no atención:
    - Viernes desde las 18:00 hasta Sábado 18:00
    """
    weekday = dt.weekday()  # 4=viernes, 5=sábado
    hour = dt.hour
    if weekday == 4 and hour >= 18:  # viernes 6pm en adelante
        return True
    if weekday == 5 and hour < 18:   # sábado hasta 6pm
        return True
    return True if weekday == 6 else False  # domingo bloqueado también


def get_available_slots(target_date: datetime, service) -> list[dict]:
    """
    Retorna hasta 3 horarios disponibles en target_date.
    Bloques permitidos: 8:00-13:00 y 16:00-20:00 (Lima)
    Slots de 1 hora cada uno.
    """
    candidate_hours = [8, 9, 10, 11, 12, 16, 17, 18, 19]
    available = []

    for hour in candidate_hours:
        if len(available) >= 3:
            break

        slot_start = target_date.replace(hour=hour, minute=0, second=0, microsecond=0)

        # Verificar bloqueo de fin de semana
        if is_blocked_slot(slot_start):
            continue

        # Verificar que no sea en el pasado
        now = datetime.now(LIMA_TZ)
        if slot_start <= now + timedelta(hours=2):
            continue

        slot_end = slot_start + timedelta(hours=1)

        # Consultar disponibilidad en Calendar
        if service:
            try:
                start_utc = slot_start.astimezone(timezone.utc).isoformat()
                end_utc   = slot_end.astimezone(timezone.utc).isoformat()
                events_result = service.freebusy().query(body={
                    "timeMin": start_utc,
                    "timeMax": end_utc,
                    "timeZone": "America/Lima",
                    "items": [{"id": GCAL_CALENDAR_ID}]
                }).execute()
                busy = events_result.get("calendars", {}).get(GCAL_CALENDAR_ID, {}).get("busy", [])
                if busy:
                    continue  # slot ocupado
            except Exception as e:
                log.warning(f"freebusy error: {e}")
                # Si falla la consulta, igual ofrecemos el slot

        available.append({
            "hour": hour,
            "start": slot_start,
            "end": slot_end,
            "label": slot_start.strftime("%-I:%M %p")
        })

    return available


async def create_calendar_event(data: dict, slot_start: datetime) -> tuple[str, str]:
    """
    Crea evento en Google Calendar con Google Meet.
    Retorna (event_id, meet_link).
    """
    loop = asyncio.get_event_loop()

    def _create():
        service = get_calendar_service()
        if not service:
            return None, ""

        slot_end = slot_start + timedelta(hours=1)
        nombre   = data.get("nombre", "Cliente")
        servicio = data.get("servicio", "Consultoría")
        empresa  = data.get("empresa", "") or "Personal"
        desc     = data.get("descripcion", "")
        sender   = data.get("sender_phone", "")

        event_body = {
            "summary": f"Reunión ASFIN — {nombre} ({servicio})",
            "description": (
                f"Cliente: {nombre}\n"
                f"Empresa: {empresa}\n"
                f"Servicio: {servicio}\n"
                f"Descripción: {desc}\n"
                f"WhatsApp: +{sender}\n"
                f"Pago: S/ 100.00 confirmado\n\n"
                f"Generado automáticamente por Bot ASFIN"
            ),
            "start": {
                "dateTime": slot_start.isoformat(),
                "timeZone": "America/Lima",
            },
            "end": {
                "dateTime": slot_end.isoformat(),
                "timeZone": "America/Lima",
            },
            "conferenceData": {
                "createRequest": {
                    "requestId": f"asfin-{sender}-{slot_start.strftime('%Y%m%d%H%M')}",
                    "conferenceSolutionKey": {"type": "hangoutsMeet"},
                }
            },
            "attendees": [
                {"email": JAMES_EMAIL},
            ],
            "reminders": {
                "useDefault": False,
                "overrides": [
                    {"method": "popup", "minutes": 30},
                    {"method": "popup", "minutes": 10},
                ],
            },
        }

        result = service.events().insert(
            calendarId=GCAL_CALENDAR_ID,
            body=event_body,
            conferenceDataVersion=1,
            sendUpdates="all",
        ).execute()

        event_id  = result.get("id", "")
        meet_link = ""
        conf_data = result.get("conferenceData", {})
        for ep in conf_data.get("entryPoints", []):
            if ep.get("entryPointType") == "video":
                meet_link = ep.get("uri", "")
                break

        return event_id, meet_link

    return await loop.run_in_executor(None, _create)


# ─── Helper: external-tool CLI ────────────────────────────────────────────────
async def call_tool(source_id: str, tool_name: str, arguments: dict):
    payload = json.dumps({"source_id": source_id, "tool_name": tool_name, "arguments": arguments})
    proc = await asyncio.create_subprocess_exec(
        "external-tool", "call", payload,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()
    if proc.returncode != 0:
        raise RuntimeError(f"Tool {tool_name} failed: {stderr.decode()[:200]}")
    raw = stdout.decode().strip()
    if raw == "null" or not raw:
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {"raw": raw}


# ─── Helper: enviar mensaje WA ────────────────────────────────────────────────
async def send_wa_message(to: str, text: str):
    url = f"https://graph.facebook.com/v21.0/{PHONE_NUMBER_ID}/messages"
    body = json.dumps({
        "messaging_product": "whatsapp",
        "to": to,
        "type": "text",
        "text": {"body": text}
    }).encode()
    req = urllib.request.Request(
        url, data=body,
        headers={"Authorization": f"Bearer {WA_TOKEN}", "Content-Type": "application/json"},
        method="POST"
    )
    loop = asyncio.get_event_loop()
    def _send():
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read())
    result = await loop.run_in_executor(None, _send)
    log.info(f"WA sent to {to}: {str(result)[:80]}")
    return result


# ─── Helper: reenviar imagen Yape a James ─────────────────────────────────────
async def forward_image_to_james(media_id: str, caption: str):
    media_url_req = urllib.request.Request(
        f"https://graph.facebook.com/v21.0/{media_id}",
        headers={"Authorization": f"Bearer {WA_TOKEN}"},
        method="GET"
    )
    loop = asyncio.get_event_loop()
    def _get_url():
        with urllib.request.urlopen(media_url_req, timeout=15) as r:
            return json.loads(r.read())
    media_info = await loop.run_in_executor(None, _get_url)
    media_dl_url = media_info.get("url", "")
    if not media_dl_url:
        await send_wa_message(JAMES_WA_PERSONAL, f"⚠️ No pude obtener imagen. media_id: {media_id}\n{caption}")
        return

    def _download():
        dl_req = urllib.request.Request(media_dl_url,
                                        headers={"Authorization": f"Bearer {WA_TOKEN}"})
        with urllib.request.urlopen(dl_req, timeout=30) as r:
            return r.read(), r.headers.get("Content-Type", "image/jpeg")
    img_bytes, ctype = await loop.run_in_executor(None, _download)

    boundary = "----ASFINBoundary"
    ext = "jpg" if "jpeg" in ctype else ctype.split("/")[-1]
    body_parts = (
        f"--{boundary}\r\nContent-Disposition: form-data; name=\"messaging_product\"\r\n\r\nwhatsapp\r\n"
        f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"comprobante.{ext}\"\r\nContent-Type: {ctype}\r\n\r\n"
    ).encode() + img_bytes + f"\r\n--{boundary}--\r\n".encode()

    upload_req = urllib.request.Request(
        f"https://graph.facebook.com/v21.0/{PHONE_NUMBER_ID}/media",
        data=body_parts,
        headers={"Authorization": f"Bearer {WA_TOKEN}",
                 "Content-Type": f"multipart/form-data; boundary={boundary}"},
        method="POST"
    )
    def _upload():
        with urllib.request.urlopen(upload_req, timeout=30) as r:
            return json.loads(r.read())
    upload_result = await loop.run_in_executor(None, _upload)
    new_media_id = upload_result.get("id", "")

    if not new_media_id:
        await send_wa_message(JAMES_WA_PERSONAL, f"⚠️ Error subiendo imagen.\n{caption}")
        return

    img_msg = json.dumps({
        "messaging_product": "whatsapp",
        "to": JAMES_WA_PERSONAL,
        "type": "image",
        "image": {"id": new_media_id, "caption": caption}
    }).encode()
    send_img_req = urllib.request.Request(
        f"https://graph.facebook.com/v21.0/{PHONE_NUMBER_ID}/messages",
        data=img_msg,
        headers={"Authorization": f"Bearer {WA_TOKEN}", "Content-Type": "application/json"},
        method="POST"
    )
    def _send_img():
        with urllib.request.urlopen(send_img_req, timeout=15) as r:
            return json.loads(r.read())
    await loop.run_in_executor(None, _send_img)
    log.info("Imagen Yape reenviada a James")


# ─── Helper: notificar a James (CallMeBot fallback) ───────────────────────────
async def notify_james_callmebot(text: str):
    encoded = urllib.parse.quote(text)
    url = f"https://api.callmebot.com/whatsapp.php?phone=51934284408&apikey={CALLMEBOT_KEY}&text={encoded}"
    loop = asyncio.get_event_loop()
    try:
        await loop.run_in_executor(None, lambda: urllib.request.urlopen(url, timeout=15).read())
    except Exception as e:
        log.error(f"CallMeBot error: {e}")


# ─── Helper: enviar correo a James ────────────────────────────────────────────
async def send_email_to_james(subject: str, body_html: str):
    if not GMAIL_USER or not GMAIL_APP_PASS:
        return False
    loop = asyncio.get_event_loop()
    def _send():
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = GMAIL_USER
        msg["To"] = JAMES_EMAIL
        msg.attach(MIMEText(body_html, "html", "utf-8"))
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as s:
            s.login(GMAIL_USER, GMAIL_APP_PASS)
            s.sendmail(GMAIL_USER, JAMES_EMAIL, msg.as_string())
    try:
        await loop.run_in_executor(None, _send)
        return True
    except Exception as e:
        log.error(f"Email error: {e}")
        return False


# ─── Helper: leer hoja ────────────────────────────────────────────────────────
async def get_sheet_rows() -> list[list]:
    result = await call_tool(
        "google_sheets__pipedream", "google_sheets-get-values-in-range",
        {"sheetId": SHEET_ID, "worksheetId": WORKSHEET_ID, "range": "A1:K200"}
    )
    if result is None: return []
    if isinstance(result, list): return result
    return result.get("values", [])

async def update_row_status(sheet_row: int, estado: str, obs_extra: str):
    await call_tool("google_sheets__pipedream", "google_sheets-update-row", {
        "sheetId": SHEET_ID, "worksheetId": WORKSHEET_ID,
        "hasHeaders": True, "row": sheet_row,
        "ESTADO": estado, "OBSERVACIONES": obs_extra
    })


# ══════════════════════════════════════════════════════════════════════════════
# FLUJO ASFIN — Clientes externos
# ══════════════════════════════════════════════════════════════════════════════

def get_session(sender: str) -> dict:
    if sender not in CLIENT_SESSIONS:
        CLIENT_SESSIONS[sender] = {"step": "inicio", "data": {}}
    return CLIENT_SESSIONS[sender]

def reset_session(sender: str):
    CLIENT_SESSIONS.pop(sender, None)


async def handle_asfin(sender: str, msg_type: str, text: str, media_id: str = "") -> None:
    session = get_session(sender)
    step    = session["step"]
    data    = session["data"]
    now     = datetime.now(LIMA_TZ)

    # ── inicio ────────────────────────────────────────────────────────────────
    if step == "inicio":
        session["step"] = "esperar_nombre"
        await send_wa_message(sender,
            "¡Bienvenido/a! 👋\n\n"
            "Soy *ASFIN*, el asistente virtual de *ASFIN Consultoría*.\n\n"
            "Ofrecemos servicios especializados en:\n"
            "1️⃣ Consultoría empresarial\n"
            "2️⃣ Gestión financiera\n"
            "3️⃣ Asesoría en contrataciones y arbitraje\n\n"
            "Para comenzar, ¿cuál es su nombre completo?"
        )
        return

    # ── esperar nombre ────────────────────────────────────────────────────────
    if step == "esperar_nombre":
        data["nombre"] = text.strip()
        session["step"] = "esperar_empresa"
        await send_wa_message(sender,
            f"Mucho gusto, *{data['nombre']}* 😊\n\n"
            "¿Representa usted a alguna empresa u organización?\n"
            "_Si es a título personal, escriba *personal*._"
        )
        return

    # ── esperar empresa ───────────────────────────────────────────────────────
    if step == "esperar_empresa":
        emp = text.strip()
        data["empresa"] = "" if emp.lower() == "personal" else emp
        session["step"] = "esperar_servicio"
        await send_wa_message(sender,
            "¿Qué servicio le interesa?\n\n"
            "1️⃣ Consultoría empresarial\n"
            "2️⃣ Gestión financiera\n"
            "3️⃣ Asesoría en contrataciones y arbitraje\n\n"
            "_Responda con el número (1, 2 o 3)_"
        )
        return

    # ── esperar servicio ──────────────────────────────────────────────────────
    if step == "esperar_servicio":
        opcion = text.strip()
        if opcion not in SERVICIOS:
            await send_wa_message(sender,
                "Por favor responda con *1*, *2* o *3*:\n\n"
                "1️⃣ Consultoría empresarial\n"
                "2️⃣ Gestión financiera\n"
                "3️⃣ Asesoría en contrataciones y arbitraje"
            )
            return
        data["servicio"] = SERVICIOS[opcion]
        session["step"] = "esperar_descripcion"
        await send_wa_message(sender,
            f"Excelente, *{data['servicio']}* ✅\n\n"
            "Cuéntenos brevemente sobre su proyecto o necesidad:\n"
            "_¿Cuál es la situación que desea resolver?_"
        )
        return

    # ── esperar descripción ───────────────────────────────────────────────────
    if step == "esperar_descripcion":
        data["descripcion"] = text.strip()
        session["step"] = "esperar_reunion"
        await send_wa_message(sender,
            "Gracias por la información 🙏\n\n"
            "¿Le gustaría agendar una *reunión con nuestro consultor* para evaluar su caso?\n\n"
            "✅ *Sí* — Agendamos una reunión (S/ 100.00 soles)\n"
            "📋 *No* — Solo deseo recibir una cotización\n\n"
            "_Responda *sí* o *no*_"
        )
        return

    # ── esperar decisión reunión ──────────────────────────────────────────────
    if step == "esperar_reunion":
        resp = text.strip().lower()
        if resp in ["no", "solo cotización", "solo cotizacion", "cotizacion", "cotización"]:
            await notificar_james_nuevo_cliente(sender, data, reunion=False, now=now)
            reset_session(sender)
            await send_wa_message(sender,
                f"Perfecto, *{data['nombre']}* 😊\n\n"
                "Hemos registrado su consulta. Nuestro equipo le enviará una "
                "*cotización personalizada* a la brevedad.\n\n"
                "📞 Si tiene alguna duda adicional, no dude en escribirnos.\n\n"
                "*ASFIN Consultoría* — A su servicio 🏢"
            )
            return
        if resp in ["sí", "si", "s", "yes", "claro", "ok", "quiero", "deseo"]:
            session["step"] = "esperar_dia"
            await send_wa_message(sender,
                "¡Excelente! 📅\n\n"
                "La reunión tiene un costo de *S/ 100.00 soles* (pago previo).\n\n"
                "¿Qué día le resultaría conveniente?\n"
                "_Indíquenos un día. Ejemplos: *lunes*, *viernes 20*, *20 de marzo*_\n\n"
                "📌 Horarios de atención:\n"
                "• Lunes a viernes: 8:00 AM – 1:00 PM y 4:00 PM – 8:00 PM\n"
                "• Sábados: 8:00 AM – 6:00 PM\n"
                "• Domingos y viernes desde 6:00 PM: no disponible"
            )
            return
        await send_wa_message(sender,
            "Por favor responda *sí* para agendar reunión o *no* para solo recibir cotización."
        )
        return

    # ── esperar día ───────────────────────────────────────────────────────────
    if step == "esperar_dia":
        dia_str = text.strip()
        target_date = parse_dia_to_date(dia_str, now)

        if not target_date:
            await send_wa_message(sender,
                "No pude identificar la fecha. Por favor indique un día más claro.\n"
                "_Ejemplos: *lunes*, *martes*, *20 de marzo*, *mañana*_"
            )
            return

        # Verificar bloqueo viernes 6pm - sábado 6pm / domingo
        if is_blocked_slot(target_date.replace(hour=9)):
            await send_wa_message(sender,
                f"Lo sentimos, el *{dia_str}* no está disponible para reuniones.\n\n"
                "📌 Horarios de atención:\n"
                "• Lunes a viernes: 8:00 AM – 1:00 PM y 4:00 PM – 8:00 PM\n"
                "• Sábados: 8:00 AM – 6:00 PM\n\n"
                "¿Puede sugerir otro día?"
            )
            return

        # Buscar slots disponibles en Calendar
        loop = asyncio.get_event_loop()
        service = await loop.run_in_executor(None, get_calendar_service)
        slots = await loop.run_in_executor(None, lambda: get_available_slots(target_date, service))

        if not slots:
            await send_wa_message(sender,
                f"No encontré horarios disponibles para el *{dia_str}*.\n\n"
                "La agenda está completa ese día. ¿Puede sugerir otro día?\n"
                "_Recuerde: atendemos lunes a viernes 8am-1pm y 4pm-8pm, sábados 8am-6pm._"
            )
            return

        # Guardar slots en sesión
        data["dia_str"]      = dia_str
        data["target_date"]  = target_date.isoformat()
        data["slots"]        = [{"label": s["label"], "start": s["start"].isoformat(), "end": s["end"].isoformat()} for s in slots]
        session["step"] = "esperar_horario"

        opciones = "\n".join([f"{i+1}️⃣ {s['label']}" for i, s in enumerate(slots)])
        await send_wa_message(sender,
            f"Para el *{dia_str}*, estos son los horarios disponibles:\n\n"
            f"{opciones}\n\n"
            "_Responda con el número de su preferencia_"
        )
        return

    # ── esperar horario ───────────────────────────────────────────────────────
    if step == "esperar_horario":
        opcion = text.strip()
        slots  = data.get("slots", [])
        num_slots = len(slots)

        # Horario fuera de rango → ofrecer a James para aprobación
        if opcion not in [str(i+1) for i in range(num_slots)]:
            # Verificar si el cliente pide un horario específico distinto
            hora_match = re.search(r"(\d{1,2})(?::(\d{2}))?\s*(am|pm)?", opcion, re.IGNORECASE)
            if hora_match and num_slots > 0:
                # Guardar solicitud especial y notificar a James
                data["horario_especial"] = opcion
                session["step"] = "esperando_aprobacion_horario"
                codigo = sender[-4:]
                PENDING_CONFIRM[f"hora_{codigo}"] = {**data, "sender": sender, "tipo": "horario_especial"}
                try:
                    await send_wa_message(JAMES_WA_PERSONAL,
                        f"⏰ SOLICITUD HORARIO ESPECIAL\n\n"
                        f"👤 {data.get('nombre','?')}\n"
                        f"📅 {data.get('dia_str','?')}\n"
                        f"🕐 Horario solicitado: {opcion}\n"
                        f"📋 {data.get('servicio','?')}\n"
                        f"📱 {sender}\n\n"
                        f"Para aprobar: *aprobar hora_{codigo}*\n"
                        f"Para rechazar: *rechazar hora_{codigo}*"
                    )
                except Exception:
                    pass
                await send_wa_message(sender,
                    "Su solicitud de horario especial ha sido enviada a nuestro consultor.\n\n"
                    "En breve recibirá confirmación. ⏳"
                )
                return
            # Respuesta inválida normal
            opciones = "\n".join([f"{i+1}️⃣ {s['label']}" for i, s in enumerate(slots)])
            await send_wa_message(sender,
                f"Por favor responda con un número del 1 al {num_slots}:\n\n{opciones}"
            )
            return

        idx_sel  = int(opcion) - 1
        slot_sel = slots[idx_sel]
        data["horario_label"] = slot_sel["label"]
        data["slot_start"]    = slot_sel["start"]
        data["slot_end"]      = slot_sel["end"]
        session["step"] = "esperar_yape"

        await send_wa_message(sender,
            f"Perfecto 👍 Su reunión está *pre-agendada*:\n\n"
            f"📅 *{data['dia_str']}* a las *{slot_sel['label']}*\n\n"
            f"Para confirmar la reserva, realice el pago de *S/ 100.00* vía:\n\n"
            f"💚 *YAPE* o 💜 *PLIN* al número: *934 284 408*\n"
            f"👤 Titular: *James Quispe*\n\n"
            f"Una vez realizado el pago, *envíe la captura de pantalla del comprobante* por este chat.\n\n"
            f"_El pago confirma su reserva._"
        )
        return

    # ── esperar imagen Yape/Plin ──────────────────────────────────────────────
    if step == "esperar_yape":
        if msg_type == "image":
            data["media_id"]      = media_id
            data["sender_phone"]  = sender
            session["step"] = "esperando_validacion"
            codigo = sender[-4:]
            PENDING_CONFIRM[codigo] = {**data, "sender": sender}

            caption = (
                f"🔔 PAGO RECIBIDO — CONFIRMAR REUNIÓN\n\n"
                f"👤 {data.get('nombre','?')}\n"
                f"🏢 {data.get('empresa','Personal')}\n"
                f"📋 {data.get('servicio','?')}\n"
                f"📅 {data.get('dia_str','?')} {data.get('horario_label','?')}\n"
                f"📱 +{sender}\n\n"
                f"✅ Para confirmar responde:\n"
                f"*confirmar {codigo}*"
            )
            PENDING_CONFIRM[codigo] = {**data, "sender": sender}
            try:
                await forward_image_to_james(media_id, caption)
            except Exception as e:
                log.error(f"forward_image error: {e}")
                await send_wa_message(JAMES_WA_PERSONAL,
                    f"🔔 PAGO RECIBIDO (imagen no disponible)\n\n"
                    f"👤 {data.get('nombre','?')} | {data.get('empresa','Personal')}\n"
                    f"📅 {data.get('dia_str','?')} {data.get('horario_label','?')}\n"
                    f"📱 +{sender}\n\n*confirmar {codigo}* para validar"
                )
            await notificar_james_nuevo_cliente(sender, data, reunion=True, now=now)
            await send_wa_message(sender,
                "¡Comprobante recibido! 📸✅\n\n"
                "Estamos *validando su pago*. En breve recibirá la confirmación oficial con el enlace de la reunión.\n\n"
                "_Tiempo estimado: menos de 30 minutos en horario de oficina._"
            )
            return
        else:
            await send_wa_message(sender,
                "Por favor envíe la *captura de pantalla del comprobante* 📸\n\n"
                "💚 *YAPE* o 💜 *PLIN* al número *934 284 408*\n"
                "👤 Titular: *James Quispe*\n"
                "💰 Monto: *S/ 100.00*"
            )
            return

    # ── esperando validación ──────────────────────────────────────────────────
    if step in ("esperando_validacion", "esperando_aprobacion_horario", "completado"):
        await send_wa_message(sender,
            "Su solicitud está siendo procesada ⏳\n\n"
            "Recibirá la confirmación en breve.\n"
            "_Si tiene alguna consulta adicional, escríbanos._"
        )
        return


async def notificar_james_nuevo_cliente(sender: str, data: dict, reunion: bool, now: datetime):
    nombre   = data.get("nombre", "?")
    empresa  = data.get("empresa", "") or "Personal"
    servicio = data.get("servicio", "?")
    desc     = data.get("descripcion", "?")
    dia      = data.get("dia_str", "")
    horario  = data.get("horario_label", "")
    fecha    = now.strftime("%d/%m/%Y %H:%M")
    tipo     = "REUNIÓN + COTIZACIÓN" if reunion else "SOLO COTIZACIÓN"

    subject = f"🔔 ASFIN — Nuevo cliente: {nombre} ({tipo})"
    html = f"""
    <html><body style="font-family:Arial,sans-serif;max-width:600px;margin:auto">
    <h2 style="color:#2c5282">🔔 Nuevo cliente — ASFIN Consultoría</h2>
    <table style="border-collapse:collapse;width:100%">
      <tr><td style="padding:8px;background:#ebf8ff;font-weight:bold">Nombre</td><td style="padding:8px">{nombre}</td></tr>
      <tr><td style="padding:8px;background:#ebf8ff;font-weight:bold">Empresa</td><td style="padding:8px">{empresa}</td></tr>
      <tr><td style="padding:8px;background:#ebf8ff;font-weight:bold">WhatsApp</td><td style="padding:8px">+{sender}</td></tr>
      <tr><td style="padding:8px;background:#ebf8ff;font-weight:bold">Servicio</td><td style="padding:8px">{servicio}</td></tr>
      <tr><td style="padding:8px;background:#ebf8ff;font-weight:bold">Descripción</td><td style="padding:8px">{desc}</td></tr>
      <tr><td style="padding:8px;background:#ebf8ff;font-weight:bold">Tipo</td><td style="padding:8px"><b>{tipo}</b></td></tr>
      {'<tr><td style="padding:8px;background:#ebf8ff;font-weight:bold">Reunión</td><td style="padding:8px">' + dia + ' ' + horario + '</td></tr>' if reunion else ''}
      <tr><td style="padding:8px;background:#ebf8ff;font-weight:bold">Fecha contacto</td><td style="padding:8px">{fecha}</td></tr>
    </table>
    {'<p><b>Para confirmar: responde <code>confirmar ' + sender[-4:] + '</code> en WhatsApp</b></p>' if reunion else '<p>Prepara la cotización y responde al cliente.</p>'}
    </body></html>
    """
    await send_email_to_james(subject, html)

    wa_msg = (
        f"🔔 ASFIN — Nuevo cliente\n\n"
        f"👤 {nombre} | {empresa}\n📋 {servicio}\n"
        f"📝 {desc[:80]}\n📱 +{sender}\n🗓️ {fecha}\n"
    )
    if reunion:
        wa_msg += f"📅 Reunión: {dia} {horario}\n"
    wa_msg += f"\nTipo: *{tipo}*"
    if reunion:
        wa_msg += f"\n\n✅ Para confirmar: *confirmar {sender[-4:]}*"
    try:
        await send_wa_message(JAMES_WA_PERSONAL, wa_msg)
    except Exception:
        await notify_james_callmebot(wa_msg)


# ══════════════════════════════════════════════════════════════════════════════
# COMANDOS JAMES
# ══════════════════════════════════════════════════════════════════════════════

async def process_james_command(sender: str, text: str) -> str:
    text_lower = text.lower().strip()
    now_lima   = datetime.now(LIMA_TZ)

    # CONFIRMAR reunión cliente
    match_confirm = re.search(r"confirmar\s+(\w+)", text_lower)
    if match_confirm:
        return await cmd_confirmar_reunion(match_confirm.group(1), now_lima)

    # APROBAR / RECHAZAR horario especial
    match_aprobar = re.search(r"(aprobar|rechazar)\s+(hora_\w+)", text_lower)
    if match_aprobar:
        accion = match_aprobar.group(1)
        codigo = match_aprobar.group(2)
        return await cmd_gestionar_horario_especial(accion, codigo, now_lima)

    # RESUMEN
    if any(w in text_lower for w in ["resumen", "estado", "pendientes", "status", "cuántos", "cuantos"]):
        return await cmd_resumen(now_lima)

    # RESOLVER N°X
    match_resolve = re.search(r"(resuelto|resolver|completar|marcar|cerrar?).*?(\d+)", text_lower)
    if match_resolve:
        return await cmd_resolver(int(match_resolve.group(2)), now_lima)

    # VER N°X
    match_ver = re.search(r"(ver|detalle|info).*?(\d+)", text_lower)
    if match_ver:
        return await cmd_ver_fila(int(match_ver.group(2)))

    # URGENTES
    if any(w in text_lower for w in ["urgente", "urgentes", "crítico", "critico"]):
        return await cmd_urgentes()

    # TAREAS
    if any(w in text_lower for w in ["tareas", "google tasks", "mis tareas", "task"]):
        return await cmd_listar_tareas()

    # AGENDA
    if any(w in text_lower for w in ["agenda", "crear tarea", "nueva tarea", "agregar tarea"]):
        return await cmd_crear_tarea(text, now_lima)

    # HOJA
    if any(w in text_lower for w in ["hoja", "sheet", "link", "url", "enlace"]):
        return f"📊 Hoja de Control:\nhttps://docs.google.com/spreadsheets/d/{SHEET_ID}/edit"

    # AYUDA
    if any(w in text_lower for w in ["ayuda", "help", "comandos", "qué puedes", "que puedes"]):
        return cmd_ayuda()

    return (f"Hola James 👋\n\nRecibí: \"{text[:80]}\"\n\n"
            f"Escribe *ayuda* para ver los comandos disponibles.")


async def cmd_confirmar_reunion(codigo: str, now_lima: datetime) -> str:
    if codigo not in PENDING_CONFIRM:
        return (f"Hola James ❌ No encontré reserva con código *{codigo}*.\n"
                f"Los códigos son los últimos 4 dígitos del número del cliente.")

    client_data = PENDING_CONFIRM.pop(codigo)
    sender      = client_data["sender"]
    nombre      = client_data.get("nombre", "?")
    servicio    = client_data.get("servicio", "?")
    dia         = client_data.get("dia_str", "?")
    horario     = client_data.get("horario_label", "?")
    slot_start_str = client_data.get("slot_start", "")

    # Crear evento en Google Calendar
    meet_link  = ""
    event_link = ""
    if slot_start_str:
        try:
            slot_start = datetime.fromisoformat(slot_start_str)
            if slot_start.tzinfo is None:
                slot_start = slot_start.replace(tzinfo=LIMA_TZ)
            client_data["sender_phone"] = sender
            event_id, meet_link = await create_calendar_event(client_data, slot_start)
            if event_id:
                event_link = f"https://calendar.google.com/calendar/event?eid={event_id}"
                log.info(f"Evento Calendar creado: {event_id}, Meet: {meet_link}")
        except Exception as e:
            log.error(f"create_calendar_event error: {e}", exc_info=True)

    if sender in CLIENT_SESSIONS:
        CLIENT_SESSIONS[sender]["step"] = "completado"

    # Mensaje al cliente con Meet link
    meet_txt = f"\n\n🎥 *Enlace Google Meet:*\n{meet_link}" if meet_link else ""
    cal_txt  = f"\n📅 *Ver en Calendar:*\n{event_link}" if event_link else ""

    try:
        await send_wa_message(sender,
            f"✅ *¡REUNIÓN CONFIRMADA!*\n\n"
            f"Estimado/a *{nombre}*,\n\n"
            f"Su pago ha sido verificado y su reunión ha quedado *oficialmente agendada*:\n\n"
            f"📅 *Fecha:* {dia}\n"
            f"⏰ *Hora:* {horario}\n"
            f"📋 *Servicio:* {servicio}"
            f"{meet_txt}"
            f"{cal_txt}\n\n"
            f"Le esperamos. ¡Hasta pronto! 🏢\n"
            f"*ASFIN Consultoría*"
        )
    except Exception as e:
        return f"Hola James ❌ Error enviando confirmación al cliente: {str(e)[:80]}"

    meet_info = f"\n🎥 Meet: {meet_link}" if meet_link else "\n⚠️ Meet no generado (verificar Calendar)"
    return (
        f"Hola James ✅ REUNIÓN CONFIRMADA Y AGENDADA\n\n"
        f"👤 {nombre}\n"
        f"📅 {dia} {horario}\n"
        f"📋 {servicio}"
        f"{meet_info}\n\n"
        f"El cliente ya recibió su confirmación con el link."
    )


async def cmd_gestionar_horario_especial(accion: str, codigo: str, now_lima: datetime) -> str:
    if codigo not in PENDING_CONFIRM:
        return f"Hola James ❌ No encontré solicitud con código *{codigo}*."

    client_data = PENDING_CONFIRM[codigo]
    sender      = client_data["sender"]
    nombre      = client_data.get("nombre", "?")
    dia         = client_data.get("dia_str", "?")
    horario_esp = client_data.get("horario_especial", "?")

    if accion == "rechazar":
        PENDING_CONFIRM.pop(codigo)
        if sender in CLIENT_SESSIONS:
            CLIENT_SESSIONS[sender]["step"] = "esperar_horario"
        await send_wa_message(sender,
            f"Lo sentimos, el horario *{horario_esp}* no está disponible para el *{dia}*.\n\n"
            "Por favor elija uno de los horarios disponibles que le ofrecimos anteriormente.\n"
            "_Escriba 1, 2 o 3 para seleccionar._"
        )
        return f"Hola James ℹ️ Horario especial rechazado. El cliente debe elegir de los disponibles."

    # Aprobar: continuar con ese horario como si fuera normal
    # Parseamos la hora especial
    hora_match = re.search(r"(\d{1,2})(?::(\d{2}))?\s*(am|pm)?", horario_esp, re.IGNORECASE)
    hora = 9  # default
    if hora_match:
        hora = int(hora_match.group(1))
        ampm = (hora_match.group(3) or "").lower()
        if ampm == "pm" and hora < 12:
            hora += 12
        elif ampm == "am" and hora == 12:
            hora = 0

    target_date = datetime.fromisoformat(client_data.get("target_date", now_lima.isoformat()))
    if target_date.tzinfo is None:
        target_date = target_date.replace(tzinfo=LIMA_TZ)
    slot_start = target_date.replace(hour=hora, minute=0, second=0, microsecond=0)
    slot_end   = slot_start + timedelta(hours=1)
    label      = slot_start.strftime("%-I:%M %p")

    PENDING_CONFIRM.pop(codigo)
    # Crear nuevo código para confirmación de pago
    new_code = sender[-4:]
    client_data["horario_label"] = label
    client_data["slot_start"]    = slot_start.isoformat()
    client_data["slot_end"]      = slot_end.isoformat()
    PENDING_CONFIRM[new_code] = client_data

    if sender in CLIENT_SESSIONS:
        CLIENT_SESSIONS[sender]["step"] = "esperar_yape"
        CLIENT_SESSIONS[sender]["data"] = client_data

    await send_wa_message(sender,
        f"¡Buenas noticias! 🎉\n\n"
        f"El horario *{label}* del *{dia}* ha sido *aprobado* para usted.\n\n"
        f"Para confirmar la reserva, realice el pago de *S/ 100.00* vía:\n\n"
        f"💚 *YAPE* o 💜 *PLIN* al número: *934 284 408*\n"
        f"👤 Titular: *James Quispe*\n\n"
        f"Una vez pagado, *envíe la captura del comprobante* por este chat."
    )
    return f"Hola James ✅ Horario especial aprobado. El cliente procederá con el pago."


# ─── Comandos gestión (James) ──────────────────────────────────────────────────

async def cmd_resumen(now_lima: datetime) -> str:
    try:
        rows = await get_sheet_rows()
        if len(rows) <= 1:
            return "Hola James ✅ No hay registros en la hoja de control."
        conteo = {"CONSULT01": 0, "CONSULT02": 0, "CONSULT03": 0, "CONSULT04": 0, "PERSONAL": 0}
        urgentes, vencen_hoy = [], []
        hoy_str = now_lima.strftime("%d/%m/%Y")
        total = 0
        for row in rows[1:]:
            if len(row) < 10: continue
            if row[9] not in ("Pendiente", "En proceso"): continue
            total += 1
            if row[1] in conteo: conteo[row[1]] += 1
            cat  = row[5] if len(row) > 5 else ""
            flim = row[7] if len(row) > 7 else ""
            corto = (row[4] if len(row) > 4 else "?")[:45]
            if "URGENTE" in cat.upper(): urgentes.append(corto)
            if flim == hoy_str: vencen_hoy.append(corto)
        return (
            f"Hola James 📊 RESUMEN ACTUAL\n📅 {hoy_str}\n\n"
            f"🏢 CONSULT01 (SaludAllinta) — {conteo['CONSULT01']} pendientes\n"
            f"🏢 CONSULT02 (SaludOcobamba) — {conteo['CONSULT02']} pendientes\n"
            f"🏢 CONSULT03 (SuperObras) — {conteo['CONSULT03']} pendientes\n"
            f"🏢 CONSULT04 (IE Mayapo) — {conteo['CONSULT04']} pendientes\n"
            f"👤 PERSONAL — {conteo['PERSONAL']} pendientes\n"
            f"─────────\n📌 TOTAL: {total} pendientes\n\n"
            f"🔴 URGENTES: {', '.join(urgentes) if urgentes else 'ninguno'}\n"
            f"⚠️ VENCEN HOY: {', '.join(vencen_hoy) if vencen_hoy else 'ninguno'}\n\n"
            f"📊 https://docs.google.com/spreadsheets/d/{SHEET_ID}/edit"
        )
    except Exception as e:
        return f"Hola James ❌ Error: {str(e)[:100]}"

async def cmd_resolver(n: int, now_lima: datetime) -> str:
    try:
        rows = await get_sheet_rows()
        for idx, row in enumerate(rows[1:], start=2):
            if row and str(row[0]) == str(n):
                estado  = row[9] if len(row) > 9 else "?"
                asunto  = row[4] if len(row) > 4 else "?"
                negocio = row[1] if len(row) > 1 else "?"
                obs     = row[10] if len(row) > 10 else ""
                if estado == "Resuelto":
                    return f"Hola James ℹ️ N°{n} ya está *Resuelto*.\n📌 {asunto}"
                fecha_str = now_lima.strftime("%d/%m/%Y")
                obs_nueva = (obs + f" | Resuelto vía WhatsApp el {fecha_str}").strip(" |")
                await update_row_status(idx, "Resuelto", obs_nueva)
                return (f"Hola James ✅ RESUELTO\n\n📌 N°{n}: {asunto}\n🏢 {negocio}\n📅 {fecha_str}\n\n"
                        f"La hoja fue actualizada.\n📊 https://docs.google.com/spreadsheets/d/{SHEET_ID}/edit")
        return f"Hola James ❌ No encontré el registro N°{n}."
    except Exception as e:
        return f"Hola James ❌ Error: {str(e)[:100]}"

async def cmd_ver_fila(n: int) -> str:
    try:
        rows = await get_sheet_rows()
        for row in rows[1:]:
            if row and str(row[0]) == str(n):
                def g(i): return row[i] if len(row) > i else "?"
                return (f"Hola James 📋 REGISTRO N°{g(0)}\n\n"
                        f"🏢 {g(1)}\n📅 {g(2)}\n👤 De: {g(3)}\n📌 {g(4)}\n"
                        f"📂 {g(5)}\n⚡ {g(6)}\n📆 {g(7)}\n✅ {g(8)}\n🔄 {g(9)}\n📝 {g(10) or 'ninguna'}")
        return f"Hola James ❌ No encontré N°{n}."
    except Exception as e:
        return f"Hola James ❌ Error: {str(e)[:100]}"

async def cmd_urgentes() -> str:
    try:
        rows = await get_sheet_rows()
        urgentes = [r for r in rows[1:] if len(r) >= 10 and "URGENTE" in str(r[5]).upper() and r[9] in ("Pendiente", "En proceso")]
        if not urgentes:
            return "Hola James ✅ No hay urgentes pendientes."
        lines = [f"Hola James 🔴 URGENTES ({len(urgentes)})\n"]
        for r in urgentes:
            lines.append(f"🔴 N°{r[0]}: {r[4][:45]}\n   {r[1]} | Límite: {r[7] if len(r)>7 else '?'}")
        lines.append(f"\n📊 https://docs.google.com/spreadsheets/d/{SHEET_ID}/edit")
        return "\n\n".join(lines)
    except Exception as e:
        return f"Hola James ❌ Error: {str(e)[:100]}"

async def cmd_listar_tareas() -> str:
    try:
        result = await call_tool("google_tasks__pipedream", "google_tasks-list-tasks",
                                 {"taskListId": TASK_LIST_ID, "showCompleted": False, "maxResults": 20})
        if not result:
            return "Hola James ✅ No tienes tareas pendientes."
        items = result if isinstance(result, list) else result.get("items", [])
        items = [t for t in items if t.get("status") != "completed"]
        if not items:
            return "Hola James ✅ No tienes tareas pendientes."
        lines = [f"Hola James 📋 TAREAS ({len(items)})\n"]
        for t in items[:15]:
            due = t.get("due", "")[:10] if t.get("due") else "sin fecha"
            lines.append(f"⏳ {t.get('title','?')[:60]}\n   📆 {due}")
        lines.append("\n🔗 https://tasks.google.com/")
        return "\n\n".join(lines)
    except Exception as e:
        return f"Hola James ❌ Error: {str(e)[:100]}"

async def cmd_crear_tarea(text: str, now_lima: datetime) -> str:
    asunto = text.strip()
    for kw in ["agenda", "crear tarea", "nueva tarea", "agregar tarea"]:
        if kw in asunto.lower():
            asunto = asunto[asunto.lower().find(kw)+len(kw):].strip(": ")
            break
    if not asunto:
        return "Hola James ℹ️ Escribe el asunto.\nEjemplo: *agenda reunión OSCE el lunes*"
    due   = (now_lima + timedelta(days=3)).strftime("%Y-%m-%dT00:00:00Z")
    title = f"🟠 [Personal] {asunto[:80]}"
    try:
        await call_tool("google_tasks__pipedream", "google_tasks-create-task",
                        {"taskListId": TASK_LIST_ID, "title": title,
                         "notes": f"Creada vía WhatsApp el {now_lima.strftime('%d/%m/%Y %H:%M')}",
                         "due": due, "status": "needsAction"})
        return (f"Hola James ✅ TAREA CREADA\n\n📌 {title}\n"
                f"📆 Vence: {(now_lima + timedelta(days=3)).strftime('%d/%m/%Y')}\n"
                f"📋 Lista: Mis tareas\n\n🔗 https://tasks.google.com/")
    except Exception as e:
        return f"Hola James ❌ Error: {str(e)[:100]}"

def cmd_ayuda() -> str:
    return (
        "Hola James 📖 COMANDOS\n\n"
        "📊 *resumen* — Pendientes por negocio\n"
        "🔴 *urgentes* — Solo urgentes\n"
        "📋 *tareas* — Google Tasks\n"
        "📋 *ver N°5* — Detalle del N°5\n"
        "✅ *resolver N°5* — Marcar N°5 Resuelto\n"
        "➕ *agenda [asunto]* — Nueva tarea\n"
        "🔗 *hoja* — Link a la hoja\n"
        "✅ *confirmar XXXX* — Confirmar pago y crear reunión\n"
        "⏰ *aprobar hora_XXXX* — Aprobar horario especial\n"
        "❌ *rechazar hora_XXXX* — Rechazar horario especial\n\n"
        "Ejemplo:\n  confirmar 4408\n  aprobar hora_4408"
    )


# ══════════════════════════════════════════════════════════════════════════════
# ENDPOINTS
# ══════════════════════════════════════════════════════════════════════════════

@app.get("/webhook")
async def verify_webhook(
    hub_mode: Optional[str] = Query(None, alias="hub.mode"),
    hub_challenge: Optional[str] = Query(None, alias="hub.challenge"),
    hub_verify_token: Optional[str] = Query(None, alias="hub.verify_token"),
):
    if hub_mode == "subscribe" and hub_verify_token == VERIFY_TOKEN:
        return PlainTextResponse(hub_challenge or "")
    raise HTTPException(status_code=403, detail="Verification failed")


@app.post("/webhook")
async def receive_webhook(request: Request):
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON")

    log.info(f"Webhook POST: {json.dumps(body)[:300]}")

    try:
        changes  = body.get("entry", [{}])[0].get("changes", [{}])[0].get("value", {})
        messages = changes.get("messages", [])
        for msg in messages:
            sender   = msg.get("from", "")
            msg_type = msg.get("type", "text")
            text     = ""
            media_id = ""
            if msg_type == "text":
                text = msg.get("text", {}).get("body", "").strip()
            elif msg_type == "image":
                media_id = msg.get("image", {}).get("id", "")
                text     = msg.get("image", {}).get("caption", "").strip()
            if not sender:
                continue
            if sender == JAMES_WA_PERSONAL:
                asyncio.create_task(handle_james_message(sender, text))
            else:
                asyncio.create_task(handle_client_message(sender, msg_type, text, media_id))
    except Exception as e:
        log.error(f"Webhook parse error: {e}", exc_info=True)

    return {"status": "ok"}


async def handle_james_message(sender: str, text: str):
    try:
        response = await process_james_command(sender, text)
        await send_wa_message(sender, response)
    except Exception as e:
        log.error(f"handle_james: {e}", exc_info=True)
        try:
            await send_wa_message(sender, f"Hola James ❌ Error: {str(e)[:80]}")
        except Exception:
            pass

async def handle_client_message(sender: str, msg_type: str, text: str, media_id: str):
    try:
        await handle_asfin(sender, msg_type, text, media_id)
    except Exception as e:
        log.error(f"handle_client {sender}: {e}", exc_info=True)
        try:
            await send_wa_message(sender,
                "Lo sentimos, ocurrió un error. Por favor intente nuevamente.\n🏢 *ASFIN Consultoría*")
        except Exception:
            pass


@app.get("/health")
async def health():
    service = get_calendar_service()
    return {
        "status": "ok",
        "server": "WA Webhook — Control Correos James + ASFIN v2",
        "time_lima": datetime.now(LIMA_TZ).strftime("%Y-%m-%d %H:%M:%S"),
        "calendar_connected": service is not None,
        "active_sessions": len(CLIENT_SESSIONS),
        "pending_confirmations": len(PENDING_CONFIRM),
    }

@app.get("/")
async def root():
    return {
        "name": "WhatsApp Webhook — James + ASFIN v2",
        "status": "running",
        "features": ["gestión_correos", "captación_clientes", "google_calendar", "google_meet"],
    }

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000, log_level="info")
