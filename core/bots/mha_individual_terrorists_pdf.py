# bots/mha_individual_terrorists_pdf.py
import os
import re
import unicodedata
import random
import asyncio
import logging
from datetime import datetime

from django.conf import settings
from asgiref.sync import sync_to_async
from playwright.async_api import async_playwright
import fitz  # PyMuPDF

from core.models import Resultado, Fuente

logger = logging.getLogger(__name__)

URL = "https://www.mha.gov.in/en/page/individual-terrorists-under-uapa"
NOMBRE_SITIO = "mha_individual_terrorists"
MAX_INTENTOS = 3

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:132.0) Gecko/20100101 Firefox/132.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
]


# --------- utilidades ----------
def _get_browser_context_args():
    """Retorna argumentos realistas para el contexto del navegador."""
    return {
        "viewport": {"width": 1440, "height": 1000},
        "locale": "en-IN",
        "timezone_id": "Asia/Kolkata",
        "user_agent": random.choice(USER_AGENTS),
        "extra_http_headers": {
            "Accept-Language": "en-IN,en-US;q=0.9,en;q=0.8",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
            "Accept-Encoding": "gzip, deflate, br",
            "DNT": "1",
            "Connection": "keep-alive",
            "Upgrade-Insecure-Requests": "1",
            "Sec-Fetch-Dest": "document",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Site": "none",
            "Sec-Fetch-User": "?1",
        },
    }

async def _delay_humano(min_ms: int = 800, max_ms: int = 2000):
    """Espera aleatoria para simular comportamiento humano."""
    await asyncio.sleep(random.uniform(min_ms / 1000, max_ms / 1000))

async def _mover_mouse_aleatorio(page):
    """Simula movimientos aleatorios del mouse."""
    try:
        x = random.randint(100, 800)
        y = random.randint(100, 600)
        await page.mouse.move(x, y)
    except Exception:
        pass

def _safe_name(s: str) -> str:
    s = (s or "consulta").strip()
    s = re.sub(r"\s+", "_", s)
    s = re.sub(r"[^\w\.-]+", "_", s)
    return s or "consulta"

def _norm(s: str) -> str:
    s = (s or "").strip()
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = re.sub(r"\s+", " ", s)
    return s.upper()

def _render_pdf_first_page_to_png(pdf_path: str, png_path: str, zoom: float = 2.0) -> bool:
    """Renderiza la primera página del PDF a PNG usando PyMuPDF."""
    try:
        with fitz.open(pdf_path) as doc:
            if doc.page_count == 0:
                return False
            page = doc[0]
            mat = fitz.Matrix(zoom, zoom)
            pix = page.get_pixmap(matrix=mat, alpha=False)
            pix.save(png_path)
        return os.path.exists(png_path) and os.path.getsize(png_path) > 0
    except Exception:
        return False

def _fallback_blank_pdf(out_pdf_abs: str, text: str) -> bool:
    """Si no se pudo generar el PDF, crea uno simple con un mensaje."""
    try:
        from reportlab.lib.pagesizes import A4
        from reportlab.pdfgen import canvas
        os.makedirs(os.path.dirname(out_pdf_abs), exist_ok=True)
        c = canvas.Canvas(out_pdf_abs, pagesize=A4)
        w, h = A4
        c.setFont("Helvetica", 12)
        c.drawString(40, h - 60, text[:120])
        c.save()
        return True
    except Exception:
        return False


# --------- BOT PRINCIPAL ----------
async def consultar_mha_individual_terrorists_pdf(consulta_id: int, nombre: str, cedula):
    """
    Busca en MHA Individual Terrorists con técnicas anti-detección y evasión de WAF.
    - Busca nombre en página estática del sitio MHA
    - Genera PDF de resultados (1ª página) y PNG como evidencia
    - Retry logic con 3 intentos
    """
    # Fuente
    fuente_obj = await sync_to_async(lambda: Fuente.objects.filter(nombre=NOMBRE_SITIO).first())()
    if not fuente_obj:
        await sync_to_async(Resultado.objects.create)(
            consulta_id=consulta_id,
            fuente=None,
            score=0,
            estado="Sin validar",
            archivo="",
            mensaje=f"No existe Fuente con nombre='{NOMBRE_SITIO}'"
        )
        return

    # Rutas
    relative_folder = os.path.join("resultados", str(consulta_id))
    absolute_folder = os.path.join(settings.MEDIA_ROOT, relative_folder)
    os.makedirs(absolute_folder, exist_ok=True)

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe_ced = _safe_name(str(cedula))

    pdf_name = f"{NOMBRE_SITIO}_{safe_ced}_{ts}.pdf"
    png_name = f"{NOMBRE_SITIO}_{safe_ced}_{ts}.png"

    abs_pdf = os.path.join(absolute_folder, pdf_name)
    rel_pdf = os.path.join(relative_folder, pdf_name).replace("\\", "/")
    abs_png = os.path.join(absolute_folder, png_name)
    rel_png = os.path.join(relative_folder, png_name).replace("\\", "/")

    query_norm = _norm(nombre)
    final_url = URL
    mensaje = "No hay coincidencias"  # default

    for intento in range(1, MAX_INTENTOS + 1):
        logger.info(f"Intento {intento}/{MAX_INTENTOS} para MHA Individual Terrorists")
        navegador = None
        context = None
        pagina = None

        try:
            # --- Etapa 1: buscar y evaluar resultados con anti-detección WAF ---
            async with async_playwright() as p:
                # Configurar navegador con argumentos anti-WAF agresivos
                navegador = await p.chromium.launch(
                    headless=True,
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
                        "--disable-site-isolation-trials",
                        "--disable-features=VizDisplayCompositor",
                    ]
                )

                # Crear contexto con configuración realista
                context = await navegador.new_context(**_get_browser_context_args())

                # Inyectar scripts anti-detección avanzados contra WAF
                await context.add_init_script("""
                    // Ocultar webdriver
                    Object.defineProperty(navigator, 'webdriver', {
                        get: () => undefined
                    });
                    
                    // Plugins realistas
                    Object.defineProperty(navigator, 'plugins', {
                        get: () => [1, 2, 3, 4, 5]
                    });
                    
                    // Idiomas
                    Object.defineProperty(navigator, 'languages', {
                        get: () => ['en-IN', 'en-US', 'en']
                    });
                    
                    // Chrome runtime completo
                    window.chrome = {
                        runtime: {},
                        loadTimes: function() {},
                        csi: function() {},
                        app: {}
                    };
                    
                    // Permisos
                    Object.defineProperty(navigator, 'permissions', {
                        get: () => ({
                            query: () => Promise.resolve({state: 'granted'})
                        })
                    });
                    
                    // Hardware Concurrency
                    Object.defineProperty(navigator, 'hardwareConcurrency', {
                        get: () => 8
                    });
                    
                    // DeviceMemory
                    Object.defineProperty(navigator, 'deviceMemory', {
                        get: () => 8
                    });
                    
                    // Platform
                    Object.defineProperty(navigator, 'platform', {
                        get: () => 'Win32'
                    });
                """)

                pagina = await context.new_page()
                
                # Configurar headers adicionales por página
                await pagina.set_extra_http_headers({
                    "Cache-Control": "max-age=0",
                    "sec-ch-ua": '"Google Chrome";v="131", "Chromium";v="131", "Not_A Brand";v="24"',
                    "sec-ch-ua-mobile": "?0",
                    "sec-ch-ua-platform": '"Windows"',
                })

                # Navegación con comportamiento humano y delays anti-WAF
                logger.info("Cargando página de MHA...")
                await _delay_humano(2000, 4000)  # Delay antes de navegar
                await pagina.goto(URL, wait_until="domcontentloaded", timeout=120000)
                await _delay_humano(3000, 5000)  # Delay mayor después de cargar
                
                try:
                    await pagina.wait_for_load_state("networkidle", timeout=15000)
                except Exception:
                    pass
                
                await _delay_humano(1500, 2500)
                await _mover_mouse_aleatorio(pagina)

                # El sitio es una página estática con lista de terroristas
                # Extraer todo el texto de la página para buscar coincidencias
                logger.info(f"Buscando '{nombre}' en contenido de página...")
                
                # Esperar que cargue el contenido principal
                try:
                    await pagina.wait_for_selector("main, .main-content, article, .content", timeout=10000)
                except Exception:
                    pass
                
                await _delay_humano(1000, 1500)
                
                # Obtener todo el texto visible de la página
                page_text = await pagina.inner_text("body")
                page_text_norm = _norm(page_text)
                
                # Buscar coincidencia
                if query_norm and query_norm in page_text_norm:
                    mensaje = "Se encontraron resultados"
                    logger.info(f"✓ Match encontrado para: {nombre}")
                else:
                    mensaje = "No hay coincidencias"
                    logger.info(f"✗ No hay coincidencias para: {nombre}")

                final_url = pagina.url
                await context.close()
                await navegador.close()

            # --- Etapa 2: imprimir a PDF (1 página) con anti-detección ---
            async with async_playwright() as p:
                navegador = await p.chromium.launch(
                    headless=True,
                    args=[
                        "--disable-blink-features=AutomationControlled",
                        "--disable-dev-shm-usage",
                        "--no-sandbox",
                        "--disable-setuid-sandbox",
                        "--disable-site-isolation-trials",
                    ]
                )
                context = await navegador.new_context(**_get_browser_context_args())
                await context.add_init_script("""
                    Object.defineProperty(navigator, 'webdriver', {
                        get: () => undefined
                    });
                    window.chrome = { runtime: {}, loadTimes: function() {}, csi: function() {} };
                    Object.defineProperty(navigator, 'plugins', {
                        get: () => [1, 2, 3, 4, 5]
                    });
                """)
                
                pagina = await context.new_page()
                await pagina.set_extra_http_headers({
                    "Cache-Control": "max-age=0",
                    "sec-ch-ua": '"Google Chrome";v="131", "Chromium";v="131", "Not_A Brand";v="24"',
                })
                
                logger.info(f"Generando PDF de: {final_url}")
                await _delay_humano(2000, 3000)
                await pagina.goto(final_url, wait_until="domcontentloaded", timeout=120000)
                await _delay_humano(2000, 3000)
                
                try:
                    await pagina.wait_for_load_state("networkidle", timeout=15000)
                except Exception:
                    pass
                
                try:
                    await pagina.emulate_media(media="print")
                except Exception:
                    pass

                await pagina.pdf(
                    path=abs_pdf,
                    format="A4",
                    print_background=True,
                    margin={"top": "10mm", "right": "10mm", "bottom": "10mm", "left": "10mm"},
                    page_ranges="1",
                )
                logger.info(f"PDF generado: {abs_pdf}")
                await context.close()
                await navegador.close()

            # Fallback PDF en blanco si quedó vacío
            if not os.path.exists(abs_pdf) or os.path.getsize(abs_pdf) < 500:
                _fallback_blank_pdf(abs_pdf, f"MHA – sin datos visibles para: {nombre}")
                logger.warning("PDF vacío, generado PDF fallback")

            # --- PNG evidencia desde el PDF ---
            ok_png = _render_pdf_first_page_to_png(abs_pdf, abs_png, zoom=2.0)
            if not ok_png:
                open(abs_png, "wb").close()
                logger.warning("No se pudo generar PNG desde PDF")
            else:
                logger.info(f"PNG generado: {abs_png}")

            # Guardar Resultado apuntando al PNG
            await sync_to_async(Resultado.objects.create)(
                consulta_id=consulta_id,
                fuente=fuente_obj,
                score=0,
                estado="Validada",
                archivo=rel_png,
                mensaje=mensaje,
            )
            logger.info(f"Resultado guardado: {mensaje}")

            return {
                "estado": "Validada",
                "archivo_png": rel_png,
                "archivo_pdf": rel_pdf,
                "mensaje": mensaje,
                "score": 0,
            }

        except Exception as e:
            logger.error(f"Error en intento {intento}: {str(e)}")
            
            # Guardar debug
            error_path = ""
            try:
                if pagina:
                    error_path = os.path.join(
                        absolute_folder,
                        f"debug_{NOMBRE_SITIO}_{intento}.png"
                    )
                    await pagina.screenshot(path=error_path, full_page=True)
                    logger.info(f"Debug guardado: {error_path}")
            except Exception as debug_error:
                logger.error(f"Error guardando debug: {debug_error}")

            # Cierre defensivo
            try:
                if context:
                    await context.close()
            except Exception:
                pass
            try:
                if navegador is not None:
                    await navegador.close()
            except Exception:
                pass

            if intento == MAX_INTENTOS:
                # Intentar dejar constancia en PDF/PNG
                try:
                    _fallback_blank_pdf(abs_pdf, f"MHA – error: {e}")
                    _render_pdf_first_page_to_png(abs_pdf, abs_png, zoom=2.0)
                except Exception:
                    pass

                error_msg = f"Error después de {MAX_INTENTOS} intentos: {str(e)}"
                logger.error(error_msg)
                
                await sync_to_async(Resultado.objects.create)(
                    consulta_id=consulta_id,
                    fuente=fuente_obj,
                    score=0,
                    estado="Sin validar",
                    archivo="",
                    mensaje=str(e) or "Ocurrió un problema en la validación",
                )
                return {"estado": "Sin validar", "archivo_png": "", "archivo_pdf": "", "mensaje": str(e), "score": 0}

            # Delay entre reintentos
            delay = random.uniform(3, 6)
            logger.info(f"Esperando {delay:.1f}s antes del siguiente intento...")
            await asyncio.sleep(delay)