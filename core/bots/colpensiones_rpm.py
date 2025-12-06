import os
import re
import unicodedata
import logging
import random
import asyncio
from datetime import datetime
from pathlib import Path

from django.conf import settings
from asgiref.sync import sync_to_async
from playwright.async_api import async_playwright, TimeoutError

from core.models import Resultado, Fuente

logger = logging.getLogger(__name__)

# ---------------- USER AGENTS REALISTAS ----------------
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
]

# ---------------- URLs ----------------
LANDING_URL = "https://sede.colpensiones.gov.co/login"
RPM_URL = "https://sede.colpensiones.gov.co/loader.php?lServicio=Se&lTipo=Process&lFuncion=start&id=2"

NOMBRE_SITIO = "colpensiones_rpm"

# ---------------- MAPA TIPO DOC REAL ----------------
TIPO_DOC_MAP = {
    "CC": "231",
    "CE": "232",
    "NU": "705",
    "PA": "706",
    "TI": "707",
}

CORREO_NO_VALUE = "1807"

# ---------------- TIMEOUTS ----------------
TIMEOUTS = {
    "navigation": 20000,
    "trámite": 20000,
    "boton_descargar": 35000,
    "download": 40000,
}

MAX_RETRIES = 3

# ---------------- HELPERS ----------------
def _strip(s: str):
    return "".join(c for c in unicodedata.normalize("NFD", s or "") if unicodedata.category(c) != "Mn").upper()


def _get_browser_context_args():
    """Configuración del contexto del navegador para evadir detección"""
    return {
        "viewport": {"width": 1920, "height": 1080},
        "user_agent": random.choice(USER_AGENTS),
        "locale": "es-CO",
        "timezone_id": "America/Bogota",
        "accept_downloads": True,
        "extra_http_headers": {
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
            "Accept-Language": "es-CO,es;q=0.9,en;q=0.8",
            "Accept-Encoding": "gzip, deflate, br",
            "DNT": "1",
            "Connection": "keep-alive",
            "Upgrade-Insecure-Requests": "1",
            "Sec-Fetch-Dest": "document",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Site": "none",
            "Sec-Fetch-User": "?1",
            "sec-ch-ua": '"Not_A Brand";v="8", "Chromium";v="120", "Google Chrome";v="120"',
            "sec-ch-ua-mobile": "?0",
            "sec-ch-ua-platform": '"Windows"',
        },
    }


async def _delay_humano(min_ms=800, max_ms=2000):
    """Simula delays humanos aleatorios"""
    await asyncio.sleep(random.uniform(min_ms, max_ms) / 1000)


async def _mover_mouse_aleatorio(page):
    """Simula movimiento natural del mouse"""
    try:
        x = random.randint(100, 500)
        y = random.randint(100, 400)
        await page.mouse.move(x, y)
        await asyncio.sleep(random.uniform(0.1, 0.3))
    except:
        pass


def _extraer_texto_pdf(path_pdf):
    try:
        import fitz
        with fitz.open(path_pdf) as doc:
            return "\n".join(page.get_text("text") for page in doc)
    except:
        return ""


def _png_from_pdf(path_pdf, path_png):
    try:
        import fitz
        with fitz.open(path_pdf) as doc:
            pix = doc[0].get_pixmap(matrix=fitz.Matrix(2, 2))
            pix.save(path_png)
            return True
    except:
        return False


def _interpretar(texto):
    t = _strip(texto)
    if "NO ESTA REGISTRAD" in t:
        return ("No está registrado(a) en RPM – Colpensiones.", 0.5)
    if "REGIMEN DE PRIMA MEDIA" in t and "COLPENSIONES" in t:
        return ("Está registrado(a) en RPM – Colpensiones.", 1.0)
    return ("El PDF no permite concluir registro en RPM.", 0)


async def _esperar_opciones(page, selector):
    for _ in range(40):
        try:
            count = await page.evaluate(
                """(sel)=>{
                    const el = document.querySelector(sel);
                    if (!el) return 0;
                    return Array.from(el.options).filter(o=>o.value.trim()!='').length;
                }""",
                selector,
            )
            if count > 0:
                return True
        except:
            pass
        await page.wait_for_timeout(200)
    return False


async def _navegar_flujo_inicial(page):
    """Navega al formulario con comportamiento más humano"""
    # Navegar a la página principal primero
    await page.goto(LANDING_URL, wait_until="domcontentloaded")
    await _delay_humano(1500, 3000)
    await _mover_mouse_aleatorio(page)
    
    # Esperar que la página cargue completamente
    await page.wait_for_load_state("networkidle")
    await _delay_humano(800, 1500)

    variantes = [
        "Certificado de afiliación",
        "Certificado de afiliacion",
        "Certificado afiliación",
        "Certificado afiliacion",
        "Certificado",
    ]

    for texto in variantes:
        loc = page.locator(f"a.grid-item:has-text('{texto}')").first
        try:
            await loc.wait_for(state="visible", timeout=4000)
            await _mover_mouse_aleatorio(page)
            await _delay_humano(500, 1000)
            async with page.expect_navigation(timeout=30000):
                await loc.click()
            break
        except:
            continue

    try:
        await page.wait_for_url(lambda url: "id=2" in url, timeout=TIMEOUTS["trámite"])
    except:
        await _delay_humano(1000, 2000)
        await page.goto(RPM_URL, wait_until="domcontentloaded")
    
    await page.wait_for_load_state("networkidle")
    await _delay_humano(1000, 2000)


async def consultar_colpensiones_rpm(consulta_id: int, cedula: str, tipo_doc: str):
    tipo_doc = tipo_doc.upper().strip()
    if tipo_doc not in TIPO_DOC_MAP:
        return "Tipo de documento inválido."

    fuente = await sync_to_async(Fuente.objects.get)(nombre=NOMBRE_SITIO)

    folder = Path(settings.MEDIA_ROOT) / "resultados" / str(consulta_id)
    folder.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    pdf_path = folder / f"colpensiones_{cedula}_{timestamp}.pdf"
    png_path = folder / f"colpensiones_{cedula}_{timestamp}.png"

    async with async_playwright() as pw:
        for intento in range(1, MAX_RETRIES + 1):
            logger.info(f"Intento {intento}/{MAX_RETRIES} para consultar Colpensiones")
            # Configurar navegador con argumentos anti-detección
            browser = await pw.chromium.launch(
                headless=False,
                args=[
                    "--disable-blink-features=AutomationControlled",
                    "--disable-dev-shm-usage",
                    "--no-sandbox",
                    "--disable-setuid-sandbox",
                    "--disable-web-security",
                    "--disable-features=IsolateOrigins,site-per-process",
                    "--disable-infobars",
                    "--window-size=1920,1080",
                    "--start-maximized",
                    "--window-position=2000,0"
                ]
            )
            
            # Crear contexto con configuración realista
            context = await browser.new_context(**_get_browser_context_args())
            
            # Inyectar scripts anti-detección
            await context.add_init_script("""
                Object.defineProperty(navigator, 'webdriver', {
                    get: () => undefined
                });
                
                Object.defineProperty(navigator, 'plugins', {
                    get: () => [1, 2, 3, 4, 5]
                });
                
                Object.defineProperty(navigator, 'languages', {
                    get: () => ['es-CO', 'es', 'en-US', 'en']
                });
                
                window.chrome = {
                    runtime: {}
                };
                
                Object.defineProperty(navigator, 'permissions', {
                    get: () => ({
                        query: () => Promise.resolve({state: 'granted'})
                    })
                });
            """)
            
            page = await context.new_page()

            try:
                # ---------------- INICIO ----------------
                await _navegar_flujo_inicial(page)
                await _delay_humano(1000, 2000)

                # ---------------- SELECTORES REALES ----------------
                sel_tipo = "#fieldFrm356"
                sel_numero = "#fieldFrm978"
                sel_correo = "#fieldFrm2544"

                # ---------------- ESPERAR SELECTS ----------------
                await page.wait_for_selector(sel_tipo, timeout=20000)
                await _esperar_opciones(page, sel_tipo)
                await _delay_humano(500, 1000)

                # ---------------- LLENAR FORMULARIO CON DELAYS HUMANOS ----------------
                await _mover_mouse_aleatorio(page)
                await page.select_option(sel_tipo, value=TIPO_DOC_MAP[tipo_doc])
                await _delay_humano(600, 1200)
                
                # Escribir número de documento caracter por caracter (más humano)
                await page.click(sel_numero)
                await _delay_humano(300, 600)
                for char in cedula:
                    await page.type(sel_numero, char, delay=random.randint(80, 150))
                await _delay_humano(500, 1000)

                await page.select_option(sel_correo, value=CORREO_NO_VALUE)
                await _delay_humano(800, 1500)

                # Scroll más natural
                await _mover_mouse_aleatorio(page)
                await page.evaluate("window.scrollBy(0, 400)")
                await _delay_humano(500, 800)
                await page.evaluate("window.scrollBy(0, 200)")
                await _delay_humano(800, 1500)

                # ---------------- BOTÓN CONSULTAR ----------------
                sel_boton = "input[type='submit'][value='Consultar'], button:has-text('Consultar')"

                await page.wait_for_selector(sel_boton, timeout=20000)
                await _mover_mouse_aleatorio(page)
                await _delay_humano(500, 1000)

                btn = page.locator(sel_boton).first
                await btn.scroll_into_view_if_needed()
                await _delay_humano(400, 800)
                await btn.click()

                await page.wait_for_load_state("networkidle")
                await _delay_humano(2000, 3000)

                # ---------------- BOTÓN DESCARGAR ----------------
                btn_descargar = page.locator("a.btn-primary:has-text('Descargar')")

                await btn_descargar.wait_for(state="visible", timeout=45000)
                await _delay_humano(1000, 2000)
                await _mover_mouse_aleatorio(page)

                async with page.expect_download(timeout=60000) as d:
                    await btn_descargar.click()

                download = await d.value
                await download.save_as(str(pdf_path))
                logger.info(f"PDF descargado exitosamente: {pdf_path}")

                # ---------------- PNG ----------------
                if not _png_from_pdf(str(pdf_path), str(png_path)):
                    await page.screenshot(path=str(png_path), full_page=True)

                # ---------------- INTERPRETAR ----------------
                texto = _extraer_texto_pdf(str(pdf_path))
                mensaje, score = _interpretar(texto)

                await context.close()
                await browser.close()

                # ---------------- GUARDAR EN BD ----------------
                await sync_to_async(Resultado.objects.create)(
                    consulta_id=consulta_id,
                    fuente=fuente,
                    estado="Validada" if score > 0 else "Sin Validar",
                    mensaje=mensaje,
                    score=score,
                    archivo=png_path.as_posix(),
                )

                return mensaje

            except Exception as e:
                logger.error(f"Error en intento {intento}: {str(e)}")
                
                # GUARDAR DEBUG
                debug_html = folder / f"debug_colpensiones_timeout_{intento}.html"
                debug_png = folder / f"debug_colpensiones_timeout_{intento}.png"

                try:
                    debug_html.write_text(await page.content(), encoding="utf-8")
                    await page.screenshot(path=str(debug_png), full_page=True)
                    logger.info(f"Debug guardado: {debug_html}")
                except Exception as debug_error:
                    logger.error(f"Error guardando debug: {debug_error}")

                await context.close()
                await browser.close()

                if intento == MAX_RETRIES:
                    error_msg = f"Error después de {MAX_RETRIES} intentos: {str(e)}"
                    logger.error(error_msg)
                    await sync_to_async(Resultado.objects.create)(
                        consulta_id=consulta_id,
                        fuente=fuente,
                        estado="Sin Validar",
                        mensaje=error_msg,
                        score=0,
                        archivo="",
                    )
                    return error_msg

                # Delay más largo entre reintentos
                delay = random.uniform(3, 6)
                logger.info(f"Esperando {delay:.1f}s antes del siguiente intento...")
                await asyncio.sleep(delay)