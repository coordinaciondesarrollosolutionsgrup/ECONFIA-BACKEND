# core/bots/skandia_certificados.py
import os
import re
from datetime import datetime, date

from django.conf import settings
from asgiref.sync import sync_to_async
from playwright.async_api import async_playwright

from core.models import Resultado, Fuente
from core.resolver.captcha_v2 import resolver_captcha_v2

URL = "https://www.skandia.co/consulta-extractos-y-certificados"
NOMBRE_SITIO = "skandia_certificados"
HEADLESS = True

# ---------- SELECTORES ----------
SEL_TIPO = "#_com_skandia_co_certificates_web_portlet_SkandiaCoCertificatesWebPortlet_typeDocument"
SEL_DOC  = "#_com_skandia_co_certificates_web_portlet_SkandiaCoCertificatesWebPortlet_document"
SEL_YEAR = "#_com_skandia_co_certificates_web_portlet_SkandiaCoCertificatesWebPortlet_yearBirth"
SEL_BTN  = "#sendCertificate"

SEL_CAPTCHA_CONTAINER = "[data-sitekey]"
SEL_H3_SUCCESS = "h3:has-text('Tu solicitud ha sido enviada con éxito')"
SEL_H3_FAIL    = "h3:has-text('Tu solicitud ha fallado')"

SITEKEY_FALLBACK = "6Le7iZAgAAAAABS-YU1fbnxjcxEvLtb77q4Z_YvK"

TIPO_MAP = {
    "CC": "C",
    "CE": "E",
    "TI": "T",
    "PA": "P",
    "RC": "R",
}

# ---------- HELPERS ----------
def year_only(fecha):
    if isinstance(fecha, (datetime, date)):
        return f"{fecha.year:04d}"
    if isinstance(fecha, str):
        m = re.search(r"\d{4}", fecha)
        if m:
            return m.group(0)
    return ""

async def crear_resultado(consulta_id, fuente, estado, mensaje, archivo, score):
    await sync_to_async(Resultado.objects.create)(
        consulta_id=consulta_id,
        fuente=fuente,
        estado=estado,
        mensaje=mensaje,
        archivo=archivo,
        score=score,
    )

# ---------- BOT ----------
async def consultar_skandia_certificados(
    consulta_id: int,
    tipo_doc: str,
    numero: str,
    fecha_nacimiento,
):
    fuente = await sync_to_async(Fuente.objects.filter(nombre=NOMBRE_SITIO).first)()
    if not fuente:
        return

    folder_rel = os.path.join("resultados", str(consulta_id))
    folder_abs = os.path.join(settings.MEDIA_ROOT, folder_rel)
    os.makedirs(folder_abs, exist_ok=True)

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    img_name = f"skandia_{numero}_{ts}.png"
    img_abs = os.path.join(folder_abs, img_name)
    img_rel = os.path.join(folder_rel, img_name).replace("\\", "/")

    tipo_val = TIPO_MAP.get((tipo_doc or "").upper(), "C")
    year_val = year_only(fecha_nacimiento)
    numero = str(numero).strip()

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=HEADLESS)
        context = await browser.new_context(locale="es-CO")
        page = await context.new_page()

        try:
            await page.goto(URL, wait_until="domcontentloaded", timeout=45000)

            # Llenar formulario
            await page.select_option(SEL_TIPO, value=tipo_val)
            await page.fill(SEL_DOC, numero)
            await page.fill(SEL_YEAR, year_val)

            # Resolver captcha si existe
            try:
                sitekey = await page.get_attribute(SEL_CAPTCHA_CONTAINER, "data-sitekey")
                if not sitekey:
                    sitekey = SITEKEY_FALLBACK

                token = await resolver_captcha_v2(page.url, sitekey)
                await page.evaluate(
                    """tok=>{
                        let el=document.getElementById('g-recaptcha-response');
                        if(!el){
                            el=document.createElement('textarea');
                            el.id='g-recaptcha-response';
                            el.name='g-recaptcha-response';
                            el.style.display='none';
                            document.body.appendChild(el);
                        }
                        el.value=tok;
                    }""",
                    token,
                )
            except Exception:
                pass

            # Enviar
            await page.click(SEL_BTN)
            await page.wait_for_timeout(1500)

            # Evaluar resultado
            if await page.locator(SEL_H3_SUCCESS).count():
                estado = "Validado"
                mensaje = "Tu solicitud ha sido enviada con éxito"
                score = 1
            elif await page.locator(SEL_H3_FAIL).count():
                estado = "Sin validar"
                mensaje = "Tu solicitud ha fallado"
                score = 0
            else:
                estado = "Sin validar"
                mensaje = "Resultado indeterminado (ver evidencia)"
                score = 0

            await page.screenshot(path=img_abs, full_page=True)

            await crear_resultado(
                consulta_id, fuente, estado, mensaje, img_rel, score
            )

        except Exception as e:
            try:
                await page.screenshot(path=img_abs, full_page=True)
            except Exception:
                pass

            await crear_resultado(
                consulta_id,
                fuente,
                "Sin validar",
                f"{type(e).__name__}: {e}",
                img_rel if os.path.exists(img_abs) else "",
                0,
            )

        finally:
            await context.close()
            await browser.close()
