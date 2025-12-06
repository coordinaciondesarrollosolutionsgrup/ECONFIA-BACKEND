import os
import random
import asyncio
import logging
from datetime import datetime
from playwright.async_api import async_playwright
from django.conf import settings
from asgiref.sync import sync_to_async

from core.models import Resultado, Fuente
from core.resolver.captcha_img2 import resolver_captcha_imagen  # async

logger = logging.getLogger(__name__)

url = "https://mat.inpec.gov.co/consultasWeb/faces/index.xhtml"
nombre_sitio = "inpec"

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
        "viewport": {"width": 1920, "height": 1080},
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


async def consultar_inpec(consulta_id: int, cedula: str, apellidos: str):
    """
    Consulta INPEC con técnicas anti-detección y sistema de reintentos.
    """
    # Buscar la fuente
    try:
        fuente_obj = await sync_to_async(Fuente.objects.get)(nombre=nombre_sitio)
    except Exception as e:
        await sync_to_async(Resultado.objects.create)(
            consulta_id=consulta_id,
            fuente=None,
            score=0,
            estado="Sin Validar",
            mensaje=f"No se encontró la Fuente '{nombre_sitio}': {e}",
            archivo=""
        )
        return

    # Carpeta de resultados
    relative_folder = os.path.join('resultados', str(consulta_id))
    absolute_folder = os.path.join(settings.MEDIA_ROOT, relative_folder)
    os.makedirs(absolute_folder, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    screenshot_name = f"{nombre_sitio}_{cedula}_{timestamp}.png"
    absolute_path = os.path.join(absolute_folder, screenshot_name)
    relative_path = os.path.join(relative_folder, screenshot_name)

    async with async_playwright() as p:
        for intento in range(1, MAX_RETRIES + 1):
            logger.info(f"Intento {intento}/{MAX_RETRIES} para consultar INPEC")
            navegador = None
            context = None
            pagina = None

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
                        "--window-size=1920,1080",
                        "--start-maximized",
                    ]
                )

                # Crear contexto con configuración realista
                context = await navegador.new_context(**_get_browser_context_args())

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

                pagina = await context.new_page()

                # Intentar cargar la página con comportamiento humano
                logger.info("Cargando página INPEC...")
                await pagina.goto(url, timeout=20000, wait_until="domcontentloaded")
                await _delay_humano(1500, 3000)
                
                try:
                    await pagina.wait_for_load_state("networkidle", timeout=10000)
                except Exception:
                    pass
                
                await _delay_humano(1000, 2000)
                await _mover_mouse_aleatorio(pagina)

                # Esperar formulario
                await pagina.wait_for_selector('form[id="solicitudTurno"]', timeout=15000)
                await _delay_humano(800, 1500)
                logger.info("Formulario encontrado")

                # Llenar datos con comportamiento humano
                primer_apellido = (apellidos or "").strip().split()[0].upper()
                
                # Campo cédula
                await _mover_mouse_aleatorio(pagina)
                cedula_input = pagina.locator('input[id="solicitudTurno:identificacion"]')
                await cedula_input.click()
                await _delay_humano(300, 600)
                for char in str(cedula):
                    await cedula_input.type(char, delay=random.randint(80, 150))
                await _delay_humano(500, 1000)

                # Campo apellido
                await _mover_mouse_aleatorio(pagina)
                apellido_input = pagina.locator('input[id="solicitudTurno:apellido"]')
                await apellido_input.click()
                await _delay_humano(300, 600)
                for char in primer_apellido:
                    await apellido_input.type(char, delay=random.randint(80, 150))
                await _delay_humano(800, 1500)

                # Capturar captcha
                logger.info("Capturando CAPTCHA...")
                captcha_locator = pagina.locator("img[id='solicitudTurno:im']")
                await captcha_locator.wait_for(timeout=8000)
                await _delay_humano(500, 1000)
                
                captcha_name = f"captcha_{nombre_sitio}_{cedula}_{timestamp}.png"
                captcha_abs_path = os.path.join(absolute_folder, captcha_name)
                await captcha_locator.screenshot(path=captcha_abs_path)
                logger.info(f"CAPTCHA guardado: {captcha_abs_path}")

                # Resolver captcha
                captcha_resultado = await resolver_captcha_imagen(captcha_abs_path)
                logger.info(f"CAPTCHA resuelto: {captcha_resultado}")
                
                await _delay_humano(500, 1000)
                await _mover_mouse_aleatorio(pagina)
                
                captcha_input = pagina.locator('input[id="solicitudTurno:catpcha"]')
                await captcha_input.click()
                await _delay_humano(300, 600)
                for char in captcha_resultado:
                    await captcha_input.type(char, delay=random.randint(80, 150))
                await _delay_humano(1000, 2000)

                # Click botón "Consultar" con comportamiento humano
                await _mover_mouse_aleatorio(pagina)
                btn = pagina.locator('button:has-text("Consultar")').first
                await btn.scroll_into_view_if_needed()
                await _delay_humano(500, 1000)
                await btn.click()
                logger.info("Botón Consultar clickeado")

                # Esperar tabla o mensaje
                await pagina.wait_for_selector("#solicitudTurno\\:tablainterno, #solicitudTurno\\:msg", timeout=15000)
                await _delay_humano(1500, 2500)

                # Determinar mensaje y score
                mensaje_final = "No se encontraron registros con los datos suministrados"
                score_final = 0
                msg_loc = pagina.locator("#solicitudTurno\\:msg li span").first
                if await msg_loc.count() > 0:
                    texto = (await msg_loc.text_content() or "").strip().lower()
                    logger.info(f"Mensaje encontrado: {texto}")
                    if "no se encontraron registros" not in texto:
                        mensaje_final = "Se encontraron registros con los datos suministrados"
                        score_final = 10

                # Pantallazo final de página completa
                await pagina.evaluate("window.scrollTo(0, 0)")
                await _delay_humano(300, 500)
                await pagina.screenshot(path=absolute_path, full_page=True)
                logger.info(f"Screenshot de página completa guardado: {absolute_path}")

                await context.close()
                await navegador.close()

                # Guardar resultado en BD
                await sync_to_async(Resultado.objects.create)(
                    consulta_id=consulta_id,
                    fuente=fuente_obj,
                    score=score_final,
                    estado="Validada",
                    mensaje=mensaje_final,
                    archivo=relative_path
                )
                logger.info(f"Resultado guardado: {mensaje_final}")
                return

            except Exception as e:
                logger.error(f"Error en intento {intento}: {str(e)}")
                
                # Cierre defensivo
                try:
                    if pagina:
                        debug_path = os.path.join(absolute_folder, f"debug_inpec_{intento}.png")
                        await pagina.screenshot(path=debug_path, full_page=True)
                        logger.info(f"Debug guardado: {debug_path}")
                except Exception as debug_error:
                    logger.error(f"Error guardando debug: {debug_error}")
                
                try:
                    if context:
                        await context.close()
                except Exception:
                    pass
                try:
                    if navegador:
                        await navegador.close()
                except Exception:
                    pass

                if intento == MAX_RETRIES:
                    error_msg = f"Error después de {MAX_RETRIES} intentos: {str(e)}"
                    logger.error(error_msg)
                    
                    # Guardar error en BD
                    await sync_to_async(Resultado.objects.create)(
                        consulta_id=consulta_id,
                        fuente=fuente_obj,
                        score=0,
                        estado="Sin Validar",
                        mensaje="La fuente no se encuentra en funcionamiento en este momento, por favor intente más tarde",
                        archivo=relative_path if os.path.exists(absolute_path) else ""
                    )
                    return

                # Delay entre reintentos
                delay = random.uniform(3, 6)
                logger.info(f"Esperando {delay:.1f}s antes del siguiente intento...")
                await asyncio.sleep(delay)

