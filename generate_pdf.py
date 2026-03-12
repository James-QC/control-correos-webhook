#!/usr/bin/env python3
"""
Generate the WhatsApp Bidirectional System Setup Guide PDF.
"""

import os
from reportlab.lib.pagesizes import letter
from reportlab.lib.units import inch, mm
from reportlab.lib.colors import HexColor, white, black
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.enums import TA_LEFT, TA_CENTER, TA_JUSTIFY
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, PageBreak, Table, TableStyle,
    HRFlowable, ListFlowable, ListItem, KeepTogether
)
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

# ── Paths ──
FONT_DIR = "/home/user/workspace/wa-webhook/fonts"
OUTPUT   = "/home/user/workspace/wa-webhook/guia_webhook_whatsapp.pdf"

# ── Register DM Sans ──
pdfmetrics.registerFont(TTFont("DMSans",         os.path.join(FONT_DIR, "DMSans-Regular-static.ttf")))
pdfmetrics.registerFont(TTFont("DMSans-Bold",    os.path.join(FONT_DIR, "DMSans-Bold-static.ttf")))
pdfmetrics.registerFont(TTFont("DMSans-Italic",  os.path.join(FONT_DIR, "DMSans-Italic-static.ttf")))
pdfmetrics.registerFont(TTFont("DMSans-BoldItalic", os.path.join(FONT_DIR, "DMSans-BoldItalic-static.ttf")))

from reportlab.pdfbase.pdfmetrics import registerFontFamily
registerFontFamily(
    "DMSans",
    normal="DMSans",
    bold="DMSans-Bold",
    italic="DMSans-Italic",
    boldItalic="DMSans-BoldItalic"
)

# ── Colors ──
GREEN      = HexColor("#128C7E")
DARK_GREEN = HexColor("#0E6B62")
LIGHT_GREEN= HexColor("#E8F5F3")
DARK_TEXT   = HexColor("#1A1A1A")
MEDIUM_TEXT = HexColor("#333333")
MUTED_TEXT  = HexColor("#666666")
LIGHT_BG    = HexColor("#F5F5F5")
WHITE       = white
ACCENT_ORANGE = HexColor("#E67E22")
ACCENT_RED    = HexColor("#C0392B")
BORDER_GRAY   = HexColor("#CCCCCC")

# ── Styles ──
styles = {}

styles["title"] = ParagraphStyle(
    "Title", fontName="DMSans-Bold", fontSize=22, leading=28,
    textColor=GREEN, alignment=TA_CENTER, spaceAfter=6
)

styles["subtitle"] = ParagraphStyle(
    "Subtitle", fontName="DMSans", fontSize=12, leading=16,
    textColor=MUTED_TEXT, alignment=TA_CENTER, spaceAfter=20
)

styles["h1"] = ParagraphStyle(
    "H1", fontName="DMSans-Bold", fontSize=17, leading=22,
    textColor=GREEN, spaceBefore=12, spaceAfter=8
)

styles["h2"] = ParagraphStyle(
    "H2", fontName="DMSans-Bold", fontSize=13, leading=17,
    textColor=DARK_GREEN, spaceBefore=10, spaceAfter=4
)

styles["h3"] = ParagraphStyle(
    "H3", fontName="DMSans-Bold", fontSize=11, leading=15,
    textColor=DARK_TEXT, spaceBefore=10, spaceAfter=4
)

styles["body"] = ParagraphStyle(
    "Body", fontName="DMSans", fontSize=10, leading=14,
    textColor=MEDIUM_TEXT, spaceAfter=4, alignment=TA_JUSTIFY
)

styles["body_left"] = ParagraphStyle(
    "BodyLeft", fontName="DMSans", fontSize=10, leading=14,
    textColor=MEDIUM_TEXT, spaceAfter=4, alignment=TA_LEFT
)

styles["bullet"] = ParagraphStyle(
    "Bullet", fontName="DMSans", fontSize=10, leading=14,
    textColor=MEDIUM_TEXT, leftIndent=20, spaceAfter=3,
    bulletIndent=8, bulletFontName="DMSans", bulletFontSize=10
)

styles["numbered"] = ParagraphStyle(
    "Numbered", fontName="DMSans", fontSize=10, leading=14,
    textColor=MEDIUM_TEXT, leftIndent=24, spaceAfter=3,
    bulletIndent=8
)

styles["code"] = ParagraphStyle(
    "Code", fontName="Courier", fontSize=9, leading=12,
    textColor=HexColor("#2C3E50"), backColor=LIGHT_BG,
    leftIndent=16, rightIndent=16, spaceBefore=4, spaceAfter=4,
    borderPadding=(6, 8, 6, 8)
)

styles["warning"] = ParagraphStyle(
    "Warning", fontName="DMSans-Bold", fontSize=10, leading=14,
    textColor=ACCENT_RED, spaceBefore=8, spaceAfter=4,
    leftIndent=8
)

styles["important_box"] = ParagraphStyle(
    "ImportantBox", fontName="DMSans-Bold", fontSize=10, leading=14,
    textColor=ACCENT_RED, spaceBefore=4, spaceAfter=2,
)

styles["note"] = ParagraphStyle(
    "Note", fontName="DMSans-Italic", fontSize=9, leading=13,
    textColor=MUTED_TEXT, leftIndent=8, spaceAfter=4
)

styles["command"] = ParagraphStyle(
    "Command", fontName="DMSans-Bold", fontSize=10, leading=14,
    textColor=GREEN, leftIndent=20, spaceAfter=2
)

styles["command_desc"] = ParagraphStyle(
    "CommandDesc", fontName="DMSans", fontSize=10, leading=14,
    textColor=MEDIUM_TEXT, leftIndent=20, spaceAfter=6
)

styles["page_num"] = ParagraphStyle(
    "PageNum", fontName="DMSans", fontSize=8, leading=10,
    textColor=MUTED_TEXT, alignment=TA_CENTER
)

styles["footer"] = ParagraphStyle(
    "Footer", fontName="DMSans", fontSize=7, leading=9,
    textColor=MUTED_TEXT, alignment=TA_CENTER
)

styles["ref_label"] = ParagraphStyle(
    "RefLabel", fontName="DMSans-Bold", fontSize=9, leading=12,
    textColor=DARK_TEXT, spaceAfter=1
)

styles["ref_value"] = ParagraphStyle(
    "RefValue", fontName="DMSans", fontSize=9, leading=12,
    textColor=MEDIUM_TEXT, leftIndent=12, spaceAfter=4
)


# ── Helper functions ──
def hr():
    return HRFlowable(width="100%", thickness=1, color=GREEN, spaceBefore=6, spaceAfter=6)

def thin_hr():
    return HRFlowable(width="100%", thickness=0.5, color=BORDER_GRAY, spaceBefore=4, spaceAfter=4)

def bullet(text, style_key="bullet"):
    return Paragraph(f"<bullet>&bull;</bullet> {text}", styles[style_key])

def numbered_item(num, text):
    return Paragraph(f"<b>{num}.</b> {text}", styles["numbered"])

def green_box_table(content_flowables):
    """Wrap flowables in a green-bordered box."""
    t = Table([[content_flowables]], colWidths=[6.3*inch])
    t.setStyle(TableStyle([
        ("BOX", (0,0), (-1,-1), 1.5, GREEN),
        ("BACKGROUND", (0,0), (-1,-1), LIGHT_GREEN),
        ("TOPPADDING", (0,0), (-1,-1), 8),
        ("BOTTOMPADDING", (0,0), (-1,-1), 8),
        ("LEFTPADDING", (0,0), (-1,-1), 10),
        ("RIGHTPADDING", (0,0), (-1,-1), 10),
    ]))
    return t

def warning_box(content_flowables):
    """Wrap flowables in a red-bordered warning box."""
    t = Table([[content_flowables]], colWidths=[6.3*inch])
    t.setStyle(TableStyle([
        ("BOX", (0,0), (-1,-1), 1.5, ACCENT_RED),
        ("BACKGROUND", (0,0), (-1,-1), HexColor("#FDF2F0")),
        ("TOPPADDING", (0,0), (-1,-1), 8),
        ("BOTTOMPADDING", (0,0), (-1,-1), 8),
        ("LEFTPADDING", (0,0), (-1,-1), 10),
        ("RIGHTPADDING", (0,0), (-1,-1), 10),
    ]))
    return t


# ── Page template callbacks ──
def on_first_page(canvas, doc):
    canvas.saveState()
    # Top green bar
    canvas.setFillColor(GREEN)
    canvas.rect(0, letter[1] - 8, letter[0], 8, fill=1, stroke=0)
    # Bottom bar
    canvas.setFillColor(GREEN)
    canvas.rect(0, 0, letter[0], 4, fill=1, stroke=0)
    # Footer text
    canvas.setFont("DMSans", 7)
    canvas.setFillColor(MUTED_TEXT)
    canvas.drawCentredString(letter[0]/2, 12, "Sistema WhatsApp Bidireccional — Control de Correos James")
    canvas.restoreState()

def on_later_pages(canvas, doc):
    canvas.saveState()
    # Top green bar (thin)
    canvas.setFillColor(GREEN)
    canvas.rect(0, letter[1] - 4, letter[0], 4, fill=1, stroke=0)
    # Bottom bar
    canvas.setFillColor(GREEN)
    canvas.rect(0, 0, letter[0], 4, fill=1, stroke=0)
    # Header text
    canvas.setFont("DMSans", 7)
    canvas.setFillColor(MUTED_TEXT)
    canvas.drawString(doc.leftMargin, letter[1] - 14,
                      "Guía de Configuración — WhatsApp Bidireccional")
    # Page number
    canvas.drawRightString(letter[0] - doc.rightMargin, letter[1] - 14,
                           f"Página {doc.page}")
    # Footer
    canvas.drawCentredString(letter[0]/2, 12,
                             "Sistema WhatsApp Bidireccional — Control de Correos James")
    canvas.restoreState()


# ── Build document ──
doc = SimpleDocTemplate(
    OUTPUT,
    pagesize=letter,
    topMargin=0.9*inch,
    bottomMargin=0.7*inch,
    leftMargin=0.85*inch,
    rightMargin=0.85*inch,
    title="Sistema WhatsApp Bidireccional — Guía de Configuración",
    author="Perplexity Computer"
)

story = []

# ════════════════════════════════════════════════════════════════════
# COVER / TITLE
# ════════════════════════════════════════════════════════════════════
story.append(Spacer(1, 20))
story.append(Paragraph("Sistema WhatsApp Bidireccional", styles["title"]))
story.append(Paragraph("Guía de Configuración", ParagraphStyle(
    "TitleSub", fontName="DMSans", fontSize=16, leading=20,
    textColor=DARK_GREEN, alignment=TA_CENTER, spaceAfter=16
)))
story.append(hr())
story.append(Paragraph("Control de Correos James | Configurado el 12/03/2026", styles["subtitle"]))
story.append(Spacer(1, 6))

# ════════════════════════════════════════════════════════════════════
# PAGE 1: RESUMEN DEL SISTEMA
# ════════════════════════════════════════════════════════════════════
story.append(Paragraph("1. Resumen del Sistema", styles["h1"]))
story.append(hr())

story.append(Paragraph("Arquitectura implementada", styles["h2"]))
story.append(bullet("Servidor webhook FastAPI (Python) ejecutándose en el sandbox de Perplexity Computer"))
story.append(bullet("Túnel Cloudflare para URL pública HTTPS"))
story.append(bullet('URL pública actual (temporal): <font color="#2C3E50"><b>https://famous-inches-months-generators.trycloudflare.com/webhook</b></font>'))
story.append(bullet('Token de verificación: <font color="#2C3E50"><b>james_control_correos_2026</b></font>'))

story.append(Spacer(1, 8))
story.append(Paragraph("Cómo funciona", styles["h2"]))
story.append(numbered_item(1, 'James escribe un mensaje desde su WhatsApp personal (<b>+51 934 284 408</b>) al número de WA Business (<b>+51 968 742 772</b>)'))
story.append(numbered_item(2, "Meta reenvía el mensaje al servidor webhook vía HTTPS POST"))
story.append(numbered_item(3, "El servidor procesa el comando y consulta Google Sheets / Google Tasks"))
story.append(numbered_item(4, "El servidor responde de vuelta al WhatsApp de James"))

story.append(Spacer(1, 8))
story.append(Paragraph("Comandos disponibles", styles["h2"]))

# Commands table
cmd_data = [
    ["Comando", "Descripción"],
    ["resumen", "Ver pendientes por negocio"],
    ["urgentes", "Solo urgentes pendientes"],
    ["tareas", "Ver Google Tasks"],
    ["ver N°X", "Detalle del registro N°X"],
    ["resolver N°X", "Marcar N°X como Resuelto en la hoja"],
    ["agenda [asunto]", "Crear nueva tarea en Google Tasks"],
    ["hoja", "Link a la hoja de control"],
    ["ayuda", "Lista completa de comandos"],
]
cmd_table = Table(cmd_data, colWidths=[1.6*inch, 4.4*inch])
cmd_table.setStyle(TableStyle([
    # Header
    ("BACKGROUND", (0,0), (-1,0), GREEN),
    ("TEXTCOLOR", (0,0), (-1,0), WHITE),
    ("FONTNAME", (0,0), (-1,0), "DMSans-Bold"),
    ("FONTSIZE", (0,0), (-1,0), 10),
    # Body
    ("FONTNAME", (0,1), (0,-1), "DMSans-Bold"),
    ("TEXTCOLOR", (0,1), (0,-1), GREEN),
    ("FONTNAME", (1,1), (1,-1), "DMSans"),
    ("FONTSIZE", (0,1), (-1,-1), 9),
    ("TEXTCOLOR", (1,1), (1,-1), MEDIUM_TEXT),
    # Grid
    ("GRID", (0,0), (-1,-1), 0.5, BORDER_GRAY),
    ("ROWBACKGROUNDS", (0,1), (-1,-1), [WHITE, LIGHT_GREEN]),
    ("TOPPADDING", (0,0), (-1,-1), 5),
    ("BOTTOMPADDING", (0,0), (-1,-1), 5),
    ("LEFTPADDING", (0,0), (-1,-1), 8),
    ("VALIGN", (0,0), (-1,-1), "MIDDLE"),
]))
story.append(cmd_table)

# ════════════════════════════════════════════════════════════════════
# PAGE 2: PASO 1 — REGISTRAR WEBHOOK EN META
# ════════════════════════════════════════════════════════════════════
story.append(PageBreak())
story.append(Paragraph("2. Paso 1 — Registrar Webhook en Meta Developer Console", styles["h1"]))
story.append(hr())

story.append(warning_box([
    Paragraph("⚠ Este paso debe realizarse manualmente. Requiere la App Secret de Meta.", styles["important_box"]),
]))
story.append(Spacer(1, 8))

story.append(Paragraph("Instrucciones:", styles["h2"]))
story.append(numbered_item(1, 'Ir a <a href="https://developers.facebook.com/apps/1695869685126292/" color="#128C7E"><u>https://developers.facebook.com/apps/1695869685126292/</u></a>'))
story.append(numbered_item(2, 'En el menú izquierdo: <b>WhatsApp → Configuración</b>'))
story.append(numbered_item(3, 'Sección "Webhook": hacer clic en <b>"Editar"</b>'))
story.append(numbered_item(4, "Ingresar los datos:"))

# Sub-items for step 4
sub_style = ParagraphStyle("SubItem", parent=styles["body_left"], leftIndent=44, spaceAfter=3)
story.append(Paragraph('<b>URL de devolución de llamada:</b> <font color="#2C3E50">https://famous-inches-months-generators.trycloudflare.com/webhook</font>', sub_style))
story.append(Paragraph('<b>Token de verificación:</b> <font color="#2C3E50">james_control_correos_2026</font>', sub_style))

story.append(numbered_item(5, 'Hacer clic en <b>"Verificar y guardar"</b>'))
story.append(numbered_item(6, 'En la sección de campos del webhook, habilitar: <b>messages</b>'))
story.append(numbered_item(7, 'Hacer clic en <b>"Suscribir"</b>'))

story.append(Spacer(1, 12))
story.append(warning_box([
    Paragraph("<b>IMPORTANTE: La URL actual es temporal</b>", styles["important_box"]),
    Spacer(1, 4),
    Paragraph(
        "La URL de Cloudflare (trycloudflare.com) solo funciona mientras la sesión de Perplexity Computer esté activa.",
        ParagraphStyle("WarningBody", fontName="DMSans", fontSize=10, leading=14, textColor=ACCENT_RED)
    ),
    Spacer(1, 4),
    Paragraph(
        "Para una solución permanente, ver <b>Página 4: Soluciones de Hosting Permanente</b>.",
        ParagraphStyle("WarningBody2", fontName="DMSans", fontSize=10, leading=14, textColor=ACCENT_RED)
    ),
]))

# ════════════════════════════════════════════════════════════════════
# PAGE 3: PASO 2 — TOKEN PERMANENTE
# ════════════════════════════════════════════════════════════════════
story.append(PageBreak())
story.append(Paragraph("3. Paso 2 — Generar Token Permanente de Meta", styles["h1"]))
story.append(hr())

story.append(Paragraph(
    "El token actual expira en ~24h. Para generar uno permanente, se tienen dos opciones:",
    styles["body"]
))
story.append(Spacer(1, 6))

# Option A
story.append(green_box_table([
    Paragraph("Opción A — Meta Business Suite (Recomendado)", ParagraphStyle(
        "OptA", fontName="DMSans-Bold", fontSize=12, leading=16, textColor=GREEN, spaceAfter=6
    )),
]))
story.append(Spacer(1, 6))

story.append(numbered_item(1, 'Ir a <a href="https://business.facebook.com/" color="#128C7E"><u>https://business.facebook.com/</u></a>'))
story.append(numbered_item(2, '<b>Configuración del Negocio → Usuarios → Usuarios del sistema</b>'))
story.append(numbered_item(3, "Crear nuevo usuario del sistema (Admin)"))
story.append(numbered_item(4, 'Hacer clic en <b>"Generar nuevo token"</b>'))
story.append(numbered_item(5, 'Seleccionar App: <b>"Control Correos WA"</b> (ID: 1695869685126292)'))
story.append(numbered_item(6, "Marcar permisos:"))

perm_style = ParagraphStyle("Perm", parent=styles["body_left"], leftIndent=44, spaceAfter=2)
story.append(Paragraph('<font color="#2C3E50"><b>whatsapp_business_messaging</b></font>', perm_style))
story.append(Paragraph('<font color="#2C3E50"><b>whatsapp_business_management</b></font>', perm_style))

story.append(numbered_item(7, "Copiar el token generado"))
story.append(numbered_item(8, "Actualizar el token en el archivo del servidor:"))

story.append(Paragraph(
    '<font face="Courier" size="9" color="#2C3E50">/home/user/workspace/wa-webhook/webhook_server.py</font>',
    ParagraphStyle("FilePath", parent=styles["body_left"], leftIndent=44, spaceAfter=2)
))
story.append(Paragraph(
    'Línea: <font face="Courier" size="9" color="#2C3E50">WA_TOKEN = "NUEVO_TOKEN_AQUI"</font>',
    ParagraphStyle("CodeLine", parent=styles["body_left"], leftIndent=44, spaceAfter=8)
))

# Option B
story.append(Spacer(1, 8))
story.append(green_box_table([
    Paragraph("Opción B — Token que no expira (solo para desarrollo/testing)", ParagraphStyle(
        "OptB", fontName="DMSans-Bold", fontSize=12, leading=16, textColor=GREEN, spaceAfter=6
    )),
]))
story.append(Spacer(1, 6))

story.append(numbered_item(1, 'Ir a <a href="https://developers.facebook.com/apps/1695869685126292/" color="#128C7E"><u>https://developers.facebook.com/apps/1695869685126292/</u></a>'))
story.append(numbered_item(2, '<b>WhatsApp → Configuración de la API</b>'))
story.append(numbered_item(3, 'En la sección "Token de acceso temporal", hacer clic en <b>"Generar"</b>'))
story.append(numbered_item(4, "Estos tokens duran 60 días pero requieren renovación manual"))

# ════════════════════════════════════════════════════════════════════
# PAGE 4: HOSTING PERMANENTE
# ════════════════════════════════════════════════════════════════════
story.append(PageBreak())
story.append(Paragraph("4. Soluciones de Hosting Permanente", styles["h1"]))
story.append(hr())

story.append(Paragraph(
    "Para que el webhook esté disponible 24/7, necesitas una URL fija. Opciones en orden de recomendación:",
    styles["body"]
))
story.append(Spacer(1, 8))

# ── Option 1: Railway ──
story.append(green_box_table([
    Paragraph("OPCIÓN 1 — Railway.app (Más fácil, gratis)", ParagraphStyle(
        "Opt1Title", fontName="DMSans-Bold", fontSize=12, leading=16, textColor=GREEN, spaceAfter=2
    )),
]))
story.append(Spacer(1, 4))
story.append(numbered_item(1, 'Ir a <a href="https://railway.app" color="#128C7E"><u>https://railway.app</u></a> y crear cuenta'))
story.append(numbered_item(2, 'Nuevo proyecto → <b>Deploy from GitHub</b>'))
story.append(numbered_item(3, 'Subir el archivo <font face="Courier" size="9">webhook_server.py</font> a GitHub'))
story.append(numbered_item(4, "Railway detecta Python y despliega automáticamente"))
story.append(numbered_item(5, 'Obtienes URL permanente como: <font color="#2C3E50">https://tu-app.up.railway.app</font>'))
story.append(numbered_item(6, "Registrar esa URL en Meta como webhook permanente"))
story.append(Paragraph('<b>Costo:</b> Gratis (hasta $5/mes de créditos)', styles["body_left"]))

story.append(Spacer(1, 10))

# ── Option 2: Render ──
story.append(green_box_table([
    Paragraph("OPCIÓN 2 — Render.com (Gratis)", ParagraphStyle(
        "Opt2Title", fontName="DMSans-Bold", fontSize=12, leading=16, textColor=GREEN, spaceAfter=2
    )),
]))
story.append(Spacer(1, 4))
story.append(numbered_item(1, 'Ir a <a href="https://render.com" color="#128C7E"><u>https://render.com</u></a>'))
story.append(numbered_item(2, '<b>New Web Service → Connect a repository</b>'))
story.append(numbered_item(3, 'Subir <font face="Courier" size="9">webhook_server.py</font> + <font face="Courier" size="9">requirements.txt</font> a GitHub'))
story.append(numbered_item(4, 'URL permanente: <font color="#2C3E50">https://tu-app.onrender.com</font>'))
story.append(Paragraph('<b>Costo:</b> Gratis (el servicio se "duerme" después de 15 min de inactividad)', styles["body_left"]))

story.append(Spacer(1, 10))

# ── Option 3: VPS ──
story.append(green_box_table([
    Paragraph("OPCIÓN 3 — VPS propio", ParagraphStyle(
        "Opt3Title", fontName="DMSans-Bold", fontSize=12, leading=16, textColor=GREEN, spaceAfter=2
    )),
]))
story.append(Spacer(1, 4))
story.append(Paragraph(
    'Usar un servidor Ubuntu en DigitalOcean ($6/mes), instalar Python + uvicorn, correr el servidor con <font face="Courier" size="9">systemd</font>. URL permanente con tu propio dominio.',
    styles["body"]
))

story.append(Spacer(1, 12))
story.append(Paragraph("Archivos necesarios para deployment", styles["h2"]))
story.append(thin_hr())

# requirements.txt
story.append(Paragraph('<b>requirements.txt</b>', styles["h3"]))
code_style = ParagraphStyle("CodeBlock", fontName="Courier", fontSize=9, leading=13,
                             textColor=HexColor("#2C3E50"), backColor=LIGHT_BG,
                             leftIndent=16, spaceAfter=8,
                             borderPadding=(6,8,6,8))
story.append(Paragraph("fastapi==0.115.0<br/>uvicorn==0.32.0", code_style))

# Procfile
story.append(Paragraph('<b>Procfile</b> (para Railway/Render)', styles["h3"]))
story.append(Paragraph("web: uvicorn webhook_server:app --host 0.0.0.0 --port $PORT", code_style))


# ════════════════════════════════════════════════════════════════════
# PAGE 5: DATOS DE CONFIGURACIÓN
# ════════════════════════════════════════════════════════════════════
story.append(PageBreak())
story.append(Paragraph("5. Datos de Configuración (Referencia Rápida)", styles["h1"]))
story.append(hr())

# Reference data table
ref_data = [
    ["Campo", "Valor"],
    ["WhatsApp Business Number", "+51 968 742 772"],
    ["Phone Number ID", "1017000174828335"],
    ["WhatsApp Business Account ID", "2406705339791456"],
    ["Meta App ID", "1695869685126292"],
    ["Meta App Name", "Control Correos WA"],
    ["Token de Verificación Webhook", "james_control_correos_2026"],
    ["Google Sheets ID", "1RSAc1hYS3utB13tK5VS3L-Qu2Kc8kaEHXiJnLk9BgHs"],
    ["Google Tasks List ID", "MDY5MzE5MDc1NDA2NzkyNDA4ODQ6MDow"],
    ["CallMeBot (notificaciones)", "phone=51934284408, apikey=1235044"],
]

ref_table = Table(ref_data, colWidths=[2.3*inch, 4.0*inch])
ref_table.setStyle(TableStyle([
    # Header
    ("BACKGROUND", (0,0), (-1,0), GREEN),
    ("TEXTCOLOR", (0,0), (-1,0), WHITE),
    ("FONTNAME", (0,0), (-1,0), "DMSans-Bold"),
    ("FONTSIZE", (0,0), (-1,0), 10),
    # Body
    ("FONTNAME", (0,1), (0,-1), "DMSans-Bold"),
    ("FONTSIZE", (0,1), (0,-1), 9),
    ("TEXTCOLOR", (0,1), (0,-1), DARK_TEXT),
    ("FONTNAME", (1,1), (1,-1), "DMSans"),
    ("FONTSIZE", (1,1), (1,-1), 9),
    ("TEXTCOLOR", (1,1), (1,-1), MEDIUM_TEXT),
    # Grid
    ("GRID", (0,0), (-1,-1), 0.5, BORDER_GRAY),
    ("ROWBACKGROUNDS", (0,1), (-1,-1), [WHITE, LIGHT_GREEN]),
    ("TOPPADDING", (0,0), (-1,-1), 5),
    ("BOTTOMPADDING", (0,0), (-1,-1), 5),
    ("LEFTPADDING", (0,0), (-1,-1), 8),
    ("VALIGN", (0,0), (-1,-1), "MIDDLE"),
]))
story.append(ref_table)

story.append(Spacer(1, 16))
story.append(Paragraph("URLs de gestión", styles["h2"]))
story.append(thin_hr())

urls_data = [
    ["Servicio", "URL"],
    ["Meta Developer Console", "https://developers.facebook.com/apps/1695869685126292/"],
    ["Meta Business Suite", "https://business.facebook.com/"],
    ["Google Sheets", "https://docs.google.com/spreadsheets/d/1RSAc1hYS3utB13tK5VS3L-Qu2Kc8kaEHXiJnLk9BgHs/edit"],
    ["Google Tasks", "https://tasks.google.com/"],
]

# Use Paragraph for URL cells to make them clickable/wrappable
urls_table_data = [[
    Paragraph("<b>Servicio</b>", ParagraphStyle("TH", fontName="DMSans-Bold", fontSize=10, textColor=WHITE)),
    Paragraph("<b>URL</b>", ParagraphStyle("TH2", fontName="DMSans-Bold", fontSize=10, textColor=WHITE)),
]]
for row in urls_data[1:]:
    urls_table_data.append([
        Paragraph(f"<b>{row[0]}</b>", ParagraphStyle("TD1", fontName="DMSans-Bold", fontSize=9, textColor=DARK_TEXT)),
        Paragraph(f'<a href="{row[1]}" color="#128C7E"><u>{row[1]}</u></a>',
                  ParagraphStyle("TD2", fontName="DMSans", fontSize=8, textColor=GREEN, leading=11)),
    ])

urls_table = Table(urls_table_data, colWidths=[1.8*inch, 4.5*inch])
urls_table.setStyle(TableStyle([
    ("BACKGROUND", (0,0), (-1,0), GREEN),
    ("GRID", (0,0), (-1,-1), 0.5, BORDER_GRAY),
    ("ROWBACKGROUNDS", (0,1), (-1,-1), [WHITE, LIGHT_GREEN]),
    ("TOPPADDING", (0,0), (-1,-1), 6),
    ("BOTTOMPADDING", (0,0), (-1,-1), 6),
    ("LEFTPADDING", (0,0), (-1,-1), 8),
    ("VALIGN", (0,0), (-1,-1), "MIDDLE"),
]))
story.append(urls_table)

story.append(Spacer(1, 16))
story.append(Paragraph("Archivo del servidor", styles["h2"]))
story.append(thin_hr())
story.append(Paragraph(
    '<font face="Courier" size="10" color="#2C3E50">/home/user/workspace/wa-webhook/webhook_server.py</font>',
    styles["body_left"]
))

# ── Build ──
doc.build(story, onFirstPage=on_first_page, onLaterPages=on_later_pages)
print(f"PDF generado exitosamente: {OUTPUT}")
