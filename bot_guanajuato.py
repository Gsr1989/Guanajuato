"""
GUANAJUATO — Bot de Telegram (aiogram).

Cambios respecto al original recuperado del .docx:
  · Ya NO crea su propia app FastAPI (eso lo hace main.py)
  · Usa el generador de folio y el PDF completo compartidos de config_guanajuato
  · ⚠️ El candado de PDF es el compartido con el panel (antes ninguno tenía uno)
  · Se corrigió "len(anio) ¡= 4" -> "len(anio) != 4" (autocorrección de Word)
  · Se corrigió la entidad a minúscula "guanajuato" (antes "Guanajuato")
  · Se agregó snapshot_timers() para que el panel web liste los timers
  · El lifespan se partió en arranque_bot() / cierre_bot()
Los handlers y el FSM quedaron idénticos a la lógica original.
"""

from datetime import datetime, timedelta
import asyncio
import aiohttp

from aiogram import Bot, Dispatcher, types
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext
from aiogram.filters import Command
from aiogram.types import (FSInputFile, ContentType, InlineKeyboardMarkup,
                           InlineKeyboardButton, CallbackQuery)

from config_guanajuato import (
    supabase, logger, BOT_TOKEN, BASE_URL, TZ_MEXICO, now_guanajuato,
    ENTIDAD, PRECIO_PERMISO, DIAS_PERMISO, HORAS_TIMER_BOT,
    FOLIO_NUM_PREFIJO, generar_folio_guanajuato, leer_siguiente_folio,
    generar_subir_y_guardar_pdf,
)

_bot_session = AiohttpSession(timeout=aiohttp.ClientTimeout(total=300))
bot     = Bot(token=BOT_TOKEN, session=_bot_session)
storage = MemoryStorage()
dp      = Dispatcher(storage=storage)

timers_activos       = {}
user_folios          = {}
pending_comprobantes = {}
TOTAL_MINUTOS_TIMER  = HORAS_TIMER_BOT * 60

_folio_lock = asyncio.Lock()


async def generar_folio_192() -> str:
    """Usa el generador compartido (mismo candado que el panel)."""
    async with _folio_lock:
        return await asyncio.to_thread(generar_folio_guanajuato)


# ── TIMERS ────────────────────────────────────────────────────────────────────
async def eliminar_folio_automatico(folio: str):
    try:
        user_id = timers_activos.get(folio, {}).get("user_id")
        await asyncio.to_thread(lambda: (
            supabase.table("folios_registrados").delete().eq("folio", folio).execute(),
            supabase.table("borradores_registros").delete().eq("folio", folio).execute(),
        ))
        if user_id:
            await bot.send_message(user_id,
                f"⏰ TIEMPO AGOTADO - GUANAJUATO\n\n"
                f"El folio {folio} ha sido eliminado por no completar el pago en {HORAS_TIMER_BOT} horas.\n\n"
                f"📋 Para generar otro permiso use /banamex")
        limpiar_timer_folio(folio)
    except Exception as e:
        print(f"Error eliminando folio {folio}: {e}")


async def enviar_recordatorio(folio: str, minutos_restantes: int):
    try:
        if folio not in timers_activos:
            return
        user_id = timers_activos[folio]["user_id"]
        await bot.send_message(user_id,
            f"⚡ RECORDATORIO DE PAGO - GUANAJUATO\n\n"
            f"Folio: {folio}\n"
            f"Tiempo restante: {minutos_restantes} minutos\n"
            f"Monto: ${PRECIO_PERMISO}\n\n"
            f"📸 Envíe su comprobante de pago (imagen).\n\n"
            f"📋 Para generar otro permiso use /banamex")
    except Exception as e:
        print(f"Error enviando recordatorio para folio {folio}: {e}")


async def iniciar_timer_pago(user_id: int, folio: str, nombre: str = ""):
    async def timer_task():
        print(f"[TIMER] Iniciado folio {folio}, usuario {user_id} ({HORAS_TIMER_BOT}h)")
        await asyncio.sleep(34.5 * 3600)
        if folio not in timers_activos: return
        await enviar_recordatorio(folio, 90)
        await asyncio.sleep(30 * 60)
        if folio not in timers_activos: return
        await enviar_recordatorio(folio, 60)
        await asyncio.sleep(30 * 60)
        if folio not in timers_activos: return
        await enviar_recordatorio(folio, 30)
        await asyncio.sleep(20 * 60)
        if folio not in timers_activos: return
        await enviar_recordatorio(folio, 10)
        await asyncio.sleep(10 * 60)
        if folio in timers_activos:
            print(f"[TIMER] Expirado folio {folio} - eliminando")
            await eliminar_folio_automatico(folio)

    task = asyncio.create_task(timer_task())
    timers_activos[folio] = {"task": task, "user_id": user_id,
                             "start_time": datetime.now(), "nombre": nombre}
    user_folios.setdefault(user_id, []).append(folio)
    print(f"[SISTEMA] Timer {HORAS_TIMER_BOT}h iniciado folio {folio}, total: {len(timers_activos)}")


def cancelar_timer_folio(folio: str):
    if folio in timers_activos:
        try:
            timers_activos[folio]["task"].cancel()
        except Exception:
            pass
        uid = timers_activos[folio]["user_id"]
        del timers_activos[folio]
        if uid in user_folios and folio in user_folios[uid]:
            user_folios[uid].remove(folio)
            if not user_folios[uid]:
                del user_folios[uid]
        print(f"[SISTEMA] Timer cancelado folio {folio}")
        return True
    return False


def limpiar_timer_folio(folio: str):
    if folio in timers_activos:
        uid = timers_activos[folio]["user_id"]
        del timers_activos[folio]
        if uid in user_folios and folio in user_folios[uid]:
            user_folios[uid].remove(folio)
            if not user_folios[uid]:
                del user_folios[uid]


def obtener_folios_usuario(user_id: int) -> list:
    return user_folios.get(user_id, [])


def snapshot_timers() -> list:
    """Lista los timers activos para que el PANEL WEB pueda mostrarlos."""
    salida = []
    for folio, info in timers_activos.items():
        mins = max(0, TOTAL_MINUTOS_TIMER - int(
            (datetime.now() - info["start_time"]).total_seconds() / 60))
        salida.append({
            "folio":    folio,
            "nombre":   info.get("nombre", ""),
            "user_id":  info.get("user_id"),
            "restante": f"{mins//60}h {mins%60}min",
            "minutos":  mins,
        })
    salida.sort(key=lambda x: x["minutos"])
    return salida


# ── FSM ───────────────────────────────────────────────────────────────────────
class PermisoForm(StatesGroup):
    marca  = State()
    linea  = State()
    anio   = State()
    serie  = State()
    motor  = State()
    color  = State()
    nombre = State()


# ── BACKGROUND TASK ───────────────────────────────────────────────────────────
async def _generar_y_enviar_background(chat_id: int, datos: dict,
                                       user_id: int, username: str,
                                       folio: str, hoy: datetime, fecha_ven: datetime):
    """PDF, insert y envío en background. El webhook ya respondió."""
    folio_final = folio
    try:
        pdf_path, _ = await asyncio.to_thread(
            generar_subir_y_guardar_pdf, folio_final, datos, hoy, fecha_ven
        )

        keyboard = InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="🔑 Validar Admin",  callback_data=f"validar_{folio_final}"),
            InlineKeyboardButton(text="⏹️ Detener Timer",  callback_data=f"detener_{folio_final}")
        ]])

        await bot.send_document(
            chat_id, FSInputFile(pdf_path),
            caption=(
                f"📋 PERMISO COMPLETO GUANAJUATO\n"
                f"Folio: {folio_final}\n"
                f"Vigencia: {fecha_ven.strftime('%d/%m/%Y')}\n"
                f"📄 2 páginas + QR dinámico de verificación\n\n"
                f"⏰ TIMER ACTIVO ({HORAS_TIMER_BOT} horas)"
            ),
            reply_markup=keyboard
        )

        def _insert_folios(folio_usar: str):
            supabase.table("folios_registrados").insert({
                "folio":             folio_usar,
                "marca":             datos["marca"],
                "linea":             datos["linea"],
                "anio":              datos["anio"],
                "numero_serie":      datos["serie"],
                "numero_motor":      datos["motor"],
                "color":             datos["color"],
                "nombre":            datos["nombre"],
                "fecha_expedicion":  hoy.date().isoformat(),
                "fecha_vencimiento": fecha_ven.date().isoformat(),
                "entidad":           ENTIDAD,
                "estado":            "PENDIENTE",
                "user_id":           user_id,
                "creado_por":        f"BOT_TG_{username or 'unknown'}",
            }).execute()

        for _ in range(20):
            try:
                await asyncio.to_thread(_insert_folios, folio_final)
                print(f"[DB] Insertado folio {folio_final}")
                break
            except Exception as e:
                em = str(e).lower()
                if any(k in em for k in ("duplicate", "unique", "23505")):
                    print(f"[DB] Folio {folio_final} duplicado - obteniendo nuevo...")
                    folio_final = await generar_folio_192()
                else:
                    print(f"[DB ERROR] {e}"); break

        try:
            await asyncio.to_thread(lambda: supabase.table("borradores_registros").insert({
                "folio":             folio_final,
                "entidad":           ENTIDAD,
                "numero_serie":      datos["serie"],
                "marca":             datos["marca"],
                "linea":             datos["linea"],
                "numero_motor":      datos["motor"],
                "anio":              datos["anio"],
                "color":             datos["color"],
                "fecha_expedicion":  hoy.isoformat(),
                "fecha_vencimiento": fecha_ven.isoformat(),
                "contribuyente":     datos["nombre"],
                "estado":            "PENDIENTE",
                "user_id":           user_id
            }).execute())
        except Exception as e:
            print(f"[WARN] Error guardando borrador: {e}")

        await iniciar_timer_pago(user_id, folio_final, datos.get("nombre", ""))

        await bot.send_message(user_id,
            f"💰 INSTRUCCIONES DE PAGO\n\n"
            f"📄 Folio: {folio_final}\n"
            f"💵 Cantidad: ${PRECIO_PERMISO}\n"
            f"⏰ Tiempo límite: {HORAS_TIMER_BOT} horas\n\n"
            "🏦 TRANSFERENCIA:\n"
            "• Banco: [TU BANCO]\n"
            "• Cuenta: [TU CUENTA]\n"
            "• CLABE: [TU CLABE]\n"
            f"• Concepto: Permiso {folio_final}\n\n"
            "🏪 OXXO:\n"
            "• Referencia: [TU REFERENCIA]\n"
            f"• Cantidad: ${PRECIO_PERMISO}\n\n"
            f"📸 Envía foto del comprobante para validar.\n"
            f"⚠️ Sin pago en {HORAS_TIMER_BOT}h el folio se elimina.\n\n"
            f"📋 Para generar otro permiso use /banamex")
    except Exception as e:
        print(f"[ERROR] background folio {folio_final}: {e}")
        try:
            await bot.send_message(user_id,
                f"❌ Error al generar el documento: {e}\n\nUse /banamex para reintentar.")
        except Exception:
            pass


# ── HANDLERS ──────────────────────────────────────────────────────────────────
@dp.message(Command("start"))
async def start_cmd(message: types.Message, state: FSMContext):
    await state.clear()
    await message.answer(
        "🏛️ SISTEMA DIGITAL DE PERMISOS - GUANAJUATO\n\n"
        f"🚗 Permiso de circulación: ${PRECIO_PERMISO}\n"
        f"⏰ Tiempo límite de pago: {HORAS_TIMER_BOT} horas\n"
        "💳 Métodos: Transferencia y OXXO\n\n"
        "⚠️ Su folio será eliminado automáticamente si no realiza el pago dentro del tiempo límite"
    )


@dp.message(Command("banamex"))
async def banamex_cmd(message: types.Message, state: FSMContext):
    await state.clear()
    folios_activos = obtener_folios_usuario(message.from_user.id)
    if folios_activos:
        texto   = "📋 FOLIOS ACTIVOS CON TIMER\n" + "─" * 28 + "\n\n"
        botones = []
        for f in folios_activos:
            if f in timers_activos:
                info = timers_activos[f]
                seg  = max(0, int(HORAS_TIMER_BOT * 3600 -
                    (datetime.now() - info["start_time"]).total_seconds()))
                h, m = divmod(seg // 60, 60)
                texto += f"Folio: {f}\n{h}h {m}min restantes\n\n"
            else:
                texto += f"Folio: {f}\n(sin timer)\n\n"
            botones.append([InlineKeyboardButton(
                text=f"⏹️ Detener timer {f}", callback_data=f"detener_{f}")])
        await message.answer(texto.strip(),
                             reply_markup=InlineKeyboardMarkup(inline_keyboard=botones))
        await message.answer(
            f"Para NUEVO permiso escribe la MARCA del vehículo:\n\nCosto: ${PRECIO_PERMISO} | Plazo: {HORAS_TIMER_BOT}h")
    else:
        await message.answer(
            f"🚗 NUEVO PERMISO DE GUANAJUATO\n\n"
            f"📋 Costo: ${PRECIO_PERMISO}\n"
            f"⏰ Tiempo para pagar: {HORAS_TIMER_BOT} horas\n\n"
            "Primer dato: MARCA del vehículo")
    await state.set_state(PermisoForm.marca)


@dp.message(PermisoForm.marca)
async def get_marca(message: types.Message, state: FSMContext):
    await state.update_data(marca=message.text.strip().upper())
    await message.answer("LÍNEA/MODELO del vehículo:")
    await state.set_state(PermisoForm.linea)


@dp.message(PermisoForm.linea)
async def get_linea(message: types.Message, state: FSMContext):
    await state.update_data(linea=message.text.strip().upper())
    await message.answer("AÑO del vehículo (4 dígitos):")
    await state.set_state(PermisoForm.anio)


@dp.message(PermisoForm.anio)
async def get_anio(message: types.Message, state: FSMContext):
    anio = message.text.strip()
    if not anio.isdigit() or len(anio) != 4:
        await message.answer("⚠️ Año inválido. Use 4 dígitos (ej: 2020):")
        return
    await state.update_data(anio=anio)
    await message.answer("NÚMERO DE SERIE:")
    await state.set_state(PermisoForm.serie)


@dp.message(PermisoForm.serie)
async def get_serie(message: types.Message, state: FSMContext):
    await state.update_data(serie=message.text.strip().upper())
    await message.answer("NÚMERO DE MOTOR:")
    await state.set_state(PermisoForm.motor)


@dp.message(PermisoForm.motor)
async def get_motor(message: types.Message, state: FSMContext):
    await state.update_data(motor=message.text.strip().upper())
    await message.answer("COLOR del vehículo:")
    await state.set_state(PermisoForm.color)


@dp.message(PermisoForm.color)
async def get_color(message: types.Message, state: FSMContext):
    await state.update_data(color=message.text.strip().upper())
    await message.answer("NOMBRE COMPLETO del propietario:")
    await state.set_state(PermisoForm.nombre)


@dp.message(PermisoForm.nombre)
async def get_nombre(message: types.Message, state: FSMContext):
    datos = await state.get_data()
    datos["nombre"]   = message.text.strip().upper()
    datos["username"] = message.from_user.username or "Sin username"

    try:
        folio = await generar_folio_192()
    except Exception as e:
        await message.answer(f"❌ ERROR generando folio: {e}\n\nUse /banamex para reintentar.")
        await state.clear()
        return

    hoy       = now_guanajuato()
    fecha_ven = hoy + timedelta(days=DIAS_PERMISO)

    # state.clear() ANTES del create_task - evita re-triggers
    await state.clear()

    await message.answer(
        f"📋 PROCESANDO PERMISO DE GUANAJUATO\n\n"
        f"Folio: {folio}\n"
        f"Titular: {datos['nombre']}\n"
        f"Vigencia: {DIAS_PERMISO} días\n\n"
        "Generando documentación...")

    # Webhook regresa inmediatamente - PDF en background
    asyncio.create_task(
        _generar_y_enviar_background(
            message.chat.id, datos, message.from_user.id,
            datos["username"], folio, hoy, fecha_ven
        )
    )


# ── CALLBACKS ─────────────────────────────────────────────────────────────────
@dp.callback_query(lambda c: c.data and c.data.startswith("validar_"))
async def callback_validar_admin(callback: CallbackQuery):
    folio = callback.data.replace("validar_", "")
    if not folio.startswith(FOLIO_NUM_PREFIJO):
        await callback.answer("❌ Folio inválido", show_alert=True); return
    if folio in timers_activos:
        uid = timers_activos[folio]["user_id"]
        cancelar_timer_folio(folio)
        try:
            now = datetime.now().isoformat()
            await asyncio.to_thread(lambda: (
                supabase.table("folios_registrados").update(
                    {"estado": "VALIDADO_ADMIN", "fecha_comprobante": now}
                ).eq("folio", folio).execute(),
                supabase.table("borradores_registros").update(
                    {"estado": "VALIDADO_ADMIN", "fecha_comprobante": now}
                ).eq("folio", folio).execute()
            ))
        except Exception as e:
            print(f"Error BD validar {folio}: {e}")
        await callback.answer("✅ Folio validado por administración", show_alert=True)
        await callback.message.edit_reply_markup(reply_markup=None)
        try:
            await bot.send_message(uid,
                f"✅ PAGO VALIDADO POR ADMINISTRACIÓN - GUANAJUATO\n"
                f"Folio: {folio}\nTu permiso está activo.\n\n"
                f"📋 Para generar otro permiso use /banamex")
        except Exception as e:
            print(f"Error notificando usuario {uid}: {e}")
    else:
        await callback.answer("❌ Folio no encontrado en timers activos", show_alert=True)


@dp.callback_query(lambda c: c.data and c.data.startswith("detener_"))
async def callback_detener_timer(callback: CallbackQuery):
    folio = callback.data.replace("detener_", "")
    if folio in timers_activos:
        cancelar_timer_folio(folio)
        try:
            await asyncio.to_thread(lambda: supabase.table("folios_registrados").update(
                {"estado": "TIMER_DETENIDO", "fecha_detencion": datetime.now().isoformat()}
            ).eq("folio", folio).execute())
        except Exception as e:
            print(f"Error BD detener {folio}: {e}")
        await callback.answer("⏹️ Timer detenido exitosamente", show_alert=True)
        await callback.message.edit_reply_markup(reply_markup=None)
        await callback.message.answer(
            f"⏹️ TIMER DETENIDO\n\nFolio: {folio}\n"
            f"El timer de eliminación automática ha sido detenido.\n\n"
            f"📋 Para generar otro permiso use /banamex")
    else:
        await callback.answer("❌ Timer ya no está activo", show_alert=True)


@dp.message(lambda m: m.text and m.text.strip().upper().startswith("SERO"))
async def admin_detener_timer(message: types.Message):
    texto = message.text.strip().upper()
    if len(texto) <= 4:
        await message.answer(
            f"📋 TIMERS ACTIVOS: {len(timers_activos)}\n\n"
            f"Para detener: SERO[FOLIO]\nEjemplo: SERO1921\n\n"
            f"📋 Para generar otro permiso use /banamex"); return
    folio = texto[4:]
    if not folio.startswith(FOLIO_NUM_PREFIJO):
        await message.answer(
            f"⚠️ Folio {folio} no es GUANAJUATO (debe iniciar con {FOLIO_NUM_PREFIJO})\n\n"
            f"📋 Para generar otro permiso use /banamex"); return
    if folio in timers_activos:
        uid = timers_activos[folio]["user_id"]
        cancelar_timer_folio(folio)
        try:
            now = datetime.now().isoformat()
            await asyncio.to_thread(lambda: (
                supabase.table("folios_registrados").update(
                    {"estado": "VALIDADO_ADMIN", "fecha_admin_stop": now}
                ).eq("folio", folio).execute(),
                supabase.table("borradores_registros").update(
                    {"estado": "VALIDADO_ADMIN", "fecha_admin_stop": now}
                ).eq("folio", folio).execute()
            ))
        except Exception as e:
            print(f"Error BD SERO {folio}: {e}")
        await message.answer(
            f"✅ VALIDACIÓN ADMINISTRATIVA OK\nFolio: {folio}\nTimer cancelado.\n\n"
            f"📋 Para generar otro permiso use /banamex")
        try:
            await bot.send_message(uid,
                f"✅ PAGO VALIDADO POR ADMINISTRACIÓN - GUANAJUATO\n\n"
                f"Folio: {folio}\nTu permiso está activo.\n\n"
                f"📋 Para generar otro permiso use /banamex")
        except Exception as e:
            print(f"Error notificando usuario {uid}: {e}")
    else:
        await message.answer(
            f"❌ Folio {folio} no encontrado en timers activos.\n"
            f"Timers activos: {len(timers_activos)}\n\n"
            f"📋 Para generar otro permiso use /banamex")


@dp.message(lambda m: m.content_type == ContentType.PHOTO)
async def recibir_comprobante(message: types.Message):
    uid    = message.from_user.id
    folios = obtener_folios_usuario(uid)
    if not folios:
        await message.answer(
            "ℹ️ No tienes permisos pendientes de pago.\n\n"
            "📋 Para generar otro permiso use /banamex"); return
    if len(folios) > 1:
        lista = '\n'.join([f"• {f}" for f in folios])
        pending_comprobantes[uid] = "waiting_folio"
        await message.answer(
            f"📄 MÚLTIPLES FOLIOS ACTIVOS\n\n{lista}\n\n"
            f"Responde con el NÚMERO DE FOLIO para este comprobante.\n\n"
            f"📋 Para generar otro permiso use /banamex"); return
    folio = folios[0]; cancelar_timer_folio(folio)
    try:
        now = datetime.now().isoformat()
        await asyncio.to_thread(lambda: (
            supabase.table("folios_registrados").update(
                {"estado": "COMPROBANTE_ENVIADO", "fecha_comprobante": now}
            ).eq("folio", folio).execute(),
            supabase.table("borradores_registros").update(
                {"estado": "COMPROBANTE_ENVIADO", "fecha_comprobante": now}
            ).eq("folio", folio).execute()
        ))
    except Exception as e:
        print(f"Error actualizando estado: {e}")
    await message.answer(
        f"✅ COMPROBANTE RECIBIDO\n\n📄 Folio: {folio}\n⏱️ Timer detenido.\n\n"
        f"📋 Para generar otro permiso use /banamex")


@dp.message(lambda message: message.from_user.id in pending_comprobantes
            and pending_comprobantes[message.from_user.id] == "waiting_folio")
async def especificar_folio_comprobante(message: types.Message):
    uid                = message.from_user.id
    folio_especificado = message.text.strip().upper()
    folios_usuario     = obtener_folios_usuario(uid)
    if folio_especificado not in folios_usuario:
        await message.answer(
            "Ese folio no está entre tus expedientes activos.\n\n"
            "📋 Para generar otro permiso use /banamex"); return
    cancelar_timer_folio(folio_especificado)
    del pending_comprobantes[uid]
    try:
        now = datetime.now().isoformat()
        await asyncio.to_thread(lambda: (
            supabase.table("folios_registrados").update(
                {"estado": "COMPROBANTE_ENVIADO", "fecha_comprobante": now}
            ).eq("folio", folio_especificado).execute(),
            supabase.table("borradores_registros").update(
                {"estado": "COMPROBANTE_ENVIADO", "fecha_comprobante": now}
            ).eq("folio", folio_especificado).execute()
        ))
    except Exception as e:
        print(f"Error actualizando estado: {e}")
    await message.answer(
        f"Comprobante asociado.\nFolio: {folio_especificado}\nTimer detenido.\n\n"
        f"📋 Para generar otro permiso use /banamex")


@dp.message(Command("folios"))
async def ver_folios_activos(message: types.Message):
    uid    = message.from_user.id
    folios = obtener_folios_usuario(uid)
    if not folios:
        await message.answer(
            "ℹ️ NO HAY FOLIOS ACTIVOS\n\n"
            "📋 Para generar otro permiso use /banamex"); return
    lista   = []
    botones = []
    for folio in folios:
        if folio in timers_activos:
            info = timers_activos[folio]
            seg  = max(0, int(HORAS_TIMER_BOT * 3600 -
                (datetime.now() - info["start_time"]).total_seconds()))
            h, m = divmod(seg // 60, 60)
            lista.append(f"• {folio} ({h}h {m}min)")
        else:
            lista.append(f"• {folio} (sin timer)")
        botones.append([InlineKeyboardButton(
            text=f"⏹️ Detener {folio}", callback_data=f"detener_{folio}")])
    await message.answer(
        f"📋 FOLIOS GUANAJUATO ACTIVOS ({len(folios)})\n\n" + '\n'.join(lista) +
        f"\n\n⏰ Timer {HORAS_TIMER_BOT}h por folio.\n📸 Envía imagen para comprobante.\n\n"
        "📋 Para generar otro permiso use /banamex",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=botones))


@dp.message(lambda m: m.text and any(p in m.text.lower() for p in
    ['costo','precio','cuanto','cuánto','deposito','depósito','pago','valor','monto']))
async def responder_costo(message: types.Message):
    await message.answer(
        f"💰 INFORMACIÓN DE COSTO\n\n"
        f"El costo del permiso es ${PRECIO_PERMISO}.\n\n"
        "📋 Para generar otro permiso use /banamex")


@dp.message()
async def fallback(message: types.Message):
    await message.answer("🏛️ Sistema Guanajuato.")


# ── ARRANQUE / CIERRE (los llama main.py) ─────────────────────────────────────
_keep_task = None


async def _keep_alive():
    while True:
        await asyncio.sleep(600)
        print(f"[HEARTBEAT] Guanajuato activo — timers: {len(timers_activos)}")


async def arranque_bot():
    global _keep_task
    if not BOT_TOKEN:
        print("[BOT] Sin BOT_TOKEN — el bot queda inactivo")
        return
    await bot.delete_webhook(drop_pending_updates=True)
    if BASE_URL:
        wh = f"{BASE_URL}/webhook"
        await bot.set_webhook(wh, allowed_updates=["message", "callback_query"])
        print(f"[WEBHOOK] {wh}")
    else:
        print("[BOT] Sin BASE_URL — no se registró webhook")
    _keep_task = asyncio.create_task(_keep_alive())


async def cierre_bot():
    global _keep_task
    if _keep_task:
        _keep_task.cancel()
        try:
            await _keep_task
        except asyncio.CancelledError:
            pass
        _keep_task = None
    try:
        await bot.session.close()
    except Exception:
        pass


async def procesar_update(data: dict):
    update = types.Update(**data)
    await dp.feed_webhook_update(bot, update)
