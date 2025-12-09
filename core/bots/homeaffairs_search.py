# bots/homeaffairs_search.py
import os
import re
import random
import urllib.parse
import unicodedata
import asyncio
import json
from datetime import datetime

from django.conf import settings
from asgiref.sync import sync_to_async
from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeoutError

from core.models import Resultado, Fuente

NOMBRE_SITIO = "homeaffairs_search"
URL_SEARCH = "https://www.homeaffairs.gov.au/sitesearch?k={q}"
GOTO_TIMEOUT_MS = 180_000

# Selectores (UI fallback)
SEL_UI_INPUT = "input[name='search']"
SEL_UI_BUTTON = "button.search-submit"

# Selectores de resultado
SEL_NORES_WRAPPER = "div.search-results-list"
SEL_NORES_H4      = f"{SEL_NORES_WRAPPER} > h4"
SEL_RESULT_ITEM   = "ha-result-item"
SEL_RESULT_TITLE  = "ha-result-item a"   # fallback, el primer <a> dentro del item

# Indicadores de bloqueo en HTML/texto
BLOCK_INDICATORS = [
    "access denied", "forbidden", "service unavailable", "error 403", "error 503",
    "cloudflare", "edge", "akamai", "reference #", "access denied by"
]

def _norm(s: str) -> str:
    """Normaliza para comparación exacta 'humana': minúsculas, sin diacríticos, espacios comprimidos."""
    s = (s or "").strip().lower()
    s = "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn")
    s = re.sub(r"\s+", " ", s)
    return s

def _is_blocked_html(html: str) -> bool:
    """Detecta si el HTML contiene indicadores de bloqueo/Access Denied."""
    if not html:
        return False
    lower = html.lower()
    # Detectar variantes de 'No results' usando regex y frases comunes
    no_results_patterns = [
        r"no\s+results",
        r"unfortunately\s+there\s+were\s+no\s+results",
        r"no\s+hay\s+resultados",  # español
        r"sin\s+resultados",        # español
        r"aucun\s+r\u00e9sultat",  # francés
        r"keine\s+ergebnisse",      # alemán
    ]
    for pat in no_results_patterns:
        if re.search(pat, lower, re.IGNORECASE):
            return False
    for ind in BLOCK_INDICATORS:
        if ind in lower:
            return True
    return False

async def _goto_with_retries(page, url, attempts=3, base_delay=1.0, timeout=GOTO_TIMEOUT_MS):
    """Intentar page.goto con reintentos exponenciales; devuelve response o lanza."""
    last_exc = None
    for i in range(1, attempts + 1):
        try:
            resp = await page.goto(url, timeout=timeout)
            return resp
        except Exception as e:
            last_exc = e
            print(f"[RGM][WARN] goto intento {i} falló: {e}")
            if i < attempts:
                await asyncio.sleep(base_delay * (2 ** (i - 1)))
    raise last_exc

async def _wait_for_networkidle_with_retries(page, retries=3, base_delay=1.0, timeout=45000):
    for attempt in range(1, retries + 1):
        try:
            await page.wait_for_load_state("networkidle", timeout=timeout)
            return True
        except Exception as e:
            print(f"[RGM][WARN] networkidle intento {attempt} falló: {e}")
            if attempt < retries:
                await asyncio.sleep(base_delay * (2 ** (attempt - 1)))
    return False

async def _save_debug_artifacts(page, absolute_folder, prefix):
    """Guarda HTML y screenshot con prefijo y timestamp; devuelve rutas."""
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    png_path = os.path.join(absolute_folder, f"{prefix}_{ts}.png")
    html_path = os.path.join(absolute_folder, f"{prefix}_{ts}.html")
    try:
        await page.screenshot(path=png_path, full_page=True)
        print(f"[RGM] DEBUG: Screenshot guardado en: {png_path}")
    except Exception as e:
        print(f"[RGM][WARN] No se pudo guardar screenshot debug: {e}")
        png_path = ""
    try:
        html_content = await page.content()
        with open(html_path, "w", encoding="utf-8") as f:
            f.write(html_content)
        print(f"[RGM] DEBUG: HTML guardado en: {html_path}")
    except Exception as e:
        print(f"[RGM][WARN] No se pudo guardar HTML debug: {e}")
        html_path = ""
    return html_path, png_path

async def consultar_homeaffairs_search(consulta_id: int, nombre: str, apellido: str, headless=False):
    """
    Flujo robusto para consultar homeaffairs.gov.au:
    - Intenta URL directa en modo headless (por defecto).
    - Si recibe bloqueo (403 / Access Denied) o resultado inesperado, ejecuta una comparación headful.
    - Guarda artefactos (HTML + screenshots) para diagnóstico.
    - No intenta evadir bloqueos avanzados; marca la consulta para revisión humana si está bloqueada.
    - Importante: NO guarda como 'archivo' la captura de una página de bloqueo. Solo guarda captura cuando la página contiene resultados válidos.
    """
    navegador = None
    full_name = f"{(nombre or '').strip()} {(apellido or '').strip()}".strip()
    print(f"[RGM] Iniciando consulta HomeAffairs: consulta_id={consulta_id} nombre='{full_name}' headless={headless}")

    # 1) Fuente
    try:
        fuente_obj = await sync_to_async(Fuente.objects.get)(nombre=NOMBRE_SITIO)
        print(f"[RGM] Fuente encontrada id={getattr(fuente_obj, 'id', None)}")
    except Exception as e:
        print(f"[RGM][ERROR] No se encontró la Fuente '{NOMBRE_SITIO}': {e}")
        await sync_to_async(Resultado.objects.create)(
            consulta_id=consulta_id, fuente=None, score=1,
            estado="Sin Validar",
            mensaje=f"No se encontró la Fuente '{NOMBRE_SITIO}': {e}",
            archivo=""
        )
        return

    if not full_name:
        print("[RGM][ERROR] Nombre y/o apellido vacíos")
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
    html_name = f"{NOMBRE_SITIO}_{safe_name}_{ts}.html"
    absolute_png = os.path.join(absolute_folder, png_name)
    absolute_html = os.path.join(absolute_folder, html_name)
    relative_png = os.path.join(relative_folder, png_name).replace("\\", "/")
    relative_html = os.path.join(relative_folder, html_name).replace("\\", "/")

    mensaje_final = "No hay coincidencias."
    score_final = 1  # por defecto 1 (sólo sube a 5 si hay match exacto)
    success = False
    last_error = None

    norm_query = _norm(full_name)


    try:
        # Lista de proxies para rotar
        PROXY_LIST = os.environ.get("BOT_PROXY_LIST", "").split(",") if os.environ.get("BOT_PROXY_LIST") else []
        proxy_idx = random.randint(0, len(PROXY_LIST)-1) if PROXY_LIST else None
        proxy_to_use = PROXY_LIST[proxy_idx] if proxy_idx is not None else os.environ.get("BOT_PROXY")  
        async with async_playwright() as p:
            USER_AGENTS = [
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:122.0) Gecko/20100101 Firefox/122.0",
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0",
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.0 Safari/605.1.15",
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/15.0 Safari/605.1.15"
            ]
            ua = random.choice(USER_AGENTS)
            extra_headers = [
                {
                    "Accept-Language": "en-AU,en;q=0.9",
                    "sec-ch-ua-platform": "Windows",
                    "Referer": "https://www.homeaffairs.gov.au/",
                    "Cache-Control": "max-age=0",
                    "Upgrade-Insecure-Requests": "1",
                    "DNT": "1",
                    "Connection": "keep-alive",
                    "Pragma": "no-cache",
                    "Sec-Fetch-Dest": "document",
                    "Sec-Fetch-Mode": "navigate",
                    "Sec-Fetch-Site": "same-origin",
                    "Sec-Fetch-User": "?1"
                },
                {
                    "Accept-Language": "en-US,en;q=0.8",
                    "Referer": "https://www.google.com/",
                    "Cache-Control": "no-cache",
                    "Upgrade-Insecure-Requests": "1",
                    "DNT": "1",
                    "Connection": "keep-alive",
                    "Pragma": "no-cache"
                }
            ]
            headers_to_use = random.choice(extra_headers)
            launch_args = [
                "--no-sandbox",
                "--disable-dev-shm-usage",
                "--disable-blink-features=AutomationControlled",
                "--window-size=1400,900",
                "--window-position=-2000,0"  # mueve la ventana fuera de la pantalla
            ]
            launch_kwargs = {"headless": headless, "args": launch_args}
            if proxy_to_use:
                launch_kwargs["proxy"] = {"server": proxy_to_use}
            navegador = await p.chromium.launch(**launch_kwargs)
            viewport_w = random.choice([1280, 1366, 1400, 1440, 1600])
            viewport_h = random.choice([720, 768, 800, 900, 1024])
            timezone = random.choice(["Australia/Sydney", "America/Bogota", "Europe/Madrid", "America/New_York"])
            context = await navegador.new_context(
                viewport={"width": viewport_w, "height": viewport_h},
                user_agent=ua,
                locale="en-AU",
                timezone_id=timezone,
                accept_downloads=True
            )
            page = await context.new_page()
            await page.set_extra_http_headers(headers_to_use)
            try:
                await page.add_init_script("""() => {
                    Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
                    Object.defineProperty(navigator, 'languages', {get: () => ['en-US','en']});
                    Object.defineProperty(navigator, 'plugins', {get: () => [1,2,3,4,5]});
                    Object.defineProperty(navigator, 'platform', {get: () => 'Win32'});
                    Object.defineProperty(navigator, 'hardwareConcurrency', {get: () => 8});
                    Object.defineProperty(navigator, 'deviceMemory', {get: () => 8});
                    window.chrome = { runtime: {} };
                    window.outerWidth = window.innerWidth + Math.floor(Math.random()*10);
                    window.outerHeight = window.innerHeight + Math.floor(Math.random()*10);
                    window.screenX = Math.floor(Math.random()*100);
                    window.screenY = Math.floor(Math.random()*100);
                    window.screenTop = 0;
                    window.screenLeft = 0;
                    const toDataURL = HTMLCanvasElement.prototype.toDataURL;
                    HTMLCanvasElement.prototype.toDataURL = function() {
                        return "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAUA";
                    };
                    const getParameter = WebGLRenderingContext.prototype.getParameter;
                    WebGLRenderingContext.prototype.getParameter = function(param) {
                        if (param === 37445) { return "Intel Inc."; }
                        if (param === 37446) { return "Intel Iris OpenGL Engine"; }
                        return getParameter.apply(this, arguments);
                    };
                    const originalQuery = window.navigator.permissions.query;
                    window.navigator.permissions.query = (parameters) => (
                        parameters.name === 'notifications' ? Promise.resolve({ state: Notification.permission }) : originalQuery(parameters)
                    );
                }""")
            except Exception:
                pass
            page.on("console", lambda msg: print(f"[RGM][PAGE CONSOLE] {msg.type}: {msg.text}"))
            page.on("response", lambda resp: print(f"[RGM][RESPONSE] {resp.status} {resp.url}"))
            # Simulación de acciones humanas mejorada
            acciones = [
                "scroll",
                "esperar",
                "teclear",
                "mover_mouse"
            ]
            for _ in range(random.randint(2, 5)):
                accion = random.choice(acciones)
                if accion == "scroll":
                    await page.evaluate("window.scrollBy(0, Math.floor(Math.random()*400))")
                elif accion == "esperar":
                    await asyncio.sleep(random.uniform(1, 4))
                elif accion == "teclear":
                    await page.keyboard.press(random.choice(["Tab", "ArrowDown", "ArrowUp"]))
                elif accion == "mover_mouse":
                    await page.mouse.move(random.randint(10, viewport_w-10), random.randint(10, viewport_h-10))
            # Navegar a la página principal de búsqueda
            print(f"[RGM] Intentando URL principal: https://www.homeaffairs.gov.au/sitesearch (headless={headless})")
            resp = None
            try:
                resp = await page.goto("https://www.homeaffairs.gov.au/sitesearch", timeout=GOTO_TIMEOUT_MS)
                await page.wait_for_load_state("domcontentloaded", timeout=15000)
                await asyncio.sleep(1.0 + random.random() * 1.0)
            except Exception as e:
                print(f"[RGM][WARN] Error en goto página principal: {e}")
                last_error = f"Error navegando a la página principal: {e}"
            # Escribir el nombre en el input y hacer click en el botón de búsqueda
            try:
                await page.fill(SEL_UI_INPUT, full_name)
                await asyncio.sleep(0.5 + random.random() * 0.5)
                await page.click(SEL_UI_BUTTON)
                print(f"[RGM] Búsqueda enviada: '{full_name}'")
                await page.wait_for_load_state("networkidle", timeout=20000)
                await asyncio.sleep(1.0 + random.random() * 1.0)
            except Exception as e:
                print(f"[RGM][WARN] Error al simular búsqueda: {e}")
                last_error = f"Error al simular búsqueda: {e}"
            resp_status = None
            resp_headers = {}
            if resp:
                try:
                    resp_status = resp.status
                    try:
                        resp_headers = await resp.all_headers()
                    except Exception:
                        resp_headers = getattr(resp, "headers", {}) or {}
                    print(f"[RGM] response status = {resp_status}")
                    print(f"[RGM] response headers = {json.dumps(resp_headers)}")
                except Exception as e:
                    print(f"[RGM][WARN] No se pudieron leer headers/estado: {e}")
            await _wait_for_networkidle_with_retries(page, retries=3, base_delay=1.0, timeout=45000)
            html_path, png_path = await _save_debug_artifacts(page, absolute_folder, "after_goto_headless")
            print(f"[RGM] Guardados artefactos: HTML={html_path}, PNG={png_path}")
            blocked = False
            if resp_status == 403:
                print("[RGM][WARN] La respuesta fue 403 (Access Denied).")
                blocked = True
            else:
                try:
                    content = await page.content()
                    if _is_blocked_html(content):
                        print("[RGM][WARN] Indicadores de bloqueo detectados en HTML")
                        blocked = True
                except Exception:
                    pass
            # Si está bloqueado, guardar la captura PNG si existe
            if blocked:
                archivo_para_bd = ""
                evidencia = []
                if os.path.exists(html_path) and os.path.getsize(html_path) > 0:
                    evidencia.append(relative_html)
                if os.path.exists(png_path) and os.path.getsize(png_path) > 0:
                    evidencia.append(relative_png)
                archivo_para_bd = ",".join(evidencia)
                mensaje_final = "Bloqueo detectado. Se adjunta evidencia (HTML/PNG) para diagnóstico."
                last_error = mensaje_final
                await sync_to_async(Resultado.objects.create)(
                    consulta_id=consulta_id, fuente=fuente_obj,
                    score=1,
                    estado="Sin Validar",
                    mensaje=mensaje_final,
                    archivo=archivo_para_bd
                )
                print(f"[RGM] Bloqueo persistente. Artefactos: {archivo_para_bd}")
                try:
                    await navegador.close()
                except Exception:
                    pass
                return
            # Si no está bloqueado, continuar con parseo y guardar captura
            page_for_parse = page

            # A partir de aquí, page_for_parse contiene la página con la que trabajaremos (headless o headful)
            try:
                # 4) Detectar "No results"
                nores_h4 = page_for_parse.locator(SEL_NORES_H4, has_text="No results")
                if await nores_h4.count() > 0 and await nores_h4.first.is_visible():
                    try:
                        wrapper = page_for_parse.locator(SEL_NORES_WRAPPER).first
                        wrapper_txt = (await wrapper.inner_text()).strip()
                        if wrapper_txt:
                            mensaje_final = wrapper_txt
                        else:
                            mensaje_final = (
                                "No results\n"
                                f"Unfortunately there were no results for {full_name}\n"
                                "Try refining your search with some different key words or looking under a different function"
                            )
                    except Exception:
                        mensaje_final = (
                            "No results\n"
                            f"Unfortunately there were no results for {full_name}\n"
                            "Try refining your search with some different key words or looking under a different function"
                        )
                    # Guardar captura solo si la página NO está bloqueada
                    content_now = await page_for_parse.content()
                    if not _is_blocked_html(content_now):
                        try:
                            await page_for_parse.screenshot(path=absolute_png, full_page=True)
                            with open(absolute_html, "w", encoding="utf-8") as f:
                                f.write(content_now)
                        except Exception:
                            pass
                        success = True
                        # Marcar como consulta válida aunque no haya coincidencias
                        estado_bd = "Validada"
                        mensaje_final = "Consulta realizada, sin coincidencias."
                    else:
                        # No guardar captura de bloqueo
                        success = True  # consideramos la consulta procesada, pero sin archivo adjunto
                        estado_bd = "Validada"
                        mensaje_final = "Consulta realizada, sin coincidencias. (Página sin resultados, pero no bloqueada)"
                else:
                    # 5) Hay resultados -> iterar <ha-result-item>
                    items = page_for_parse.locator(SEL_RESULT_ITEM)
                    n = await items.count()
                    print(f"[RGM] Result items count: {n}")
                    exact_hit = False

                    for i in range(n):
                        item = items.nth(i)
                        title_text = ""
                        try:
                            if await item.locator(SEL_RESULT_TITLE).count() > 0:
                                title_text = (await item.locator(SEL_RESULT_TITLE).first.inner_text(timeout=3_000)).strip()
                        except Exception:
                            title_text = ""
                        if not title_text:
                            try:
                                title_text = (await item.inner_text(timeout=2_000)).strip()
                            except Exception:
                                title_text = ""
                        print(f"[RGM] Item {i} title (trunc): {title_text[:120]!r}")
                        if title_text and _norm(title_text) == norm_query:
                            exact_hit = True
                            print(f"[RGM] Coincidencia exacta encontrada en item {i}")
                            break

                    # Antes de guardar captura, verificar que la página no sea una página de bloqueo
                    content_now = await page_for_parse.content()
                    if _is_blocked_html(content_now):
                        # Guardar HTML para diagnóstico
                        try:
                            with open(absolute_html, "w", encoding="utf-8") as f:
                                f.write(content_now)
                        except Exception:
                            pass
                        last_error = "La página resultante parece ser una página de bloqueo; se adjunta HTML para diagnóstico."
                        success = False
                    else:
                        try:
                            await page_for_parse.screenshot(path=absolute_png, full_page=True)
                            with open(absolute_html, "w", encoding="utf-8") as f:
                                f.write(content_now)
                        except Exception:
                            pass
                        if exact_hit:
                            score_final = 5
                            mensaje_final = f"Coincidencia exacta con el nombre buscado: '{full_name}'."
                        else:
                            score_final = 1
                            mensaje_final = "Se encontraron resultados, pero sin coincidencia exacta del nombre."
                        success = True

            except Exception as e:
                print(f"[RGM][WARN] Error procesando resultados: {e}")
                last_error = str(e)

            # Cerrar navegador
            try:
                await navegador.close()
            except Exception:
                pass
            navegador = None

        # Persistir Resultado final
        # Guardar la captura aunque la página esté bloqueada, marcando como Sin Validar si es necesario
        es_bloqueo = False
        try:
            if os.path.exists(absolute_png):
                html_check = await page_for_parse.content()
                es_bloqueo = _is_blocked_html(html_check)
        except Exception:
            es_bloqueo = False

        archivo_para_bd = ""
        # Priorizar PNG como evidencia principal, si existe y tiene tamaño > 0
        if os.path.exists(absolute_png) and os.path.getsize(absolute_png) > 0:
            archivo_para_bd = relative_png
        elif os.path.exists(absolute_html) and os.path.getsize(absolute_html) > 0:
            archivo_para_bd = relative_html
        # Si existe evidencia y la consulta fue exitosa, marcar como 'Validada' y mensaje claro
        if archivo_para_bd and success and not es_bloqueo:
            estado_bd = "Validada"
            mensaje_bd = "Consulta realizada correctamente. Se adjunta evidencia de la búsqueda. " + (mensaje_final or "Sin coincidencias.")
        else:
            # Si ya se definió estado_bd como 'Validada' en el flujo anterior, respetar ese valor
            if 'estado_bd' not in locals():
                estado_bd = "Validada" if success and not es_bloqueo else "Sin Validar"
            mensaje_bd = mensaje_final
            if es_bloqueo:
                mensaje_bd = "La página parece estar bloqueada o no muestra resultados. Se adjunta evidencia (HTML/PNG) para diagnóstico. " + (mensaje_final or "Bloqueo detectado.")
        await sync_to_async(Resultado.objects.create)(
            consulta_id=consulta_id, fuente=fuente_obj,
            score=score_final if success and not es_bloqueo else 1,
            estado=estado_bd,
            mensaje=mensaje_bd,
            archivo=archivo_para_bd
        )
        print(f"[RGM] Resultado guardado: score={score_final} archivo={archivo_para_bd} estado={estado_bd}")

    except Exception as e:
        print(f"[RGM][ERROR] Excepción general: {e}")

        try:
            await sync_to_async(Resultado.objects.create)(
                consulta_id=consulta_id, fuente=fuente_obj,
                score=1,
                estado="Sin Validar",
                mensaje=str(e),
                archivo=""
            )
            print("[RGM] Resultado de error guardado en BD")
        except Exception as db_exc:
            print(f"[RGM][FATAL] No se pudo crear Resultado en BD: {db_exc}")
        finally:
            try:
                if navegador is not None:
                    await navegador.close()
            except Exception:
                pass
