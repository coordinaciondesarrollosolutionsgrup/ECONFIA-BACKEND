import os
import re
import asyncio
import random
import traceback
from datetime import datetime
from typing import Optional, List
from django.conf import settings
from asgiref.sync import sync_to_async
from playwright.async_api import async_playwright
from django.core.files import File as DjangoFile

from core.models import Resultado, Fuente

URL = "https://www.dea.gov/es/node/11286"
NOMBRE_SITIO = "dea"

_DEA_BLOCK_RE = re.compile(
    r"(Access\s+Denied|You\s+don't\s+have\s+permission|errors\.edgesuite\.net|Reference\s+#)",
    re.IGNORECASE,
)


def _is_blocked_html(html: str, current_url: str) -> bool:
    if not html:
        return False
    if _DEA_BLOCK_RE.search(html):
        return True
    if "errors.edgesuite.net" in (current_url or ""):
        return True
    return False


def _guardar_resultado_adaptativo(
    consulta_id: int,
    fuente_obj,
    score: int,
    estado: str,
    mensaje: str,
    absolute_path: Optional[str],
    relative_path: Optional[str],
):
    resultado = Resultado(
        consulta_id=consulta_id,
        fuente=fuente_obj,
        score=score,
        estado=estado,
        mensaje=mensaje,
    )

    if absolute_path and os.path.exists(absolute_path):
        archivo_attr = getattr(resultado, "archivo", None)
        filename = os.path.basename(absolute_path)
        if archivo_attr is not None and hasattr(archivo_attr, "save"):
            with open(absolute_path, "rb") as f:
                django_file = DjangoFile(f)
                resultado.archivo.save(filename, django_file, save=True)
        else:
            resultado.archivo = relative_path or ""
            resultado.save()
    else:
        resultado.save()

    return resultado


async def _human_type(page, selector, text):
    await page.focus(selector)
    for ch in text:
        await page.keyboard.type(ch, delay=random.randint(50, 160))
    await asyncio.sleep(random.uniform(0.2, 0.6))


async def _human_move_mouse(page, width=1366, height=768):
    steps = random.randint(6, 12)
    for _ in range(steps):
        x = random.randint(int(width * 0.1), int(width * 0.9))
        y = random.randint(int(height * 0.1), int(height * 0.9))
        await page.mouse.move(x, y, steps=random.randint(5, 15))
        await asyncio.sleep(random.uniform(0.05, 0.25))


async def consultar_dea(
    consulta_id: int,
    cedula: str,
    headless: bool = True,
    max_intentos: int = 3,
    proxies: Optional[List[str]] = None,
    user_agents: Optional[List[str]] = None,
    stealth: bool = True,
):
    """
    Consulta DEA por cédula y guarda evidencia.
    - Timeouts reducidos, manejo automático de diálogos y popups.
    - Captura condicional: distinta para 'sin resultados' y 'con resultados'.
    - Parámetros opcionales: proxies (lista), user_agents (lista).
    """
    navegador = None

    try:
        fuente_obj = await sync_to_async(Fuente.objects.get)(nombre=NOMBRE_SITIO)
    except Exception as e:
        await sync_to_async(Resultado.objects.create)(
            consulta_id=consulta_id,
            fuente=None,
            score=0,
            estado="Sin Validar",
            mensaje=f"No se encontró la Fuente '{NOMBRE_SITIO}': {e}",
            archivo="",
        )
        return

    carpeta_rel = os.path.join("resultados", str(consulta_id))
    carpeta_abs = os.path.join(settings.MEDIA_ROOT, carpeta_rel)
    os.makedirs(carpeta_abs, exist_ok=True)

    ts_base = datetime.now().strftime("%Y%m%d_%H%M%S")
    png_name = f"{NOMBRE_SITIO}_{consulta_id}_{ts_base}.png"
    png_abs = os.path.join(carpeta_abs, png_name)
    png_rel = os.path.join(carpeta_rel, png_name).replace("\\", "/")

    cedula = (cedula or "").strip()
    if not cedula:
        await sync_to_async(Resultado.objects.create)(
            consulta_id=consulta_id,
            fuente=fuente_obj,
            score=0,
            estado="Sin Validar",
            mensaje="La cédula llegó vacía.",
            archivo="",
        )
        return

    proxies = proxies or []
    user_agents = user_agents or [
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
    ]

    intento = 0
    while intento < max_intentos:
        intento += 1
        proxy_choice = proxies[(intento - 1) % len(proxies)] if proxies else None
        ua_choice = user_agents[(intento - 1) % len(user_agents)] if user_agents else user_agents[0]

        try:
            async with async_playwright() as p:
                launch_args = [
                    "--no-sandbox",
                    "--disable-dev-shm-usage",
                    "--disable-blink-features=AutomationControlled",
                    "--window-position=2000,0"
                ]
                navegador = await p.chromium.launch(headless=headless, args=launch_args)

                context_kwargs = {
                    "user_agent": ua_choice,
                    "locale": "en-US",
                    "timezone_id": "America/Bogota",
                    "ignore_https_errors": True,
                    "viewport": {"width": 1366, "height": 768},
                }
                if proxy_choice:
                    context_kwargs["proxy"] = {"server": proxy_choice}

                context = await navegador.new_context(**context_kwargs)

                if stealth:
                    stealth_script = """
                    Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
                    window.chrome = window.chrome || { runtime: {} };
                    Object.defineProperty(navigator, 'languages', {get: () => ['en-US', 'en']});
                    Object.defineProperty(navigator, 'plugins', {get: () => [1,2,3,4,5]});
                    """
                    await context.add_init_script(stealth_script)

                try:
                    await context.set_extra_http_headers({"Accept-Language": "en-US,en;q=0.9"})
                except Exception:
                    pass

                page = await context.new_page()
                # Timeout por defecto reducido para respuestas más rápidas
                page.set_default_timeout(20000)

                # Manejar diálogos cerrándolos automáticamente
                page.on("dialog", lambda dialog: asyncio.create_task(dialog.dismiss()))

                # Manejar popups cerrándolos al aparecer
                async def _on_popup(popup):
                    try:
                        await asyncio.sleep(0.3)
                        if not popup.is_closed():
                            await popup.close()
                    except Exception:
                        pass

                page.on("popup", lambda popup: asyncio.create_task(_on_popup(popup)))

                # Navegación: usar domcontentloaded en vez de networkidle y con timeout reducido
                try:
                    await page.goto(URL, wait_until="domcontentloaded", timeout=15000)
                except Exception:
                    # intento alternativo más rápido sin espera estricta
                    try:
                        await page.goto(URL, timeout=8000)
                    except Exception:
                        # guardar evidencia temprana y propagar para manejo superior
                        try:
                            early_ts = datetime.now().strftime("%Y%m%d_%H%M%S")
                            early_png = os.path.join(carpeta_abs, f"early_timeout_{NOMBRE_SITIO}_{consulta_id}_{early_ts}.png")
                            await page.screenshot(path=early_png, full_page=True)
                        except Exception:
                            pass
                        raise

                # evidencia temprana
                try:
                    early_ts = datetime.now().strftime("%Y%m%d_%H%M%S")
                    early_png = os.path.join(carpeta_abs, f"early_{NOMBRE_SITIO}_{consulta_id}_{early_ts}.png")
                    early_html = os.path.join(carpeta_abs, f"early_{NOMBRE_SITIO}_{consulta_id}_{early_ts}.html")
                    await page.screenshot(path=early_png, full_page=True)
                    with open(early_html, "w", encoding="utf-8") as fh:
                        fh.write(await page.content())
                except Exception:
                    pass

                # comprobar bloqueo inicial
                try:
                    html0 = await page.content()
                    if _is_blocked_html(html0, page.url):
                        try:
                            await page.screenshot(path=png_abs, full_page=True)
                        except Exception:
                            pass
                        try:
                            await context.close()
                        except Exception:
                            pass
                        try:
                            await navegador.close()
                        except Exception:
                            pass
                        navegador = None
                        await sync_to_async(_guardar_resultado_adaptativo)(
                            consulta_id,
                            fuente_obj,
                            0,
                            "Sin Validar",
                            "La fuente está presentando problemas para la consulta (DEA bloqueó el acceso).",
                            png_abs,
                            png_rel if os.path.exists(png_abs) else "",
                        )
                        return
                except Exception:
                    pass

                # comportamiento humano
                await _human_move_mouse(page)
                await asyncio.sleep(random.uniform(0.2, 0.6))

                # escribir cédula con tipeo humano
                try:
                    await _human_type(page, "#edit-keywords", cedula)
                except Exception:
                    try:
                        await page.click("#edit-keywords", timeout=4000)
                        await _human_type(page, "#edit-keywords", cedula)
                    except Exception:
                        pass

                await _human_move_mouse(page)

                # disparar búsqueda
                try:
                    await page.click(".menu--search-box-button", timeout=4000)
                except Exception:
                    try:
                        await page.keyboard.press("Enter")
                    except Exception:
                        pass

                # esperar carga ligera y pequeña pausa
                try:
                    await page.wait_for_load_state("load", timeout=10000)
                except Exception:
                    pass
                await asyncio.sleep(random.uniform(0.8, 1.6))

                # comprobar bloqueo posterior
                try:
                    html1 = await page.content()
                    if _is_blocked_html(html1, page.url):
                        try:
                            await page.screenshot(path=png_abs, full_page=True)
                        except Exception:
                            pass
                        try:
                            await context.close()
                        except Exception:
                            pass
                        try:
                            await navegador.close()
                        except Exception:
                            pass
                        navegador = None
                        await sync_to_async(_guardar_resultado_adaptativo)(
                            consulta_id,
                            fuente_obj,
                            0,
                            "Sin Validar",
                            "La fuente está presentando problemas para la consulta (DEA bloqueó el acceso).",
                            png_abs,
                            png_rel if os.path.exists(png_abs) else "",
                        )
                        return
                except Exception:
                    pass

                # detectar resultados y tomar captura condicional
                score = 0
                mensaje = ""
                first_result_text = ""
                ts_now = datetime.now().strftime("%Y%m%d_%H%M%S")

                try:
                    empty_div = page.locator(".l-view__empty")
                    has_empty = (await empty_div.count() > 0) and (await empty_div.first.is_visible())
                except Exception:
                    has_empty = False

                if has_empty:
                    mensaje = (await empty_div.first.inner_text() or "").strip() or "No results"
                    score = 0
                    screenshot_name = f"{NOMBRE_SITIO}_{consulta_id}_{ts_now}_no_results.png"
                    absolute_path = os.path.join(carpeta_abs, screenshot_name)
                    relative_path = os.path.join(carpeta_rel, screenshot_name).replace("\\", "/")
                    try:
                        await page.screenshot(path=absolute_path, full_page=True)
                    except Exception:
                        absolute_path = None
                        relative_path = ""
                else:
                    # intentar extraer primer resultado textual si existe
                    try:
                        first_selector_candidates = [
                            ".search-results .result",
                            ".views-row",
                            ".node",
                        ]
                        found = False
                        for sel in first_selector_candidates:
                            locator = page.locator(sel)
                            if await locator.count() > 0:
                                first_result_text = (await locator.first.inner_text() or "").strip()
                                found = True
                                break
                        if not found:
                            main_locator = page.locator("main, #content, .region--content")
                            if await main_locator.count() > 0:
                                first_result_text = (await main_locator.first.inner_text() or "").strip()[:1000]
                    except Exception:
                        first_result_text = ""

                    mensaje = first_result_text or "se encontraron hallazgos"
                    score = 10
                    screenshot_name = f"{NOMBRE_SITIO}_{consulta_id}_{ts_now}_results.png"
                    absolute_path = os.path.join(carpeta_abs, screenshot_name)
                    relative_path = os.path.join(carpeta_rel, screenshot_name).replace("\\", "/")
                    try:
                        await page.screenshot(path=absolute_path, full_page=True)
                    except Exception:
                        absolute_path = None
                        relative_path = ""

                # cerrar context y navegador
                try:
                    await context.close()
                except Exception:
                    pass
                try:
                    await navegador.close()
                except Exception:
                    pass
                navegador = None

                # guardar resultado adaptativo
                await sync_to_async(_guardar_resultado_adaptativo)(
                    consulta_id,
                    fuente_obj,
                    score,
                    "Validada",
                    mensaje,
                    absolute_path if absolute_path else None,
                    relative_path if relative_path else "",
                )
                return

        except Exception as e:
            tb = traceback.format_exc()
            print(f"[DEA] intento {intento} error: {e}\n{tb}")

            # intentar screenshot final si queda navegador
            try:
                if navegador:
                    page = await navegador.new_page()
                    await page.goto(URL, timeout=10000)
                    await page.screenshot(path=png_abs, full_page=True)
            except Exception:
                pass
            try:
                if navegador:
                    await navegador.close()
            except Exception:
                pass
            navegador = None

            if intento < max_intentos:
                await asyncio.sleep(2 ** intento + random.uniform(0.5, 1.5))
                continue

            await sync_to_async(_guardar_resultado_adaptativo)(
                consulta_id,
                fuente_obj,
                0,
                "Sin Validar",
                str(e),
                png_abs,
                png_rel if os.path.exists(png_abs) else "",
            )
            return

    # fallback si no se completó
    await sync_to_async(_guardar_resultado_adaptativo)(
        consulta_id,
        fuente_obj,
        0,
        "Sin Validar",
        "No se completó la consulta.",
        png_abs,
        png_rel if os.path.exists(png_abs) else "",
    )
