from fastapi import FastAPI, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from supabase import create_client, Client
import fitz
import os
from aiogram import Bot, Dispatcher, types
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext
from aiogram.filters import Command
from aiogram.types import FSInputFile, ContentType, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from contextlib import asynccontextmanager, suppress
import asyncio
import qrcode
from io import BytesIO
import random
from PIL import Image
import json

# ===================== CONFIGURACIÓN =====================
BOT_TOKEN = os.getenv("BOT_TOKEN", "")
SUPABASE_URL = "https://xsagwqepoljfsogusubw.supabase.co"
SUPABASE_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InhzYWd3cWVwb2xqZnNvZ3VzdWJ3Iiwicm9sZSI6ImFub24iLCJpYXQiOjE3NDM5NjM3NTUsImV4cCI6MjA1OTUzOTc1NX0.NUixULn0m2o49At8j6X58UqbXre2O2_JStqzls_8Gws"
BASE_URL = os.getenv("BASE_URL", "https://direcciongeneraltransporteguanajuato-gob.onrender.com")

# Directorios
OUTPUT_DIR = "documentos"
TEMPLATES_DIR = "templates"
STATIC_DIR = "static"
PDF_DIR = "static/pdfs"

os.makedirs(OUTPUT_DIR, exist_ok=True)
os.makedirs(TEMPLATES_DIR, exist_ok=True)
os.makedirs(STATIC_DIR, exist_ok=True)
os.makedirs(PDF_DIR, exist_ok=True)

# Plantillas
PLANTILLA_BOT_PRIMERA = "guanajuato_imagen_fullhd.pdf"
PLANTILLA_BOT_SEGUNDA = "guanajuato.pdf"
PLANTILLA_WEB = "guanajuato.pdf"

PRECIO_PERMISO = 150
ENTIDAD = "Guanajuato"
TZ = "America/Mexico_City"

# Admin hardcodeado
ADMIN_USER = "Serg890105tm3"
ADMIN_PASS = "Serg890105tm3"

templates = Jinja2Templates(directory=TEMPLATES_DIR)
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# ===================== BOT TELEGRAM =====================
bot = Bot(token=BOT_TOKEN)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)

# ===================== SISTEMA FOLIOS 192X =====================
_folio_lock = asyncio.Lock()
_ultimo_consecutivo = None

def _leer_consecutivo_local():
    try:
        with open("folio_192_cursor.json") as f:
            return int(json.load(f).get("ultimo", 0))
    except:
        return 0

def _guardar_consecutivo_local(consecutivo: int):
    try:
        with open("folio_192_cursor.json", "w") as f:
            json.dump({"ultimo": consecutivo}, f)
    except Exception as e:
        print(f"[WARN] Error guardando consecutivo: {e}")

def _leer_consecutivo_db():
    try:
        resp = supabase.table("folios_registrados") \
            .select("folio") \
            .like("folio", "192%") \
            .order("folio", desc=True) \
            .limit(1) \
            .execute()
        
        if resp.data and len(resp.data) > 0:
            ultimo_folio = str(resp.data[0]["folio"])
            if ultimo_folio.startswith("192"):
                return int(ultimo_folio[3:])
        return 0
    except:
        return 0

async def inicializar_sistema_folios_192():
    global _ultimo_consecutivo
    local = _leer_consecutivo_local()
    db = _leer_consecutivo_db()
    _ultimo_consecutivo = max(local, db)
    print(f"[FOLIO 192X] Inicializado. Último: {_ultimo_consecutivo}")
    _guardar_consecutivo_local(_ultimo_consecutivo)

async def generar_folio_192():
    global _ultimo_consecutivo
    
    async with _folio_lock:
        for _ in range(100000):
            _ultimo_consecutivo += 1
            folio = f"192{_ultimo_consecutivo}"
            
            try:
                verificacion = supabase.table("folios_registrados") \
                    .select("folio") \
                    .eq("folio", folio) \
                    .execute()
                
                if not verificacion.data:
                    _guardar_consecutivo_local(_ultimo_consecutivo)
                    print(f"[FOLIO 192X] Generado: {folio}")
                    return folio
            except:
                continue
        
        import time
        return f"192{int(time.time()) % 1000000}"

# ===================== TIMERS 36H =====================
timers_activos = {}
user_folios = {}

async def eliminar_folio_automatico(folio: str):
    try:
        user_id = None
        if folio in timers_activos:
            user_id = timers_activos[folio]["user_id"]
        
        supabase.table("folios_registrados").delete().eq("folio", folio).execute()
        supabase.table("borradores_registros").delete().eq("folio", folio).execute()
        
        if user_id:
            await bot.send_message(
                user_id,
                f"⏰ TIEMPO AGOTADO - GUANAJUATO\n\n"
                f"El folio {folio} ha sido eliminado por no pagar en 36 horas."
            )
        
        limpiar_timer_folio(folio)
    except Exception as e:
        print(f"Error eliminando folio {folio}: {e}")

async def enviar_recordatorio(folio: str, minutos: int):
    try:
        if folio not in timers_activos:
            return
        
        user_id = timers_activos[folio]["user_id"]
        await bot.send_message(
            user_id,
            f"⚡ RECORDATORIO - GUANAJUATO\n\n"
            f"Folio: {folio}\n"
            f"Tiempo restante: {minutos} min\n"
            f"Monto: ${PRECIO_PERMISO}\n\n"
            f"📸 Envíe comprobante"
        )
    except Exception as e:
        print(f"Error recordatorio {folio}: {e}")

async def iniciar_timer_pago(user_id: int, folio: str):
    async def timer_task():
        print(f"[TIMER] Iniciado {folio} (36h)")
        
        await asyncio.sleep(34.5 * 3600)
        if folio in timers_activos:
            await enviar_recordatorio(folio, 90)
        await asyncio.sleep(30 * 60)
        
        if folio in timers_activos:
            await enviar_recordatorio(folio, 60)
        await asyncio.sleep(30 * 60)
        
        if folio in timers_activos:
            await enviar_recordatorio(folio, 30)
        await asyncio.sleep(20 * 60)
        
        if folio in timers_activos:
            await enviar_recordatorio(folio, 10)
        await asyncio.sleep(10 * 60)
        
        if folio in timers_activos:
            await eliminar_folio_automatico(folio)
    
    task = asyncio.create_task(timer_task())
    timers_activos[folio] = {
        "task": task,
        "user_id": user_id,
        "start_time": datetime.now()
    }
    
    if user_id not in user_folios:
        user_folios[user_id] = []
    user_folios[user_id].append(folio)
    
    print(f"[TIMER] Iniciado {folio}, total: {len(timers_activos)}")

def cancelar_timer_folio(folio: str):
    if folio in timers_activos:
        timers_activos[folio]["task"].cancel()
        user_id = timers_activos[folio]["user_id"]
        del timers_activos[folio]
        
        if user_id in user_folios and folio in user_folios[user_id]:
            user_folios[user_id].remove(folio)
            if not user_folios[user_id]:
                del user_folios[user_id]
        
        print(f"[TIMER] Cancelado {folio}")
        return True
    return False

def limpiar_timer_folio(folio: str):
    if folio in timers_activos:
        user_id = timers_activos[folio]["user_id"]
        del timers_activos[folio]
        
        if user_id in user_folios and folio in user_folios[user_id]:
            user_folios[user_id].remove(folio)
            if not user_folios[user_id]:
                del user_folios[user_id]

def obtener_folios_usuario(user_id: int):
    return user_folios.get(user_id, [])

# ===================== FSM STATES =====================
class PermisoForm(StatesGroup):
    marca = State()
    linea = State()
    anio = State()
    serie = State()
    motor = State()
    color = State()
    nombre = State()

# ===================== COORDENADAS PDF =====================
coords_bot_primera = {
    "folio": (1800, 455, 60, (1, 0, 0)),
    "fecha": (2200, 580, 35, (0, 0, 0)),
    "marca": (385, 715, 35, (0, 0, 0)),
    "serie": (350, 800, 35, (0, 0, 0)),
    "linea": (800, 715, 35, (0, 0, 0)),
    "motor": (1290, 800, 35, (0, 0, 0)),
    "anio": (1500, 715, 35, (0, 0, 0)),
    "color": (1960, 715, 35, (0, 0, 0)),
    "nombre": (950, 1100, 50, (0, 0, 0)),
    "vigencia": (2200, 645, 35, (0, 0, 0)),
}

coords_bot_segunda = {
    "numero_serie": (255.0, 180.0, 10, (0, 0, 0)),
    "fecha": (255.0, 396.0, 10, (0, 0, 0)),
}

coords_qr_dinamico = {
    "x": 205,
    "y": 328,
    "ancho": 290,
    "alto": 290
}

# ===================== GENERACIÓN QR =====================
def generar_qr_dinamico(folio):
    try:
        url = f"{BASE_URL}/consulta/{folio}"
        qr = qrcode.QRCode(version=2, error_correction=qrcode.constants.ERROR_CORRECT_M, box_size=4, border=1)
        qr.add_data(url)
        qr.make(fit=True)
        img = qr.make_image(fill_color="black", back_color="white").convert("RGB")
        print(f"[QR DINÁMICO] {folio} -> {url}")
        return img, url
    except:
        return None, None

def generar_qr_texto(datos, folio):
    try:
        texto = f"""FOLIO: {folio}
NOMBRE: {datos.get('nombre', '')}
MARCA: {datos.get('marca', '')}
LINEA: {datos.get('linea', '')}
AÑO: {datos.get('anio', '')}
SERIE: {datos.get('serie', '')}
MOTOR: {datos.get('motor', '')}
COLOR: {datos.get('color', '')}
GUANAJUATO PERMISOS"""
        
        qr = qrcode.QRCode(version=2, error_correction=qrcode.constants.ERROR_CORRECT_H, box_size=10, border=2)
        qr.add_data(texto.upper())
        qr.make(fit=True)
        return qr.make_image(fill_color="black", back_color="white").convert("RGB")
    except:
        return None

# ===================== GENERACIÓN PDF BOT =====================
def generar_pdf_bot(folio, datos, fecha_exp, fecha_ven):
    """PDF completo del BOT (2 páginas + QRs)"""
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    
    doc_final = fitz.open()
    
    # PRIMERA PLANTILLA
    doc1 = fitz.open(PLANTILLA_BOT_PRIMERA)
    pg1 = doc1[0]
    
    pg1.insert_text(coords_bot_primera["folio"][:2], folio, 
                    fontsize=coords_bot_primera["folio"][2], 
                    color=coords_bot_primera["folio"][3])
    
    f_exp = fecha_exp.strftime("%d/%m/%Y")
    f_ven = fecha_ven.strftime("%d/%m/%Y")
    
    pg1.insert_text(coords_bot_primera["fecha"][:2], f_exp, 
                    fontsize=coords_bot_primera["fecha"][2], 
                    color=coords_bot_primera["fecha"][3])
    pg1.insert_text(coords_bot_primera["vigencia"][:2], f_ven, 
                    fontsize=coords_bot_primera["vigencia"][2], 
                    color=coords_bot_primera["vigencia"][3])

    for key in ["marca", "serie", "linea", "motor", "anio", "color"]:
        if key in datos:
            x, y, s, col = coords_bot_primera[key]
            pg1.insert_text((x, y), datos[key], fontsize=s, color=col)

    pg1.insert_text(coords_bot_primera["nombre"][:2], datos.get("nombre", ""), 
                    fontsize=coords_bot_primera["nombre"][2], 
                    color=coords_bot_primera["nombre"][3])

    # QR TEXTO
    img_qr_texto = generar_qr_texto(datos, folio)
    if img_qr_texto:
        buf = BytesIO()
        img_qr_texto.save(buf, format="PNG")
        buf.seek(0)
        qr_pix = fitz.Pixmap(buf.read())

        cm = 85.05
        ancho_qr = alto_qr = cm * 3.0
        page_width = pg1.rect.width
        x_qr = page_width - (2.5 * cm) - ancho_qr
        y_qr = 20.5 * cm

        pg1.insert_image(
            fitz.Rect(x_qr, y_qr, x_qr + ancho_qr, y_qr + alto_qr),
            pixmap=qr_pix,
            overlay=True
        )

    # QR DINÁMICO
    img_qr_din, url_qr = generar_qr_dinamico(folio)
    if img_qr_din:
        buf = BytesIO()
        img_qr_din.save(buf, format="PNG")
        buf.seek(0)
        qr_pix = fitz.Pixmap(buf.read())

        pg1.insert_image(
            fitz.Rect(coords_qr_dinamico["x"], coords_qr_dinamico["y"], 
                     coords_qr_dinamico["x"] + coords_qr_dinamico["ancho"], 
                     coords_qr_dinamico["y"] + coords_qr_dinamico["alto"]),
            pixmap=qr_pix,
            overlay=True
        )
    
    doc_final.insert_pdf(doc1)
    doc1.close()
    
    # SEGUNDA PLANTILLA
    doc2 = fitz.open(PLANTILLA_BOT_SEGUNDA)
    pg2 = doc2[0]
    
    pg2.insert_text(coords_bot_segunda["numero_serie"][:2], 
                    datos.get("serie", ""), 
                    fontsize=coords_bot_segunda["numero_serie"][2], 
                    color=coords_bot_segunda["numero_serie"][3])
    
    pg2.insert_text(coords_bot_segunda["fecha"][:2], 
                    f_exp, 
                    fontsize=coords_bot_segunda["fecha"][2], 
                    color=coords_bot_segunda["fecha"][3])
    
    doc_final.insert_pdf(doc2)
    doc2.close()
    
    salida = os.path.join(OUTPUT_DIR, f"{folio}_bot.pdf")
    doc_final.save(salida)
    doc_final.close()
    
    print(f"[PDF BOT] Generado: {salida}")
    return salida

# ===================== GENERACIÓN PDF WEB =====================
def generar_pdf_web(folio: str, numero_serie: str) -> bool:
    """PDF simple del PANEL WEB (1 página)"""
    try:
        fecha_texto = datetime.now(tz=ZoneInfo(TZ)).strftime("%d/%m/%Y")
        ruta_pdf = f"{PDF_DIR}/{folio}.pdf"
        
        doc = fitz.open(PLANTILLA_WEB)
        page = doc[0]
        page.insert_text((255.0, 180.0), numero_serie, fontsize=10, fontname="helv")
        page.insert_text((255.0, 396.0), fecha_texto, fontsize=10, fontname="helv")
        doc.save(ruta_pdf)
        doc.close()
        
        print(f"[PDF WEB] Generado: {ruta_pdf}")
        return True
    except Exception as e:
        print(f"[PDF WEB] Error: {e}")
        return False

# ===================== HANDLERS BOT =====================
@dp.message(Command("start"))
async def start_cmd(message: types.Message, state: FSMContext):
    await state.clear()
    await message.answer(
        "🏛️ SISTEMA GUANAJUATO\n\n"
        f"💰 Costo: ${PRECIO_PERMISO}\n"
        "⏰ Tiempo de pago: 36 horas\n\n"
        "⚠️ El folio será eliminado si no paga"
    )

@dp.message(Command("chuleta"))
async def chuleta_cmd(message: types.Message, state: FSMContext):
    folios_activos = obtener_folios_usuario(message.from_user.id)
    
    msg_folios = ""
    if folios_activos:
        msg_folios = f"\n\n📋 Folios activos: {', '.join(folios_activos)}"
    
    await message.answer(
        f"🚗 NUEVO PERMISO GUANAJUATO\n\n"
        f"💰 Costo: ${PRECIO_PERMISO}\n"
        f"⏰ 36 horas para pagar"
        + msg_folios + "\n\n"
        "Paso 1/7: MARCA del vehículo"
    )
    await state.set_state(PermisoForm.marca)

@dp.message(PermisoForm.marca)
async def get_marca(message: types.Message, state: FSMContext):
    await state.update_data(marca=message.text.strip().upper())
    await message.answer("Paso 2/7: LÍNEA/MODELO")
    await state.set_state(PermisoForm.linea)

@dp.message(PermisoForm.linea)
async def get_linea(message: types.Message, state: FSMContext):
    await state.update_data(linea=message.text.strip().upper())
    await message.answer("Paso 3/7: AÑO (4 dígitos)")
    await state.set_state(PermisoForm.anio)

@dp.message(PermisoForm.anio)
async def get_anio(message: types.Message, state: FSMContext):
    anio = message.text.strip()
    if not anio.isdigit() or len(anio) != 4:
        await message.answer("⚠️ Año inválido. Intenta de nuevo:")
        return
    await state.update_data(anio=anio)
    await message.answer("Paso 4/7: NÚMERO DE SERIE")
    await state.set_state(PermisoForm.serie)

@dp.message(PermisoForm.serie)
async def get_serie(message: types.Message, state: FSMContext):
    await state.update_data(serie=message.text.strip().upper())
    await message.answer("Paso 5/7: NÚMERO DE MOTOR")
    await state.set_state(PermisoForm.motor)

@dp.message(PermisoForm.motor)
async def get_motor(message: types.Message, state: FSMContext):
    await state.update_data(motor=message.text.strip().upper())
    await message.answer("Paso 6/7: COLOR")
    await state.set_state(PermisoForm.color)

@dp.message(PermisoForm.color)
async def get_color(message: types.Message, state: FSMContext):
    await state.update_data(color=message.text.strip().upper())
    await message.answer("Paso 7/7: NOMBRE COMPLETO")
    await state.set_state(PermisoForm.nombre)

@dp.message(PermisoForm.nombre)
async def get_nombre(message: types.Message, state: FSMContext):
    datos = await state.get_data()
    datos["nombre"] = message.text.strip().upper()

    hoy = datetime.now()
    ven = hoy + timedelta(days=30)
    datos["fecha_exp"] = hoy
    datos["fecha_ven"] = ven

    await message.answer("🔄 Generando folio 192X...")

    try:
        folio = await generar_folio_192()
        datos["folio"] = folio
        
        supabase.table("folios_registrados").insert({
            "folio": folio,
            "marca": datos["marca"],
            "linea": datos["linea"],
            "anio": datos["anio"],
            "numero_serie": datos["serie"],
            "numero_motor": datos["motor"],
            "color": datos["color"],
            "nombre": datos["nombre"],
            "fecha_expedicion": hoy.date().isoformat(),
            "fecha_vencimiento": ven.date().isoformat(),
            "entidad": ENTIDAD,
            "estado": "PENDIENTE",
            "user_id": message.from_user.id,
            "username": message.from_user.username or "Sin username"
        }).execute()

        pdf = generar_pdf_bot(folio, datos, hoy, ven)

        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(text="🔑 Validar Admin", callback_data=f"validar_{folio}"),
                InlineKeyboardButton(text="⏹️ Detener Timer", callback_data=f"detener_{folio}")
            ]
        ])

        await message.answer_document(
            FSInputFile(pdf),
            caption=f"📋 PERMISO GUANAJUATO\nFolio: {folio}\n⏰ TIMER ACTIVO (36h)",
            reply_markup=keyboard
        )

        await iniciar_timer_pago(message.from_user.id, folio)

        await message.answer(
            f"💰 PAGO\n\n"
            f"Folio: {folio}\n"
            f"Monto: ${PRECIO_PERMISO}\n"
            f"⏰ 36 horas\n\n"
            f"📸 Envía comprobante"
        )
        
    except Exception as e:
        await message.answer(f"❌ ERROR: {e}")
    finally:
        await state.clear()

@dp.callback_query(lambda c: c.data and c.data.startswith("validar_"))
async def callback_validar(callback: CallbackQuery):
    folio = callback.data.replace("validar_", "")
    
    if folio in timers_activos:
        user_id = timers_activos[folio]["user_id"]
        cancelar_timer_folio(folio)
        
        supabase.table("folios_registrados").update({
            "estado": "VALIDADO_ADMIN"
        }).eq("folio", folio).execute()
        
        await callback.answer("✅ Validado", show_alert=True)
        await callback.message.edit_reply_markup(reply_markup=None)
        
        await bot.send_message(user_id, f"✅ PAGO VALIDADO\nFolio: {folio}")
    else:
        await callback.answer("❌ No encontrado", show_alert=True)

@dp.callback_query(lambda c: c.data and c.data.startswith("detener_"))
async def callback_detener(callback: CallbackQuery):
    folio = callback.data.replace("detener_", "")
    
    if folio in timers_activos:
        cancelar_timer_folio(folio)
        
        supabase.table("folios_registrados").update({
            "estado": "TIMER_DETENIDO"
        }).eq("folio", folio).execute()
        
        await callback.answer("⏹️ Timer detenido", show_alert=True)
        await callback.message.edit_reply_markup(reply_markup=None)
    else:
        await callback.answer("❌ Timer inactivo", show_alert=True)

@dp.message(lambda m: m.text and m.text.strip().upper().startswith("SERO"))
async def admin_sero(message: types.Message):
    texto = message.text.strip().upper()
    
    if len(texto) > 4:
        folio = texto[4:]
        
        if not folio.startswith("192"):
            await message.answer("⚠️ Folio inválido. Debe empezar con 192")
            return
        
        if folio in timers_activos:
            user_id = timers_activos[folio]["user_id"]
            cancelar_timer_folio(folio)
            
            supabase.table("folios_registrados").update({
                "estado": "VALIDADO_ADMIN"
            }).eq("folio", folio).execute()
            
            await message.answer(f"✅ Validado: {folio}")
            await bot.send_message(user_id, f"✅ PAGO VALIDADO\nFolio: {folio}")
        else:
            await message.answer(f"❌ Folio no encontrado: {folio}")
    else:
        await message.answer(f"📋 Timers activos: {len(timers_activos)}\n\nUso: SERO[FOLIO]")

@dp.message(lambda m: m.content_type == ContentType.PHOTO)
async def recibir_comprobante(message: types.Message):
    user_id = message.from_user.id
    folios = obtener_folios_usuario(user_id)
    
    if not folios:
        await message.answer("ℹ️ No tienes folios pendientes")
        return
    
    if len(folios) > 1:
        lista = '\n'.join([f"• {f}" for f in folios])
        await message.answer(f"📄 Tienes {len(folios)} folios:\n{lista}\n\nResponde con el folio")
        return
    
    folio = folios[0]
    cancelar_timer_folio(folio)
    
    supabase.table("folios_registrados").update({
        "estado": "COMPROBANTE_ENVIADO"
    }).eq("folio", folio).execute()
    
    await message.answer(f"✅ Comprobante recibido\nFolio: {folio}\n⏹️ Timer detenido")

@dp.message(Command("folios"))
async def ver_folios(message: types.Message):
    folios = obtener_folios_usuario(message.from_user.id)
    
    if not folios:
        await message.answer("ℹ️ No tienes folios activos")
        return
    
    lista = []
    for f in folios:
        if f in timers_activos:
            tiempo = 2160 - int((datetime.now() - timers_activos[f]["start_time"]).total_seconds() / 60)
            tiempo = max(0, tiempo)
            h = tiempo // 60
            m = tiempo % 60
            lista.append(f"• {f} ({h}h {m}min)")
        else:
            lista.append(f"• {f} (sin timer)")
    
    await message.answer(f"📋 Folios activos ({len(folios)}):\n\n" + '\n'.join(lista))

@dp.message()
async def fallback(message: types.Message):
    await message.answer("🏛️ Sistema Guanajuato")

# ===================== FASTAPI =====================
_keep_task = None

async def keep_alive():
    while True:
        await asyncio.sleep(600)
        print("[HEARTBEAT] Sistema activo")

@asynccontextmanager
async def lifespan(app: FastAPI):
    global _keep_task
    
    await inicializar_sistema_folios_192()
    
    await bot.delete_webhook(drop_pending_updates=True)
    if BASE_URL:
        await bot.set_webhook(f"{BASE_URL}/webhook", allowed_updates=["message", "callback_query"])
        _keep_task = asyncio.create_task(keep_alive())
    
    print("[SISTEMA] Guanajuato Bot + Web iniciado")
    
    yield
    
    if _keep_task:
        _keep_task.cancel()
        with suppress(asyncio.CancelledError):
            await _keep_task
    await bot.session.close()

app = FastAPI(lifespan=lifespan)

app.add_middleware(SessionMiddleware, secret_key="clave_muy_segura_123456")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

# ===================== RUTAS WEB =====================
@app.post("/webhook")
async def telegram_webhook(request: Request):
    try:
        data = await request.json()
        update = types.Update(**data)
        await dp.feed_webhook_update(bot, update)
        return {"ok": True}
    except Exception as e:
        print(f"[WEBHOOK] Error: {e}")
        return {"ok": False}

@app.get("/", response_class=HTMLResponse)
async def root():
    return RedirectResponse(url="/login")

@app.get("/login", response_class=HTMLResponse)
async def login_get(request: Request):
    return templates.TemplateResponse("login.html", {"request": request})

@app.post("/login")
async def login_post(request: Request, username: str = Form(...), password: str = Form(...)):
    # Admin
    if username == ADMIN_USER and password == ADMIN_PASS:
        request.session["admin"] = True
        return RedirectResponse(url="/admin", status_code=303)
    
    # Usuario normal
    res = supabase.table("verificaciondigitalcdmx") \
        .select("*") \
        .eq("username", username) \
        .eq("password", password) \
        .execute()
    
    if res.data:
        request.session["user_id"] = res.data[0]['id']
        request.session["username"] = username
        return RedirectResponse(url="/registro_usuario", status_code=303)
    
    return templates.TemplateResponse("bloqueado.html", {"request": request})

@app.get("/admin", response_class=HTMLResponse)
async def admin(request: Request):
    if not request.session.get("admin"):
        return RedirectResponse(url="/login", status_code=303)
    return templates.TemplateResponse("panel.html", {"request": request})

@app.get("/crear_usuario", response_class=HTMLResponse)
async def crear_usuario_get(request: Request):
    if not request.session.get("admin"):
        return RedirectResponse(url="/login", status_code=303)
    return templates.TemplateResponse("crear_usuario.html", {"request": request})

@app.post("/crear_usuario")
async def crear_usuario_post(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    folios: int = Form(...)
):
    if not request.session.get("admin"):
        return RedirectResponse(url="/login", status_code=303)
    
    exists = supabase.table("verificaciondigitalcdmx") \
        .select("id") \
        .eq("username", username) \
        .execute()
    
    if exists.data:
        return templates.TemplateResponse("crear_usuario.html", {
            "request": request,
            "error": "Usuario ya existe"
        })
    
    supabase.table("verificaciondigitalcdmx").insert({
        "username": username,
        "password": password,
        "folios_asignac": folios,
        "folios_usados": 0
    }).execute()
    
    return templates.TemplateResponse("crear_usuario.html", {
        "request": request,
        "success": "Usuario creado"
    })

@app.get("/registro_usuario", response_class=HTMLResponse)
async def registro_usuario_get(request: Request):
    if not request.session.get("user_id"):
        return RedirectResponse(url="/login", status_code=303)
    
    uid = request.session["user_id"]
    info = supabase.table("verificaciondigitalcdmx") \
        .select("folios_asignac, folios_usados") \
        .eq("id", uid) \
        .execute().data[0]
    
    return templates.TemplateResponse("registro_usuario.html", {
        "request": request,
        "folios_info": info
    })

@app.post("/registro_usuario")
async def registro_usuario_post(
    request: Request,
    folio: str = Form(...),
    marca: str = Form(...),
    linea: str = Form(...),
    anio: str = Form(...),
    serie: str = Form(...),
    motor: str = Form(...),
    telefono: str = Form(""),
    vigencia: int = Form(...)
):
    if not request.session.get("user_id"):
        return RedirectResponse(url="/login", status_code=303)
    
    uid = request.session["user_id"]
    
    # Verifica duplicado
    if supabase.table("folios_registrados").select("folio").eq("folio", folio).execute().data:
        return templates.TemplateResponse("registro_usuario.html", {
            "request": request,
            "error": "Folio ya existe"
        })
    
    # Verifica folios disponibles
    ud = supabase.table("verificaciondigitalcdmx") \
        .select("folios_asignac, folios_usados") \
        .eq("id", uid) \
        .execute().data[0]
    
    if ud['folios_asignac'] - ud['folios_usados'] < 1:
        return templates.TemplateResponse("registro_usuario.html", {
            "request": request,
            "error": "Sin folios disponibles"
        })
    
    ahora = datetime.now()
    supabase.table("folios_registrados").insert({
        "folio": folio,
        "marca": marca,
        "linea": linea,
        "anio": anio,
        "numero_serie": serie,
        "numero_motor": motor,
        "fecha_expedicion": ahora.isoformat(),
        "fecha_vencimiento": (ahora + timedelta(days=vigencia)).isoformat(),
        "entidad": ENTIDAD,
        "numero_telefono": telefono
    }).execute()
    
    supabase.table("verificaciondigitalcdmx").update({
        "folios_usados": ud['folios_usados'] + 1
    }).eq("id", uid).execute()
    
    generar_pdf_web(folio, serie)
    
    return templates.TemplateResponse("exitoso.html", {
        "request": request,
        "folio": folio,
        "enlace_pdf": f"/descargar_pdf/{folio}"
    })

@app.get("/registro_admin", response_class=HTMLResponse)
async def registro_admin_get(request: Request):
    if not request.session.get("admin"):
        return RedirectResponse(url="/login", status_code=303)
    return templates.TemplateResponse("registro_admin.html", {"request": request})

@app.post("/registro_admin")
async def registro_admin_post(
    request: Request,
    folio: str = Form(...),
    marca: str = Form(...),
    linea: str = Form(...),
    anio: str = Form(...),
    serie: str = Form(...),
    motor: str = Form(...),
    telefono: str = Form(""),
    vigencia: int = Form(...)
):
    if not request.session.get("admin"):
        return RedirectResponse(url="/login", status_code=303)
    
    if supabase.table("folios_registrados").select("folio").eq("folio", folio).execute().data:
        return templates.TemplateResponse("registro_admin.html", {
            "request": request,
            "error": "Folio ya existe"
        })
    
    ahora = datetime.now()
    supabase.table("folios_registrados").insert({
        "folio": folio,
        "marca": marca,
        "linea": linea,
        "anio": anio,
        "numero_serie": serie,
        "numero_motor": motor,
        "fecha_expedicion": ahora.isoformat(),
        "fecha_vencimiento": (ahora + timedelta(days=vigencia)).isoformat(),
        "entidad": ENTIDAD,
        "numero_telefono": telefono
    }).execute()
    
    generar_pdf_web(folio, serie)
    
    return templates.TemplateResponse("exitoso.html", {
        "request": request,
        "folio": folio,
        "enlace_pdf": f"/descargar_pdf/{folio}"
    })

@app.get("/consulta_folio", response_class=HTMLResponse)
async def consulta_folio_get(request: Request):
    return templates.TemplateResponse("consulta_folio.html", {"request": request})

@app.post("/consulta_folio")
async def consulta_folio_post(request: Request, folio: str = Form(...)):
    folio = folio.strip().upper()
    row = supabase.table("folios_registrados").select("*").eq("folio", folio).execute().data
    
    if not row:
        resultado = {"estado": "No encontrado", "folio": folio}
    else:
        r = row[0]
        fe = datetime.fromisoformat(r['fecha_expedicion'])
        fv = datetime.fromisoformat(r['fecha_vencimiento'])
        estado = "VIGENTE" if datetime.now() <= fv else "VENCIDO"
        resultado = {
            "estado": estado,
            "folio": folio,
            "fecha_expedicion": fe.strftime("%d/%m/%Y"),
            "fecha_vencimiento": fv.strftime("%d/%m/%Y"),
            "marca": r['marca'],
            "linea": r['linea'],
            "año": r['anio'],
            "numero_serie": r['numero_serie'],
            "numero_motor": r['numero_motor'],
            "entidad": r.get('entidad', ''),
            "telefono": r.get('numero_telefono', '')
        }
    
    return templates.TemplateResponse("resultado_consulta.html", {
        "request": request,
        "resultado": resultado
    })

@app.get("/consulta/{folio}", response_class=HTMLResponse)
async def consulta_directa(folio: str, request: Request):
    """Ruta para QR dinámico"""
    folio = folio.strip().upper()
    row = supabase.table("folios_registrados").select("*").eq("folio", folio).execute().data
    
    if not row:
        resultado = {"estado": "No encontrado", "folio": folio}
    else:
        r = row[0]
        fe = datetime.fromisoformat(r['fecha_expedicion'])
        fv = datetime.fromisoformat(r['fecha_vencimiento'])
        estado = "VIGENTE" if datetime.now() <= fv else "VENCIDO"
        resultado = {
            "estado": estado,
            "folio": folio,
            "fecha_expedicion": fe.strftime("%d/%m/%Y"),
            "fecha_vencimiento": fv.strftime("%d/%m/%Y"),
            "marca": r['marca'],
            "linea": r['linea'],
            "año": r['anio'],
            "numero_serie": r['numero_serie'],
            "numero_motor": r['numero_motor'],
            "entidad": r.get('entidad', ''),
            "telefono": r.get('numero_telefono', '')
        }
    
    return templates.TemplateResponse("resultado_consulta.html", {
        "request": request,
        "resultado": resultado
    })

@app.get("/admin_folios", response_class=HTMLResponse)
async def admin_folios(request: Request):
    if not request.session.get("admin"):
        return RedirectResponse(url="/login", status_code=303)
    
    folios = supabase.table("folios_registrados").select("*").execute().data or []
    ahora = datetime.now()
    
    for f in folios:
        fv = datetime.fromisoformat(f['fecha_vencimiento'])
        f['estado'] = "VIGENTE" if ahora <= fv else "VENCIDO"
    
    return templates.TemplateResponse("admin_folios.html", {
        "request": request,
        "folios": folios
    })

@app.get("/editar_folio/{folio}", response_class=HTMLResponse)
async def editar_folio_get(folio: str, request: Request):
    if not request.session.get("admin"):
        return RedirectResponse(url="/login", status_code=303)
    
    row = supabase.table("folios_registrados").select("*").eq("folio", folio).execute().data
    
    if not row:
        return RedirectResponse(url="/admin_folios", status_code=303)
    
    return templates.TemplateResponse("editar_folio.html", {
        "request": request,
        "folio": row[0]
    })

@app.post("/editar_folio/{folio}")
async def editar_folio_post(
    folio: str,
    request: Request,
    marca: str = Form(...),
    linea: str = Form(...),
    anio: str = Form(...),
    numero_serie: str = Form(...),
    numero_motor: str = Form(...),
    entidad: str = Form(...),
    numero_telefono: str = Form(...),
    fecha_expedicion: str = Form(...),
    fecha_vencimiento: str = Form(...)
):
    if not request.session.get("admin"):
        return RedirectResponse(url="/login", status_code=303)
    
    supabase.table("folios_registrados").update({
        "marca": marca,
        "linea": linea,
        "anio": anio,
        "numero_serie": numero_serie,
        "numero_motor": numero_motor,
        "entidad": entidad,
        "numero_telefono": numero_telefono,
        "fecha_expedicion": fecha_expedicion,
        "fecha_vencimiento": fecha_vencimiento
    }).eq("folio", folio).execute()
    
    return RedirectResponse(url="/admin_folios", status_code=303)

@app.post("/eliminar_folio")
async def eliminar_folio(request: Request, folio: str = Form(...)):
    if not request.session.get("admin"):
        return RedirectResponse(url="/login", status_code=303)
    
    supabase.table("folios_registrados").delete().eq("folio", folio).execute()
    return RedirectResponse(url="/admin_folios", status_code=303)

@app.get("/descargar_pdf/{folio}")
async def descargar_pdf(folio: str):
    path = f"{PDF_DIR}/{folio}.pdf"
    return FileResponse(path, media_type="application/pdf", filename=f"{folio}.pdf")

@app.get("/logout")
async def logout(request: Request):
    request.session.clear()
    return RedirectResponse(url="/login", status_code=303)

@app.get("/status")
async def status():
    return {
        "sistema": "Guanajuato Unificado (Bot + Web)",
        "version": "1.0",
        "bot_activo": True,
        "web_activo": True,
        "folios_192x": _ultimo_consecutivo,
        "timers_activos": len(timers_activos)
    }

if __name__ == '__main__':
    import uvicorn
    port = int(os.getenv("PORT", 8000))
    print(f"[ARRANQUE] Puerto {port}")
    uvicorn.run(app, host="0.0.0.0", port=port)
