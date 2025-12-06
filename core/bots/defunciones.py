# bots/defunciones.py
import os
import random
import asyncio
import logging
from datetime import datetime
from playwright.async_api import async_playwright
from django.conf import settings
from asgiref.sync import sync_to_async

from core.models import Resultado, Fuente

logger = logging.getLogger(__name__)

DEFUNCIONES_URL = "https://defunciones.registraduria.gov.co/"
NOMBRE_SITIO = "defunciones"

# ---------------- USER AGENTS REALISTAS ----------------
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
]

MAX_RETRIES = 3


def _get_browser_context_args():
    """Configuración del contexto del navegador para evadir detección"""
    return {
        "viewport": {"width": 1600, "height": 1000},
        "device_scale_factor": 1,
        "locale": "es-CO",
        "timezone_id": "America/Bogota",
        "user_agent": random.choice(USER_AGENTS),
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


async def consultar_defunciones(consulta_id: int, cedula: str):
    """
    Consulta en el portal de Defunciones de la Registraduría:
      - Ingresa la cédula en el campo de búsqueda
      - Hace clic en "Buscar"
      - Obtiene el mensaje final (Vigente / Fallecido)
      - Guarda pantallazo de **página completa** y resultado en la BD
    """

    # Buscar la fuente
    try:
        fuente_obj = await sync_to_async(Fuente.objects.get)(nombre=NOMBRE_SITIO)
    except Exception as e:
        await sync_to_async(Resultado.objects.create)(
            consulta_id=consulta_id, fuente=None, score=0,
            estado="Sin Validar", mensaje=f"No se encontró la Fuente '{NOMBRE_SITIO}': {e}", archivo=""
        )
        return

    # Carpeta resultados/<consulta_id>
    relative_folder = os.path.join("resultados", str(consulta_id))
    absolute_folder = os.path.join(settings.MEDIA_ROOT, relative_folder)
    os.makedirs(absolute_folder, exist_ok=True)

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    screenshot_name = f"defunciones_{cedula}_{ts}.png"
    absolute_path = os.path.join(absolute_folder, screenshot_name)
    relative_path = os.path.join(relative_folder, screenshot_name).replace("\\", "/")

    async with async_playwright() as p:
        for intento in range(1, MAX_RETRIES + 1):
            logger.info(f"Intento {intento}/{MAX_RETRIES} para consultar Defunciones")
            navegador = None
            contexto = None

            try:
                # Configurar navegador con argumentos anti-detección
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
                        "--window-size=1600,1000",
                        "--start-maximized",
                    ]
                )

                # Crear contexto con configuración realista
                contexto = await navegador.new_context(**_get_browser_context_args())

                # Inyectar scripts anti-detección
                await contexto.add_init_script("""
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

                page = await contexto.new_page()

                # 1) Abrir página con comportamiento humano
                await page.goto(DEFUNCIONES_URL, wait_until="domcontentloaded", timeout=60000)
                await _delay_humano(1500, 3000)
                
                try:
                    await page.wait_for_load_state("networkidle", timeout=8000)
                except Exception:
                    pass
                
                await _delay_humano(1000, 2000)
                await _mover_mouse_aleatorio(page)

                # 2) Llenar la cédula con comportamiento humano
                input_selector = 'input[id="nuip"]'
                await page.wait_for_selector(input_selector, timeout=15000)
                await _delay_humano(500, 1000)
                
                # Escribir caracter por caracter
                await page.click(input_selector)
                await _delay_humano(300, 600)
                for char in str(cedula).strip():
                    await page.type(input_selector, char, delay=random.randint(80, 150))
                await _delay_humano(800, 1500)

                # 3) Clic en "Buscar" con movimiento de mouse
                await _mover_mouse_aleatorio(page)
                await _delay_humano(500, 1000)
                
                boton_buscar = page.locator("button.btn.btn-primary")
                await boton_buscar.scroll_into_view_if_needed()
                await _delay_humano(400, 800)
                await boton_buscar.click()

                # Esperar que aparezca el resultado
                result_locator = page.locator("div.card-footer")
                await result_locator.wait_for(timeout=20000)
                await _delay_humano(1000, 2000)

                # 4) Extraer mensaje
                mensaje_final = (await result_locator.inner_text()).strip()
                score_final = 0
                
                if "Vigente" in mensaje_final:
                    score_final = 0
                elif "Fallecido" in mensaje_final or "Defuncion" in mensaje_final or "Defunción" in mensaje_final:
                    score_final = 10
                else:
                    score_final = 0

                # 5) Pantallazo **de página completa**
                await page.evaluate("window.scrollTo(0, 0)")
                await _delay_humano(400, 800)
                await page.screenshot(path=absolute_path, full_page=True)
                logger.info(f"Screenshot guardado: {absolute_path}")

                await contexto.close()
                await navegador.close()

                # 6) Guardar en BD
                await sync_to_async(Resultado.objects.create)(
                    consulta_id=consulta_id,
                    fuente=fuente_obj,
                    score=score_final,
                    estado="Validada",
                    mensaje=mensaje_final,
                    archivo=relative_path,
                )
                logger.info(f"Resultado guardado exitosamente: {mensaje_final}")
                return

            except Exception as e:
                logger.error(f"Error en intento {intento}: {str(e)}")
                
                # Cierre defensivo
                try:
                    if contexto:
                        await contexto.close()
                except Exception:
                    pass
                try:
                    if navegador:
                        await navegador.close()
                except Exception:
                    pass

                # Guardar debug
                try:
                    debug_path = os.path.join(absolute_folder, f"debug_defunciones_{intento}.png")
                    if page:
                        await page.screenshot(path=debug_path, full_page=True)
                        logger.info(f"Debug guardado: {debug_path}")
                except Exception as debug_error:
                    logger.error(f"Error guardando debug: {debug_error}")

                if intento == MAX_RETRIES:
                    error_msg = f"Error después de {MAX_RETRIES} intentos: {str(e)}"
                    logger.error(error_msg)
                    await sync_to_async(Resultado.objects.create)(
                        consulta_id=consulta_id,
                        fuente=fuente_obj,
                        score=0,
                        estado="Sin Validar",
                        mensaje=error_msg,
                        archivo="",
                    )
                    return

                # Delay entre reintentos
                delay = random.uniform(3, 6)
                logger.info(f"Esperando {delay:.1f}s antes del siguiente intento...")
                await asyncio.sleep(delay)