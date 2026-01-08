import os
import re
import unicodedata
import logging
import random
import asyncio
from datetime import datetime
from pathlib import Path
from core.resolver.captcha_v2 import resolver_captcha_v2

from django.conf import settings
from asgiref.sync import sync_to_async
from playwright.async_api import async_playwright, TimeoutError


from core.models import Resultado, Fuente

NOMBRE_SITIO = "colfondos_cert_afiliacion"
URL = "https://www.colfondos.com.co/dxp/personas/pensiones-obligatorias/certificado-afiliacion"

# Ajusta a tus tipos (Colfondos maneja varios)
TIPO_DOC_MAP = {
    "CC": "Cédula de Ciudadanía",
    "CE": "Cédula de Extranjería",
    "NIT": "Nit",
    "RC": "Registro Civil",
    "PA": "Pasaporte",
    "TI": "Tarjeta de Identidad",
    "PEP": "Permiso especial de permanencia",
    "PPT": "Protección Temporal",
}

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

def _safe(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "")).strip()

async def _click_if_exists(page, selectors, timeout=2000):
    for sel in selectors:
        try:
            loc = page.locator(sel)
            if await loc.count() > 0:
                await loc.first.click(timeout=timeout)
                return True
        except Exception:
            pass
    return False

async def consultar_colfondos_cert_afiliacion(cedula: str, tipo_doc: str, consulta_id: int):
    """
    Colfondos: formulario web (React) donde ingresas tipo y número de documento
    y normalmente envía certificado al correo registrado.
    Evidencia: screenshot + mensaje en Resultado.
    """
    relative_folder = os.path.join("resultados", str(consulta_id))
    absolute_folder = os.path.join(settings.MEDIA_ROOT, relative_folder)
    os.makedirs(absolute_folder, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")

    fuente_obj = await sync_to_async(Fuente.objects.filter(nombre=NOMBRE_SITIO).first)()
    # Obtener el objeto Consulta correspondiente
    from core.models import Consulta
    consulta_obj = await sync_to_async(Consulta.objects.get)(id=consulta_id)

    tipo_label = TIPO_DOC_MAP.get(str(tipo_doc).upper())
    if not tipo_label:
        raise ValueError(f"Tipo de documento no válido para Colfondos: {tipo_doc}")

    # Mapeo de valores para el select real
    SELECT_VALUE_MAP = {
        "Cédula de Ciudadanía": "C.C",
        "Cédula de Extranjería": "C.E",
        "Nit": "NIT",
        "Registro Civil": "R.C",
        "Pasaporte": "PAS",
        "Tarjeta de Identidad": "T.I",
        "Permiso especial de permanencia": "PEP",
        "Protección Temporal": "P.T",
    }
    tipo_value = SELECT_VALUE_MAP.get(tipo_label)
    if not tipo_value:
        raise ValueError(f"No se encontró el valor para el tipo de documento: {tipo_label}")

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(user_agent=UA, locale="es-CO")
        page = await context.new_page()

        try:
            await page.goto(URL, wait_until="domcontentloaded", timeout=60000)

            # Cookies (si sale)
            await _click_if_exists(page, [
                'button:has-text("Aceptar")',
                'text=Aceptar',
                'button#onetrust-accept-btn-handler',
            ])

            # Esperar que aparezca el formulario (inputs/select)
            # Colfondos es React: buscamos un select y un input de documento
            await page.wait_for_timeout(1500)


            # 1) Seleccionar tipo de documento
            await page.wait_for_selector('#select_TipoDoc', timeout=10000)
            await page.select_option('#select_TipoDoc', value=tipo_value)

            # 2) Llenar número de documento
            await page.wait_for_selector('#input_Identificacion', timeout=10000)
            await page.fill('#input_Identificacion', str(cedula))


            # 2.5) Resolver reCAPTCHA si existe
            try:
                # Buscar el sitekey en el iframe o div del captcha
                iframe = await page.query_selector('iframe[title="reCAPTCHA"]')
                if iframe:
                    src = await iframe.get_attribute('src')
                    import urllib.parse
                    params = urllib.parse.parse_qs(urllib.parse.urlparse(src).query)
                    sitekey = params.get('k', [None])[0]
                    print(f"[Colfondos] Sitekey detectado: {sitekey}")
                    if sitekey:
                        # Simular click en el iframe del captcha para mayor realismo
                        try:
                            box = await iframe.bounding_box()
                            if box:
                                await page.mouse.click(box['x'] + box['width']/2, box['y'] + box['height']/2)
                                await page.wait_for_timeout(1000)
                        except Exception as click_ex:
                            print(f"[Colfondos] No se pudo simular click en el captcha: {click_ex}")
                        token = await resolver_captcha_v2(sitekey, page.url)
                        print(f"[Colfondos] Token captcha recibido: {token}")
                        # Inyectar el token en todos los textareas con clase g-recaptcha-response y disparar eventos
                        await page.evaluate('''(token) => {
                            let textareas = document.querySelectorAll('textarea.g-recaptcha-response');
                            textareas.forEach(ta => {
                                ta.value = token;
                                ta.innerHTML = token;
                                ta.dispatchEvent(new Event('input', { bubbles: true }));
                                ta.dispatchEvent(new Event('change', { bubbles: true }));
                            });
                        }''', token)
                        # Esperar más tiempo para que el JS procese el token
                        await page.wait_for_timeout(4000)
                        # Verificar si el iframe del captcha sigue visible
                        iframe_visible = await page.evaluate('''() => {
                            const iframe = document.querySelector('iframe[title="reCAPTCHA"]');
                            if (!iframe) return false;
                            const style = window.getComputedStyle(iframe);
                            return style && style.display !== 'none' && style.visibility !== 'hidden' && iframe.offsetParent !== null;
                        }''')
                        print(f"[Colfondos] ¿Iframe captcha sigue visible tras inyección?: {iframe_visible}")
            except Exception as ex:
                print(f"[Colfondos] Error resolviendo captcha: {ex}")


            # 3) Botón enviar certificación (input con id)
            await page.wait_for_selector('#btnSendCertification', timeout=10000)
            await page.click('#btnSendCertification')

            # 4) Esperar feedback (toast / texto)
            await page.wait_for_timeout(2500)

            # Captura evidencia
            shot_path = os.path.join(absolute_folder, f"{NOMBRE_SITIO}_{cedula}_{ts}.png")
            await page.screenshot(path=shot_path, full_page=True)

            mensaje = "Solicitud de certificado enviada / generada (ver evidencia)."
            # Intentar capturar texto de confirmación si existe
            try:
                # Buscar un texto típico de confirmación
                candidates = [
                    "text=te enviaremos el certificado",
                    "text=correo",
                    "text=solicitud",
                    "text=confirmación",
                    "text=exitos",
                ]
                for c in candidates:
                    if await page.locator(c).count() > 0:
                        mensaje = _safe(await page.locator(c).first.inner_text())
                        break
            except Exception:
                pass

            if fuente_obj:
                await sync_to_async(Resultado.objects.create)(
                    consulta=consulta_obj,
                    fuente=fuente_obj,
                    score=0,
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
                    consulta=consulta_obj,
                    fuente=fuente_obj,
                    score=0,
                    estado="Sin validar",
                    mensaje=f"Error Colfondos certificado afiliación: {e}",
                    archivo=os.path.join(relative_folder, os.path.basename(err_path)),
                )
        finally:
            await context.close()
            await browser.close()
