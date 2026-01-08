import os
import aiohttp
import asyncio
from datetime import datetime
from django.conf import settings

from playwright.async_api import async_playwright
from asgiref.sync import sync_to_async

from core.resolver.captcha_img2 import resolver_captcha_imagen
from core.models import Resultado, Fuente

import cv2
import numpy as np
import fitz  # PyMuPDF
import traceback


URL = "https://ruaf.sispro.gov.co/Filtro.aspx?AspxAutoDetectCookieSupport=1"
NOMBRE_SITIO = "ruaf"

TIPO_DOC_MAP = {
    'CC': '5|CC', 'PA': '6|PA', 'AS': '7|AS', 'CD': '10|CD',
    'CN': '12|CN', 'SC': '13|SC', 'PE': '14|PE', 'PT': '15|PT',
    'MS': '1|MS', 'RC': '2|RC', 'TI': '3|TI', 'CE': '4|CE'
}


def preprocesar_captcha(ruta_origen, ruta_destino):
    """Resalta las letras negras sobre fondo verde."""
    img = cv2.imread(ruta_origen)
    if img is None:
        return
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    lower_green = np.array([35, 40, 40])
    upper_green = np.array([85, 255, 255])
    mask = cv2.inRange(hsv, lower_green, upper_green)
    letras_negras = cv2.bitwise_not(mask)
    cv2.imwrite(ruta_destino, letras_negras)


def pdf_a_imagen(pdf_path, output_path, dpi=200):
    """Convierte la primera página de un PDF en PNG usando PyMuPDF."""
    doc = fitz.open(pdf_path)
    pagina = doc[0]
    pix = pagina.get_pixmap(dpi=dpi)
    pix.save(output_path)
    doc.close()


async def _aceptar_terminos(page):
    """
    Acepta el modal de términos y condiciones si aparece.
    Es robusto: prueba varios selectores típicos.
    """
    print("⏳ Verificando modal de Términos y Condiciones...")

    try:
        # Buscamos algún checkbox típico del modal
        chk_selectors = [
            '#MainContent_chkPoliticas',
            '#MainContent_chkAcepto',
            'input[type="checkbox"][id*="chk"]',
        ]

        checkbox = None
        for sel in chk_selectors:
            if await page.locator(sel).count() > 0:
                checkbox = sel
                break

        if not checkbox:
            print("ℹ No se detectó modal de términos (posiblemente ya aceptado).")
            return

        print(f"✔ Checkbox de términos encontrado: {checkbox}")
        await page.click(checkbox)

        await asyncio.sleep(0.5)

        # Buscar botón de aceptar
        btn_selectors = [
            '#MainContent_btnAceptar',
            'input[id*="btnAceptar"]',
            'input[type="submit"][value*="Aceptar"]',
            'button:has-text("Aceptar")',
        ]

        btn = None
        for sel in btn_selectors:
            if await page.locator(sel).count() > 0:
                btn = sel
                break

        if not btn:
            print("⚠ No se encontró botón de Aceptar, se continúa de todas formas.")
            return

        print(f"✔ Botón de Aceptar encontrado: {btn}")
        await page.click(btn)

        # Esperar a que desaparezca el botón (el modal se cierra)
        try:
            await page.locator(btn).wait_for(state="detached", timeout=15000)
        except Exception:
            pass

        print("✔ Términos aceptados correctamente.")

    except Exception as e:
        print(f"⚠ Error aceptando términos, se continúa de todas formas: {e}")


async def consultar_ruaf(cedula, tipo_doc, consulta_id, fecha_expedicion=None):
    """
    Bot RUAF:
    - Acepta términos
    - Entra al iframe del formulario
    - Llenar datos
    - Resolver captcha y validar
    - Descargar PDF, convertir a PNG
    - Guardar Resultado en BD
    """
    # Reducir intentos para evitar bloqueos
    import time
    import random
    MAX_INTENTOS = 2
    MAX_INTENTOS_CAPTCHA = 2
    CAPTCHA_FALLBACK_API_KEY = os.environ.get('CAPTCHA_API_KEY')  # Para servicios externos
    CAPTCHA_FALLBACK_PROVIDER = os.environ.get('CAPTCHA_PROVIDER', '2captcha')

    async def resolver_captcha_externo(captcha_path, api_key, provider='2captcha'):
        """
        Resuelve el captcha usando un servicio externo (2Captcha).
        """
        if provider == '2captcha':
            # 1. Subir imagen
            url_in = 'http://2captcha.com/in.php'
            url_res = 'http://2captcha.com/res.php'
            async with aiohttp.ClientSession() as session:
                with open(captcha_path, 'rb') as f:
                    data = {
                        'key': api_key,
                        'method': 'post',
                        'json': 1
                    }
                    files = {'file': f}
                    resp = await session.post(url_in, data=data, files=files)
                    result = await resp.json()
                if result.get('status') != 1:
                    print(f"[2Captcha] Error al subir captcha: {result}")
                    return ''
                captcha_id = result['request']
                # 2. Esperar y consultar resultado
                for _ in range(20):
                    await asyncio.sleep(5)
                    params = {'key': api_key, 'action': 'get', 'id': captcha_id, 'json': 1}
                    resp = await session.get(url_res, params=params)
                    result = await resp.json()
                    if result.get('status') == 1:
                        return result['request']
                    if result.get('request') == 'CAPCHA_NOT_READY':
                        continue
                    else:
                        print(f"[2Captcha] Error: {result}")
                        break
        return ''

    relative_folder = os.path.join('resultados', str(consulta_id))
    absolute_folder = os.path.join(settings.MEDIA_ROOT, relative_folder)
    os.makedirs(absolute_folder, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    fuente_obj = await sync_to_async(Fuente.objects.filter(nombre=NOMBRE_SITIO).first)()

    # Normalizar fecha de expedición a dd/mm/YYYY
    # Si no se proporciona, usar la fecha de hoy
    if fecha_expedicion is None:
        fecha_str = datetime.now().strftime("%Y-%m-%d")
    elif isinstance(fecha_expedicion, datetime):
        fecha_str = fecha_expedicion.strftime("%Y-%m-%d")
    elif hasattr(fecha_expedicion, "strftime"):
        fecha_str = fecha_expedicion.strftime("%Y-%m-%d")
    else:
        fecha_str = str(fecha_expedicion)

    fecha_formateada = datetime.strptime(fecha_str, "%Y-%m-%d").strftime("%d/%m/%Y")

    tipo_documento_val = TIPO_DOC_MAP.get(str(tipo_doc).upper())
    if not tipo_documento_val:
        raise ValueError(f"Tipo de documento no válido: {tipo_doc}")

    navegador = None
    page = None

    # Rotación de user-agent para cada intento
    user_agents = [
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:118.0) Gecko/20100101 Firefox/118.0",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:119.0) Gecko/20100101 Firefox/119.0",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:120.0) Gecko/20100101 Firefox/120.0",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/118.0.5993.70 Safari/537.36",
    ]
    random.shuffle(user_agents)

    for intento_general in range(1, MAX_INTENTOS + 1):
        t0_intento = time.time()
        try:
            print(f"🔄 [RUAF] Intento general {intento_general}/{MAX_INTENTOS}")
            navegador_tipo = 'firefox' if intento_general % 2 == 1 else 'chromium'
            async with async_playwright() as p:
                navegador = await getattr(p, navegador_tipo).launch(headless=True)
                ua = user_agents[intento_general % len(user_agents)]
                page = await navegador.new_page(user_agent=ua)
                await page.context.clear_cookies()
                await page.mouse.move(100, 200)
                # Agregar headers realistas y rotar referer
                referers = ["https://www.google.com/", "https://www.bing.com/", "https://duckduckgo.com/"]
                await page.set_extra_http_headers({
                    "Accept-Language": "es-ES,es;q=0.9",
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                    "Referer": random.choice(referers),
                })
                await page.goto(URL, wait_until="domcontentloaded", timeout=40000)
                await _aceptar_terminos(page)
                print("⏳ Esperando formulario RUAF...")
                frame_locator = None
                iframe_count = await page.locator('iframe').count()
                print(f"ℹ Número de iframes encontrados: {iframe_count}")
                if iframe_count > 0:
                    for i in range(min(iframe_count, 5)):
                        iframe_id = await page.locator('iframe').nth(i).get_attribute('id')
                        iframe_name = await page.locator('iframe').nth(i).get_attribute('name')
                        print(f"  - iframe[{i}]: id='{iframe_id}', name='{iframe_name}'")
                    frame_locator = page.frame_locator('iframe').nth(0)
                    print("✅ Usando primer iframe encontrado")
                if not frame_locator:
                    print("⚠ No se encontró iframe, buscando campos en la página principal...")
                    select_count = await page.locator('select').count()
                    print(f"ℹ Selectores encontrados en página: {select_count}")
                    if select_count > 0:
                        frame_locator = page
                        print("✅ Usando página principal para buscar campos")
                    else:
                        raise Exception("No se encontró formulario (ni iframe ni selectores en página principal)")
                await frame_locator.locator('#MainContent_txbNumeroIdentificacion').wait_for(state="visible", timeout=20000)
                print("✏ Llenando formulario...")
                select_candidates = [
                    '#ddlTiposDocumentos',
                    'select[id*="ddlTipos"]',
                    'select[id*="TiposDocumentos"]',
                    'select'
                ]
                select_selector = None
                for sel in select_candidates:
                    if await frame_locator.locator(sel).count() > 0:
                        select_selector = sel
                        break
                if not select_selector:
                    raise Exception("No se encontró el selector de tipo de documento dentro del iframe")
                await frame_locator.locator(select_selector).select_option(tipo_documento_val)
                await frame_locator.locator('#MainContent_txbNumeroIdentificacion').fill(cedula)
                await frame_locator.locator('#MainContent_datepicker').fill(fecha_formateada)
                await page.keyboard.press("Escape")
                # 5) Intentos de captcha
                for intento_captcha in range(1, MAX_INTENTOS_CAPTCHA + 1):
                    t0_captcha = time.time()
                    print(f"🔐 Intento captcha {intento_captcha}/{MAX_INTENTOS_CAPTCHA}")
                    captcha_path = os.path.join(absolute_folder, f"captcha_{NOMBRE_SITIO}_{intento_general}_{intento_captcha}.png")
                    await frame_locator.locator('img[src*="Captcha"]').wait_for(state="visible", timeout=7000)
                    await frame_locator.locator('img[src*="Captcha"]').screenshot(path=captcha_path)
                    preprocesar_captcha(captcha_path, captcha_path)
                    captcha_texto = await resolver_captcha_imagen(captcha_path)
                    # Fallback externo si falla el captcha local
                    if (not captcha_texto or len(captcha_texto) < 4) and CAPTCHA_FALLBACK_API_KEY:
                        print("[Captcha] Usando fallback externo...")
                        captcha_texto = await resolver_captcha_externo(captcha_path, CAPTCHA_FALLBACK_API_KEY, CAPTCHA_FALLBACK_PROVIDER)

                    import asyncio

                    async def procesar_batch_ruaf(lista_consultas, batch_size=5):
                        """
                        Procesa un batch de consultas RUAF en paralelo usando asyncio.gather.
                        lista_consultas: lista de tuplas (cedula, tipo_doc, consulta_id, fecha_expedicion)
                        batch_size: máximo de consultas simultáneas
                        """
                        resultados = []
                        for i in range(0, len(lista_consultas), batch_size):
                            batch = lista_consultas[i:i+batch_size]
                            tasks = [consultar_ruaf(*args) for args in batch]
                            batch_result = await asyncio.gather(*tasks, return_exceptions=True)
                            resultados.extend(batch_result)
                        return resultados

                    # Ejemplo de uso:
                    # lista = [("123", "CC", 1, "2000-01-01"), ("456", "CC", 2, "2001-01-01")]
                    # asyncio.run(procesar_batch_ruaf(lista, batch_size=3))

                    # Guardar captchas fallidos para análisis
                    if not captcha_texto or len(captcha_texto) < 4:
                        fail_path = captcha_path.replace('.png', '_fail.png')
                        os.rename(captcha_path, fail_path)
                        print(f"[Captcha] Guardado captcha fallido en {fail_path}")
                    else:
                        try:
                            os.remove(captcha_path)
                        except FileNotFoundError:
                            pass
                    await frame_locator.locator('#MainContent_txtCaptcha').fill(captcha_texto)
                    await frame_locator.locator('#MainContent_btnVerify').click()
                    await asyncio.sleep(0.7)  # Espera mínima para respuesta
                    mensaje = (await frame_locator.locator('#MainContent_lblMessage').inner_text()).strip()
                    print(f"ℹ Mensaje captcha: {mensaje}")
                    t_captcha = time.time() - t0_captcha
                    print(f"[Captcha] Tiempo de intento: {t_captcha:.2f}s")
                    if "bloqueado" in mensaje.lower() or "demasiados" in mensaje.lower():
                        print("⚠ Detectado posible bloqueo, limpiando cookies y cambiando navegador...")
                        await page.context.clear_cookies()
                        await navegador.close()
                        await asyncio.sleep(10)
                        break
                    if "Inválido" in mensaje or "Invalido" in mensaje:
                        print("❌ Captcha inválido, recargando...")
                        await frame_locator.locator('img[src*="Captcha"]').click()
                        await asyncio.sleep(0.5)
                        continue
                    if "Válido" in mensaje or "Valido" in mensaje:
                        print("✅ Captcha válido, consultando...")
                        await frame_locator.locator('#MainContent_btnConsultar').click()
                        export_btn_selector = 'a#ctl00_MainContent_rvConsulta_ctl09_ctl04_ctl00_ButtonLink'
                        await frame_locator.locator(export_btn_selector).wait_for(state="visible", timeout=15000)
                        await frame_locator.locator(export_btn_selector).click()
                        pdf_link_selector = 'a.ActiveLink[title="PDF"]'
                        await frame_locator.locator(pdf_link_selector).wait_for(state="visible", timeout=9000)
                        async with page.expect_download() as descarga_info:
                            await frame_locator.locator(pdf_link_selector).click()
                        descarga = await descarga_info.value
                        pdf_path = os.path.join(
                            absolute_folder,
                            f"{NOMBRE_SITIO}_{cedula}_{timestamp}.pdf"
                        )
                        await descarga.save_as(pdf_path)
                        imagen_path = pdf_path.replace(".pdf", ".png")
                        pdf_a_imagen(pdf_path, imagen_path)
                        if fuente_obj:
                            await sync_to_async(Resultado.objects.create)(
                                consulta_id=consulta_id,
                                fuente=fuente_obj,
                                score=0,
                                estado="Validado",
                                mensaje="",
                                archivo=os.path.join(relative_folder, os.path.basename(imagen_path))
                            )
                        await navegador.close()
                        t_intento = time.time() - t0_intento
                        print(f"✅ Consulta RUAF finalizada correctamente en {t_intento:.2f}s.")
                        return
                    print("⚠ Mensaje captcha no reconocido, reintentando...")
                    await frame_locator.locator('img[src*="Captcha"]').click()
                    await asyncio.sleep(0.5)
                print("⚠ Fallo captcha en todos los intentos.")
                await navegador.close()
                await asyncio.sleep(2)
        except Exception as e:
            tb = traceback.format_exc()
            print(f"❌ Error intento general {intento_general}: {e}\n{tb}")
            if intento_general == MAX_INTENTOS:
                error_screenshot = os.path.join(
                    absolute_folder,
                    f"{NOMBRE_SITIO}_{cedula}_{timestamp}_error.png"
                )
                try:
                    if page:
                        await page.screenshot(path=error_screenshot, full_page=False)
                    else:
                        raise Exception("No hay page para screenshot")
                except Exception:
                    img_blank = np.ones((400, 600, 3), dtype=np.uint8) * 255
                    cv2.putText(
                        img_blank,
                        "Error en la consulta RUAF",
                        (50, 200),
                        cv2.FONT_HERSHEY_SIMPLEX,
                        1,
                        (0, 0, 0),
                        2,
                        cv2.LINE_AA
                    )
                    cv2.imwrite(error_screenshot, img_blank)
                if fuente_obj:
                    mensaje_err = f"No se pudo realizar la consulta en el momento. Error: {str(e)}"
                    tb_snippet = (tb or '').strip()[:1500]
                    if tb_snippet:
                        mensaje_err = mensaje_err + "\nTraceback:\n" + tb_snippet
                    await sync_to_async(Resultado.objects.create)(
                        consulta_id=consulta_id,
                        fuente=fuente_obj,
                        score=0,
                        estado="Sin validar",
                        mensaje=mensaje_err,
                        archivo=os.path.join(relative_folder, os.path.basename(error_screenshot))
                    )
        finally:
            try:
                if navegador:
                    await navegador.close()
            except Exception:
                pass
        t_intento = time.time() - t0_intento
        print(f"[RUAF] Tiempo total del intento {intento_general}: {t_intento:.2f}s")
    print("⚠ RUAF: no fue posible realizar la consulta en ninguno de los intentos.")
                