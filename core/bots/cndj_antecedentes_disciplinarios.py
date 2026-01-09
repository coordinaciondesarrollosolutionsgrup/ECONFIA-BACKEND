import os
import asyncio
import base64
import logging
from datetime import datetime

from django.conf import settings
from asgiref.sync import sync_to_async
from playwright.async_api import async_playwright

import pypdf
from pdf2image import convert_from_path

from core.models import Resultado, Fuente

logger = logging.getLogger(__name__)

NOMBRE_SITIO = "CNDJ Antecedentes Disciplinarios"
URL = "https://antecedentesdisciplinarios.cndj.gov.co/"


# ---------- Helpers PDF ----------
def _pdf_text_pypdf(abs_pdf: str) -> str:
    try:
        from pypdf import PdfReader
        r = PdfReader(abs_pdf)
        parts = []
        for pg in r.pages:
            try:
                parts.append(pg.extract_text() or "")
            except Exception:
                pass
        return "\n".join(parts)
    except Exception:
        return ""


def _pdf_text_pdfminer(abs_pdf: str) -> str:
    try:
        from pdfminer.high_level import extract_text
        return extract_text(abs_pdf) or ""
    except Exception:
        return ""


def _parse_mensaje_cndj(texto: str):
    t = (texto or "").upper()

    negativos = [
        "ANTECEDENTE",
        "HALLAZGO",
        "SANCION",
        "SUSPENSION",
        "INHABILIDAD",
        "EXCLUSION",
        "REGISTRA ANTECEDENTES",
    ]

    positivos = [
        "NO REGISTRA ANTECEDENTES",
        "NO SE ENCONTRARON ANTECEDENTES",
        "SIN REGISTRO DISCIPLINARIO",
        "NO REGISTRA SANCION",
    ]

    for n in negativos:
        if n in t:
            return (
                "Registra antecedentes disciplinarios ante el Consejo Nacional de Disciplina Judicial.",
                1,
            )

    for p in positivos:
        if p in t:
            return (
                "No registra antecedentes disciplinarios ante el Consejo Nacional de Disciplina Judicial.",
                0,
            )

    return (
        "No fue posible determinar con claridad si registra antecedentes. Revisar evidencia.",
        0,
    )


async def consultar_antecedentes_cndj(
    consulta_id: int,
    cedula: str,
    tipo_doc: str,
    **kwargs,   # para que run_bot_single no falle
):
    """
    CNDJ – Antecedentes Disciplinarios
    ✔ Llena formulario
    ✔ Captcha invisible (automático)
    ✔ Extrae PDF en base64 desde el DOM
    ✔ Guarda PDF + screenshot
    ✔ Registra Resultado en BD
    """

    browser = None

    # 1---- Fuente 
    fuente = await sync_to_async(Fuente.objects.get)(nombre=NOMBRE_SITIO)

    # ---Carpeta resultados
    relative_folder = os.path.join("resultados", str(consulta_id))
    absolute_folder = os.path.join(settings.MEDIA_ROOT, relative_folder)
    os.makedirs(absolute_folder, exist_ok=True)

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe_ced = str(cedula).strip()

    pdf_name = f"cndj_{safe_ced}_{ts}.pdf"
    png_name = f"cndj_{safe_ced}_{ts}.png"

    abs_pdf = os.path.join(absolute_folder, pdf_name)
    abs_png = os.path.join(absolute_folder, png_name)

    rel_pdf = os.path.join(relative_folder, pdf_name)
    rel_png = os.path.join(relative_folder, png_name)

    estado = "Sin Validar"
    score = 0
    mensaje = "No se pudo obtener resultado."
    archivo = ""


    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(
                headless=False,
                args=["--disable-blink-features=AutomationControlled"]
            )

            context = await browser.new_context(
                locale="es-CO",
                viewport={"width": 1440, "height": 1000},
            )

            page = await context.new_page()

            # ----- Navegar
            await page.goto(URL, wait_until="domcontentloaded", timeout=60000)
            await page.wait_for_load_state("networkidle")

            # ----- Llenar formulario
            await page.wait_for_selector("#inputDocumentType", timeout=15000)

            tipo_label = (
                "Documento de identidad"
                if tipo_doc.upper() in ("CC", "CEDULA", "CI")
                else "Tarjeta profesional"
            )

            await page.select_option("#inputDocumentType", label=tipo_label)
            await page.fill("#inputDocumentNumber", safe_ced)

            # ----- Submit (captcha invisible se ejecuta solo)
            await page.click('button[type="submit"]')

            # Dar tiempo a Google + backend
            await asyncio.sleep(10)

            # ----- Buscar PDF base64 en el DOM
            pdf_base64 = await page.evaluate("""
            () => {
                const link = document.querySelector(
                    'a[href^="data:application/pdf;base64"]'
                );
                return link ? link.getAttribute("href") : null;
            }
            """)

            if not pdf_base64:
                logger.warning("[CNDJ] No se encontró PDF base64 en el DOM")
                await page.screenshot(path=abs_png, full_page=True)
                mensaje = "No se encontró el PDF en la página."
            else:
                # ----- Decodificar y guardar PDF
                prefix = "data:application/pdf;base64,"
                pdf_bytes = base64.b64decode(pdf_base64[len(prefix):])

                with open(abs_pdf, "wb") as f:
                    f.write(pdf_bytes)

                texto = _pdf_text_pypdf(abs_pdf)
                if not texto.strip():
                    texto = _pdf_text_pdfminer(abs_pdf)

                # Screenshot de evidencia (pantalla)
                await page.screenshot(path=abs_png, full_page=True)

                # --- Captura de imagen del PDF (primera página)
                try:
                    images = convert_from_path(abs_pdf, first_page=1, last_page=1)
                    if images:
                        pdf_img_name = f"cndj_{safe_ced}_{ts}_pdf.png"
                        abs_pdf_img = os.path.join(absolute_folder, pdf_img_name)
                        rel_pdf_img = os.path.join(relative_folder, pdf_img_name)
                        images[0].save(abs_pdf_img, "PNG")
                        archivo = rel_pdf_img
                    else:
                        archivo = rel_pdf
                except Exception as e_img:
                    logger.warning(f"[CNDJ] No se pudo generar imagen del PDF: {e_img}")
                    archivo = rel_pdf

                mensaje, score = _parse_mensaje_cndj(texto)
                estado = "Validada"
                score = 0  # ajusta si quieres lógica adicional

            await context.close()
            await browser.close()
            browser = None
            print(f"[CNDJ] Consulta completada para cédula {safe_ced}")

    except Exception as e:
        logger.error(f"[CNDJ] Error: {e}", exc_info=True)
        mensaje = f"Error en la consulta: {e}"

        try:
            if browser:
                await browser.close()
        except Exception:
            pass

    # ----- Guardar resultado en BD (SIEMPRE)
    await sync_to_async(Resultado.objects.create)(
        consulta_id=consulta_id,
        fuente=fuente,
        estado=estado,
        score=score,
        mensaje=mensaje,
        archivo=archivo or rel_png,
    )
