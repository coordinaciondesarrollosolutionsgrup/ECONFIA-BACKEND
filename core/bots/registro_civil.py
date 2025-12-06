import os
import traceback
from datetime import datetime
from playwright.async_api import async_playwright
from django.conf import settings
from asgiref.sync import sync_to_async
from django.core.files import File as DjangoFile
from core.resolver.captcha_img2 import resolver_captcha_imagen
from core.models import Resultado, Fuente

url = "https://consultasrc.registraduria.gov.co:28080/ProyectoSCCRC/"
nombre_sitio = "registro_civil"
MAX_INTENTOS = 3

def _crear_resultado_guardando_archivo(absolute_path, screenshot_name, relative_path,
                                      consulta_id, fuente_obj, score, mensaje_error):
    """
    Crea y guarda un Resultado. Si resultado.archivo es FileField, usa .save().
    Si es CharField/TextField, guarda la ruta relativa como string.
    """
    resultado = Resultado(
        consulta_id=consulta_id,
        fuente=fuente_obj,
        score=score,
        estado="Validado",
        mensaje=mensaje_error
    )

    if absolute_path and os.path.exists(absolute_path):
        archivo_attr = getattr(resultado, 'archivo', None)
        if archivo_attr is not None and hasattr(archivo_attr, 'save'):
            with open(absolute_path, "rb") as f:
                django_file = DjangoFile(f)
                resultado.archivo.save(screenshot_name, django_file, save=True)
        else:
            # Guardar ruta relativa (la app que consuma debe usar MEDIA_URL + resultado.archivo)
            resultado.archivo = relative_path
            resultado.save()
    else:
        resultado.save()

    return resultado

def _crear_resultado_error(error_screenshot_path, consulta_id, fuente_obj, mensaje_error):
    resultado = Resultado(
        consulta_id=consulta_id,
        fuente=fuente_obj,
        score=0,
        estado="Sin validar",
        mensaje=mensaje_error
    )

    if error_screenshot_path and os.path.exists(error_screenshot_path):
        archivo_attr = getattr(resultado, 'archivo', None)
        filename = os.path.basename(error_screenshot_path)
        if archivo_attr is not None and hasattr(archivo_attr, 'save'):
            with open(error_screenshot_path, "rb") as f:
                django_file = DjangoFile(f)
                resultado.archivo.save(filename, django_file, save=True)
        else:
            relative = os.path.join('resultados', str(consulta_id), filename)
            resultado.archivo = relative
            resultado.save()
    else:
        resultado.save()

    return resultado

async def consultar_registro_civil(cedula, consulta_id, sexo="SIN INFORMACION", headless=True):
    relative_folder = os.path.join('resultados', str(consulta_id))
    absolute_folder = os.path.join(settings.MEDIA_ROOT, relative_folder)
    os.makedirs(absolute_folder, exist_ok=True)

    fuente_obj = await sync_to_async(lambda: Fuente.objects.filter(nombre=nombre_sitio).first())()
    intento_global = 0

    while intento_global < MAX_INTENTOS:
        intento_global += 1
        browser = None
        context = None
        page = None
        try:
            async with async_playwright() as p:
                browser = await p.chromium.launch(
                    headless=headless,
                    args=["--no-sandbox", "--disable-dev-shm-usage"]
                )
                context = await browser.new_context(
                    ignore_https_errors=True,
                    user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                               "(KHTML, like Gecko) Chrome/115.0 Safari/537.36"
                )
                page = await context.new_page()
                page.set_default_timeout(60000)

                await page.goto(url, wait_until="networkidle", timeout=60000)

                # Capturas tempranas para depuración
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                early_screenshot = os.path.join(absolute_folder, f"early_{nombre_sitio}_{cedula}_{timestamp}.png")
                await page.screenshot(path=early_screenshot, full_page=True)
                early_html_path = os.path.join(absolute_folder, f"early_{nombre_sitio}_{cedula}_{timestamp}.html")
                with open(early_html_path, "w", encoding="utf-8") as f:
                    f.write(await page.content())

                # Intentar click en main frame o en iframes
                selector_control = 'input[id="controlador:consultasId"]'
                clicked = False
                try:
                    await page.wait_for_selector(selector_control, timeout=60000)
                    await page.click(selector_control)
                    clicked = True
                except Exception:
                    for frame in page.frames:
                        try:
                            await frame.wait_for_selector(selector_control, timeout=5000)
                            await frame.click(selector_control)
                            clicked = True
                            break
                        except Exception:
                            continue

                if not clicked:
                    for i, frame in enumerate(page.frames):
                        try:
                            frame_html = await frame.content()
                            frame_html_path = os.path.join(absolute_folder, f"frame_{i}_{cedula}_{timestamp}.html")
                            with open(frame_html_path, "w", encoding="utf-8") as fh:
                                fh.write(frame_html)
                        except Exception:
                            pass
                    raise RuntimeError("Selector controlador:consultasId no encontrado en main frame ni en iframes.")

                await page.wait_for_timeout(2000)
                await page.select_option('select[id="searchForm:tiposBusqueda"]', 'DOCUMENTO (NUIP/NIP/Tarjeta de Identidad)')
                if sexo != "SIN INFORMACION":
                    await page.select_option('select#searchForm\\:sexo', sexo)

                await page.fill('input[id="searchForm:documento"]', cedula)
                await page.wait_for_timeout(1000)

                # Captcha
                captcha = page.locator("img[src*='kaptcha.jpg']")
                await captcha.wait_for(timeout=30000)
                captcha_src = await captcha.get_attribute("src")
                if captcha_src.startswith("http"):
                    captcha_url = captcha_src
                else:
                    captcha_url = f"https://consultasrc.registraduria.gov.co:28080{captcha_src}"
                response = await page.request.get(captcha_url)
                image_bytes = await response.body()
                captcha_path = os.path.join(absolute_folder, f"captcha_{nombre_sitio}_{cedula}_{timestamp}.png")
                with open(captcha_path, "wb") as f:
                    f.write(image_bytes)

                captcha_resultado = await resolver_captcha_imagen(captcha_path)
                await page.fill('input[id="searchForm:inCaptcha"]', captcha_resultado)
                await page.click('input[id="searchForm:busquedaRCX"]')
                await page.wait_for_timeout(5000)

                # Revisar mensajes
                div_captcha_error = page.locator("div[id='searchForm:j_idt76'] ul li")
                mensaje_error = ""
                if await div_captcha_error.count() > 0:
                    texto_error = (await div_captcha_error.inner_text()).strip()
                    if "no corresponde con la imagen de verificación" in texto_error.lower():
                        print(f"[Intento {intento_global}] Captcha incorrecto, reintentando...")
                        await context.close()
                        await browser.close()
                        continue
                    elif "no se han encontrado registros en la base de datos" in texto_error.lower():
                        mensaje_error = texto_error
                        score = 0
                    else:
                        mensaje_error = texto_error
                        score = 0
                else:
                    mensaje_error = "La persona se encuentra registrada"
                    score = 0

                # Screenshot final
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                screenshot_name = f"{nombre_sitio}_{cedula}_{timestamp}.png"
                absolute_path = os.path.join(absolute_folder, screenshot_name)
                relative_path = os.path.join(relative_folder, screenshot_name)
                await page.screenshot(path=absolute_path, full_page=True)

                # Guardar resultado (adaptativo según tipo de campo 'archivo')
                await sync_to_async(_crear_resultado_guardando_archivo)(
                    absolute_path, screenshot_name, relative_path,
                    consulta_id, fuente_obj, score, mensaje_error
                )

                await context.close()
                await browser.close()
                return

        except Exception as e:
            tb = traceback.format_exc()
            print(f"[Intento {intento_global}] Error: {e}\n{tb}")

            error_screenshot = ""
            try:
                if page and not page.is_closed():
                    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                    error_screenshot = os.path.join(absolute_folder, f"{nombre_sitio}_{cedula}_{timestamp}_error.png")
                    await page.screenshot(path=error_screenshot, full_page=True)
            except Exception as e2:
                print("No se pudo tomar screenshot de error:", e2)

            if intento_global == MAX_INTENTOS:
                await sync_to_async(_crear_resultado_error)(
                    error_screenshot, consulta_id, fuente_obj,
                    f"Error tras {MAX_INTENTOS} intentos: {str(e)}"
                )

        finally:
            try:
                if page and not page.is_closed():
                    try:
                        await page.close()
                    except Exception:
                        pass
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
            except Exception:
                pass
