# consulta/eu_sanctions_tracker.py (versión async adaptada a BD)
import os
import re
import asyncio
import random
import logging
from datetime import datetime
from django.conf import settings
from asgiref.sync import sync_to_async
from playwright.async_api import async_playwright

from core.models import Resultado, Fuente

logger = logging.getLogger(__name__)

URL = "https://data.europa.eu/apps/eusanctionstracker/"
NOMBRE_SITIO = "eu_sanctions_tracker"

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
        "viewport": {"width": 1400, "height": 900},
        "locale": "en-US",
        "timezone_id": "Europe/Brussels",
        "user_agent": random.choice(USER_AGENTS),
        "extra_http_headers": {
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
            "Accept-Language": "en-US,en;q=0.9,es;q=0.8",
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


async def _accept_cookies(page):
    """Acepta cookies con delays humanos"""
    await _delay_humano(500, 1000)
    for sel in [
        "button:has-text('I accept cookies')",
        "button:has-text('Accept all cookies')",
        "button#onetrust-accept-btn-handler",
        "button:has-text('I accept')",
    ]:
        try:
            btn = page.locator(sel).first
            if await btn.count() > 0:
                await _delay_humano(300, 600)
                await btn.click(timeout=2000)
                await _delay_humano(500, 1000)
                logger.info("Cookies aceptadas")
                return True
        except Exception:
            pass
    return False

async def consultar_eu_sanctions_tracker(consulta_id: int, nombre_completo: str):
    """
    Busca `nombre_completo` en EU sanctions tracker y toma un pantallazo del resultado
    (o del mensaje 'No results found'). Guarda en MEDIA_ROOT/resultados/<consulta_id>/.
    En lugar de return, registra el resultado en la BD.
    """
    nombre_completo = (nombre_completo or "").strip()

    # 1) Fuente
    try:
        fuente_obj = await sync_to_async(Fuente.objects.get)(nombre=NOMBRE_SITIO)
    except Exception as e:
        await sync_to_async(Resultado.objects.create)(
            consulta_id=consulta_id, fuente=None, score=0,
            estado="Sin Validar", mensaje=f"No se encontró la Fuente '{NOMBRE_SITIO}': {e}", archivo=""
        )
        return

    if not nombre_completo:
        await sync_to_async(Resultado.objects.create)(
            consulta_id=consulta_id, fuente=fuente_obj, score=0,
            estado="Sin Validar", mensaje="Nombre vacío para la consulta.", archivo=""
        )
        return

    # 2) Carpeta destino
    relative_folder = os.path.join("resultados", str(consulta_id))
    absolute_folder = os.path.join(settings.MEDIA_ROOT, relative_folder)
    os.makedirs(absolute_folder, exist_ok=True)

    # 3) Nombre de archivo
    safe = re.sub(r"\s+", "_", nombre_completo) or "consulta"
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    img_name = f"{NOMBRE_SITIO}_{safe}_{ts}.png"
    absolute_path = os.path.join(absolute_folder, img_name)
    relative_path = os.path.join(relative_folder, img_name)

    async with async_playwright() as p:
        for intento in range(1, MAX_RETRIES + 1):
            logger.info(f"Intento {intento}/{MAX_RETRIES} para consultar EU Sanctions Tracker")
            navegador = None
            context = None

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
                        "--window-size=1400,900",
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
                        get: () => ['en-US', 'en', 'es']
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

                # Navegación con comportamiento humano
                await page.goto(URL, wait_until="domcontentloaded")
                await _delay_humano(1500, 3000)
                
                try:
                    await page.wait_for_load_state("networkidle", timeout=20000)
                except Exception:
                    pass
                
                await _delay_humano(1000, 2000)
                await _mover_mouse_aleatorio(page)

                # Aceptar cookies
                await _accept_cookies(page)

                # Localizar combobox (Tom Select)
                inp = None
                try:
                    inp = page.get_by_role("combobox", name=re.compile(r"Search sanctions", re.I))
                    await inp.wait_for(state="visible", timeout=12000)
                    logger.info("Campo de búsqueda encontrado por rol")
                except Exception:
                    for s in [
                        "div#search-field-ts-control input",
                        "input#search-field",
                        "input[role='combobox']",
                        "input[aria-autocomplete='list']",
                    ]:
                        loc = page.locator(s).first
                        if await loc.count() > 0:
                            inp = loc
                            logger.info(f"Campo de búsqueda encontrado por selector: {s}")
                            break

                if inp is None:
                    await page.screenshot(path=absolute_path, full_page=True)
                    await context.close()
                    await navegador.close()
                    navegador = None
                    
                    if intento == MAX_RETRIES:
                        await sync_to_async(Resultado.objects.create)(
                            consulta_id=consulta_id, fuente=fuente_obj, score=0,
                            estado="Sin Validar", mensaje="No se encontró el campo de búsqueda del tracker.", archivo=""
                        )
                        return
                    
                    delay = random.uniform(3, 6)
                    logger.info(f"Campo no encontrado. Esperando {delay:.1f}s antes del siguiente intento...")
                    await asyncio.sleep(delay)
                    continue

                # Llenar búsqueda con comportamiento humano
                query = nombre_completo
                await _delay_humano(500, 1000)
                await _mover_mouse_aleatorio(page)
                await inp.click()
                await _delay_humano(300, 600)
                
                try:
                    await inp.fill("")
                except Exception:
                    pass
                
                # Escribir con delays
                for char in query:
                    await inp.type(char, delay=random.randint(80, 150))
                
                await _delay_humano(800, 1500)

                # Si .type no dejó valor, forzar value + events
                try:
                    if query and (await inp.input_value() or "").strip() == "":
                        el = await inp.element_handle()
                        await page.evaluate(
                            """(el, val) => { el.value = val; el.dispatchEvent(new Event('input', {bubbles:true})); }""",
                            el, query
                        )
                        logger.info("Valor forzado en el campo de búsqueda")
                except Exception as e:
                    logger.warning(f"Error forzando valor: {e}")

                # Esperar dropdown
                await _delay_humano(1000, 2000)
                try:
                    await page.locator(".ts-dropdown").wait_for(state="visible", timeout=10000)
                    logger.info("Dropdown visible")
                except Exception:
                    logger.warning("Dropdown no visible")
                    pass

                # ===== Detección SIN resultados =====
                try:
                    nores = page.locator(".ts-dropdown .no-results:has-text('No results found')")
                    if await nores.count() > 0 and await nores.first.is_visible():
                        logger.info("No results found detectado")
                        await _delay_humano(500, 1000)
                        await page.screenshot(path=absolute_path, full_page=True)
                        await context.close()
                        await navegador.close()
                        
                        await sync_to_async(Resultado.objects.create)(
                            consulta_id=consulta_id, fuente=fuente_obj, score=0,
                            estado="Validada", mensaje="No results found", archivo=relative_path
                        )
                        logger.info("Resultado guardado: No results found")
                        return
                except Exception:
                    pass

                # ===== Con resultados: seleccionar el primero y capturar =====
                found = False
                first_opt = page.locator(".ts-dropdown .option").first
                
                if await first_opt.count() > 0:
                    found = True
                    logger.info("Resultados encontrados, seleccionando el primero")
                    await _delay_humano(500, 1000)
                    await _mover_mouse_aleatorio(page)
                    await first_opt.click()
                    
                    try:
                        await page.wait_for_selector("h1, h2, .profile, .details, [role='main']", timeout=15000)
                    except Exception:
                        await _delay_humano(2000, 3000)
                    
                    try:
                        await page.wait_for_selector(".chart, table, .dataTables_wrapper, .related-entities", timeout=10000)
                    except Exception:
                        pass
                    
                    await _delay_humano(2000, 3000)
                    
                    try:
                        await page.mouse.wheel(0, 1500)
                        await _delay_humano(500, 1000)
                    except Exception:
                        pass
                    
                    await page.screenshot(path=absolute_path, full_page=True)
                    logger.info(f"Screenshot guardado: {absolute_path}")
                else:
                    # Fallback: Enter + capturar algo del estado actual
                    logger.info("No se encontraron opciones, intentando Enter")
                    try:
                        await inp.press("Enter")
                        await _delay_humano(3000, 5000)
                    except Exception:
                        pass
                    
                    # intentar detectar si apareció algo en pantalla
                    if await page.locator(".ts-dropdown .option").count() > 0:
                        found = True
                    
                    await page.screenshot(path=absolute_path, full_page=True)

                await context.close()
                await navegador.close()

                # Registrar según se hayan encontrado hallazgos
                if found:
                    await sync_to_async(Resultado.objects.create)(
                        consulta_id=consulta_id, fuente=fuente_obj, score=10,
                        estado="Validada", mensaje="Se han encontrado hallazgos", archivo=relative_path
                    )
                    logger.info("Resultado guardado: Se han encontrado hallazgos")
                else:
                    await sync_to_async(Resultado.objects.create)(
                        consulta_id=consulta_id, fuente=fuente_obj, score=0,
                        estado="Validada", mensaje="No results found", archivo=relative_path
                    )
                    logger.info("Resultado guardado: No results found (fallback)")
                
                return

            except Exception as e:
                logger.error(f"Error en intento {intento}: {str(e)}")
                
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

                # Guardar debug
                try:
                    debug_path = os.path.join(absolute_folder, f"debug_eu_sanctions_{intento}.png")
                    if page:
                        await page.screenshot(path=debug_path, full_page=True)
                        logger.info(f"Debug guardado: {debug_path}")
                except Exception as debug_error:
                    logger.error(f"Error guardando debug: {debug_error}")

                if intento == MAX_RETRIES:
                    error_msg = f"Error después de {MAX_RETRIES} intentos: {str(e)}"
                    logger.error(error_msg)
                    await sync_to_async(Resultado.objects.create)(
                        consulta_id=consulta_id, fuente=fuente_obj, score=0,
                        estado="Sin Validar", mensaje=error_msg, archivo=""
                    )
                    return

                # Delay entre reintentos
                delay = random.uniform(3, 6)
                logger.info(f"Esperando {delay:.1f}s antes del siguiente intento...")
                await asyncio.sleep(delay)