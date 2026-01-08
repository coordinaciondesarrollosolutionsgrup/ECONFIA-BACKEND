# Antecedentes Tribunal Nacional de Ética Médica para médicoss
import os
from datetime import datetime
from django.conf import settings
from asgiref.sync import sync_to_async
from playwright.async_api import async_playwright
from core.models import Resultado, Fuente

NOMBRE_SITIO = "tribunal_etica_medica"
URL = "https://www.tribunalnacionaldeeticamedica.org/certificados/generar/"

def _safe(s: str) -> str:
    return (s or "").replace("\n", " ").replace("\r", " ").strip()

async def consultar_tribunal_etica_medica(cedula: str, tipo_doc: str, consulta_id: int):
    """
    Consulta antecedentes para médicos en el Tribunal Nacional de Ética Médica.
    Registra si tiene hallazgos y los enumera. Si no tiene, indica que no tiene antecedentes.
    """
    relative_folder = os.path.join("resultados", str(consulta_id))
    absolute_folder = os.path.join(settings.MEDIA_ROOT, relative_folder)
    os.makedirs(absolute_folder, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")

    fuente_obj = await sync_to_async(Fuente.objects.filter(nombre=NOMBRE_SITIO).first)()
    mensaje = ""
    hallazgos = []
    tiene_antecedentes = False

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(locale="es-CO")
        page = await context.new_page()
        try:
            await page.goto(URL, wait_until="domcontentloaded", timeout=60000)
            # Llenar formulario
            await page.fill('input[name="numero_documento"]', str(cedula))
            await page.select_option('select[name="tipo_documento"]', value=tipo_doc.upper())
            await page.click('button[type="submit"]')
            await page.wait_for_timeout(2500)
            # Captura evidencia
            shot_path = os.path.join(absolute_folder, f"{NOMBRE_SITIO}_{cedula}_{ts}.png")
            await page.screenshot(path=shot_path, full_page=True)
            # Buscar hallazgos
            content = await page.content()
            if "No se encontraron antecedentes" in content:
                mensaje = "No se encontraron antecedentes."
            else:
                # Buscar y enumerar hallazgos
                rows = await page.query_selector_all('table tbody tr')
                for idx, row in enumerate(rows, 1):
                    tds = await row.query_selector_all('td')
                    values = [await td.inner_text() for td in tds]
                    hallazgos.append(f"{idx}. {' | '.join([_safe(v) for v in values])}")
                if hallazgos:
                    mensaje = "Antecedentes encontrados:\n" + "\n".join(hallazgos)
                    tiene_antecedentes = True
                else:
                    mensaje = "No se encontraron antecedentes (tabla vacía)."
            if fuente_obj:
                await sync_to_async(Resultado.objects.create)(
                    consulta_id=consulta_id,
                    fuente=fuente_obj,
                    score=1 if tiene_antecedentes else 0,
                    estado="Validado",
                    mensaje=mensaje,
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
                    mensaje=f"Error Tribunal Ética Médica: {e}",
                    archivo=os.path.join(relative_folder, os.path.basename(err_path)),
                )
        finally:
            await context.close()
            await browser.close()
