import os
import random
import asyncio
import logging
from datetime import datetime
from playwright.async_api import async_playwright
from django.conf import settings
from asgiref.sync import sync_to_async

from core.models import Resultado, Fuente
from core.resolver.captcha_v2 import resolver_captcha_v2

logger = logging.getLogger(__name__)

url = "https://wsp.registraduria.gov.co/jurados_atipicas/consultar_jurados.php"
site_key = "6LcthjAgAAAAAFIQLxy52074zanHv47cIvmIHglH"
nombre_sitio = "jurados_votacion"

# ---------------- USER AGENTS REALISTAS ----------------
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
]

MAX_INTENTOS = 3


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


async def consultar_jurados_votacion(consulta_id: int, cedula: str):
    """
    Consulta Jurados de Votación con técnicas anti-detección y reCAPTCHA v2.
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

    # Crear carpeta resultados/<consulta_id>
    relative_folder = os.path.join("resultados", str(consulta_id))
    absolute_folder = os.path.join(settings.MEDIA_ROOT, relative_folder)
    os.makedirs(absolute_folder, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    screenshot_name = f"{nombre_sitio}_{cedula}_{timestamp}.png"
    absolute_path = os.path.join(absolute_folder, screenshot_name)
    relative_path = os.path.join(relative_folder, screenshot_name)

    async with async_playwright() as p:
        for intento in range(1, MAX_INTENTOS + 1):
            logger.info(f"Intento {intento}/{MAX_INTENTOS} para consultar Jurados de Votación")
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

                # Navegación con comportamiento humano
                logger.info("Cargando página de Jurados de Votación...")
                await pagina.goto(url, timeout=20000, wait_until="domcontentloaded")
                await _delay_humano(1500, 3000)
                
                try:
                    await pagina.wait_for_load_state("networkidle", timeout=10000)
                except Exception:
                    pass
                
                await _delay_humano(1000, 2000)
                await _mover_mouse_aleatorio(pagina)

                # Llenar cédula con comportamiento humano
                logger.info("Llenando campo de cédula...")
                await _mover_mouse_aleatorio(pagina)
                cedula_input = pagina.locator('input[id="cedula"]')
                await cedula_input.wait_for(state="visible", timeout=10000)
                await cedula_input.click()
                await _delay_humano(300, 600)
                
                for char in str(cedula):
                    await cedula_input.type(char, delay=random.randint(80, 150))
                
                await _delay_humano(1000, 2000)

                # Resolver reCAPTCHA v2
                logger.info("Resolviendo reCAPTCHA v2...")
                token = await resolver_captcha_v2(url, site_key)
                logger.info(f"reCAPTCHA resuelto: {token[:50]}...")

                await _delay_humano(800, 1500)

                # Inyectar token de reCAPTCHA
                await pagina.evaluate(
                    """
                    (token) => {
                        let el = document.getElementById('g-recaptcha-response');
                        if (!el) {
                            el = document.createElement("textarea");
                            el.id = "g-recaptcha-response";
                            el.name = "g-recaptcha-response";
                            el.style = "display:none;";
                            document.forms[0]?.appendChild(el);
                        }
                        el.value = token;
                        el.dispatchEvent(new Event('input', {bubbles: true}));
                        el.dispatchEvent(new Event('change', {bubbles: true}));
                    }
                    """,
                    token,
                )
                logger.info("Token de reCAPTCHA inyectado")

                await _delay_humano(800, 1500)

                # Enviar formulario con comportamiento humano
                await _mover_mouse_aleatorio(pagina)
                submit_btn = pagina.locator("input[type='submit']")
                await submit_btn.scroll_into_view_if_needed()
                await _delay_humano(500, 1000)
                await submit_btn.click()
                logger.info("Formulario enviado")

                await _delay_humano(2000, 3000)
                
                # Esperar respuesta
                await pagina.wait_for_selector("#consulta_resp", timeout=12000)
                await _delay_humano(1000, 1500)

                # Extraer mensaje completo de #consulta_resp
                elemento = pagina.locator("#consulta_resp")
                texto_portal = (await elemento.inner_text() or "").strip()
                mensaje_final = " ".join(texto_portal.split())  # limpiar saltos y espacios extra
                logger.info(f"Mensaje recibido: {mensaje_final[:100]}...")

                # Determinar score en base al texto
                low = mensaje_final.lower()
                if ("no ha sido designado" in low) or ("no figura" in low) or ("aún no figura" in low):
                    score_final = 0
                else:
                    score_final = 10

                # Guardar pantallazo completo de la página
                await pagina.evaluate("window.scrollTo(0, 0)")
                await _delay_humano(300, 500)
                await pagina.screenshot(path=absolute_path, full_page=True)
                logger.info(f"Screenshot de página completa guardado: {absolute_path}")

                await context.close()
                await navegador.close()

                # Registrar resultado
                await sync_to_async(Resultado.objects.create)(
                    consulta_id=consulta_id,
                    fuente=fuente_obj,
                    score=score_final,
                    estado="Validada",
                    mensaje=mensaje_final,
                    archivo=relative_path
                )
                logger.info(f"Resultado guardado: {mensaje_final[:100]}...")
                return  # ✅ éxito, no seguimos reintentando

            except Exception as e:
                logger.error(f"Error en intento {intento}: {str(e)}")
                
                # Guardar debug
                error_path = ""
                try:
                    if pagina:
                        error_path = os.path.join(
                            absolute_folder,
                            f"debug_{nombre_sitio}_{intento}.png"
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
                    # Registrar error solo si agotamos los intentos
                    error_msg = f"Error después de {MAX_INTENTOS} intentos: {str(e)}"
                    logger.error(error_msg)
                    
                    relative_error = os.path.join(relative_folder, os.path.basename(error_path)) if error_path else ""
                    await sync_to_async(Resultado.objects.create)(
                        consulta_id=consulta_id,
                        fuente=fuente_obj,
                        score=0,
                        estado="Sin Validar",
                        mensaje="No se pudo realizar la consulta en el momento.",
                        archivo=relative_error
                    )
                    return

                # Delay entre reintentos
                delay = random.uniform(3, 6)
                logger.info(f"Esperando {delay:.1f}s antes del siguiente intento...")
                await asyncio.sleep(delay)