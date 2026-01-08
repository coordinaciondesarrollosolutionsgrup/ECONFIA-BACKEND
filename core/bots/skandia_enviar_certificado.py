import os
import re
import random
import asyncio
import logging
from datetime import datetime, date
from pathlib import Path

from django.conf import settings
from asgiref.sync import sync_to_async
from playwright.async_api import async_playwright, TimeoutError

from core.models import Resultado, Fuente
from core.resolver.captcha_v2 import resolver_captcha_v2

# =========================================================
# CONFIGURACIÓN GENERAL
# =========================================================
URL = "https://www.skandia.co/consulta-extractos-y-certificados"
NOMBRE_SITIO = "skandia_certificados"
HEADLESS = False
MAX_RETRIES = 3

logger = logging.getLogger(__name__)

# =========================================================
# SELECTORES REALES SKANDIA
# =========================================================
SEL_TIPO = "#_com_skandia_co_certificates_web_portlet_SkandiaCoCertificatesWebPortlet_typeDocument"
SEL_DOC  = "#_com_skandia_co_certificates_web_portlet_SkandiaCoCertificatesWebPortlet_document"
SEL_YEAR = "#_com_skandia_co_certificates_web_portlet_SkandiaCoCertificatesWebPortlet_yearBirth"
SEL_BTN  = "#sendCertificate"

SEL_H3_SUCCESS = "h3:has-text('éxito')"
SEL_H3_FAIL    = "h3:has-text('fall')"

SEL_CAPTCHA_CONTAINER = "[data-sitekey]"

SITEKEY_FALLBACK = "6Le7iZAgAAAAABS-YU1fbnxjcxEvLtb77q4Z_YvK"

# =========================================================
# MAPAS
# =========================================================
TIPO_MAP = {
    "CC": "C",
    "CE": "E",
    "TI": "T",
    "PA": "P",
    "RC": "R",
}

# =========================================================
# HELPERS
# =========================================================
def year_only(fecha):
    if isinstance(fecha, (datetime, date)):
        return str(fecha.year)
    if isinstance(fecha, str):
        m = re.search(r"\d{4}", fecha)
        if m:
            return m.group(0)
    return ""


async def _delay_humano(min_ms=800, max_ms=2000):
    await asyncio.sleep(random.uniform(min_ms, max_ms) / 1000)


async def _interpretar_skandia(page):
    texto = (await page.inner_text("body")).upper()

    if "ÉXITO" in texto or "ENVIADA CON ÉXITO" in texto:
        return ("Solicitud Skandia enviada exitosamente.", 1)

    if "ERROR" in texto or "FALLÓ" in texto:
        return ("Solicitud Skandia falló.", 0)

    return ("Skandia no devolvió respuesta clara.", 0)


# =========================================================
# BOT PRINCIPAL
# =========================================================
async def consultar_skandia_certificados(
    consulta_id: int,
    numero: str,
    tipo_doc: str,
    fecha_nacimiento,
):
    logger.info(f"[Skandia] Inicio consulta_id={consulta_id}")

    fuente = await sync_to_async(Fuente.objects.get)(nombre=NOMBRE_SITIO)
    print(f"[Skandia] Parámetros recibidos: consulta_id={consulta_id}, numero={numero}, tipo_doc={tipo_doc}, fecha_nacimiento={fecha_nacimiento}")

    # ---------------- RUTAS ----------------
    folder = Path(settings.MEDIA_ROOT) / "resultados" / str(consulta_id)
    folder.mkdir(parents=True, exist_ok=True)

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    img_path = folder / f"skandia_{numero}_{ts}.png"

    tipo_val = TIPO_MAP.get(tipo_doc.upper(), "C")
    year_val = year_only(fecha_nacimiento)

    async with async_playwright() as pw:
        for intento in range(1, MAX_RETRIES + 1):
            print(f"[Skandia] Intento {intento}/{MAX_RETRIES}")

            browser = await pw.chromium.launch(
                headless=HEADLESS,
                args=[
                    "--disable-blink-features=AutomationControlled",
                    "--no-sandbox",
                    "--disable-dev-shm-usage",
                    "--window-size=1920,1080",
                ],
            )

            context = await browser.new_context(
                locale="es-CO",
                viewport={"width": 1920, "height": 1080},
            )

            page = await context.new_page()

            try:
                # ---------------- NAVEGACIÓN ----------------
                await page.goto(URL, wait_until="domcontentloaded", timeout=45000)
                await _delay_humano()

                # ---------------- FORMULARIO ----------------
                await page.wait_for_selector(SEL_TIPO, timeout=20000)
                await page.select_option(SEL_TIPO, tipo_val)
                await _delay_humano()

                await page.fill(SEL_DOC, numero)
                await _delay_humano()

                if year_val:
                    await page.fill(SEL_YEAR, year_val)
                    await _delay_humano()

                # ---------------- CAPTCHA (SI EXISTE) ----------------
                try:
                    sitekey = await page.get_attribute(SEL_CAPTCHA_CONTAINER, "data-sitekey")
                    sitekey = sitekey or SITEKEY_FALLBACK

                    token = await resolver_captcha_v2(sitekey, page.url)
                    await page.evaluate(
                        """(token)=>{
                            document.getElementById('g-recaptcha-response').innerHTML = token;
                        }""",
                        token,
                    )
                    await _delay_humano()
                except Exception:
                    pass  # no siempre hay captcha

                # ---------------- ENVIAR ----------------
                await page.wait_for_selector(SEL_BTN, timeout=20000)
                await _delay_humano()
                await page.click(SEL_BTN)

                # ---------------- ESPERAR RESPUESTA ----------------
                await page.wait_for_selector(
                    f"{SEL_H3_SUCCESS}, {SEL_H3_FAIL}",
                    timeout=45000,
                )

                await _delay_humano(1500, 2500)

                # ---------------- SCREENSHOT FINAL ----------------
                await page.screenshot(path=str(img_path), full_page=True)

                # ---------------- INTERPRETAR ----------------
                mensaje, score = await _interpretar_skandia(page)
                print(f"[Skandia] Mensaje interpretado: {mensaje}, score: {score}")
                # ---------------- BD ----------------
                await sync_to_async(Resultado.objects.create)(
                    consulta_id=consulta_id,
                    fuente=fuente,
                    mensaje=mensaje,
                    score=score,
                    archivo=str(img_path.relative_to(settings.MEDIA_ROOT)),
                    estado="validado" if score == 1 else "error"
                )
                print(f"[Skandia] Resultado guardado en BD para consulta_id={consulta_id}")
                await context.close()
                await browser.close()
                return mensaje

            except Exception as e:
                print(f"[Skandia] Error intento {intento}: {e}")
                import traceback
                traceback.print_exc()
                try:
                    await page.screenshot(path=str(img_path), full_page=True)
                except Exception as ex:
                    print(f"[Skandia] Error al tomar screenshot: {ex}")
                await context.close()
                await browser.close()
                if intento == MAX_RETRIES:
                    await sync_to_async(Resultado.objects.create)(
                        consulta_id=consulta_id,
                        fuente=fuente,
                        mensaje=f"Error Skandia: {e}",
                        score=0,
                        archivo=str(img_path.relative_to(settings.MEDIA_ROOT)) if img_path.exists() else "",
                        estado="error"
                    )
                    print(f"[Skandia] Resultado de error guardado en BD para consulta_id={consulta_id}")
                    return f"Error Skandia: {e}"
                await asyncio.sleep(random.uniform(3, 6))
        # Alias para compatibilidad con el sistema de bots
    consultar = consultar_skandia_certificados
