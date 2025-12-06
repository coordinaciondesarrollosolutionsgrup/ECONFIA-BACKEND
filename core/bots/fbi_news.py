# consulta/fbi_news.py (versión async adaptada a BD)
import os
import re
import asyncio
import random
import logging
import unicodedata
from datetime import datetime
from django.conf import settings
from asgiref.sync import sync_to_async
from playwright.async_api import async_playwright

from core.models import Resultado, Fuente

logger = logging.getLogger(__name__)

URL = "https://www.fbi.gov/news/stories"
NOMBRE_SITIO = "fbi_news"

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
        "viewport": {"width": 1440, "height": 900},
        "locale": "en-US",
        "timezone_id": "America/New_York",
        "user_agent": random.choice(USER_AGENTS),
        "extra_http_headers": {
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
            "Accept-Language": "en-US,en;q=0.9",
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


def _norm(s: str) -> str:
    if not s:
        return ""
    s = unicodedata.normalize("NFD", s)
    s = "".join(ch for ch in s if unicodedata.category(ch) != "Mn")
    s = " ".join(s.split())
    return s.casefold()

async def consultar_fbi_news(consulta_id: int, nombre_completo: str):
    """
    Busca nombre_completo en FBI News con técnicas anti-detección avanzadas.
    """
    # 1) Fuente
    try:
        fuente_obj = await sync_to_async(Fuente.objects.get)(nombre=NOMBRE_SITIO)
    except Exception as e:
        await sync_to_async(Resultado.objects.create)(
            consulta_id=consulta_id, fuente=None, score=0,
            estado="Sin Validar", mensaje=f"No se encontró la Fuente '{NOMBRE_SITIO}': {e}", archivo=""
        )
        return

    nombre_completo = (nombre_completo or "").strip()
    if not nombre_completo:
        await sync_to_async(Resultado.objects.create)(
            consulta_id=consulta_id, fuente=fuente_obj, score=0,
            estado="Sin Validar", mensaje="Nombre vacío para la consulta.", archivo=""
        )
        return

    # 2) Rutas de salida
    relative_folder = os.path.join("resultados", str(consulta_id))
    absolute_folder = os.path.join(settings.MEDIA_ROOT, relative_folder)
    os.makedirs(absolute_folder, exist_ok=True)

    safe = re.sub(r"[^\w\.-]+", "_", nombre_completo) or "consulta"
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    png_name = f"{NOMBRE_SITIO}_{safe}_{ts}.png"
    absolute_path = os.path.join(absolute_folder, png_name)
    relative_path = os.path.join(relative_folder, png_name)

    async def _leer_total(p) -> int:
        """Devuelve N del “Results: N Items”. 0 si no aparece."""
        try:
            total_p = p.locator(".row.top-total p.right, .top-total .right, p.right:has-text('Results:')")
            if await total_p.count() > 0:
                txt = (await total_p.first.inner_text()).strip()
                txt = " ".join(txt.split())
                m = re.search(r"Results:\s*([\d,\.]+)\s*Items", txt, flags=re.I)
                if m:
                    num = m.group(1).replace(",", "").replace(".", "")
                    return int(num) if num.isdigit() else 0
        except Exception:
            pass
        return 0

    async def _hay_match_exacto(p, objetivo_norm: str) -> bool:
        """
        Busca coincidencia EXACTA del título en cada <li> del listado:
        <ul class="dt-media"> ... <p class="title"><a>...</a>
        Incluye fallbacks por si el layout varía.
        """
        link_sel = (
            "ul.dt-media li .title a, "             # layout actual
            "ul.castle-grid-block-sm-1 li .title a, "
            ".collection-listing .item .title a, "
            "article .title a"
        )
        try:
            links = p.locator(link_sel)
            n = 0
            try:
                n = await links.count()
            except Exception:
                n = 0
            for i in range(n):
                try:
                    t = (await links.nth(i).inner_text() or "").strip()
                    if _norm(t) == objetivo_norm:
                        return True
                except Exception:
                    continue
        except Exception:
            pass
        return False

    async with async_playwright() as p:
        for intento in range(1, MAX_RETRIES + 1):
            logger.info(f"Intento {intento}/{MAX_RETRIES} para consultar FBI News")
            navegador = None
            context = None
            page = None

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
                        "--window-size=1440,900",
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
                        get: () => ['en-US', 'en']
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
                await page.goto(URL, timeout=120000, wait_until="domcontentloaded")
                await _delay_humano(1500, 3000)
                
                try:
                    await page.wait_for_load_state("networkidle", timeout=15000)
                except Exception:
                    pass
                
                await _delay_humano(1000, 2000)
                await _mover_mouse_aleatorio(page)

                await _mover_mouse_aleatorio(page)

                # Cookies (best-effort)
                for sel in [
                    "button:has-text('Accept')",
                    "button#onetrust-accept-btn-handler",
                    "button:has-text('I agree')",
                ]:
                    try:
                        btn = page.locator(sel).first
                        if await btn.count() > 0:
                            await _delay_humano(300, 600)
                            await btn.click(timeout=2000)
                            await _delay_humano(500, 1000)
                            logger.info("Cookies aceptadas")
                            break
                    except Exception:
                        pass

                # Filtro con comportamiento humano
                inp = page.locator("#filter-input")
                await inp.wait_for(state="visible", timeout=60000)
                await _delay_humano(500, 1000)
                await _mover_mouse_aleatorio(page)
                await inp.click()
                await _delay_humano(300, 600)
                
                try:
                    await inp.fill("")
                except Exception:
                    pass
                
                # Escribir con delays
                for char in nombre_completo:
                    await inp.type(char, delay=random.randint(50, 100))
                
                await _delay_humano(800, 1500)

                await _delay_humano(800, 1500)

                # Enter para aplicar
                try:
                    await inp.press("Enter")
                except Exception:
                    await page.keyboard.press("Enter")

                await _delay_humano(1000, 2000)

                # Esperar contenedor
                for sel in [
                    ".row.top-total",
                    ".dt-media",
                    ".collection-listing",
                    "section[role='main']",
                    "div#content",
                ]:
                    try:
                        await page.wait_for_selector(sel, timeout=12000)
                        logger.info(f"Contenedor encontrado: {sel}")
                        break
                    except Exception:
                        continue

                try:
                    await page.wait_for_load_state("networkidle", timeout=10000)
                except Exception:
                    pass
                
                await _delay_humano(800, 1500)

                # 4) Total y lógica de score/mensaje
                total = await _leer_total(page)
                logger.info(f"Total de resultados: {total}")
                
                if total == 0:
                    score_final = 0
                    mensaje_final = "Results: 0 items"
                else:
                    objetivo = _norm(nombre_completo)
                    match = await _hay_match_exacto(page, objetivo)
                    if match:
                        score_final = 10
                        mensaje_final = "Se han encontrado coincidencias"
                        logger.info("Match exacto encontrado")
                    else:
                        score_final = 0
                        mensaje_final = "No se han encontrado coincidencias"
                        logger.info("No se encontró match exacto")

                # 5) Screenshot de página completa
                try:
                    # Scroll para cargar todo el contenido
                    await page.evaluate("window.scrollTo(0, 0)")
                    await _delay_humano(300, 500)
                    await _mover_mouse_aleatorio(page)
                    await page.mouse.wheel(0, 800)
                    await _delay_humano(400, 800)
                    # Volver arriba para captura completa
                    await page.evaluate("window.scrollTo(0, 0)")
                    await _delay_humano(300, 500)
                except Exception:
                    pass
                
                await page.screenshot(path=absolute_path, full_page=True)
                logger.info(f"Screenshot de página completa guardado: {absolute_path}")

                await context.close()
                await navegador.close()

                # 6) Registrar
                await sync_to_async(Resultado.objects.create)(
                    consulta_id=consulta_id, fuente=fuente_obj, score=score_final,
                    estado="Validada", mensaje=mensaje_final, archivo=relative_path
                )
                logger.info(f"Resultado guardado: {mensaje_final}")
                return

            except Exception as e:
                logger.error(f"Error en intento {intento}: {str(e)}")
                
                # Cierre defensivo
                try:
                    if context is not None:
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
                    debug_path = os.path.join(absolute_folder, f"debug_fbi_news_{intento}.png")
                    if page:
                        await page.screenshot(path=debug_path)
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