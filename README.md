# WhatsApp Webhook — Control Correos James

Servidor webhook para recibir y procesar mensajes de WhatsApp Business.
Integra con Google Sheets, Google Tasks y WhatsApp Business API.

## Deploy en Railway

1. Subir este repositorio a GitHub
2. En [railway.app](https://railway.app) → New Project → Deploy from GitHub
3. Seleccionar este repositorio
4. En **Settings → Variables**, agregar:

| Variable | Valor |
|---|---|
| `WA_TOKEN` | Token permanente de Meta (ver abajo) |
| `VERIFY_TOKEN` | `james_control_correos_2026` |
| `PHONE_NUMBER_ID` | `1017000174828335` |

5. Railway genera una URL pública automáticamente (ej: `https://tu-app.up.railway.app`)
6. Registrar esa URL en Meta Developer Console como webhook

## Comandos disponibles (vía WhatsApp)

| Comando | Acción |
|---|---|
| `resumen` | Pendientes por negocio |
| `urgentes` | Solo urgentes pendientes |
| `tareas` | Ver Google Tasks |
| `ver N°X` | Detalle del registro X |
| `resolver N°X` | Marcar X como Resuelto |
| `agenda [asunto]` | Crear nueva tarea |
| `hoja` | Link al spreadsheet |
| `ayuda` | Lista completa |

## Generar token permanente de Meta

1. Ir a [business.facebook.com](https://business.facebook.com)
2. Configuración → Usuarios del sistema → Nuevo usuario (Admin)
3. Generar token → App: "Control Correos WA"
4. Permisos: `whatsapp_business_messaging` + `whatsapp_business_management`
5. Copiar token → pegarlo en Railway como variable `WA_TOKEN`

## Endpoints

- `GET /webhook` — Verificación de Meta
- `POST /webhook` — Recibe mensajes
- `GET /health` — Estado del servidor
