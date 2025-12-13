import os
import asyncio
import random
import urllib.parse
from datetime import datetime
from typing import Optional

from playwright.async_api import async_playwright, Page, BrowserContext
from django.conf import settings
from asgiref.sync import sync_to_async
from core.models import Resultado, Fuente

NOMBRE_SITIO = "interpol_red_notices"

# URLs
GOOGLE_URL = "https://www.google.com/?hl=es"
INTERPOL_SEARCH_BASE = "https://www.interpol.int/es/Pagina-de-busqueda?search={q}"

# DB helpers
@sync_to_async
def _get_fuente(nombre: str):
    return Fuente.objects.filter(nombre=nombre).first()

@sync_to_async
def _crear_resultado(consulta_id, fuente, score, estado, mensaje, archivo):
    return Resultado.objects.create(
        consulta_id=consulta_id,
        fuente=fuente,
        score=score,
        estado=estado,
        mensaje=mensaje,
        archivo=archivo,
    )

# --------------------------
# Anti-bot utilities
# --------------------------
async def _human_actions(page: Page):
    try:
        w, h = page.viewport_size["width"], page.viewport_size["height"]
        for _ in range(random.randint(2, 4)):
            await page.mouse.move(
                random.randint(0, w),
                random.randint(0, h),
                steps=random.randint(6, 15)
            )
            await asyncio.sleep(random.uniform(0.15, 0.35))

        await page.evaluate("() => window.scrollBy(0, window.innerHeight * 0.4)")
        await asyncio.sleep(random.uniform(0.3, 0.6))

    except Exception:
        pass

async def _save_png(page: Page, folder: str, prefix: str):
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = os.path.join(folder, f"{prefix}_{ts}.png")
    try:
        await page.screenshot(path=path, full_page=True)
    except:
        await page.screenshot(path=path)
    return os.path.relpath(path, settings.MEDIA_ROOT)

# --------------------------
# BOT PRINCIPAL
# --------------------------
async def consultar_interpol_red_notices(consulta_id: int, nombre: str, cedula: str):
    """
    Acceso a Interpol usando método anti-bot:
    - Entrar primero a Google
    - Simular acciones humanas
    - Luego navegar DIRECTO a la página de búsqueda global
    """
    nombre = (nombre or "").strip()
    if not nombre:
        return

    # preparar carpetas
    relative_folder = os.path.join("resultados", str(consulta_id))
    absolute_folder = os.path.join(settings.MEDIA_ROOT, relative_folder)
    os.makedirs(absolute_folder, exist_ok=True)

    fuente_obj = await _get_fuente(NOMBRE_SITIO)

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-blink-features=AutomationControlled", "--window-position=2000,0"]
        )

        context: BrowserContext = await browser.new_context(
            viewport={"width": 1366, "height": 768},
            locale="es-ES",
            ignore_https_errors=True
        )

        page: Page = await context.new_page()

        print("⚡ BOT INTERPOL – BUSCADOR GLOBAL EJECUTANDO...")

        # 1) Entrar a Google
        print("➡ Entrando a Google…")
        await page.goto(GOOGLE_URL, wait_until="domcontentloaded")

        # anti-bot
        await _human_actions(page)

        # 2) Construir URL de búsqueda global de Interpol
        q = urllib.parse.quote(nombre)
        interpol_url = INTERPOL_SEARCH_BASE.format(q=q)
        print(f"➡ Accediendo al buscador global: {interpol_url}")

        # 3) Navegar directamente DESPUÉS de Google
        await page.goto(interpol_url, wait_until="domcontentloaded")

        # anti-bot otra vez
        await _human_actions(page)

        # 4) Captura de pantalla
        rel_png = await _save_png(page, absolute_folder, "interpol_global_search")

        # 5) Evaluar si hay resultados
        try:
            text_body = (await page.inner_text("body")).lower()
            if "no se han encontrado" in text_body or "no results" in text_body:
                score = 0
                mensaje = "No se encontraron resultados en el buscador global."
            else:
                score = 10
                mensaje = "Búsqueda realizada. Revisar captura."
        except:
            score = 0
            mensaje = "No se pudo analizar la página. Revisar captura."

        # 6) Registrar resultado
        await _crear_resultado(
            consulta_id, fuente_obj, score, "Validada", mensaje, rel_png
        )

        await context.close()
        await browser.close()

    print("✔ BOT FINALIZADO")