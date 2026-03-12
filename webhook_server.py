#!/usr/bin/env python3
"""
WhatsApp Webhook Server — Control Correos James
Recibe mensajes de James desde +51 968 742 772 (WA Business)
y ejecuta acciones sobre Google Sheets, Google Tasks y Gmail.
"""

import asyncio
import json
import logging
import os
import re
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from typing import Optional

import uvicorn
from fastapi import FastAPI, HTTPException, Request, Query
from fastapi.responses import PlainTextResponse

# ─── Configuración — lee desde variables de entorno (Railway) ──────────────────
# En Railway: Settings → Variables → agregar cada una de estas
VERIFY_TOKEN      = os.getenv("VERIFY_TOKEN",      "james_control_correos_2026")
WA_TOKEN          = os.getenv("WA_TOKEN",          "")
PHONE_NUMBER_ID   = os.getenv("PHONE_NUMBER_ID",   "1017000174828335")
JAMES_WA_PERSONAL = os.getenv("JAMES_WA_PERSONAL", "51934284408")
JAMES_WA_BIZ      = os.getenv("JAMES_WA_BIZ",      "51968742772")
SHEET_ID          = os.getenv("SHEET_ID",          "1RSAc1hYS3utB13tK5VS3L-Qu2Kc8kaEHXiJnLk9BgHs")
WORKSHEET_ID      = int(os.getenv("WORKSHEET_ID",  "0"))
TASK_LIST_ID      = os.getenv("TASK_LIST_ID",      "MDY5MzE5MDc1NDA2NzkyNDA4ODQ6MDow")
CALLMEBOT_KEY     = os.getenv("CALLMEBOT_KEY",     "1235044")

# Zona horaria Lima
LIMA_TZ = timezone(timedelta(hours=-5))

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("wa-webhook")

app = FastAPI(title="WA Webhook — Control Correos James")

# ─── Helper: llamar external-tool CLI ─────────────────────────────────────────
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

# ─── Helper: leer hoja de control ─────────────────────────────────────────────
async def get_sheet_rows() -> list[list]:
    """Lee A1:K200. Retorna lista de listas (incluye encabezado en índice 0)."""
    result = await call_tool(
        "google_sheets__pipedream",
        "google_sheets-get-values-in-range",
        {"sheetId": SHEET_ID, "worksheetId": WORKSHEET_ID, "range": "A1:K200"}
    )
    if result is None:
        return []
    if isinstance(result, list):
        return result
    # fallback: buscar 'values' en dict
    return result.get("values", [])

# ─── Helper: actualizar estado de fila ────────────────────────────────────────
async def update_row_status(sheet_row: int, estado: str, obs_extra: str):
    """
    sheet_row = número de fila en Google Sheets (1=encabezado, 2=primer dato, etc.)
    """
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

# ─── Procesador de comandos ────────────────────────────────────────────────────
async def process_command(sender: str, text: str) -> str:
    text_lower = text.lower().strip()
    now_lima = datetime.now(LIMA_TZ)

    # RESUMEN / STATUS
    if any(w in text_lower for w in ["resumen", "estado", "pendientes", "status", "cuántos", "cuantos"]):
        return await cmd_resumen(now_lima)

    # RESOLVER N°X
    match_resolve = re.search(r"(resuelto|resolver|completar|marcar|cerrar?).*?(\d+)", text_lower)
    if match_resolve:
        return await cmd_resolver(int(match_resolve.group(2)), now_lima)

    # VER N°X / DETALLE N°X
    match_ver = re.search(r"(ver|detalle|info).*?(\d+)", text_lower)
    if match_ver:
        return await cmd_ver_fila(int(match_ver.group(2)))

    # URGENTES
    if any(w in text_lower for w in ["urgente", "urgentes", "crítico", "critico"]):
        return await cmd_urgentes()

    # TAREAS
    if any(w in text_lower for w in ["tareas", "google tasks", "mis tareas", "task"]):
        return await cmd_listar_tareas()

    # AGENDA / CREAR TAREA
    if any(w in text_lower for w in ["agenda", "crear tarea", "nueva tarea", "agregar tarea"]):
        return await cmd_crear_tarea(text, now_lima)

    # HOJA / LINK
    if any(w in text_lower for w in ["hoja", "sheet", "link", "url", "enlace"]):
        return f"📊 Hoja de Control:\nhttps://docs.google.com/spreadsheets/d/{SHEET_ID}/edit"

    # AYUDA
    if any(w in text_lower for w in ["ayuda", "help", "comandos", "qué puedes", "que puedes"]):
        return cmd_ayuda()

    # Default
    return (f"Hola James 👋\n\nRecibí: \"{text[:80]}\"\n\n"
            f"Escribe *ayuda* para ver los comandos disponibles.")

# ─── Comandos ─────────────────────────────────────────────────────────────────

async def cmd_resumen(now_lima: datetime) -> str:
    try:
        rows = await get_sheet_rows()
        if len(rows) <= 1:
            return "Hola James ✅ No hay registros en la hoja de control."

        conteo = {"CONSULT01": 0, "CONSULT02": 0, "CONSULT03": 0, "CONSULT04": 0, "PERSONAL": 0}
        urgentes = []
        vencen_hoy = []
        hoy_str = now_lima.strftime("%d/%m/%Y")
        total_pendientes = 0

        for row in rows[1:]:
            if len(row) < 10:
                continue
            estado = row[9]
            if estado not in ("Pendiente", "En proceso"):
                continue
            total_pendientes += 1
            negocio = row[1]
            if negocio in conteo:
                conteo[negocio] += 1
            cat  = row[5] if len(row) > 5 else ""
            flim = row[7] if len(row) > 7 else ""
            asunto_corto = (row[4] if len(row) > 4 else "?")[:45]
            if "URGENTE" in cat.upper():
                urgentes.append(asunto_corto)
            if flim == hoy_str:
                vencen_hoy.append(asunto_corto)

        return (
            f"Hola James 📊 RESUMEN ACTUAL\n"
            f"📅 {hoy_str}\n\n"
            f"🏢 CONSULT01 (SaludAllinta) — {conteo['CONSULT01']} pendientes\n"
            f"🏢 CONSULT02 (SaludOcobamba) — {conteo['CONSULT02']} pendientes\n"
            f"🏢 CONSULT03 (SuperObras) — {conteo['CONSULT03']} pendientes\n"
            f"🏢 CONSULT04 (IE Mayapo) — {conteo['CONSULT04']} pendientes\n"
            f"👤 PERSONAL — {conteo['PERSONAL']} pendientes\n"
            f"─────────\n"
            f"📌 TOTAL: {total_pendientes} pendientes\n\n"
            f"🔴 URGENTES: {', '.join(urgentes) if urgentes else 'ninguno'}\n"
            f"⚠️ VENCEN HOY: {', '.join(vencen_hoy) if vencen_hoy else 'ninguno'}\n\n"
            f"📊 https://docs.google.com/spreadsheets/d/{SHEET_ID}/edit"
        )
    except Exception as e:
        log.error(f"cmd_resumen: {e}", exc_info=True)
        return f"Hola James ❌ Error en resumen: {str(e)[:100]}"

async def cmd_resolver(n: int, now_lima: datetime) -> str:
    try:
        rows = await get_sheet_rows()
        for idx, row in enumerate(rows[1:], start=2):  # sheet row 2 = idx 0 in rows[1:]
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
                    f"📌 N°{n}: {asunto}\n"
                    f"🏢 {negocio}\n"
                    f"📅 {fecha_str}\n\n"
                    f"La hoja fue actualizada.\n"
                    f"📊 https://docs.google.com/spreadsheets/d/{SHEET_ID}/edit"
                )
        return f"Hola James ❌ No encontré el registro N°{n}."
    except Exception as e:
        log.error(f"cmd_resolver: {e}", exc_info=True)
        return f"Hola James ❌ Error: {str(e)[:100]}"

async def cmd_ver_fila(n: int) -> str:
    try:
        rows = await get_sheet_rows()
        for row in rows[1:]:
            if row and str(row[0]) == str(n):
                def g(i): return row[i] if len(row) > i else "?"
                return (
                    f"Hola James 📋 REGISTRO N°{g(0)}\n\n"
                    f"🏢 {g(1)}\n"
                    f"📅 Recepción: {g(2)}\n"
                    f"👤 De: {g(3)}\n"
                    f"📌 Asunto: {g(4)}\n"
                    f"📂 Categoría: {g(5)}\n"
                    f"⚡ Prioridad: {g(6)}\n"
                    f"📆 Límite: {g(7)}\n"
                    f"✅ Acción: {g(8)}\n"
                    f"🔄 Estado: {g(9)}\n"
                    f"📝 Obs: {g(10) or 'ninguna'}"
                )
        return f"Hola James ❌ No encontré N°{n}."
    except Exception as e:
        return f"Hola James ❌ Error: {str(e)[:100]}"

async def cmd_urgentes() -> str:
    try:
        rows = await get_sheet_rows()
        urgentes = [
            r for r in rows[1:]
            if len(r) >= 10 and "URGENTE" in str(r[5]).upper() and r[9] in ("Pendiente", "En proceso")
        ]
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
        result = await call_tool(
            "google_tasks__pipedream",
            "google_tasks-list-tasks",
            {"taskListId": TASK_LIST_ID, "showCompleted": False, "maxResults": 20}
        )
        if not result:
            return "Hola James ✅ No tienes tareas pendientes en 'Mis tareas'."
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
        log.error(f"cmd_listar_tareas: {e}", exc_info=True)
        return f"Hola James ❌ Error tareas: {str(e)[:100]}"

async def cmd_crear_tarea(text: str, now_lima: datetime) -> str:
    asunto = text.strip()
    for kw in ["agenda", "crear tarea", "nueva tarea", "agregar tarea"]:
        if kw in asunto.lower():
            asunto = asunto[asunto.lower().find(kw)+len(kw):].strip(": ")
            break
    if not asunto:
        return "Hola James ℹ️ Escribe el asunto.\nEjemplo: *agenda reunión OSCE el lunes*"
    due  = (now_lima + timedelta(days=3)).strftime("%Y-%m-%dT00:00:00Z")
    title = f"🟠 [Personal] {asunto[:80]}"
    try:
        await call_tool(
            "google_tasks__pipedream",
            "google_tasks-create-task",
            {
                "taskListId": TASK_LIST_ID,
                "title": title,
                "notes": f"Creada vía WhatsApp el {now_lima.strftime('%d/%m/%Y %H:%M')}\n\n📊 https://docs.google.com/spreadsheets/d/{SHEET_ID}/edit",
                "due": due,
                "status": "needsAction"
            }
        )
        return (
            f"Hola James ✅ TAREA CREADA\n\n"
            f"📌 {title}\n"
            f"📆 Vence: {(now_lima + timedelta(days=3)).strftime('%d/%m/%Y')}\n"
            f"📋 Lista: Mis tareas\n\n"
            f"🔗 https://tasks.google.com/"
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
        "🔗 *hoja* — Link a la hoja\n\n"
        "Ejemplos:\n"
        "  resumen\n"
        "  resolver N°6\n"
        "  ver N°3\n"
        "  agenda llamar a OSCE"
    )

# ─── Endpoints ────────────────────────────────────────────────────────────────

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
        messages = (
            body.get("entry", [{}])[0]
                .get("changes", [{}])[0]
                .get("value", {})
                .get("messages", [])
        )
        for msg in messages:
            if msg.get("type") == "text":
                sender = msg.get("from", "")
                text   = msg.get("text", {}).get("body", "").strip()
                if text and sender:
                    asyncio.create_task(handle_message(sender, text))
    except Exception as e:
        log.error(f"Webhook parse error: {e}", exc_info=True)

    return {"status": "ok"}  # Meta requiere 200 OK inmediato

async def handle_message(sender: str, text: str):
    try:
        response = await process_command(sender, text)
        await send_wa_message(sender, response)
        log.info(f"Replied to {sender}: {response[:80]}")
    except Exception as e:
        log.error(f"handle_message error: {e}", exc_info=True)
        try:
            await send_wa_message(sender, f"Hola James ❌ Error interno: {str(e)[:80]}")
        except Exception:
            pass

@app.get("/health")
async def health():
    return {
        "status": "ok",
        "server": "WA Webhook — Control Correos James",
        "time_lima": datetime.now(LIMA_TZ).strftime("%Y-%m-%d %H:%M:%S"),
        "verify_token": VERIFY_TOKEN,
        "phone_number_id": PHONE_NUMBER_ID
    }

@app.get("/")
async def root():
    return {
        "name": "WhatsApp Webhook — Control Correos James",
        "status": "running",
        "verify_token": VERIFY_TOKEN,
        "commands": ["resumen","urgentes","tareas","ver N°X","resolver N°X","agenda [asunto]","hoja","ayuda"]
    }

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000, log_level="info")
