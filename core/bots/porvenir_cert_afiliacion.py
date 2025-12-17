# core/bots/porvenir_cert_afiliacion.py
import os, re, asyncio
from datetime import datetime
import random

from django.conf import settings
from asgiref.sync import sync_to_async
from playwright.async_api import async_playwright, TimeoutError as PWTimeout

from core.models import Resultado, Fuente

LANDING_URL = "https://www.porvenir.com.co/certificados-y-extractos"
URL = "https://www.porvenir.com.co/web/certificados-y-extractos/certificado-de-afiliacion"
NOMBRE_SITIO = "porvenir_cert_afiliacion"

TIPO_DOC_MAP = {"CC": "CC", "CE": "CE", "TI": "TI"}

import random

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
]

UA = random.choice(USER_AGENTS)


def _normalize_ws(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "")).strip()

def _render_pdf_first_page_pymupdf(pdf_path: str, png_path: str, zoom: float = 2.0) -> bool:
    try:
        import fitz  # PyMuPDF
        with fitz.open(pdf_path) as doc:
            if doc.page_count == 0:
                return False
            page = doc[0]
            pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), alpha=False)
            pix.save(png_path)
        return os.path.exists(png_path) and os.path.getsize(png_path) > 0
    except Exception:
        return False

async def consultar_porvenir_cert_afiliacion(consulta_id: int, cedula: str, tipo_doc: str):
    fuente_obj = await sync_to_async(lambda: Fuente.objects.filter(nombre=NOMBRE_SITIO).first())()
    if not fuente_obj:
        await sync_to_async(Resultado.objects.create)(
            consulta_id=consulta_id, fuente=None, estado="Sin Validar",
            mensaje=f"No existe la fuente '{NOMBRE_SITIO}'", archivo="", score=0
        )
        return

    # Carpetas
    relative_folder = os.path.join("resultados", str(consulta_id))
    absolute_folder = os.path.join(settings.MEDIA_ROOT, relative_folder)
    os.makedirs(absolute_folder, exist_ok=True)

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    base = f"porvenir_{cedula}_{ts}"

    abs_png = os.path.join(absolute_folder, f"{base}.png")
    rel_png = os.path.join(relative_folder, f"{base}.png").replace("\\", "/")

    abs_pdf = os.path.join(absolute_folder, f"{base}.pdf")
    rel_pdf = os.path.join(relative_folder, f"{base}.pdf").replace("\\", "/")
    abs_png_pdf = os.path.join(absolute_folder, f"{base}_pdf.png")
    rel_png_pdf = os.path.join(relative_folder, f"{base}_pdf.png").replace("\\", "/")

    tipo_val = TIPO_DOC_MAP.get((tipo_doc or "").upper())
    if not tipo_val:
        await sync_to_async(Resultado.objects.create)(
            consulta_id=consulta_id, fuente=fuente_obj, estado="Sin Validar",
            mensaje=f"Tipo de documento no soportado: {tipo_doc!r}", archivo="", score=0
        )
        return

    browser = context = page = None

    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(
                headless=True,
                args=["--no-sandbox", "--disable-dev-shm-usage", "--disable-blink-features=AutomationControlled"]
            )

            context = await browser.new_context(
                user_agent=UA,
                viewport={"width": 1400, "height": 900},
                locale="es-CO",
                accept_downloads=True,
            )

            # Bloquear recursos pesados
            async def _route(route):
                rtype = route.request.resource_type
                if rtype in ("image", "font", "media"):
                    await route.abort()
                else:
                    await route.continue_()

            await context.route("**/*", _route)

            page = await context.new_page()
            page.set_default_timeout(8000)
            page.set_default_navigation_timeout(30000)

            # 1) Ir DIRECTO al formulario y esperar solo los campos necesarios
            await page.goto(URL, wait_until="domcontentloaded")
            await page.wait_for_selector('select[id$="_documento"]', timeout=10000)
            await page.wait_for_selector('input[id$="_numeroIdentificacion"]:not([type="hidden"])', timeout=10000)

            # 2) Cookies (si aparecen)
            try:
                cookie = page.locator(
                    "button:has-text('Aceptar'), button:has-text('Acepto'), [aria-label*='acept']"
                ).first
                if await cookie.count() > 0:
                    await cookie.click(timeout=1500)
            except Exception:
                pass

            # 3) Formulario
            await page.select_option('select[id$="_documento"]', tipo_val)
            input_field = page.locator('input[id$="_numeroIdentificacion"]:not([type="hidden"])')
            await input_field.fill(str(cedula))

            # 4) Descargar PDF (fail fast)
            downloaded = False
            try:
                async with page.expect_download(timeout=12000) as dl:
                    await page.click("#submitDescargarCertificado", timeout=2000)
                d = await dl.value
                await d.save_as(abs_pdf)
                downloaded = os.path.exists(abs_pdf) and os.path.getsize(abs_pdf) > 0
            except Exception:
                downloaded = False

            # 5) Detectar mensajes (en paralelo “fast”)
            estado = "Sin Validar"
            mensaje = "No se pudo determinar el estado. Revise la evidencia."

            # Busca rápido sin esperas largas
            candidates = [
                ("Validada", "p:has-text('descargado con éxito'), p:has-text('se ha descargado con éxito'), "
                            "p:has-text('enviado'), p:has-text('se ha enviado'), "
                            "h2:has-text('Tu certificado se ha descargado con éxito')", 4000),
                ("Validada", "p.p-status", 3000),
                ("Sin Validar", "p:has-text('problema técnico'), p:has-text('ingresa más tarde'), "
                                "p:has-text('problema tecnico')", 3000),
            ]

            for est, sel, to in candidates:
                try:
                    loc = page.locator(sel).first
                    await loc.wait_for(state="visible", timeout=to)
                    mensaje = _normalize_ws(await loc.inner_text())
                    estado = est
                    break
                except Exception:
                    pass

            # 6) Evidencia (más rápida que full_page si quieres)
            await page.screenshot(path=abs_png, full_page=False)

            # 7) Render PDF SOLO si descargó (y solo PyMuPDF)
            rendered = False
            if downloaded:
                # Ojo: esto es sync; si quieres, luego lo pasamos a thread
                rendered = _render_pdf_first_page_pymupdf(abs_pdf, abs_png_pdf, zoom=2.0)

            await sync_to_async(Resultado.objects.create)(
                consulta_id=consulta_id,
                fuente=fuente_obj,
                estado=estado,
                mensaje=mensaje + ("" if downloaded else " | PDF no descargado"),
                archivo=(rel_png_pdf if rendered else rel_png),
                score=1 if estado == "Validada" else 0,
            )

    except Exception as e:
        await sync_to_async(Resultado.objects.create)(
            consulta_id=consulta_id,
            fuente=fuente_obj,
            estado="Sin Validar",
            mensaje=str(e),
            archivo="",
            score=0,
        )
    finally:
        try:
            if context:
                await context.close()
        except Exception:
            pass
        try:
            if browser:
                await browser.close()
        except Exception:
            pass
