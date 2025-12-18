import os
import re
import asyncio
from datetime import datetime

from django.conf import settings
from asgiref.sync import sync_to_async
from playwright.async_api import async_playwright, TimeoutError as PWTimeout

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

    tipo_label = TIPO_DOC_MAP.get(str(tipo_doc).upper())
    if not tipo_label:
        raise ValueError(f"Tipo de documento no válido para Colfondos: {tipo_doc}")

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

            # 1) Abrir selector tipo doc (robusto)
            # Intento A: <select>
            select_candidates = [
                "select",
                'select[name*="document"]',
                'select[id*="document"]',
                'select[id*="tipo"]',
            ]
            selected = False
            for sel in select_candidates:
                try:
                    if await page.locator(sel).count() > 0:
                        await page.locator(sel).first.select_option(label=tipo_label)
                        selected = True
                        break
                except Exception:
                    pass

            # Intento B: combobox (div role=combobox)
            if not selected:
                # abrir dropdown
                await page.locator('[role="combobox"]').first.click(timeout=8000)
                await page.locator(f'text={tipo_label}').first.click(timeout=8000)

            # 2) Número documento
            input_candidates = [
                'input[type="text"]',
                'input[inputmode="numeric"]',
                'input[placeholder*="Número"]',
                'input[aria-label*="Número"]',
            ]
            doc_input = None
            for sel in input_candidates:
                if await page.locator(sel).count() > 0:
                    doc_input = page.locator(sel).first
                    break
            if not doc_input:
                raise Exception("No se encontró el input de número de documento (Colfondos).")

            await doc_input.fill(str(cedula))

            # 3) Botón generar/enviar
            btn_candidates = [
                'button:has-text("Generar")',
                'button:has-text("Enviar")',
                'button:has-text("Solicitar")',
                'button:has-text("Continuar")',
                'input[type="submit"]',
            ]
            clicked = False
            for sel in btn_candidates:
                try:
                    if await page.locator(sel).count() > 0:
                        await page.locator(sel).first.click(timeout=12000)
                        clicked = True
                        break
                except Exception:
                    pass
            if not clicked:
                raise Exception("No se encontró botón para generar/enviar certificado (Colfondos).")

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
                    consulta_id=consulta_id,
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
                    consulta_id=consulta_id,
                    fuente=fuente_obj,
                    score=0,
                    estado="Sin validar",
                    mensaje=f"Error Colfondos certificado afiliación: {e}",
                    archivo=os.path.join(relative_folder, os.path.basename(err_path)),
                )
        finally:
            await context.close()
            await browser.close()
