import os
import asyncio
from datetime import datetime

from django.conf import settings
from asgiref.sync import sync_to_async
from playwright.async_api import async_playwright

from core.models import Resultado, Fuente

import fitz  # PyMuPDF (si quieres convertir pdf->png)

NOMBRE_SITIO = "proteccion_cert_afiliacion"
URL = "https://www.proteccion.com/portalafiliados/afiliados/certifacil"

TIPO_DOC_MAP = {
    "CC": "Cédula de ciudadanía",
    "CE": "Cédula de extranjería",
    "TI": "Tarjeta de identidad",
    "PA": "Pasaporte",
    "NIT": "NIT",
}

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

def pdf_a_png(pdf_path, png_path, dpi=200):
    doc = fitz.open(pdf_path)
    pix = doc[0].get_pixmap(dpi=dpi)
    pix.save(png_path)
    doc.close()

async def consultar_proteccion_cert_afiliacion(cedula: str, tipo_doc: str, consulta_id: int):
    """
    Protección Certifácil:
    - Llenar tipo_doc + cedula
    - Elegir "Generar certificados" (si existe)
    - Elegir certificado (pensión obligatoria / afiliación) si hay menú
    - Descargar PDF (si el flujo lo permite)
    Evidencia: PDF/PNG o screenshot.
    """
    relative_folder = os.path.join("resultados", str(consulta_id))
    absolute_folder = os.path.join(settings.MEDIA_ROOT, relative_folder)
    os.makedirs(absolute_folder, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")

    fuente_obj = await sync_to_async(Fuente.objects.filter(nombre=NOMBRE_SITIO).first)()

    tipo_label = TIPO_DOC_MAP.get(str(tipo_doc).upper(), str(tipo_doc).upper())

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            user_agent=UA,
            locale="es-CO",
            viewport={"width": 1366, "height": 768},
        )
        page = await context.new_page()

        try:
            await page.goto(URL, wait_until="domcontentloaded", timeout=60000)
            await page.wait_for_timeout(1500)

            # Cookies si salen
            for sel in ['button:has-text("Aceptar")', '#onetrust-accept-btn-handler']:
                try:
                    if await page.locator(sel).count() > 0:
                        await page.locator(sel).first.click(timeout=3000)
                        break
                except Exception:
                    pass

            # Buscar select tipo doc (o combobox)
            selected = False
            for sel in ["select", 'select[id*="document"]', 'select[id*="tipo"]']:
                try:
                    if await page.locator(sel).count() > 0:
                        await page.locator(sel).first.select_option(label=tipo_label)
                        selected = True
                        break
                except Exception:
                    pass
            if not selected:
                # combobox
                try:
                    await page.locator('[role="combobox"]').first.click(timeout=8000)
                    await page.locator(f'text={tipo_label}').first.click(timeout=8000)
                except Exception:
                    pass

            # Input documento
            doc_input = None
            for sel in [
                'input[inputmode="numeric"]',
                'input[placeholder*="document"]',
                'input[aria-label*="document"]',
                'input[type="text"]',
            ]:
                if await page.locator(sel).count() > 0:
                    doc_input = page.locator(sel).first
                    break
            if not doc_input:
                raise Exception("No se encontró input de documento en Protección Certifácil.")

            await doc_input.fill(str(cedula))

            # Botón continuar / consultar / generar
            clicked = False
            for sel in [
                'button:has-text("Generar")',
                'button:has-text("Consultar")',
                'button:has-text("Continuar")',
                'button:has-text("Ingresar")',
                'input[type="submit"]',
            ]:
                try:
                    if await page.locator(sel).count() > 0:
                        await page.locator(sel).first.click(timeout=12000)
                        clicked = True
                        break
                except Exception:
                    pass
            if not clicked:
                # No siempre hay botón, a veces es submit implícito
                await page.keyboard.press("Enter")

            await page.wait_for_timeout(2500)

            # Intentar descargar PDF si aparece un botón/enlace PDF
            pdf_path = os.path.join(absolute_folder, f"{NOMBRE_SITIO}_{cedula}_{ts}.pdf")
            downloaded = False

            # Selectores típicos para "PDF" / "Descargar"
            pdf_btn_candidates = [
                'a:has-text("PDF")',
                'button:has-text("PDF")',
                'a[title*="PDF"]',
                'button:has-text("Descargar")',
                'a:has-text("Descargar")',
            ]

            for sel in pdf_btn_candidates:
                try:
                    if await page.locator(sel).count() > 0:
                        async with page.expect_download(timeout=30000) as di:
                            await page.locator(sel).first.click(timeout=12000)
                        d = await di.value
                        await d.save_as(pdf_path)
                        downloaded = True
                        break
                except Exception:
                    pass

            if downloaded and os.path.exists(pdf_path):
                # Convertir a PNG para evidencia visual si quieres
                png_path = pdf_path.replace(".pdf", ".png")
                try:
                    pdf_a_png(pdf_path, png_path, dpi=200)
                    evidencia = png_path
                except Exception:
                    evidencia = pdf_path

                if fuente_obj:
                    await sync_to_async(Resultado.objects.create)(
                        consulta_id=consulta_id,
                        fuente=fuente_obj,
                        score=0,
                        estado="Validado",
                        mensaje="Certificado descargado (ver evidencia).",
                        archivo=os.path.join(relative_folder, os.path.basename(evidencia)),
                    )
                return

            # Si no hubo descarga, al menos deja screenshot
            shot_path = os.path.join(absolute_folder, f"{NOMBRE_SITIO}_{cedula}_{ts}.png")
            await page.screenshot(path=shot_path, full_page=True)

            if fuente_obj:
                await sync_to_async(Resultado.objects.create)(
                    consulta_id=consulta_id,
                    fuente=fuente_obj,
                    score=0,
                    estado="Validado",
                    mensaje="Proceso ejecutado, pero no se detectó descarga PDF (ver evidencia).",
                    archivo=os.path.join(relative_folder, os.path.basename(shot_path)),
                )

        except Exception as e:
            err_path = os.path.join(absolute_folder, f"{NOMBRE_SITIO}_{cedula}_{ts}_error.png")
            try:
                await page.screenshot(path=err_path, full_page=True)
            except Exception:
                pass

            if fuente_obj:
                await sync_to_async(Resultado.objects.create)(
                    consulta_id=consulta_id,
                    fuente=fuente_obj,
                    score=0,
                    estado="Sin validar",
                    mensaje=f"Error Protección certificado afiliación: {e}",
                    archivo=os.path.join(relative_folder, os.path.basename(err_path)),
                )
        finally:
            await context.close()
            await browser.close()
