# bots/sca_search.py
import os, re, asyncio, urllib.parse, unicodedata
from datetime import datetime

from django.conf import settings
from asgiref.sync import sync_to_async
from playwright.async_api import async_playwright, TimeoutError as PWTimeout

from core.models import Resultado, Fuente

NOMBRE_SITIO = "sca_search"
URL_SEARCH = "https://www.sca.gov.ae/en/search.aspx"

GOTO_TIMEOUT_MS = 45_000     # Mucho más rápido
WAIT_RESULTS_MS = 12_000     # Antes era 60-90 seg
RETRIES = 2

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

def _norm(s: str) -> str:
    s = (s or "").strip().lower()
    s = "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn")
    s = re.sub(r"\s+", " ", s)
    return s


async def consultar_sca_search(consulta_id: int, nombre: str, apellido: str):
    navegador = None
    full_name = f"{(nombre or '').strip()} {(apellido or '').strip()}".strip()

    # 1) Fuente
    try:
        fuente_obj = await sync_to_async(Fuente.objects.get)(nombre=NOMBRE_SITIO)
    except Exception as e:
        await sync_to_async(Resultado.objects.create)(
            consulta_id=consulta_id, fuente=None, score=1,
            estado="Sin Validar",
            mensaje=f"No se encontró la Fuente '{NOMBRE_SITIO}': {e}",
            archivo=""
        )
        return

    if not full_name:
        await sync_to_async(Resultado.objects.create)(
            consulta_id=consulta_id, fuente=fuente_obj, score=1,
            estado="Sin Validar",
            mensaje="Nombre y/o apellido vacíos para la consulta.",
            archivo=""
        )
        return

    # 2) Carpeta / archivo
    relative_folder = os.path.join("resultados", str(consulta_id))
    absolute_folder = os.path.join(settings.MEDIA_ROOT, relative_folder)
    os.makedirs(absolute_folder, exist_ok=True)

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe_name = re.sub(r"[^\w\.-]+", "_", full_name)
    png_name = f"{NOMBRE_SITIO}_{safe_name}_{ts}.png"
    absolute_png = os.path.join(absolute_folder, png_name)
    relative_png = os.path.join(relative_folder, png_name).replace("\\", "/")

    mensaje_final = "No hay coincidencias."
    score_final = 1
    success = False
    screenshot_captured = False
    norm_query = _norm(full_name)

    try:
        async with async_playwright() as p:
            navegador = await p.chromium.launch(
                headless=True,
                args=[
                    "--disable-blink-features=AutomationControlled",
                    "--no-sandbox",
                    "--disable-dev-shm-usage",
                ]
            )

            context = await navegador.new_context(
                viewport={"width": 1400, "height": 900},
                locale="en-US",
                timezone_id="Asia/Dubai",
                user_agent=UA,
                extra_http_headers={
                    "Accept-Language": "en-US,en;q=0.9,ar;q=0.8",
                }
            )

            page = await context.new_page()
            await page.add_init_script(
                "Object.defineProperty(navigator,'webdriver',{get:()=>undefined});"
            )

            async def _real_search():
                await page.goto(URL_SEARCH, timeout=GOTO_TIMEOUT_MS)

                # Esperar el panel de filtros
                await page.wait_for_selector("[data-isms-search-filters]", timeout=10_000)

                # Scroll para activar render de Angular
                await page.evaluate("window.scrollTo(0, 300)")

                # Detectar input correcto
                input_selector = None
                for sel in [
                    '[data-isms-search-filters] input[name="keywords"]',
                    'input[name="keywords"]',
                    '[data-isms-search-filters] input[type="text"]'
                ]:
                    if await page.locator(sel).count() > 0:
                        input_selector = sel
                        break

                if not input_selector:
                    raise Exception("No se encontró input de búsqueda")

                search_input = page.locator(input_selector)
                await search_input.fill(full_name)

                # Forzar espera de Angular
                await page.wait_for_timeout(500)

                # Encontrar botón real
                btn_selector = None
                for sel in [
                    "[data-isms-search-btn]",
                    "[data-isms-search-filters] button.aegov-btn",
                    "[data-isms-search-filters] button[type='button']"
                ]:
                    if await page.locator(sel).count() > 0:
                        btn_selector = sel
                        break

                if not btn_selector:
                    raise Exception("No se encontró botón para ejecutar búsqueda")

                await page.locator(btn_selector).click()

                # Esperar a que aparezca palabra clave (si realmente buscó)
                await page.wait_for_selector('[data-icms-searchkeywords]', timeout=WAIT_RESULTS_MS)

                # Scroll para cargar resultados (lazy load)
                await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                await page.wait_for_timeout(1000)

                # Intentar esperar bloque de resultados (opcional - puede no existir si no hay resultados)
                try:
                    await page.wait_for_selector('[data-icms-list="1"]', timeout=5000)
                except:
                    # No hay resultados, pero la búsqueda fue exitosa
                    pass


            # INTENTOS
            last_exception = None
            for intento in range(1, RETRIES + 1):
                try:
                    await _real_search()

                    # Si llegamos aquí, la búsqueda fue exitosa (aunque no haya resultados)
                    success = True

                    # Extraer texto de resultados
                    keyword_span = page.locator("[data-icms-searchkeywords]")
                    searched_txt = (await keyword_span.inner_text()).strip().lower()

                    # Contenedor de páginas (resultados buenos) - puede no existir si no hay resultados
                    results_block = page.locator('[data-icms-list="1"]')
                    
                    # Verificar si hay resultados
                    if await results_block.count() > 0:
                        html_block = await results_block.inner_text()

                        if _norm(full_name) in _norm(html_block):
                            score_final = 5
                            mensaje_final = (
                                f"Coincidencia exacta encontrada para '{full_name}'."
                            )
                        else:
                            score_final = 1
                            mensaje_final = (
                                "Se encontraron resultados, pero sin coincidencia exacta."
                            )
                    else:
                        # No hay resultados pero la búsqueda fue exitosa
                        score_final = 1
                        mensaje_final = "No se encontraron resultados para la búsqueda."

                    break

                except Exception as e:
                    last_exception = e
                    print(f"⚠️ Intento {intento}/{RETRIES} fallido: {str(e)[:100]}")
                    if intento == RETRIES:
                        # No re-lanzar, continuar a captura y guardar error
                        mensaje_final = f"Error en búsqueda: {str(e)[:200]}"
                        success = False
                    else:
                        await page.wait_for_timeout(1000)

            # 📸 ────────── CAPTURA FULL PAGE GRANDE ─────────────
            screenshot_captured = False
            try:
                # ⚠️ PASO 1: Cambiar viewport PRIMERO (antes de que Angular reflow)
                await page.set_viewport_size({"width": 1920, "height": 2400})
                await page.wait_for_timeout(500)

                # PASO 2: Scroll para cargar lazy-loading
                await page.evaluate("window.scrollTo(0, 0)")
                await page.wait_for_timeout(300)
                
                await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                await page.wait_for_timeout(800)

                # PASO 3: Volver a top para captura limpia
                await page.evaluate("window.scrollTo(0, 0)")
                await page.wait_for_timeout(300)

                # PASO 4: Capturar full_page (ahora SÍ debería ser grande)
                print(f"📸 Capturando en {absolute_png}...")
                await page.screenshot(path=absolute_png, full_page=True)
                screenshot_captured = True
                print(f"✅ Screenshot capturado exitosamente")

            except Exception as e:
                print(f"❌ Error screenshot FULL PAGE: {e}")
                try:
                    # Fallback: captura simple sin full_page
                    print("🔄 Intentando fallback (viewport actual)...")
                    await page.screenshot(path=absolute_png, full_page=False)
                    screenshot_captured = True
                    print(f"✅ Fallback screenshot capturado")
                except Exception as e2:
                    print(f"❌ Fallback también falló: {e2}")

            finally:
                # Cerrar contexto y navegador correctamente
                try:
                    await context.close()
                except Exception:
                    pass
                try:
                    await navegador.close()
                except Exception:
                    pass
                navegador = None

        # Guardar resultado
        # Si se logró capturar screenshot, marcar como Validada aunque haya error
        estado_resultado = "Validada" if screenshot_captured else ("Validada" if success else "Sin Validar")
        await sync_to_async(Resultado.objects.create)(
            consulta_id=consulta_id,
            fuente=fuente_obj,
            score=score_final,
            estado=estado_resultado,
            mensaje=mensaje_final,
            archivo=relative_png if screenshot_captured else "",  # Solo si se capturó
        )

    except Exception as e:
        try:
            await sync_to_async(Resultado.objects.create)(
                consulta_id=consulta_id, fuente=fuente_obj,
                score=1, estado="Sin Validar",
                mensaje=str(e), archivo=""
            )
        finally:
            try:
                if navegador is not None:
                    await navegador.close()
            except Exception:
                pass