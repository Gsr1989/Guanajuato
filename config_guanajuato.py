"""
GUANAJUATO — Configuración compartida entre el panel web (Flask) y el bot (aiogram).

Recuperado de un .docx donde Word corrompió el código al pegarlo (autocorrección
de mayúsculas, comillas curvas, un símbolo Wingdings en vez de ": (", "!" vuelto
"¡", y URLs que perdieron sus comillas al convertirse en hipervínculos). Todo
quedó corregido aquí; el comportamiento original se conservó.

También se corrigió un bug real que ya traía el código: el bot guardaba
entidad="Guanajuato" (mayúscula) y el panel entidad="guanajuato" (minúscula),
y el panel ni siquiera filtraba por entidad — mostraba folios de todos los
estados revueltos. Ahora todo usa "guanajuato" en minúscula, igual que el
resto de la plataforma.
"""

import os
import sys
import logging
import threading
from datetime import datetime, date
from zoneinfo import ZoneInfo
from supabase import create_client, Client

# ===================== LOGGING =====================
sys.dont_write_bytecode = True
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger("guanajuato")

# ===================== ZONA HORARIA =====================
TZ_GUANAJUATO = ZoneInfo("America/Mexico_City")
TZ_MEXICO     = TZ_GUANAJUATO      # alias


def now_guanajuato() -> datetime:
    return datetime.now(TZ_GUANAJUATO)


def today_guanajuato() -> date:
    return now_guanajuato().date()


def parse_date_any(value) -> date:
    import re
    if not value:
        raise ValueError("Fecha vacía")
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=TZ_GUANAJUATO)
        else:
            value = value.astimezone(TZ_GUANAJUATO)
        return value.date()
    s = str(value).strip()
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", s):
        return date.fromisoformat(s)
    dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=TZ_GUANAJUATO)
    else:
        dt = dt.astimezone(TZ_GUANAJUATO)
    return dt.date()


# ===================== SUPABASE =====================
SUPABASE_URL = os.getenv(
    "SUPABASE_URL",
    "https://xsagwqepoljfsogusubw.supabase.co"
)
SUPABASE_KEY = os.getenv(
    "SUPABASE_KEY",
    "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InhzYWd3cWVwb2xqZnNvZ3VzdWJ3Iiwicm9sZSI6ImFub24iLCJpYXQiOjE3NDM5NjM3NTUsImV4cCI6MjA1OTUzOTc1NX0.NUixULn0m2o49At8j6X58UqbXre2O2_JStqzls_8Gws"
)

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# ===================== CONFIG GENERAL =====================
BOT_TOKEN            = os.getenv("BOT_TOKEN", "")
BASE_URL             = os.getenv(
    "BASE_URL",
    "https://direcciongeneraltransporteguanajuato-gob.onrender.com"
).rstrip("/")
URL_VERIFICACION_BASE = BASE_URL     # el QR apunta al mismo servicio fusionado

OUTPUT_DIR            = "documentos"
PLANTILLA_PRIMERA     = "guanajuato_imagen_fullhd.pdf"
PLANTILLA_SEGUNDA     = "guanajuato.pdf"

ENTIDAD               = "guanajuato"     # antes: bot "Guanajuato" / panel "guanajuato" (bug)
DIAS_PERMISO          = 30
HORAS_TIMER_BOT       = 36
PRECIO_PERMISO        = 150
PAGE_SIZE             = 100
BUCKET_NAME           = "permisos-guanajuato"

ADMIN_USER            = os.getenv("ADMIN_USER", "Serg890105tm3")
ADMIN_PASS            = os.getenv("ADMIN_PASS", "Serg890105tm3")
SECRET_KEY            = os.getenv("SECRET_KEY", "clave_muy_segura_123456")

# ⚠️ PANEL Y BOT COMPARTEN LA SERIE "192".
# El panel original dejaba el folio 100% manual (lo tecleaba el operador) sin
# generador ni watermark; el bot sí tenía watermark GTO. Ahora ambos usan el
# MISMO generador — el panel puede seguir tecleando folio manual si quiere,
# pero si lo deja vacío se autogenera con el mismo contador que usa el bot.
FOLIO_NUM_PREFIJO    = "192"
FOLIO_WATERMARK_KEY  = "GTO"

os.makedirs(OUTPUT_DIR, exist_ok=True)

# ===================== CANDADOS GLOBALES =====================
# ⚠️ PDF_LOCK — el panel original tenía su propio generar_pdf() simplón (solo
# ponía serie + fecha en una página) SIN candado; el bot tenía uno más completo
# también sin candado. Al fusionar en un solo proceso, sin este candado
# compartido dos generaciones simultáneas corrompen los PDFs entre sí. Además
# se unificó: ahora AMBOS usan el generador completo (2 páginas + 2 QR) que
# antes solo tenía el bot — el panel generaba un PDF muy pobre en comparación.
PDF_LOCK   = threading.Lock()

# Serializa la asignación de folios entre panel y bot
FOLIO_LOCK = threading.Lock()

# ===================== COORDENADAS PDF =====================
# Recuperadas del documento; se corrigió la línea "vigencia" que Word había
# corrompido con un símbolo Wingdings en vez de ": (".
COORDS_PRIMERA = {
    "folio":    (1800, 455, 60, (1, 0, 0)),
    "fecha":    (2200, 580, 35, (0, 0, 0)),
    "marca":    ( 385, 715, 35, (0, 0, 0)),
    "serie":    ( 350, 800, 35, (0, 0, 0)),
    "linea":    ( 800, 715, 35, (0, 0, 0)),
    "motor":    (1290, 800, 35, (0, 0, 0)),
    "anio":     (1500, 715, 35, (0, 0, 0)),
    "color":    (1960, 715, 35, (0, 0, 0)),
    "nombre":   ( 950, 1100, 50, (0, 0, 0)),
    "vigencia": (2200, 645, 35, (0, 0, 0)),
}

COORDS_SEGUNDA = {
    "numero_serie": (255.0, 180.0, 10, (0, 0, 0)),
    "fecha":        (255.0, 396.0, 10, (0, 0, 0)),
}

COORDS_QR_DINAMICO = {"x": 205, "y": 328, "ancho": 290, "alto": 290}

# ===================== TABLAS EDITABLES DESDE EL PANEL =====================
TABLAS_DISPONIBLES = {
    'folios_registrados': {
        'nombre':   'Folios Registrados',
        'pk_col':   'folio',
        'columnas': ['folio', 'marca', 'linea', 'anio', 'numero_serie', 'numero_motor',
                     'color', 'nombre', 'numero_telefono', 'fecha_expedicion',
                     'fecha_vencimiento', 'entidad', 'estado', 'creado_por'],
    },
    'verificaciondigitalcdmx': {
        'nombre':   'Usuarios del Sistema',
        'pk_col':   'id',
        'columnas': ['id', 'username', 'password', 'folios_asignac', 'folios_usados'],
    },
    'folio_watermark': {
        'nombre':   'Watermark de Folios',
        'pk_col':   'prefijo',
        'columnas': ['prefijo', 'ultimo_asignado'],
    },
    'borradores_registros': {
        'nombre':   'Borradores (del bot)',
        'pk_col':   'folio',
        'columnas': ['folio', 'entidad', 'numero_serie', 'marca', 'linea', 'numero_motor',
                     'anio', 'color', 'fecha_expedicion', 'fecha_vencimiento',
                     'contribuyente', 'estado', 'user_id'],
    },
}

# Columnas que el editor trata como fecha (le pone selector de calendario)
COLUMNAS_FECHA = {
    'fecha_expedicion', 'fecha_vencimiento', 'fecha_comprobante',
    'fecha_detencion', 'fecha_admin_stop', 'created_at',
}


# ===================== GENERADOR DE FOLIO COMPARTIDO =====================
def _leer_watermark() -> int | None:
    try:
        r = supabase.table("folio_watermark") \
            .select("ultimo_asignado").eq("prefijo", FOLIO_WATERMARK_KEY).execute()
        return r.data[0]["ultimo_asignado"] if r.data else None
    except Exception as e:
        logger.error(f"[WATERMARK] leer: {e}")
        return None


def _guardar_watermark(numero: int):
    try:
        supabase.table("folio_watermark").upsert({
            "prefijo":         FOLIO_WATERMARK_KEY,
            "ultimo_asignado": numero
        }).execute()
    except Exception as e:
        logger.error(f"[WATERMARK] guardar: {e}")


def generar_folio_guanajuato() -> str:
    """
    ÚNICO generador de folios 192 — lo usan el panel Y el bot.
    Bloques de 500 con una sola consulta (.in_) + watermark + candado.
    El contador nunca retrocede aunque se borren folios vencidos.
    """
    with FOLIO_LOCK:
        wm = _leer_watermark()
        if wm is not None:
            inicio = wm + 1
        else:
            try:
                r = supabase.table("folios_registrados").select("folio") \
                    .eq("entidad", ENTIDAD).like("folio", f"{FOLIO_NUM_PREFIJO}%").execute()
                nums = []
                for row in r.data or []:
                    f = str(row.get("folio", ""))
                    if f.startswith(FOLIO_NUM_PREFIJO):
                        suf = f[len(FOLIO_NUM_PREFIJO):]
                        if suf.isdigit():
                            nums.append(int(suf))
                inicio = (max(nums) + 1) if nums else 1
            except Exception as e:
                logger.error(f"[FOLIO] init: {e}")
                inicio = 1

        BLOQUE = 500
        for _ in range(0, 10_000_000, BLOQUE):
            candidatos = [f"{FOLIO_NUM_PREFIJO}{inicio + i}" for i in range(BLOQUE)]
            try:
                resp = supabase.table("folios_registrados") \
                    .select("folio").in_("folio", candidatos).execute()
                ocupados = {r["folio"] for r in (resp.data or [])}
            except Exception as e:
                logger.error(f"[FOLIO] bloque: {e}")
                ocupados = set()

            logger.info(f"[FOLIO] bloque {inicio}–{inicio+BLOQUE-1}, ocupados={len(ocupados)}")
            for i, folio in enumerate(candidatos):
                if folio not in ocupados:
                    numero_final = inicio + i
                    _guardar_watermark(numero_final)
                    logger.info(f"[FOLIO] ✅ Asignado: {folio}")
                    return folio
            inicio += BLOQUE

        raise Exception("Sin folio disponible tras 10,000,000 intentos")


def leer_siguiente_folio() -> str:
    """Sólo informativo (para /health) — no reserva nada."""
    wm = _leer_watermark()
    n = (wm + 1) if wm is not None else 1
    return f"{FOLIO_NUM_PREFIJO}{n}"


# ===================== PDF COMPLETO COMPARTIDO =====================
# Antes: el bot tenía este generador completo (2 páginas + QR de texto + QR
# dinámico); el panel tenía uno mucho más pobre (solo escribía serie+fecha en
# UNA página, sin marca/línea/año/color/nombre ni ningún QR). Ahora los dos
# usan ESTE, así que un permiso hecho desde la web queda igual de completo
# que uno hecho por Telegram.
import fitz
import qrcode
from io import BytesIO


def generar_qr_dinamico(folio: str):
    try:
        url = f"{URL_VERIFICACION_BASE}/consulta/{folio}"
        qr  = qrcode.QRCode(version=2, error_correction=qrcode.constants.ERROR_CORRECT_M,
                            box_size=4, border=1)
        qr.add_data(url); qr.make(fit=True)
        img = qr.make_image(fill_color="black", back_color="white").convert("RGB")
        return img, url
    except Exception as e:
        logger.error(f"[QR DINAMICO] {e}")
        return None, None


def generar_qr_texto(datos: dict, folio: str):
    try:
        texto = (f"FOLIO: {folio}\nNOMBRE: {datos.get('nombre','')}\n"
                 f"MARCA: {datos.get('marca','')}\nLINEA: {datos.get('linea','')}\n"
                 f"AÑO: {datos.get('anio','')}\nSERIE: {datos.get('serie','')}\n"
                 f"MOTOR: {datos.get('motor','')}\nCOLOR: {datos.get('color','')}\n"
                 f"GUANAJUATO PERMISOS DIGITALES")
        qr = qrcode.QRCode(version=2, error_correction=qrcode.constants.ERROR_CORRECT_H,
                           box_size=10, border=2)
        qr.add_data(texto.upper()); qr.make(fit=True)
        return qr.make_image(fill_color="black", back_color="white").convert("RGB")
    except Exception as e:
        logger.error(f"[QR TEXTO] {e}")
        return None


def generar_pdf_guanajuato_unificado(folio: str, datos: dict,
                                     fecha_exp: datetime, fecha_ven: datetime) -> str:
    """
    ⚠️ Candado compartido: PyMuPDF no es thread-safe. El panel generaba en el
    hilo de Flask, el bot en el threadpool de asyncio — sin este lock, dos
    permisos simultáneos corrompían los PDFs entre sí.
    """
    with PDF_LOCK:
        os.makedirs(OUTPUT_DIR, exist_ok=True)
        c  = COORDS_PRIMERA
        c2 = COORDS_SEGUNDA

        try:
            doc_final   = fitz.open()
            doc_primera = fitz.open(PLANTILLA_PRIMERA)
            pg1         = doc_primera[0]

            f_exp = fecha_exp.strftime("%d/%m/%Y")
            f_ven = fecha_ven.strftime("%d/%m/%Y")

            pg1.insert_text(c["folio"][:2],    folio, fontsize=c["folio"][2],    color=c["folio"][3])
            pg1.insert_text(c["fecha"][:2],    f_exp, fontsize=c["fecha"][2],    color=c["fecha"][3])
            pg1.insert_text(c["vigencia"][:2], f_ven, fontsize=c["vigencia"][2], color=c["vigencia"][3])

            for key in ["marca", "serie", "linea", "motor", "anio", "color"]:
                if key in datos:
                    x, y, s, col = c[key]
                    pg1.insert_text((x, y), str(datos[key]), fontsize=s, color=col)

            pg1.insert_text(c["nombre"][:2], str(datos.get("nombre", "")),
                            fontsize=c["nombre"][2], color=c["nombre"][3])

            img_qr_texto = generar_qr_texto(datos, folio)
            if img_qr_texto:
                buf = BytesIO(); img_qr_texto.save(buf, format="PNG"); buf.seek(0)
                cm = 85.05; ancho_qr = alto_qr = cm * 3.0
                page_width = pg1.rect.width
                x_qr = page_width - (2.5 * cm) - ancho_qr
                y_qr = 20.5 * cm
                pg1.insert_image(fitz.Rect(x_qr, y_qr, x_qr + ancho_qr, y_qr + alto_qr),
                                 pixmap=fitz.Pixmap(buf.read()), overlay=True)

            img_qr_din, url_v = generar_qr_dinamico(folio)
            if img_qr_din:
                buf2 = BytesIO(); img_qr_din.save(buf2, format="PNG"); buf2.seek(0)
                x, y = COORDS_QR_DINAMICO["x"], COORDS_QR_DINAMICO["y"]
                w, h = COORDS_QR_DINAMICO["ancho"], COORDS_QR_DINAMICO["alto"]
                pg1.insert_image(fitz.Rect(x, y, x + w, y + h),
                                 pixmap=fitz.Pixmap(buf2.read()), overlay=True)

            doc_final.insert_pdf(doc_primera)
            doc_primera.close()

            doc_segunda = fitz.open(PLANTILLA_SEGUNDA)
            pg2 = doc_segunda[0]
            pg2.insert_text(c2["numero_serie"][:2], str(datos.get("serie", "")),
                            fontsize=c2["numero_serie"][2], color=c2["numero_serie"][3])
            pg2.insert_text(c2["fecha"][:2], f_exp,
                            fontsize=c2["fecha"][2], color=c2["fecha"][3])
            doc_final.insert_pdf(doc_segunda)
            doc_segunda.close()

            salida = os.path.join(OUTPUT_DIR, f"{folio}.pdf")
            doc_final.save(salida)
            doc_final.close()
            logger.info(f"[PDF] ✅ {salida}")

        except Exception as e:
            logger.error(f"[ERROR PDF] {e}")
            salida = os.path.join(OUTPUT_DIR, f"{folio}.pdf")
            fb = fitz.open()
            fb.new_page().insert_text((50, 50), f"ERROR - Folio: {folio}", fontsize=12)
            fb.save(salida)
            fb.close()

        return salida


def subir_pdf_a_storage(ruta_local: str, folio: str) -> str:
    try:
        with open(ruta_local, "rb") as f:
            contenido = f.read()
        nombre_archivo = f"{folio}.pdf"
        supabase.storage.from_(BUCKET_NAME).upload(
            path=nombre_archivo,
            file=contenido,
            file_options={"content-type": "application/pdf", "upsert": "true"}
        )
        url = supabase.storage.from_(BUCKET_NAME).get_public_url(nombre_archivo)
        logger.info(f"[STORAGE] Subido: {url}")
        return url
    except Exception as e:
        logger.error(f"[STORAGE] Error {folio}: {e}")
        return ""


def generar_subir_y_guardar_pdf(folio: str, datos: dict,
                                fecha_exp: datetime, fecha_ven: datetime) -> tuple:
    """Genera el PDF completo, lo sube a Storage y guarda pdf_url. Devuelve (ruta_local, url)."""
    ruta = generar_pdf_guanajuato_unificado(folio, datos, fecha_exp, fecha_ven)
    url  = subir_pdf_a_storage(ruta, folio)
    if url:
        try:
            supabase.table("folios_registrados").update({"pdf_url": url}).eq("folio", folio).execute()
        except Exception as e:
            logger.error(f"[DB] No se pudo guardar pdf_url: {e}")
    return ruta, url
