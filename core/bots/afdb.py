# core/bots/afdb.py
import os
import re
import json
import asyncio
import traceback
import random
from datetime import datetime

from django.conf import settings
from asgiref.sync import sync_to_async
from playwright.async_api import async_playwright

from core.models import Resultado, Fuente

# --- Solver (CapSolver) ---
import capsolver
from decouple import config
capsolver.api_key = config('CAPTCHA_TOKEN', default="")

def resolver_captcha_v2_sync(url, sitekey):
    # debug: imprime la clave (solo en entorno controlado)
    print("CAPSOLVER KEY (len):", len(config('CAPTCHA_TOKEN', default="")))
    solution = capsolver.solve({
        "type": "ReCaptchaV2TaskProxyLess",
        "websiteURL": url,
        "websiteKey": sitekey,
    })
    # debug: volcar respuesta completa
    print("capsolver response:", solution)
    return solution.get('gRecaptchaResponse') or solution.get('token') or ""

async def resolver_captcha_v2(url, sitekey):
    return await asyncio.to_thread(resolver_captcha_v2_sync, url, sitekey)

def resolver_capsolver_turnstile_sync(url, sitekey):
    print("CAPSOLVER KEY (len):", len(config('CAPTCHA_TOKEN', default="")))
    solution = capsolver.solve({
        "type": "TurnstileTaskProxyLess",
        "websiteURL": url,
        "websiteKey": sitekey,
    })
    print("capsolver turnstile response:", solution)
    return solution.get('token') or ""

async def resolver_capsolver_turnstile(url, sitekey):
    return await asyncio.to_thread(resolver_capsolver_turnstile_sync, url, sitekey)
# --- end solver ---

URL = "https://www.afdb.org/en"
NOMBRE_SITIO = "afdb"

SEARCH_INPUT = "#edit-search-block-form--2"
VIEW_EMPTY   = ".view-empty"
ROW_SEL      = ".views-row"
TITLE_SEL    = ".views-field-title"
BODY_SEL     = ".views-field-body"
PATH_SEL     = ".views-field-path"

NAV_TIMEOUT_MS = 120_000
WAIT_IDLE_MS   = 6_000
WAIT_AFTER_MS  = 1_000
MANUAL_WAIT_MAX = 300
MANUAL_POLL_INTERVAL = 5

async def _mover_mouse_aleatorio(page):
    try:
        box = await page.evaluate("""() => {
            return {width: window.innerWidth, height: window.innerHeight};
        }""")
        for _ in range(5):
            x = random.randint(0, box['width'] - 1)
            y = random.randint(0, box['height'] - 1)
            await page.mouse.move(x, y)
            await asyncio.sleep(random.uniform(0.1, 0.4))
    except Exception:
        pass

def _norm(s: str) -> str:
    s = (s or "").strip()
    s = re.sub(r"\s+", " ", s)
    return s.upper()

async def _save_screenshot_safe(page, path):
    try:
        await page.screenshot(path=path, full_page=True)
    except Exception:
        try:
            await page.screenshot(path=path, full_page=False)
        except Exception:
            pass

async def _page_shows_challenge(page) -> bool:
    try:
        content = await page.content()
        low = content.lower()
        if "verify you are human" in low or "needs to review the security of your connection" in low:
            return True
        iframe = await page.query_selector("iframe[src*='captcha'], iframe[src*='recaptcha'], iframe[src*='turnstile'], iframe[src*='cloudflare']")
        if iframe:
            return True
    except Exception:
        pass
    return False

async def _extract_sitekey_from_iframe(page, debug=False):
    try:
        iframe = await page.query_selector("iframe[src*='recaptcha'], iframe[src*='turnstile'], iframe[src*='cloudflare'], iframe[src*='captcha']")
        if iframe:
            src = await iframe.get_attribute("src") or ""
            if debug: print("iframe src:", src[:300])
            m = re.search(r"(?:k|sitekey)=([^&'\"]+)", src)
            if m:
                return m.group(1)
            sk = await iframe.get_attribute("data-sitekey")
            if sk:
                return sk
    except Exception:
        pass
    # fallback: buscar en DOM scripts o elementos con data-sitekey
    try:
        possible = await page.evaluate(
            """() => {
                const el = document.querySelector('[data-sitekey], .g-recaptcha, div.g-recaptcha, div.cf-turnstile');
                if (el) {
                    if (el.getAttribute) return el.getAttribute('data-sitekey') || null;
                    if (el.dataset && el.dataset.sitekey) return el.dataset.sitekey || null;
                }
                const scripts = Array.from(document.scripts).map(s => s.textContent).join('\\n');
                const m = scripts.match(/sitekey\\s*[:=]\\s*['"]([^'"]+)['"]/i);
                return m ? m[1] : null;
            }"""
        )
        if possible:
            return possible
    except Exception:
        pass
    return None

async def _inject_token_generic(page, token: str, debug=False):
    try:
        if debug: print("Inyectando token en textareas estándar...")
        await page.evaluate(
            """(token) => {
                // ReCaptcha
                let ta = document.querySelector('textarea#g-recaptcha-response, textarea[name="g-recaptcha-response"]');
                if (!ta) {
                    ta = document.createElement('textarea');
                    ta.name = 'g-recaptcha-response';
                    ta.id = 'g-recaptcha-response';
                    ta.style.display = 'none';
                    document.body.appendChild(ta);
                }
                ta.value = token;
                ta.dispatchEvent(new Event('input', {bubbles:true}));
                ta.dispatchEvent(new Event('change', {bubbles:true}));

                // Turnstile
                let ta2 = document.querySelector('textarea#cf-turnstile-response, textarea[name="cf-turnstile-response"]');
                if (!ta2) {
                    ta2 = document.createElement('textarea');
                    ta2.name = 'cf-turnstile-response';
                    ta2.id = 'cf-turnstile-response';
                    ta2.style.display = 'none';
                    document.body.appendChild(ta2);
                }
                ta2.value = token;
                ta2.dispatchEvent(new Event('input', {bubbles:true}));
                ta2.dispatchEvent(new Event('change', {bubbles:true}));

                // Intentar disparar callbacks comunes
                try {
                    if (window.grecaptcha && window.grecaptcha.getResponse) {
                        // no forzamos render, solo intentamos si hay callback global
                    }
                } catch(e) {}
            }""",
            token
        )
        await asyncio.sleep(0.8)
        return True
    except Exception:
        return False

async def _attempt_resolve_with_capsolver(page, debug=False):
    try:
        sitekey = await _extract_sitekey_from_iframe(page, debug=debug)
        if not sitekey:
            if debug: print("No se pudo determinar sitekey.")
            return False

        url = page.url
        if debug: print(f"Sitekey detectado: {sitekey} url: {url}")

        # elegir resolver según tipo (intentar turnstile primero si detectado)
        # Intento Turnstile
        token = await resolver_capsolver_turnstile(url, sitekey)
        if token:
            if debug: print("Token Turnstile recibido:", token[:20], "...")
            injected = await _inject_token_generic(page, token, debug=debug)
            if not injected:
                if debug: print("Fallo inyección Turnstile.")
                return False
            # intentar disparar submit si hay formulario
            try:
                await page.evaluate("""() => { const f = document.querySelector('form'); if(f) f.submit(); }""")
            except Exception:
                pass
            await asyncio.sleep(2)
            # verificar si desafío desapareció
            has = await _page_shows_challenge(page)
            return not has

        # si no hubo token Turnstile, intentar ReCaptcha V2
        token2 = await resolver_captcha_v2(url, sitekey)
        if token2:
            if debug: print("Token ReCaptcha recibido:", token2[:20], "...")
            injected = await _inject_token_generic(page, token2, debug=debug)
            if not injected:
                if debug: print("Fallo inyección ReCaptcha.")
                return False
            try:
                await page.evaluate("""() => { const f = document.querySelector('form'); if(f) f.submit(); }""")
            except Exception:
                pass
            await asyncio.sleep(2)
            has = await _page_shows_challenge(page)
            return not has

        if debug: print("El solver no devolvió token para ninguno de los tipos.")
        return False

    except Exception:
        if debug:
            traceback.print_exc()
    return False

async def _wait_for_manual_resolution(page, abs_png, absolute_folder, timeout_seconds=MANUAL_WAIT_MAX, poll_interval=MANUAL_POLL_INTERVAL, debug=False):
    try:
        await _save_screenshot_safe(page, abs_png)
        try:
            html = await page.content()
            diag_path = os.path.join(absolute_folder, "diagnostic.html")
            with open(diag_path, "w", encoding="utf-8") as f:
                f.write(html)
        except Exception:
            pass

        if debug:
            print(f"Desafío detectado. Captura guardada en {abs_png}. Esperando resolución manual hasta {timeout_seconds}s.")

        waited = 0
        while waited < timeout_seconds:
            await asyncio.sleep(poll_interval)
            waited += poll_interval
            try:
                if not await _page_shows_challenge(page):
                    if debug:
                        print("Desafío aparentemente resuelto manualmente.")
                    return True
            except Exception:
                pass
        return False
    except Exception:
        return False

# ----------------- BOT principal -----------------
async def consultar_afdb(consulta_id: int, nombre: str, apellido: str, debug: bool = False):
    try:
        fuente = await sync_to_async(Fuente.objects.get)(nombre=NOMBRE_SITIO)
    except Exception as e:
        await sync_to_async(Resultado.objects.create)(
            consulta_id=consulta_id, fuente=None, score=0,
            estado="Sin validar", mensaje=f"No se encontró la Fuente '{NOMBRE_SITIO}': {e}", archivo=""
        )
        return

    full_name_raw = f"{(nombre or '').strip()} {(apellido or '').strip()}".strip()
    relative_folder = os.path.join("resultados", str(consulta_id))
    absolute_folder = os.path.join(settings.MEDIA_ROOT, relative_folder)
    os.makedirs(absolute_folder, exist_ok=True)

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    png_name = f"{NOMBRE_SITIO}_{consulta_id}_{ts}.png"
    abs_png  = os.path.join(absolute_folder, png_name)
    rel_png  = os.path.join(relative_folder, png_name).replace("\\", "/")

    browser = None
    try:
        async with async_playwright() as p:
            USER_AGENTS = [
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36",
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
            ]
            storage_state_path = os.getenv("AFDB_STORAGE_STATE")  # Opcional, para perfil persistente
            browser = await p.chromium.launch(

                headless=True,  # Ejecuta en modo visible para evitar detección
                args=[
                    "--no-sandbox",
                    "--disable-blink-features=AutomationControlled",
                    "--disable-dev-shm-usage",
                    "--window-position=2000,0"
                ]
            )
            ctx_args = {
                "viewport": {"width": 1920, "height": 1080},
                "locale": "es-CO",
                "user_agent": random.choice(USER_AGENTS),
                "extra_http_headers": {
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
                    "Accept-Language": "es-CO,es;q=0.9,en;q=0.8",
                    "Referer": "https://www.google.com/",
                    "DNT": "1",
                },
            }
            if storage_state_path:
                ctx_args["storage_state"] = storage_state_path
            ctx = await browser.new_context(**ctx_args)
            page = await ctx.new_page()
            # Simula movimientos humanos antes de interactuar
            await _mover_mouse_aleatorio(page)

            # navegar
            try:
                response = await page.goto(URL, wait_until="domcontentloaded", timeout=NAV_TIMEOUT_MS)
                if debug:
                    print("Goto response status:", response.status if response else None)
            except Exception:
                if debug:
                    traceback.print_exc()

            try:
                await page.wait_for_load_state("networkidle", timeout=WAIT_IDLE_MS)
            except Exception:
                if debug:
                    print("networkidle no alcanzado, continuando...")

            # detectar Turnstile/Recaptcha
            if await _page_shows_challenge(page):
                if debug: print("Desafío detectado al cargar la página.")
                # intentar resolver con capsovler
                solved = await _attempt_resolve_with_capsolver(page, debug=debug)
                if solved:
                    if debug: print("Solver indicó que el desafío fue resuelto.")
                else:
                    if debug: print("Solver no resolvió el desafío. Guardando evidencia y esperando intervención manual.")
                    await _save_screenshot_safe(page, abs_png)
                    # guardar HTML diagnóstico
                    try:
                        html = await page.content()
                        diag_path = os.path.join(absolute_folder, f"security_{ts}.html")
                        with open(diag_path, "w", encoding="utf-8") as f:
                            f.write(html)
                    except Exception:
                        pass
                    manual_ok = await _wait_for_manual_resolution(page, abs_png, absolute_folder, timeout_seconds=MANUAL_WAIT_MAX, poll_interval=MANUAL_POLL_INTERVAL, debug=debug)
                    if not manual_ok:
                        await sync_to_async(Resultado.objects.create)(
                            consulta_id=consulta_id, fuente=fuente, score=0,
                            estado="Sin validar",
                            mensaje="Apareció un desafío (Cloudflare/Turnstile/Recaptcha) y no se resolvió en el tiempo de espera",
                            archivo=rel_png if os.path.exists(abs_png) else ""
                        )
                        await ctx.close(); await browser.close()
                        return

            # buscar input de búsqueda
            search_selector = SEARCH_INPUT
            alt_selectors = ["input[type=search]", "input[name=search_block_form]"]
            found = False
            for sel in [search_selector] + alt_selectors:
                try:
                    await page.wait_for_selector(sel, state="visible", timeout=5000)
                    search_selector = sel
                    found = True
                    if debug: print("Selector de búsqueda encontrado:", sel)
                    break
                except Exception:
                    if debug: print("No encontrado selector:", sel)
            if not found:
                await _save_screenshot_safe(page, abs_png)
                await sync_to_async(Resultado.objects.create)(
                    consulta_id=consulta_id, fuente=fuente, score=0,
                    estado="Sin validar", mensaje="No se encontró el campo de búsqueda en la página", archivo=rel_png if os.path.exists(abs_png) else ""
                )
                await ctx.close(); await browser.close()
                return

            # escribir y buscar
            try:
                await page.fill(search_selector, full_name_raw)
                await page.keyboard.press("Enter")
            except Exception:
                if debug: traceback.print_exc()

            try:
                await page.wait_for_url("**/search/**", timeout=20000)
            except Exception:
                if debug: print("wait_for_url no se cumplió, continuando...")

            try:
                await page.wait_for_selector(f"{VIEW_EMPTY}, {ROW_SEL}", timeout=20000)
            except Exception:
                if debug: print("No apareció VIEW_EMPTY ni ROW_SEL en el timeout, esperando un poco más")
                await page.wait_for_timeout(WAIT_AFTER_MS)

            try:
                nores = await page.locator(VIEW_EMPTY).count() > 0
            except Exception:
                nores = False

            if nores:
                mensaje = "Unfortunately your search did not return any results."
                score = 1
                try:
                    await page.evaluate("window.scrollTo(0, 0)")
                except Exception:
                    pass
                try:
                    await _save_screenshot_safe(page, abs_png)
                except Exception:
                    pass
                await sync_to_async(Resultado.objects.create)(
                    consulta_id=consulta_id, fuente=fuente, score=score,
                    estado="Validado", mensaje=mensaje, archivo=rel_png if os.path.exists(abs_png) else ""
                )
                await ctx.close(); await browser.close()
                return

            # revisar filas
            needle = _norm(full_name_raw)
            exact_hit = False
            rows = page.locator(ROW_SEL)
            try:
                n = await rows.count()
            except Exception:
                n = 0

            for i in range(n):
                row = rows.nth(i)
                async def safe_text(loc):
                    try:
                        el = row.locator(loc).first
                        if await el.count():
                            return (await el.inner_text()) or ""
                    except Exception:
                        pass
                    return ""
                title = await safe_text(TITLE_SEL)
                body  = await safe_text(BODY_SEL)
                pathv = await safe_text(PATH_SEL)
                blob = _norm(" ".join([title, body, pathv]))
                if needle and needle in blob:
                    exact_hit = True
                    break

            mensaje = "Se encontraron coincidencias." if exact_hit else "No hay coincidencias."
            score = 1
            try:
                await page.evaluate("window.scrollTo(0, 0)")
            except Exception:
                pass
            try:
                await _save_screenshot_safe(page, abs_png)
            except Exception:
                pass

            await sync_to_async(Resultado.objects.create)(
                consulta_id=consulta_id, fuente=fuente, score=score,
                estado="Validado", mensaje=mensaje, archivo=rel_png if os.path.exists(abs_png) else ""
            )

            await ctx.close(); await browser.close()

    except Exception as e:
        try:
            if browser:
                await browser.close()
        except Exception:
            pass
        err = "".join(traceback.format_exception_only(type(e), e)).strip()
        await sync_to_async(Resultado.objects.create)(
            consulta_id=consulta_id, fuente=None, score=0,
            estado="Sin validar", mensaje=err, archivo=""
        )