import os
from datetime import datetime
from playwright.async_api import async_playwright
from django.conf import settings
from asgiref.sync import sync_to_async
import traceback

from core.models import Consulta, Resultado, Fuente
from core.resolver.captcha_img import resolver_captcha_imagen

url = "https://www.adres.gov.co/consulte-su-eps"
nombre_sitio = "adres"

TIPO_DOC_MAP = {
    'CC': 'CC', 'TI': 'TI', 'CE': 'CE', 'PA': 'PA', 'RC': 'RC', 'NU': 'NU',
    'AS': 'AS', 'MS': 'MS', 'CD': 'CD', 'CN': 'CN', 'SC': 'SC', 'PE': 'PE', 'PT': 'PT'
}

# ====================================================================
#                          HELPERS BD
# ====================================================================

async def _get_fuente_by_nombre(nombre: str):
    return await sync_to_async(lambda: Fuente.objects.filter(nombre=nombre).first())()

async def _crear_resultado_ok_con_score(consulta_id: int, fuente, relative_path: str, mensaje: str, score: int):
    await sync_to_async(Resultado.objects.create)(
        consulta_id=consulta_id,
        fuente=fuente,
        estado="Validada",
        mensaje=mensaje,
        archivo=relative_path,
        score=score
    )

async def _crear_resultado_error(consulta_id: int, fuente, mensaje: str):
    await sync_to_async(Resultado.objects.create)(
        consulta_id=consulta_id,
        fuente=fuente,
        estado="Sin validar",
        mensaje=mensaje,
        archivo=""
    )

# ====================================================================
#                    DETECCIÓN AUTOMÁTICA DEL IFRAME
# ====================================================================

async def get_iframe_form(pagina):
    """
    Detecta el iframe correcto donde está el formulario de ADRES.
    """
    for f in pagina.frames:
        try:
            u = f.url.lower()
            if "bdua" in u or "afiliado" in u or "consulta" in u:
                return f
        except:
            pass

    try:
        fr = await pagina.frame_locator("iframe#iframe").content_frame()
        if fr:
            return fr
    except:
        pass

    try:
        iframes = pagina.locator("iframe")
        count = await iframes.count()
        for i in range(count):
            fr = await iframes.nth(i).content_frame()
            if fr:
                return fr
    except:
        pass

    return None

# ====================================================================
#            LOCALIZADORES (funcionan dentro del iframe)
# ====================================================================

async def localizar_select_tipo(ctx):
    sels = [
        'select#tipoDoc',
        'select[name="tipoDoc"]'
    ]
    for s in sels:
        try:
            loc = ctx.locator(s)
            if await loc.count() > 0:
                return loc
        except:
            pass

    try:
        loc = ctx.get_by_label("Tipo Documento")
        if await loc.count() > 0:
            return loc
    except:
        pass

    try:
        loc = ctx.locator("text=Tipo Documento").locator("xpath=..").locator("select")
        if await loc.count() > 0:
            return loc
    except:
        pass
    return None


async def localizar_input_num(ctx):
    tries = [
        'input#txtNumDoc',
        'input[name="txtNumDoc"]',
    ]
    for s in tries:
        try:
            loc = ctx.locator(s)
            if await loc.count() > 0:
                return loc
        except:
            pass

    try:
        loc = ctx.get_by_label("Número")
        if await loc.count() > 0:
            return loc
    except:
        pass

    try:
        cand = ctx.locator('input[placeholder*="documento"], input[placeholder*="Documento"]')
        if await cand.count() > 0:
            return cand.nth(0)
    except:
        pass

    return None


async def localizar_img_captcha(ctx):
    sels = [
        'img#Capcha_CaptchaImageUP',
        'img[id*="Captcha"]',
        'img[src*="rca"]',
        'div#Capcha img',
    ]
    for s in sels:
        try:
            loc = ctx.locator(s)
            if await loc.count() > 0:
                return loc.nth(0)
        except:
            pass
    return None

# ====================================================================
#                 EXTRACCIÓN DE MENSAJE Y SCORE
# ====================================================================

async def _extraer_mensaje_y_score(pagina):
    try:
        if await pagina.locator("#PanelNoAfiliado #lblError").is_visible():
            txt = (await pagina.locator("#PanelNoAfiliado #lblError").inner_text()).strip()
            return txt, 6
    except:
        pass

    try:
        if await pagina.locator("#GridViewBasica").is_visible():
            filas = pagina.locator("#GridViewBasica tr")
            n = await filas.count()
            pares = []
            for i in range(1, n):
                celdas = filas.nth(i).locator("td")
                if await celdas.count() >= 2:
                    col = (await celdas.nth(0).inner_text()).strip()
                    val = (await celdas.nth(1).inner_text()).strip()
                    pares.append(f"{col}: {val}")

            if pares:
                mensaje = "Información Básica:\n" + "\n".join(pares)
                return mensaje, 0
    except:
        pass

    return "Resultado obtenido. Revisar captura.", 2

# ====================================================================
#                     BOT PRINCIPAL ADRES
# ====================================================================

async def consultar_adres(consulta_id: int, cedula: str, tipo_doc: str):
    max_intentos = 10

    import time
    def log_tiempo(msg, t0):
        print(f"[BOT ADRES] {msg}: {time.time() - t0:.2f}s")

    try:
        t_inicio = time.time()
        log_tiempo("Inicio consulta_adres", t_inicio)
        await sync_to_async(Consulta.objects.get)(id=consulta_id)
        log_tiempo("Consulta.objects.get", t_inicio)
        fuente = await _get_fuente_by_nombre(nombre_sitio)
        log_tiempo("Fuente obtenida", t_inicio)

        # Leer variables de entorno para headless y slow_mo
        headless_env = os.environ.get("ADRES_HEADLESS", "true").lower()
        headless_flag = headless_env not in ["false", "0", "no"]
        slow_mo_env = os.environ.get("ADRES_SLOW_MO", "0")
        try:
            slow_mo = int(slow_mo_env)
        except Exception:
            slow_mo = 0

        async with async_playwright() as p:
            log_tiempo("Playwright iniciado", t_inicio)
            navegador = await p.chromium.launch(headless=headless_flag, slow_mo=slow_mo)
            log_tiempo("Navegador lanzado", t_inicio)
            contexto = await navegador.new_context()
            log_tiempo("Contexto creado", t_inicio)
            pagina = await contexto.new_page()
            log_tiempo("Página creada", t_inicio)

            await pagina.goto(url, wait_until="networkidle")
            log_tiempo("Página cargada", t_inicio)

            # ───── Obtener iframe del formulario ─────
            form_ctx = await get_iframe_form(pagina)
            log_tiempo("Iframe obtenido", t_inicio)
            if not form_ctx:
                form_ctx = pagina  # fallback

            # ───── Seleccionar tipo documento ─────
            try:
                sel_tipo = await localizar_select_tipo(form_ctx)
                if sel_tipo:
                    await sel_tipo.select_option(TIPO_DOC_MAP.get(tipo_doc.upper(), tipo_doc.upper()))
                    await form_ctx.wait_for_timeout(500)
                log_tiempo("Tipo documento seleccionado", t_inicio)
            except:
                pass

            # ───── Rellenar número ─────
            inp_num = await localizar_input_num(form_ctx)
            log_tiempo("Input número localizado", t_inicio)
            if not inp_num:
                raise Exception("No se encontró input del número de documento.")

            await inp_num.fill(cedula)
            log_tiempo("Número de documento rellenado", t_inicio)

            # ───── Preparar carpetas ─────
            relative_folder = os.path.join("resultados", str(consulta_id))
            absolute_folder = os.path.join(settings.MEDIA_ROOT, relative_folder)
            os.makedirs(absolute_folder, exist_ok=True)
            log_tiempo("Carpetas preparadas", t_inicio)

            pagina_resultado = None

            # =================================================================
            #                        BUCLE CAPTCHA
            # =================================================================
            for intento in range(1, max_intentos + 1):
                log_tiempo(f"Intento captcha {intento}", t_inicio)
                captcha_img = await localizar_img_captcha(form_ctx)
                captcha_path = os.path.join(absolute_folder, "captcha_tmp.png")

                if captcha_img:
                    await captcha_img.screenshot(path=captcha_path)
                else:
                    await form_ctx.screenshot(path=captcha_path)
                log_tiempo("Captcha imagen guardada", t_inicio)

                captcha_text = await resolver_captcha_imagen(captcha_path)
                log_tiempo("Captcha resuelto", t_inicio)

                if not captcha_text:
                    await form_ctx.wait_for_timeout(1200)
                    continue

                try:
                    await form_ctx.fill('input#Capcha_CaptchaTextBox', captcha_text)
                except:
                    await form_ctx.fill('input[name="Capcha$CaptchaTextBox"]', captcha_text)
                log_tiempo("Captcha rellenado", t_inicio)

                # ───── Click y esperar popup ─────
                try:
                    async with pagina.expect_popup(timeout=8000) as pop:
                        await form_ctx.click('input#btnConsultar')
                    pagina_resultado = await pop.value
                    await pagina_resultado.wait_for_load_state("networkidle")
                    log_tiempo("Popup resultado cargado", t_inicio)
                    break
                except:
                    # si no hubo popup, revisar páginas
                    pages = contexto.pages
                    if len(pages) > 1:
                        pagina_resultado = pages[-1]
                        log_tiempo("Resultado por páginas alternas", t_inicio)
                        break

            if pagina_resultado is None:
                pagina_resultado = pagina
            log_tiempo("Página resultado lista", t_inicio)


            # =================================================================
            #                      SOLO SCREENSHOT
            # =================================================================
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            base_name = f"{nombre_sitio}_{cedula}_{timestamp}"

            img_path = os.path.join(absolute_folder, f"{base_name}.png")
            relative_path = os.path.join(relative_folder, f"{base_name}.png")

            screenshot_ok = False
            screenshot_error = None
            t_screenshot = time.time()
            try:
                # tomar screenshot más ligera cuando se pida (full_page puede ser lento)
                full_page_flag = not os.environ.get('DISABLE_SCREENSHOT_FULLPAGE', '').lower() in ['1','true','yes']
                if full_page_flag:
                    await pagina_resultado.screenshot(path=img_path, full_page=True)
                else:
                    await pagina_resultado.screenshot(path=img_path, full_page=False)
                screenshot_ok = os.path.exists(img_path) and os.path.getsize(img_path) > 0
                log_tiempo("Screenshot tomada", t_screenshot)
            except Exception as e:
                screenshot_error = str(e)
                try:
                    await pagina_resultado.screenshot(path=img_path)
                    screenshot_ok = os.path.exists(img_path) and os.path.getsize(img_path) > 0
                    log_tiempo("Screenshot tomada (fallback)", t_screenshot)
                except Exception as e2:
                    screenshot_error = screenshot_error + ' | ' + str(e2)
            # Si el screenshot falló, guardar error en la BD y salir
            if not screenshot_ok:
                log_tiempo(f"Screenshot falló: {screenshot_error}", t_screenshot)
                await navegador.close()
                fuente = await _get_fuente_by_nombre(nombre_sitio)
                await _crear_resultado_error(
                    consulta_id,
                    fuente,
                    f"No se pudo generar la captura de pantalla en ADRES. Error: {screenshot_error}"
                )
                return


            # =================================================================
            #                    EXTRAER MENSAJE Y GUARDAR BD
            # =================================================================
            t_msg = time.time()
            try:
                mensaje_final, score_final = await _extraer_mensaje_y_score(pagina_resultado)
                log_tiempo("Mensaje extraído", t_msg)
            except:
                mensaje_final, score_final = "Resultado obtenido.", 2
                log_tiempo("Mensaje extraído (fallback)", t_msg)

            await navegador.close()
            log_tiempo("Navegador cerrado", t_inicio)

        await _crear_resultado_ok_con_score(
            consulta_id,
            fuente,
            relative_path,
            mensaje_final,
            score_final
        )
        log_tiempo("Resultado guardado en BD", t_inicio)

    except Exception as e:
        tb = traceback.format_exc()
        fuente = await _get_fuente_by_nombre(nombre_sitio)
        await _crear_resultado_error(consulta_id, fuente, str(e) + "\n" + tb)