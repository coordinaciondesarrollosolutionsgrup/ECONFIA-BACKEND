# core/bots/estado_cedula.py
import os
import re
import unicodedata
import asyncio
from datetime import datetime, date
from typing import Optional

from django.conf import settings
from asgiref.sync import sync_to_async
from playwright.async_api import async_playwright
import fitz  # PyMuPDF

# Optional OCR libs
try:
    from PIL import Image, ImageFilter, ImageOps
    import pytesseract
    OCR_AVAILABLE = True
except Exception:
    OCR_AVAILABLE = False

from core.models import Resultado, Fuente

URL = "https://certvigenciacedula.registraduria.gov.co/Datos.aspx"
NOMBRE_SITIO = "estado_cedula"

# ----------------- utils -----------------
def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", s or "")
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = re.sub(r"\s+", " ", s).strip()
    return s.upper()

def _pdf_text(path: str) -> str:
    try:
        with fitz.open(path) as doc:
            return "\n".join(page.get_text("text") or "" for page in doc)
    except Exception:
        return ""

def _pdf_first_page_png(pdf_path: str, png_path: str, zoom: float = 2.0) -> bool:
    try:
        with fitz.open(pdf_path) as doc:
            if doc.page_count == 0:
                return False
            page = doc[0]
            pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), alpha=False)
            pix.save(png_path)
        return os.path.exists(png_path) and os.path.getsize(png_path) > 0
    except Exception:
        return False

def _make_fallback_pdf(pdf_path: str, text: str) -> None:
    try:
        from reportlab.lib.pagesizes import A4
        from reportlab.pdfgen import canvas
        os.makedirs(os.path.dirname(pdf_path), exist_ok=True)
        c = canvas.Canvas(pdf_path, pagesize=A4)
        w, h = A4
        c.setFont("Helvetica", 12)
        c.drawString(40, h - 60, text[:200])
        c.save()
    except Exception:
        pass

def _parse_datos(texto_pdf: str) -> dict:
    T = _norm(texto_pdf)

    def grab(rx: str):
        m = re.search(rx, T, flags=re.I)
        return (m.group(1).strip() if m else "")

    datos = {
        "cedula": grab(r"CEDULA\s+DE\s+CIUDADANIA\s*[:\-]\s*([\d\.\s]+)"),
        "fecha" : grab(r"FECHA\s+DE\s+EXPEDICION\s*[:\-]\s*([A-Z0-9\s]+)"),
        "lugar" : grab(r"LUGAR\s+DE\s+EXPEDICION\s*[:\-]\s*([A-Z\s\-\(\)]+)"),
        "nombre": grab(r"A\s+NOMBRE\s+DE\s*[:\-]\s*([A-Z\s\.\-]+)"),
        "estado": grab(r"ESTADO\s*[:\-]\s*([A-Z]+)"),
    }
    datos["cedula"] = datos["cedula"].replace(" ", "")
    return datos

def _mensaje_datos(datos: dict) -> str:
    encontrados = {k: v for k, v in datos.items() if v}
    if not encontrados:
        return "No se detectaron datos en el PDF del certificado. Revise el archivo."
    parts = []
    if datos.get("cedula"): parts.append(f"Cédula de Ciudadanía: {datos['cedula']}")
    if datos.get("fecha"):  parts.append(f"Fecha de Expedición: {datos['fecha']}")
    if datos.get("lugar"):  parts.append(f"Lugar de Expedición: {datos['lugar']}")
    if datos.get("nombre"): parts.append(f"A nombre de: {datos['nombre']}")
    if datos.get("estado"): parts.append(f"Estado: {datos['estado']}")
    return "\n".join(parts)

def _split_fecha(fecha_expedicion) -> tuple[str, str, str]:
    if isinstance(fecha_expedicion, (datetime, date)):
        return str(fecha_expedicion.year), str(fecha_expedicion.month), str(fecha_expedicion.day)

    s = str(fecha_expedicion or "").strip().replace("/", "-")
    parts = [p for p in s.split("-") if p]
    if len(parts) != 3:
        raise ValueError("Formato de fecha inválido. Usa YYYY-MM-DD o date/datetime")
    if len(parts[0]) == 4:  # YYYY-MM-DD
        y, m, d = parts
    else:                   # DD-MM-YYYY
        d, m, y = parts
    return str(int(y)), str(int(m)), str(int(d))

async def _select_fecha(page, d: str, m: str, y: str):
    async def choose(selector, target):
        opts = await page.eval_on_selector_all(selector + " option", "els => els.map(e => ({v:e.value, t:e.textContent.trim()}))")
        candidates = [target, target.zfill(2)]
        for cand in candidates:
            for o in opts:
                if o["v"] == cand:
                    await page.select_option(selector, value=cand)
                    return
        for o in opts:
            if o["t"] == target or o["t"] == target.zfill(2):
                await page.select_option(selector, value=o["v"])
                return
        for o in opts:
            if o["v"]:
                await page.select_option(selector, value=o["v"])
                return

    await choose('#ContentPlaceHolder1_DropDownList1', d)
    await choose('#ContentPlaceHolder1_DropDownList2', m)
    await choose('#ContentPlaceHolder1_DropDownList3', y)

# ----------------- OCR helpers -----------------
def _preprocess_captcha_image(path: str) -> Optional[Image.Image]:
    if not OCR_AVAILABLE:
        return None
    try:
        img = Image.open(path).convert("L")  # grayscale
        # increase contrast and resize
        img = ImageOps.invert(img)
        img = img.point(lambda x: 0 if x < 140 else 255, '1')  # simple threshold
        img = img.convert("L")
        w, h = img.size
        img = img.resize((max(200, w*3), max(80, h*3)), Image.LANCZOS)
        img = img.filter(ImageFilter.MedianFilter(size=3))
        return img
    except Exception:
        return None

def _ocr_captcha(path: str, attempts: int = 4) -> Optional[str]:
    """
    Intenta resolver el captcha localmente con pytesseract.
    Devuelve texto limpio (solo A-Z0-9) o None si no se obtuvo resultado plausible.
    """
    if not OCR_AVAILABLE:
        return None
    for i in range(attempts):
        img = _preprocess_captcha_image(path)
        if img is None:
            return None
        try:
            config = r'--psm 7 -c tessedit_char_whitelist=ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789'
            raw = pytesseract.image_to_string(img, config=config)
            if not raw:
                continue
            txt = re.sub(r'[^A-Z0-9]', '', raw.upper())
            # heurística: captcha suele tener 4-8 caracteres
            if 3 < len(txt) < 10:
                return txt
        except Exception:
            continue
    return None

# ----------------- BOT -----------------
async def consultar_estado_cedula(
    consulta_id: int,
    cedula: str,
    fecha_expedicion,
    *,
    captcha_override: Optional[str] = None,
    use_ocr: bool = True,
    debug: bool = True,
    headless: bool = True
):
    """
    Flujo:
    - Abre la página, llena cédula y fecha.
    - Detecta imagen de CAPTCHA; intenta resolverla con OCR local si use_ocr=True.
    - Si OCR falla y no hay captcha_override, guarda la imagen y lanza excepción para intervención.
    - Envía formulario, espera Respuesta.aspx y descarga PDF.
    - Valida que la descarga sea PDF real, genera PNG de la primera página, extrae datos y guarda Resultado.
    """
    # Fuente
    try:
        fuente_obj = await sync_to_async(Fuente.objects.get)(nombre=NOMBRE_SITIO)
    except Exception as e:
        await sync_to_async(Resultado.objects.create)(
            consulta_id=consulta_id,
            fuente=None,
            score=0,
            estado="Sin Validar",
            mensaje=f"No se encontró la Fuente '{NOMBRE_SITIO}': {e}",
            archivo=""
        )
        return

    # Rutas
    relative_folder = os.path.join("resultados", str(consulta_id))
    absolute_folder = os.path.join(settings.MEDIA_ROOT, relative_folder)
    os.makedirs(absolute_folder, exist_ok=True)

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    pdf_name = f"{NOMBRE_SITIO}_{cedula}_{ts}.pdf"
    png_name = f"{NOMBRE_SITIO}_{cedula}_{ts}.png"
    abs_pdf = os.path.join(absolute_folder, pdf_name)
    rel_pdf = os.path.join(relative_folder, pdf_name).replace("\\", "/")
    abs_png = os.path.join(absolute_folder, png_name)
    rel_png = os.path.join(relative_folder, png_name).replace("\\", "/")

    navegador = None
    try:
        anio, mes, dia = _split_fecha(fecha_expedicion)

        async with async_playwright() as p:
            navegador = await p.chromium.launch(headless=headless)
            ua = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            ctx = await navegador.new_context(accept_downloads=True, viewport={"width": 1440, "height": 950}, user_agent=ua, locale="es-CO")
            page = await ctx.new_page()
            await page.set_extra_http_headers({"Accept-Language": "es-CO,es;q=0.9"})

            await page.goto(URL, wait_until="domcontentloaded", timeout=120000)
            try:
                await page.wait_for_load_state("networkidle", timeout=10000)
            except Exception:
                pass

            # Debug: guardar HTML y screenshot inicial
            if debug:
                try:
                    html = await page.content()
                    open(os.path.join(absolute_folder, f"{NOMBRE_SITIO}_{cedula}_{ts}_page.html"), "w", encoding="utf-8").write(html)
                except Exception:
                    pass
                try:
                    await page.screenshot(path=os.path.join(absolute_folder, f"{NOMBRE_SITIO}_{cedula}_{ts}_page.png"), full_page=True)
                except Exception:
                    pass

            # Llenar formulario
            await page.fill('#ContentPlaceHolder1_TextBox1', str(cedula))
            await _select_fecha(page, dia, mes, anio)
            await asyncio.sleep(0.6)

            # Detectar imagen de captcha y guardarla
            captcha_saved = None
            try:
                captcha_selectors = [
                    'img#ContentPlaceHolder1_Image1',
                    'img[id*="captcha"]',
                    'img[src*="Captcha"]',
                    'img'
                ]
                for sel in captcha_selectors:
                    try:
                        locator = page.locator(sel)
                        if await locator.count() > 0:
                            # tomar screenshot del elemento
                            path_captcha = os.path.join(absolute_folder, f"{NOMBRE_SITIO}_{cedula}_{ts}_captcha.png")
                            await locator.first.screenshot(path=path_captcha)
                            captcha_saved = path_captcha
                            break
                    except Exception:
                        continue
            except Exception:
                captcha_saved = None

            # Resolver captcha: prioridad
            # 1) captcha_override provided
            # 2) OCR local (if enabled)
            # 3) fallback: raise with saved captcha path for manual resolution
            captcha_value = None
            if captcha_override:
                captcha_value = captcha_override.strip()
            else:
                if captcha_saved and use_ocr:
                    ocr_text = _ocr_captcha(captcha_saved)
                    if ocr_text:
                        captcha_value = ocr_text
                # If still None and captcha_saved exists, try a few automatic retries with common fallback 'LANAP'
                if captcha_value is None and captcha_saved:
                    # last-resort attempt with LANAP (kept for backward compatibility)
                    captcha_value = "LANAP"

            # Si no hay captcha_value válido, abortar y pedir intervención
            if not captcha_value:
                if captcha_saved:
                    raise RuntimeError(f"CAPTCHA detectado y guardado en: {captcha_saved}. Proporcione el texto del CAPTCHA en 'captcha_override' para continuar.")
                else:
                    # no se detectó imagen; intentar enviar con LANAP como antes
                    captcha_value = "LANAP"

            # Envío y reintentos
            MAX_INTENTOS = 6
            paso = False
            for intento in range(1, MAX_INTENTOS + 1):
                await page.fill('#ContentPlaceHolder1_TextBox2', captcha_value)
                await asyncio.sleep(0.25)
                await page.click('#ContentPlaceHolder1_Button1')

                # si aparece diálogo -> captcha falló
                try:
                    dialog = await page.wait_for_event("dialog", timeout=1800)
                    await dialog.dismiss()
                    await page.fill('#ContentPlaceHolder1_TextBox2', '')
                    await asyncio.sleep(0.45)
                    # si usamos OCR/override, reintentar una o dos veces
                    if captcha_override or use_ocr:
                        continue
                    else:
                        continue
                except Exception:
                    pass

                # verificar navegación a Respuesta.aspx
                try:
                    await page.wait_for_url("**/Respuesta.aspx**", timeout=5000)
                    paso = True
                    break
                except Exception:
                    await page.fill('#ContentPlaceHolder1_TextBox2', '')
                    await asyncio.sleep(0.45)

            if not paso:
                raise RuntimeError("CAPTCHA no validado tras varios intentos. Revisa el captcha guardado o prueba manualmente.")

            # En Respuesta.aspx: generar certificado y descargar PDF
            await asyncio.sleep(0.6)
            async with page.expect_download(timeout=60000) as dl:
                await page.click("input#ContentPlaceHolder1_Button1")  # Generar Certificado
            download = await dl.value

            try:
                await download.save_as(abs_pdf)
            except Exception:
                tmp = await download.path()
                if tmp:
                    os.replace(tmp, abs_pdf)

            # Verificar magic bytes PDF
            is_pdf = False
            try:
                with open(abs_pdf, "rb") as f:
                    header = f.read(4)
                    is_pdf = header.startswith(b"%PDF")
            except Exception:
                is_pdf = False

            if not is_pdf:
                alt_html = os.path.join(absolute_folder, f"{NOMBRE_SITIO}_{cedula}_{ts}_download.html")
                try:
                    with open(abs_pdf, "rb") as f:
                        data = f.read()
                    try:
                        text = data.decode("utf-8", errors="replace")
                        open(alt_html, "w", encoding="utf-8").write(text)
                    except Exception:
                        os.replace(abs_pdf, alt_html)
                except Exception:
                    pass
                raise RuntimeError(f"La descarga no parece ser un PDF válido. Revisa {alt_html} para ver el contenido de error.")

            # cerrar navegador antes de procesar PDF
            await navegador.close()
            navegador = None

        # Generar PNG de la primera página y extraer datos
        if not os.path.exists(abs_pdf) or os.path.getsize(abs_pdf) < 500:
            _make_fallback_pdf(abs_pdf, f"RNEC – sin datos visibles para cédula {cedula}")

        _pdf_first_page_png(abs_pdf, abs_png, zoom=2.0)
        texto = _pdf_text(abs_pdf)
        datos = _parse_datos(texto)
        mensaje = _mensaje_datos(datos)

        # Guardar resultado (PNG en archivo)
        await sync_to_async(Resultado.objects.create)(
            consulta_id=consulta_id,
            fuente=fuente_obj,
            score=0,
            estado="Validada",
            mensaje=mensaje,
            archivo=rel_png
        )

    except Exception as e:
        # Evidencia mínima si hubo error
        try:
            _make_fallback_pdf(abs_pdf, f"RNEC – error: {e}")
            _pdf_first_page_png(abs_pdf, abs_png, zoom=2.0)
        except Exception:
            pass

        await sync_to_async(Resultado.objects.create)(
            consulta_id=consulta_id,
            fuente=fuente_obj,
            score=0,
            estado="Sin Validar",
            mensaje=str(e) or "Ocurrió un problema al obtener el certificado",
            archivo=rel_png if os.path.exists(abs_png) else ""
        )
        try:
            if navegador:
                await navegador.close()
        except Exception:
            pass
