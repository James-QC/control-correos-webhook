#!/usr/bin/env python3
"""
WhatsApp Webhook Server — Control Correos James + Bot ASFIN
- Números conocidos (James): comandos de gestión
- Números desconocidos: flujo de captación ASFIN
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
from email.mime.base import MIMEBase
from email import encoders
from typing import Optional

import uvicorn
from fastapi import FastAPI, HTTPException, Request, Query
from fastapi.responses import PlainTextResponse

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
# Para envío de correo vía Gmail SMTP (opcional — si no se configura, se notifica por WA)
GMAIL_USER        = os.getenv("GMAIL_USER",        "")
GMAIL_APP_PASS    = os.getenv("GMAIL_APP_PASS",    "")

LIMA_TZ = timezone(timedelta(hours=-5))

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("wa-webhook")

app = FastAPI(title="WA Webhook — Control Correos James + ASFIN")

# ─── Sesiones clientes externos ───────────────────────────────────────────────
# Estructura: { "51912345678": { "step": "...", "data": {...} } }
CLIENT_SESSIONS: dict[str, dict] = {}

# Pendientes de confirmación de James: { "51912345678": { ...datos_cliente... } }
PENDING_CONFIRM: dict[str, dict] = {}

SERVICIOS = {
    "1": "Consultoría empresarial",
    "2": "Gestión financiera",
    "3": "Asesoría en contrataciones y arbitraje",
}

HORARIOS = ["9:00 AM", "11:00 AM", "3:00 PM"]

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
        err = stderr.decode()
        log.error(f"Tool error {tool_name}: {err}")
        raise RuntimeError(f"Tool {tool_name} failed: {err}")
    raw = stdout.decode().strip()
    if raw == "null" or not raw:
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {"raw": raw}

# ─── Helper: enviar mensaje WA Business API ───────────────────────────────────
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
    log.info(f"WA sent to {to}: {str(result)[:100]}")
    return result

# ─── Helper: reenviar imagen (media_id) a James ───────────────────────────────
async def forward_image_to_james(media_id: str, caption: str):
    """Descarga la imagen de Meta y la reenvía a James via WA."""
    # Paso 1: obtener URL de la imagen
    media_url_req = urllib.request.Request(
        f"https://graph.facebook.com/v21.0/{media_id}",
        headers={"Authorization": f"Bearer {WA_TOKEN}"},
        method="GET"
    )
    loop = asyncio.get_event_loop()
    def _get_media_url():
        with urllib.request.urlopen(media_url_req, timeout=15) as r:
            return json.loads(r.read())
    media_info = await loop.run_in_executor(None, _get_media_url)
    media_download_url = media_info.get("url", "")

    if not media_download_url:
        await send_wa_message(JAMES_WA_PERSONAL,
            f"⚠️ No pude obtener la imagen del comprobante. media_id: {media_id}\n{caption}")
        return

    # Paso 2: descargar bytes de la imagen
    dl_req = urllib.request.Request(
        media_download_url,
        headers={"Authorization": f"Bearer {WA_TOKEN}"},
        method="GET"
    )
    def _download():
        with urllib.request.urlopen(dl_req, timeout=30) as r:
            return r.read(), r.headers.get("Content-Type", "image/jpeg")
    img_bytes, content_type = await loop.run_in_executor(None, _download)

    # Paso 3: reenviar la imagen a James via WA (como imagen con caption)
    # Necesitamos hacer upload a Meta primero
    upload_url = f"https://graph.facebook.com/v21.0/{PHONE_NUMBER_ID}/media"
    boundary = "----FormBoundary7MA4YWxkTrZu0gW"
    ext = "jpg" if "jpeg" in content_type else content_type.split("/")[-1]
    body_parts = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="messaging_product"\r\n\r\n'
        f"whatsapp\r\n"
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="file"; filename="comprobante.{ext}"\r\n'
        f"Content-Type: {content_type}\r\n\r\n"
    ).encode() + img_bytes + f"\r\n--{boundary}--\r\n".encode()

    upload_req = urllib.request.Request(
        upload_url, data=body_parts,
        headers={
            "Authorization": f"Bearer {WA_TOKEN}",
            "Content-Type": f"multipart/form-data; boundary={boundary}"
        },
        method="POST"
    )
    def _upload():
        with urllib.request.urlopen(upload_req, timeout=30) as r:
            return json.loads(r.read())
    upload_result = await loop.run_in_executor(None, _upload)
    new_media_id = upload_result.get("id", "")

    if not new_media_id:
        await send_wa_message(JAMES_WA_PERSONAL,
            f"⚠️ Error al subir imagen. Revisa comprobante manualmente.\n{caption}")
        return

    # Paso 4: enviar imagen a James
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
    log.info(f"Imagen de comprobante reenviada a James")

# ─── Helper: notificar a James por WhatsApp (CallMeBot) ───────────────────────
async def notify_james_callmebot(text: str):
    encoded = urllib.parse.quote(text)
    url = f"https://api.callmebot.com/whatsapp.php?phone=51934284408&apikey={CALLMEBOT_KEY}&text={encoded}"
    loop = asyncio.get_event_loop()
    def _send():
        with urllib.request.urlopen(url, timeout=15) as r:
            return r.read().decode()
    try:
        result = await loop.run_in_executor(None, _send)
        log.info(f"CallMeBot notify: {result[:80]}")
    except Exception as e:
        log.error(f"CallMeBot error: {e}")

# ─── Helper: enviar correo a James ────────────────────────────────────────────
async def send_email_to_james(subject: str, body_html: str):
    """Envía correo vía Gmail SMTP si están configuradas las credenciales."""
    if not GMAIL_USER or not GMAIL_APP_PASS:
        log.warning("GMAIL_USER/GMAIL_APP_PASS no configurados — omitiendo correo")
        return False
    loop = asyncio.get_event_loop()
    def _send():
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = GMAIL_USER
        msg["To"] = JAMES_EMAIL
        msg.attach(MIMEText(body_html, "html", "utf-8"))
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(GMAIL_USER, GMAIL_APP_PASS)
            server.sendmail(GMAIL_USER, JAMES_EMAIL, msg.as_string())
    try:
        await loop.run_in_executor(None, _send)
        log.info(f"Email enviado a James: {subject}")
        return True
    except Exception as e:
        log.error(f"Email error: {e}")
        return False

# ─── Helper: leer hoja ────────────────────────────────────────────────────────
async def get_sheet_rows() -> list[list]:
    result = await call_tool(
        "google_sheets__pipedream",
        "google_sheets-get-values-in-range",
        {"sheetId": SHEET_ID, "worksheetId": WORKSHEET_ID, "range": "A1:K200"}
    )
    if result is None:
        return []
    if isinstance(result, list):
        return result
    return result.get("values", [])

async def update_row_status(sheet_row: int, estado: str, obs_extra: str):
    await call_tool(
        "google_sheets__pipedream",
        "google_sheets-update-row",
        {
            "sheetId": SHEET_ID,
            "worksheetId": WORKSHEET_ID,
            "hasHeaders": True,
            "row": sheet_row,
            "ESTADO": estado,
            "OBSERVACIONES": obs_extra
        }
    )

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
    """Maneja el flujo conversacional para clientes externos."""
    session = get_session(sender)
    step = session["step"]
    data = session["data"]
    now = datetime.now(LIMA_TZ)

    # ── PASO: inicio ──────────────────────────────────────────────────────────
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

    # ── PASO: esperar nombre ──────────────────────────────────────────────────
    if step == "esperar_nombre":
        data["nombre"] = text.strip()
        session["step"] = "esperar_empresa"
        await send_wa_message(sender,
            f"Mucho gusto, *{data['nombre']}* 😊\n\n"
            "¿Representa usted a alguna empresa u organización?\n"
            "_Si es a título personal, escriba *personal*._"
        )
        return

    # ── PASO: esperar empresa ─────────────────────────────────────────────────
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

    # ── PASO: esperar servicio ────────────────────────────────────────────────
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

    # ── PASO: esperar descripción ─────────────────────────────────────────────
    if step == "esperar_descripcion":
        data["descripcion"] = text.strip()
        session["step"] = "esperar_reunion"
        await send_wa_message(sender,
            "Gracias por la información 🙏\n\n"
            "¿Le gustaría agendar una *reunión con nuestro consultor* para evaluar su caso?\n\n"
            "✅ *Sí* — Agendamos una reunión (S/ 50.00 soles)\n"
            "📋 *No* — Solo deseo recibir una cotización\n\n"
            "_Responda *sí* o *no*_"
        )
        return

    # ── PASO: esperar decisión reunión ────────────────────────────────────────
    if step == "esperar_reunion":
        resp = text.strip().lower()
        if resp in ["no", "solo cotización", "solo cotizacion", "cotizacion", "cotización"]:
            # Enviar datos a James y cerrar sesión
            await notificar_james_nuevo_cliente(sender, data, reunion=False, now=now)
            reset_session(sender)
            await send_wa_message(sender,
                f"Perfecto, *{data['nombre']}* 😊\n\n"
                "Hemos registrado su consulta. Nuestro equipo le enviará una *cotización personalizada* a la brevedad.\n\n"
                "📞 Si tiene alguna duda adicional, no dude en escribirnos.\n\n"
                "*ASFIN Consultoría* — A su servicio 🏢"
            )
            return
        if resp in ["sí", "si", "s", "yes", "claro", "ok", "quiero", "deseo"]:
            session["step"] = "esperar_dia"
            await send_wa_message(sender,
                "¡Excelente! 📅\n\n"
                "La reunión tiene un costo de *S/ 50.00 soles* (pago previo vía Yape).\n\n"
                "¿Qué día le resultaría conveniente?\n"
                "_Indíquenos una fecha o día de la semana. Ejemplo: *lunes*, *viernes 20*, *20 de marzo*_"
            )
            return
        # Respuesta no reconocida
        await send_wa_message(sender,
            "Por favor responda *sí* para agendar reunión o *no* para solo recibir cotización."
        )
        return

    # ── PASO: esperar día ─────────────────────────────────────────────────────
    if step == "esperar_dia":
        data["dia_sugerido"] = text.strip()
        session["step"] = "esperar_horario"
        await send_wa_message(sender,
            f"Para el *{data['dia_sugerido']}*, estos son los horarios disponibles:\n\n"
            "1️⃣ 9:00 AM\n"
            "2️⃣ 11:00 AM\n"
            "3️⃣ 3:00 PM\n\n"
            "_Responda con el número (1, 2 o 3)_"
        )
        return

    # ── PASO: esperar horario ─────────────────────────────────────────────────
    if step == "esperar_horario":
        opcion = text.strip()
        horarios_map = {"1": "9:00 AM", "2": "11:00 AM", "3": "3:00 PM"}
        if opcion not in horarios_map:
            await send_wa_message(sender,
                "Por favor responda con *1*, *2* o *3*:\n"
                "1️⃣ 9:00 AM\n2️⃣ 11:00 AM\n3️⃣ 3:00 PM"
            )
            return
        data["horario"] = horarios_map[opcion]
        session["step"] = "esperar_yape"
        await send_wa_message(sender,
            f"Perfecto 👍 Su reunión está *pre-agendada* para:\n\n"
            f"📅 *{data['dia_sugerido']}* a las *{data['horario']}*\n\n"
            f"Para confirmar la reserva, realice el pago de *S/ 50.00 soles* vía:\n\n"
            f"💚 *YAPE* al número: *934 284 408*\n"
            f"👤 A nombre de: *James Conga*\n\n"
            f"Una vez realizado el pago, *envíe la captura de pantalla del comprobante* por este chat.\n\n"
            f"_El pago confirma su reserva._"
        )
        return

    # ── PASO: esperar imagen Yape ─────────────────────────────────────────────
    if step == "esperar_yape":
        if msg_type == "image":
            data["media_id"] = media_id
            session["step"] = "esperando_validacion"
            # Notificar a James con la imagen
            caption = (
                f"🔔 NUEVO CLIENTE — PAGO YAPE RECIBIDO\n\n"
                f"👤 {data.get('nombre','?')}\n"
                f"🏢 {data.get('empresa','Personal')}\n"
                f"📋 {data.get('servicio','?')}\n"
                f"📝 {data.get('descripcion','?')[:100]}\n"
                f"📅 {data.get('dia_sugerido','?')} {data.get('horario','?')}\n"
                f"📱 {sender}\n\n"
                f"Para confirmar responde:\n"
                f"*confirmar {sender[-4:]}*\n"
                f"(últimos 4 dígitos del número)"
            )
            # Guardar en pendientes
            PENDING_CONFIRM[sender[-4:]] = {**data, "sender": sender}
            # Reenviar imagen a James
            try:
                await forward_image_to_james(media_id, caption)
            except Exception as e:
                log.error(f"Error reenviando imagen: {e}")
                # Fallback: notificar sin imagen
                await send_wa_message(JAMES_WA_PERSONAL,
                    f"🔔 PAGO YAPE RECIBIDO (imagen no disponible)\n\n"
                    f"👤 {data.get('nombre','?')} | {data.get('empresa','Personal')}\n"
                    f"📋 {data.get('servicio','?')}\n"
                    f"📅 {data.get('dia_sugerido','?')} {data.get('horario','?')}\n"
                    f"📱 {sender}\n\n"
                    f"*confirmar {sender[-4:]}* para validar"
                )
            # También notificar datos a James por correo
            await notificar_james_nuevo_cliente(sender, data, reunion=True, now=now)
            # Responder al cliente
            await send_wa_message(sender,
                "¡Comprobante recibido! 📸✅\n\n"
                "Estamos *validando su pago*. En breve recibirá la confirmación oficial de su reunión.\n\n"
                "_Tiempo estimado: menos de 30 minutos en horario de oficina._"
            )
            return
        else:
            # No envió imagen
            await send_wa_message(sender,
                "Por favor envíe la *captura de pantalla del comprobante Yape* 📸\n\n"
                "💚 Recuerde realizar el pago de *S/ 50.00* al número *934 284 408*"
            )
            return

    # ── PASO: esperando validación de James ───────────────────────────────────
    if step == "esperando_validacion":
        await send_wa_message(sender,
            "Su solicitud está siendo procesada ⏳\n\n"
            "Recibirá la confirmación de su reunión en breve.\n"
            "_Si tiene alguna consulta, escríbanos nuevamente._"
        )
        return


async def notificar_james_nuevo_cliente(sender: str, data: dict, reunion: bool, now: datetime):
    """Notifica a James sobre un nuevo cliente — correo + WhatsApp Business."""
    nombre   = data.get("nombre", "?")
    empresa  = data.get("empresa", "") or "Personal"
    servicio = data.get("servicio", "?")
    desc     = data.get("descripcion", "?")
    dia      = data.get("dia_sugerido", "")
    horario  = data.get("horario", "")
    fecha    = now.strftime("%d/%m/%Y %H:%M")

    tipo = "REUNIÓN + COTIZACIÓN" if reunion else "SOLO COTIZACIÓN"

    # 1. Correo a James
    subject = f"🔔 ASFIN — Nuevo cliente: {nombre} ({tipo})"
    html = f"""
    <html><body style="font-family:Arial,sans-serif;max-width:600px;margin:auto">
    <h2 style="color:#2c5282">🔔 Nuevo cliente — ASFIN Consultoría</h2>
    <table style="border-collapse:collapse;width:100%">
      <tr><td style="padding:8px;background:#ebf8ff;font-weight:bold">Nombre</td>
          <td style="padding:8px">{nombre}</td></tr>
      <tr><td style="padding:8px;background:#ebf8ff;font-weight:bold">Empresa</td>
          <td style="padding:8px">{empresa}</td></tr>
      <tr><td style="padding:8px;background:#ebf8ff;font-weight:bold">WhatsApp</td>
          <td style="padding:8px">+{sender}</td></tr>
      <tr><td style="padding:8px;background:#ebf8ff;font-weight:bold">Servicio</td>
          <td style="padding:8px">{servicio}</td></tr>
      <tr><td style="padding:8px;background:#ebf8ff;font-weight:bold">Descripción</td>
          <td style="padding:8px">{desc}</td></tr>
      <tr><td style="padding:8px;background:#ebf8ff;font-weight:bold">Tipo</td>
          <td style="padding:8px"><strong>{tipo}</strong></td></tr>
      {'<tr><td style="padding:8px;background:#ebf8ff;font-weight:bold">Reunión</td><td style="padding:8px">' + dia + ' ' + horario + '</td></tr>' if reunion else ''}
      <tr><td style="padding:8px;background:#ebf8ff;font-weight:bold">Fecha contacto</td>
          <td style="padding:8px">{fecha}</td></tr>
    </table>
    <br>
    <p style="color:#718096;font-size:13px">{"Para confirmar la reunión responde <b>confirmar " + sender[-4:] + "</b> en WhatsApp al número +51 968 742 772" if reunion else "Prepara la cotización y responde al cliente."}</p>
    </body></html>
    """
    email_sent = await send_email_to_james(subject, html)

    # 2. Notificación WhatsApp a James (número personal)
    wa_msg = (
        f"🔔 ASFIN — Nuevo cliente\n\n"
        f"👤 {nombre} | {empresa}\n"
        f"📋 {servicio}\n"
        f"📝 {desc[:80]}\n"
        f"📱 +{sender}\n"
        f"🗓️ {fecha}\n"
    )
    if reunion:
        wa_msg += f"📅 Reunión: {dia} {horario}\n"
    wa_msg += f"\nTipo: *{tipo}*"
    if reunion:
        wa_msg += f"\n\nPara confirmar: *confirmar {sender[-4:]}*"

    # Enviar al número personal de James (el WA Business no puede enviarse a sí mismo)
    try:
        await send_wa_message(JAMES_WA_PERSONAL, wa_msg)
    except Exception:
        await notify_james_callmebot(wa_msg)


# ══════════════════════════════════════════════════════════════════════════════
# COMANDOS JAMES
# ══════════════════════════════════════════════════════════════════════════════

async def process_james_command(sender: str, text: str) -> str:
    text_lower = text.lower().strip()
    now_lima = datetime.now(LIMA_TZ)

    # CONFIRMAR REUNIÓN CLIENTE
    match_confirm = re.search(r"confirmar\s+(\d{4})", text_lower)
    if match_confirm:
        return await cmd_confirmar_reunion(match_confirm.group(1), now_lima)

    # RESUMEN / STATUS
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
    """James confirma la reunión de un cliente enviando 'confirmar XXXX'."""
    if codigo not in PENDING_CONFIRM:
        return (f"Hola James ❌ No encontré ninguna reserva pendiente con código *{codigo}*.\n"
                f"Los códigos son los últimos 4 dígitos del número del cliente.")

    client_data = PENDING_CONFIRM.pop(codigo)
    sender    = client_data["sender"]
    nombre    = client_data.get("nombre", "?")
    servicio  = client_data.get("servicio", "?")
    dia       = client_data.get("dia_sugerido", "?")
    horario   = client_data.get("horario", "?")

    # Marcar sesión como completada
    if sender in CLIENT_SESSIONS:
        CLIENT_SESSIONS[sender]["step"] = "completado"

    # Enviar confirmación al cliente
    try:
        await send_wa_message(sender,
            f"✅ *¡REUNIÓN CONFIRMADA!*\n\n"
            f"Estimado/a *{nombre}*,\n\n"
            f"Su pago ha sido verificado y su reunión ha quedado *oficialmente agendada*:\n\n"
            f"📅 *Fecha:* {dia}\n"
            f"⏰ *Hora:* {horario}\n"
            f"📋 *Servicio:* {servicio}\n\n"
            f"Le contactaremos para enviarle el enlace o dirección de la reunión.\n\n"
            f"¡Hasta pronto! 🏢\n"
            f"*ASFIN Consultoría*"
        )
        return (
            f"Hola James ✅ REUNIÓN CONFIRMADA\n\n"
            f"👤 {nombre}\n"
            f"📅 {dia} {horario}\n"
            f"📋 {servicio}\n\n"
            f"El cliente ya recibió su confirmación."
        )
    except Exception as e:
        return f"Hola James ❌ Error enviando confirmación al cliente: {str(e)[:80]}"


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
                estado = row[9] if len(row) > 9 else "?"
                asunto = row[4] if len(row) > 4 else "?"
                negocio = row[1] if len(row) > 1 else "?"
                obs = row[10] if len(row) > 10 else ""
                if estado == "Resuelto":
                    return f"Hola James ℹ️ N°{n} ya está *Resuelto*.\n📌 {asunto}"
                fecha_str = now_lima.strftime("%d/%m/%Y")
                obs_nueva = (obs + f" | Resuelto vía WhatsApp el {fecha_str}").strip(" |")
                await update_row_status(idx, "Resuelto", obs_nueva)
                return (
                    f"Hola James ✅ RESUELTO\n\n"
                    f"📌 N°{n}: {asunto}\n🏢 {negocio}\n📅 {fecha_str}\n\n"
                    f"La hoja fue actualizada.\n"
                    f"📊 https://docs.google.com/spreadsheets/d/{SHEET_ID}/edit"
                )
        return f"Hola James ❌ No encontré el registro N°{n}."
    except Exception as e:
        return f"Hola James ❌ Error: {str(e)[:100]}"

async def cmd_ver_fila(n: int) -> str:
    try:
        rows = await get_sheet_rows()
        for row in rows[1:]:
            if row and str(row[0]) == str(n):
                def g(i): return row[i] if len(row) > i else "?"
                return (
                    f"Hola James 📋 REGISTRO N°{g(0)}\n\n"
                    f"🏢 {g(1)}\n📅 Recepción: {g(2)}\n👤 De: {g(3)}\n"
                    f"📌 Asunto: {g(4)}\n📂 Categoría: {g(5)}\n"
                    f"⚡ Prioridad: {g(6)}\n📆 Límite: {g(7)}\n"
                    f"✅ Acción: {g(8)}\n🔄 Estado: {g(9)}\n"
                    f"📝 Obs: {g(10) or 'ninguna'}"
                )
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
        lines = [f"Hola James 📋 TAREAS PENDIENTES ({len(items)})\n"]
        for t in items[:15]:
            due = t.get("due", "")[:10] if t.get("due") else "sin fecha"
            lines.append(f"⏳ {t.get('title','?')[:60]}\n   📆 {due}")
        lines.append("\n🔗 https://tasks.google.com/")
        return "\n\n".join(lines)
    except Exception as e:
        return f"Hola James ❌ Error tareas: {str(e)[:100]}"

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
        return (
            f"Hola James ✅ TAREA CREADA\n\n📌 {title}\n"
            f"📆 Vence: {(now_lima + timedelta(days=3)).strftime('%d/%m/%Y')}\n"
            f"📋 Lista: Mis tareas\n\n🔗 https://tasks.google.com/"
        )
    except Exception as e:
        return f"Hola James ❌ Error creando tarea: {str(e)[:100]}"

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
        "✅ *confirmar XXXX* — Confirmar reunión cliente\n\n"
        "Ejemplos:\n"
        "  resumen\n"
        "  resolver N°6\n"
        "  ver N°3\n"
        "  agenda llamar a OSCE\n"
        "  confirmar 4408"
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
    log.info(f"Webhook verify: mode={hub_mode} token={hub_verify_token}")
    if hub_mode == "subscribe" and hub_verify_token == VERIFY_TOKEN:
        log.info("Webhook verified ✅")
        return PlainTextResponse(hub_challenge or "")
    raise HTTPException(status_code=403, detail="Verification failed")


@app.post("/webhook")
async def receive_webhook(request: Request):
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON")

    log.info(f"Webhook POST: {json.dumps(body)[:400]}")

    try:
        changes = body.get("entry", [{}])[0].get("changes", [{}])[0].get("value", {})
        messages = changes.get("messages", [])

        for msg in messages:
            sender    = msg.get("from", "")
            msg_type  = msg.get("type", "text")
            text      = ""
            media_id  = ""

            if msg_type == "text":
                text = msg.get("text", {}).get("body", "").strip()
            elif msg_type == "image":
                media_id = msg.get("image", {}).get("id", "")
                text     = msg.get("image", {}).get("caption", "").strip()

            if not sender:
                continue

            is_james = sender == JAMES_WA_PERSONAL

            if is_james:
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
            await send_wa_message(sender, f"Hola James ❌ Error interno: {str(e)[:80]}")
        except Exception:
            pass


async def handle_client_message(sender: str, msg_type: str, text: str, media_id: str):
    try:
        await handle_asfin(sender, msg_type, text, media_id)
    except Exception as e:
        log.error(f"handle_client {sender}: {e}", exc_info=True)
        try:
            await send_wa_message(sender,
                "Lo sentimos, ocurrió un error. Por favor intente nuevamente en unos minutos.\n"
                "🏢 *ASFIN Consultoría*")
        except Exception:
            pass


@app.get("/health")
async def health():
    return {
        "status": "ok",
        "server": "WA Webhook — Control Correos James + ASFIN",
        "time_lima": datetime.now(LIMA_TZ).strftime("%Y-%m-%d %H:%M:%S"),
        "active_client_sessions": len(CLIENT_SESSIONS),
        "pending_confirmations": len(PENDING_CONFIRM),
    }

@app.get("/")
async def root():
    return {
        "name": "WhatsApp Webhook — Control Correos James + ASFIN",
        "status": "running",
        "james_commands": ["resumen","urgentes","tareas","ver N°X","resolver N°X","agenda","confirmar XXXX","hoja","ayuda"],
        "asfin_flow": ["presentacion","nombre","empresa","servicio","descripcion","reunion","dia","horario","yape","confirmacion"],
    }

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000, log_level="info")
