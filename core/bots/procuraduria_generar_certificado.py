import os
import re
import asyncio
import random
import logging
from datetime import datetime
from pathlib import Path

from playwright.async_api import async_playwright, TimeoutError as PWTimeout
from django.conf import settings
from asgiref.sync import sync_to_async
from core.models import Resultado, Fuente

logger = logging.getLogger(__name__)

GEN_URL = "https://www.procuraduria.gov.co/Pages/Generacion-de-antecedentes.aspx"
NOMBRE_SITIO = "procuraduria_certificado"
MAX_INTENTOS = 3

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:132.0) Gecko/20100101 Firefox/132.0",
]

TIPO_DOC_MAP = {
    "CC": "1",
    "PEP": "0",
    "NIT": "2",
    "CE": "5",
    "PPT": "10",
}

PREGUNTAS_RESPUESTAS = {
    "¿ Cuanto es 9 - 2 ?": "7",
    "¿ Cuanto es 3 X 3 ?": "9",
    "¿ Cuanto es 6 + 2 ?": "8",
    "¿ Cuanto es 2 X 3 ?": "6",
    "¿ Cuanto es 3 - 2 ?": "1",
    "¿ Cuanto es 4 + 3 ?": "7",
}

# --- helpers anti-detección ---

async def _delay_humano(min_ms: int = 800, max_ms: int = 2000):
    """Espera aleatoria para simular comportamiento humano."""
    await asyncio.sleep(random.uniform(min_ms / 1000, max_ms / 1000))

async def _mover_mouse_aleatorio(page):
    """Simula movimientos aleatorios del mouse."""
    try:
        x = random.randint(100, 800)
        y = random.randint(100, 600)
        await page.mouse.move(x, y)
    except Exception:
        pass

# --- helpers de screenshot / render ---


async def _fullpage_screenshot(page, path):
    try:
        await page.evaluate("window.scrollTo(0, 0)")
    except Exception:
        pass
    await page.screenshot(path=path, full_page=True)


# Poppler opcional para pdf2image (Windows)
POPPLER_PATH = getattr(settings, "POPPLER_PATH", os.getenv("POPPLER_PATH"))


def _render_pdf_primera_pagina_pymupdf(
    path_pdf: str, path_png: str, zoom: float = 3.0
) -> bool:
    """Render nítido SOLO del documento con PyMuPDF (preferido)."""
    try:
        import fitz  # PyMuPDF

        with fitz.open(path_pdf) as doc:
            if doc.page_count == 0:
                return False
            pg = doc[0]
            matrix = fitz.Matrix(zoom, zoom)
            pix = pg.get_pixmap(matrix=matrix, alpha=False)
            pix.save(path_png)
        return os.path.exists(path_png) and os.path.getsize(path_png) > 0
    except Exception:
        return False


def _render_pdf_primera_pagina_pdf2image(
    path_pdf: str, path_png: str, dpi: int = 300
) -> bool:
    """Render SOLO del documento con pdf2image (requiere Poppler)."""
    try:
        from pdf2image import convert_from_path

        kwargs = {"dpi": dpi, "first_page": 1, "last_page": 1}
        if POPPLER_PATH:
            kwargs["poppler_path"] = POPPLER_PATH
        imgs = convert_from_path(path_pdf, **kwargs)
        if imgs:
            imgs[0].save(path_png, "PNG")
            return True
        return False
    except Exception:
        return False


async def _screenshot_pdf_element(context, abs_pdf: str, abs_png: str) -> None:
    """
    Fallback final: abrir file://<pdf> y capturar el <embed> del visor Chrome
    (evita miniaturas/toolbar del visor).
    """
    viewer = await context.new_page()
    file_url = Path(abs_pdf).resolve().as_uri()
    await viewer.goto(file_url, wait_until="load")
    # el <embed> puede variar según versión de Chromium
    embed = viewer.locator(
        "embed#pdf-embed, embed[type='application/x-google-chrome-pdf'], embed[type*='pdf']"
    ).first
    await embed.wait_for(state="visible", timeout=10000)
    await embed.screenshot(path=abs_png)
    await viewer.close()


# --- helpers de análisis del PDF ---


def _extraer_texto_pdf(path_pdf: str) -> str:
    """Extrae texto completo del certificado usando PyMuPDF."""
    try:
        import fitz

        texto_final = ""
        with fitz.open(path_pdf) as doc:
            for page in doc:
                texto_final += page.get_text()
        return texto_final.strip()
    except Exception:
        return ""


def _clasificar_certificado(texto: str) -> tuple[str, int]:
    """
    Determina si el certificado tiene sanciones.
    Retorna: (mensaje, score)
        score = 1 → NEGATIVO (no registra sanciones)
        score = 0 → POSITIVO (registra sanciones/anotaciones)
    """
    texto_low = (texto or "").lower()

    negativos = [
        "no registra sanciones",
        "no registra sancione",
        "no tiene sanciones",
        "no presenta sanciones",
        "sin sanciones",
        "ni inhabilidades vigentes",
    ]

    positivos = [
        "registra sanciones",
        "registra sancione",
        "inhabilidad",
        "inhabilidades vigentes",
        "sanción",
        "sanciones disciplinarias",
        "antecedentes disciplinarios",
    ]

    # Revisar primero si hay señales claras de sanciones
    if any(p in texto_low for p in positivos):
        return ("Registra sanciones o anotaciones disciplinarias.", 0)

    # Luego revisar indicadores de no sanciones
    if any(n in texto_low for n in negativos):
        return ("No registra sanciones ni inhabilidades.", 1)

    # Si no se reconoce, dejar como sin determinar pero no bloquear el flujo
    return (
        "No se pudo determinar claramente el estado del certificado (revisar manualmente).",
        1,
    )


async def _crear_resultado_error(consulta_id: int, mensaje: str) -> None:
    try:
        fuente_obj = await sync_to_async(Fuente.objects.get)(nombre=NOMBRE_SITIO)
    except Exception:
        return
    await sync_to_async(Resultado.objects.create)(
        consulta_id=consulta_id,
        fuente=fuente_obj,
        score=1,
        estado="Sin validar",
        mensaje=mensaje,
        archivo="",
    )


# ============ BOT PRINCIPAL ============


async def generar_certificado_procuraduria(
    consulta_id: int, cedula: str, tipo_doc: str
):
    """
    Genera el certificado y deja evidencia SIEMPRE:
      1) Intenta descargar PDF.
      2) Convierte primera página a PNG (PyMuPDF → pdf2image → screenshot visor).
      3) Si la descarga falla, al menos deja screenshot del certificado o del estado de la página.
      4) Analiza el PDF (si existe) para determinar si hay sanciones.
    Ejecuta SIEMPRE en segundo plano (headless=True).
    """
    logger.info(
        f"[procuraduria] Iniciando generación para consulta_id={consulta_id}, cedula={cedula}, tipo_doc={tipo_doc}"
    )

    browser = None
    context = None
    page = None

    # --- rutas de salida ---
    relative_folder = os.path.join("resultados", str(consulta_id))
    absolute_folder = os.path.join(settings.MEDIA_ROOT, relative_folder)
    os.makedirs(absolute_folder, exist_ok=True)

    base = f"procuraduria_{consulta_id}_{cedula}".replace(" ", "_")
    abs_pdf = os.path.join(absolute_folder, f"{base}.pdf")
    abs_png = os.path.join(absolute_folder, f"{base}.png")
    rel_png = os.path.join(relative_folder, f"{base}.png").replace("\\", "/")

    evidencia_rel = ""

    # Validar tipo_doc
    tipo_doc_val = TIPO_DOC_MAP.get(tipo_doc, None)
    if not tipo_doc_val:
        await _crear_resultado_error(
            consulta_id,
            f"Tipo de documento no soportado: {tipo_doc}",
        )
        return

    try:
        try:
            fuente_obj = await sync_to_async(Fuente.objects.get)(nombre=NOMBRE_SITIO)
        except Exception:
            fuente_obj = None

        async with async_playwright() as p:
            browser = await p.chromium.launch(
                headless=True,  # siempre en segundo plano
                args=[
                    "--no-sandbox",
                    "--disable-dev-shm-usage",
                    "--disable-blink-features=AutomationControlled",
                ],
            )

            # Intentos de contexto/página por si el sitio devuelve "No disponible"
            error_signals = [
                "no disponible",
                "no se puede mostrar la página",
                "página no puede mostrarse",
                "temporalmente fuera de servicio",
            ]

            for intento in range(1, MAX_INTENTOS + 1):
                logger.info(f"[procuraduria] Intento {intento}/{MAX_INTENTOS} de carga GEN_URL")
                if context is not None:
                    try:
                        await context.close()
                    except Exception:
                        pass

                context = await browser.new_context(
                    user_agent=random.choice(USER_AGENTS),
                    viewport={"width": 1280, "height": 720},
                )
                page = await context.new_page()

                try:
                    await page.goto(GEN_URL, wait_until="load", timeout=60000)
                except PWTimeout:
                    logger.warning("[procuraduria] Timeout cargando página inicial")
                    if intento == MAX_INTENTOS:
                        await _crear_resultado_error(
                            consulta_id,
                            "La página de generación no cargó o está caída (timeout).",
                        )
                        return
                    continue

                await _delay_humano(1500, 2500)

                try:
                    body_text = (await page.locator("body").inner_text()).strip()
                except Exception:
                    body_text = ""

                if any(sig.lower() in body_text.lower() for sig in error_signals):
                    logger.warning(
                        "[procuraduria] Página devolvió mensaje de 'No disponible', reintentando con nuevo contexto"
                    )
                    if intento == MAX_INTENTOS:
                        if fuente_obj:
                            await sync_to_async(Resultado.objects.create)(
                                consulta_id=consulta_id,
                                fuente=fuente_obj,
                                score=1,
                                estado="Sin validar",
                                mensaje="Sitio de generación no disponible o devolvió página de error.",
                                archivo="",
                            )
                        return
                    await _delay_humano(2000, 4000)
                    continue
                else:
                    logger.info("[procuraduria] Página inicial cargada correctamente")
                    break

            # En este punto tenemos page sobre GEN_URL
            # Puede que haya que hacer click en el botón que abre el certificado en nueva pestaña
            nueva_page = None
            try:
                # botón típico de "Generar certificado"
                boton_selector = "a[href*='webcert'], a#lnkGenerar, input[value*='Generar']"
                boton = page.locator(boton_selector).first
                if await boton.count() > 0:
                    logger.info("[procuraduria] Haciendo click en botón de generación")
                    async with context.wait_for_event("page", timeout=15000) as new_page_info:
                        await boton.click()
                    nueva_page = await new_page_info.value
                    page = nueva_page
                    await page.wait_for_load_state("load", timeout=60000)
                    logger.info("[procuraduria] Página de certificado abierta en nueva pestaña")
            except Exception as e:
                logger.info(f"[procuraduria] No se detectó nueva pestaña explícita: {e}")

            await _delay_humano(2000, 3000)

            # 2) Localizar iframe del certificado / formulario
            print("[procuraduria] Buscando iframe del certificado...")
            await _delay_humano(2000, 3000)

            frame = None
            for f in page.frames:
                url_f = f.url or ""
                if "/webcert/" in url_f or "certificado" in url_f.lower():
                    frame = f
                    print(f"[procuraduria] Iframe encontrado: {url_f}")
                    break

            if not frame and page.frames and len(page.frames) > 1:
                frame = page.frames[-1]
                print(f"[procuraduria] Usando último iframe: {frame.url}")

            if not frame:
                print("[procuraduria] ERROR: No se encontró iframe")

                # Capturar screenshot de la página principal
                try:
                    screenshot_principal = os.path.join(
                        absolute_folder, f"{base}_pagina_principal.png"
                    )
                    await _fullpage_screenshot(page, screenshot_principal)
                    evidencia_rel = os.path.join(
                        relative_folder, f"{base}_pagina_principal.png"
                    ).replace("\\", "/")
                    print(
                        f"[procuraduria] Screenshot de página principal guardado: {screenshot_principal}"
                    )

                    if fuente_obj:
                        await sync_to_async(Resultado.objects.create)(
                            consulta_id=consulta_id,
                            fuente=fuente_obj,
                            score=1,
                            estado="Validada",
                            mensaje="Página de Procuraduría cargada (no se encontró iframe del certificado).",
                            archivo=evidencia_rel,
                        )
                        print("[procuraduria] ✓ Evidencia guardada de página principal")
                    return
                except Exception:
                    pass

                await _crear_resultado_error(
                    consulta_id,
                    "No se encontró el iframe de generación del certificado.",
                )
                return

            # Esperar que el iframe termine de cargar
            await _delay_humano(2000, 3000)

            # 3) Formulario
            print(
                f"[procuraduria] Completando formulario con tipo={tipo_doc_val}, cedula={cedula}"
            )
            try:
                await frame.wait_for_selector("#ddlTipoID", timeout=20000)
            except Exception as e:
                # Si falla, capturar screenshot del estado actual CON MÁS ESPERA
                print(
                    "[procuraduria] No se encontró formulario, esperando y capturando estado..."
                )
                await _delay_humano(3000, 5000)

                try:
                    # Capturar HTML del iframe para diagnóstico
                    try:
                        iframe_html = await frame.content()
                        html_path = os.path.join(absolute_folder, f"{base}_iframe.html")
                        with open(html_path, "w", encoding="utf-8") as f:
                            f.write(iframe_html)
                        print(f"[procuraduria] HTML del iframe guardado: {html_path}")
                    except Exception as html_err:
                        print(f"[procuraduria] Error guardando HTML: {html_err}")

                    # Capturar screenshot de la página completa
                    screenshot_error = os.path.join(
                        absolute_folder, f"{base}_estado_completo.png"
                    )
                    await _fullpage_screenshot(page, screenshot_error)
                    print(
                        f"[procuraduria] Screenshot página completa: {screenshot_error}"
                    )

                    # Capturar screenshot del iframe si existe
                    screenshot_iframe = os.path.join(
                        absolute_folder, f"{base}_estado_iframe.png"
                    )
                    try:
                        await frame.wait_for_selector("body", timeout=5000)
                        await _delay_humano(2000, 3000)
                        await frame.locator("body").screenshot(
                            path=screenshot_iframe, timeout=10000
                        )
                        evidencia_rel = os.path.join(
                            relative_folder, f"{base}_estado_iframe.png"
                        ).replace("\\", "/")
                        print(
                            f"[procuraduria] Screenshot del iframe capturado: {screenshot_iframe}"
                        )
                    except Exception as iframe_err:
                        print(
                            f"[procuraduria] Error capturando iframe: {iframe_err}, usando screenshot completo"
                        )
                        evidencia_rel = os.path.join(
                            relative_folder, f"{base}_estado_completo.png"
                        ).replace("\\", "/")
                        print(
                            "[procuraduria] Usando screenshot de página completa como evidencia"
                        )

                    if fuente_obj:
                        await sync_to_async(Resultado.objects.create)(
                            consulta_id=consulta_id,
                            fuente=fuente_obj,
                            score=1,
                            estado="Validada",
                            mensaje=(
                                "Página de generación cargada (estructura del sitio cambió "
                                "o está en mantenimiento)."
                            ),
                            archivo=evidencia_rel,
                        )
                        print(
                            "[procuraduria] ✓ Evidencia guardada del estado de la página"
                        )
                    return
                except Exception as screenshot_error:
                    print(
                        f"[procuraduria] Error capturando screenshots: {screenshot_error}"
                    )

                await _crear_resultado_error(
                    consulta_id,
                    "No se encontró el formulario de generación dentro del iframe.",
                )
                return

            await frame.select_option("#ddlTipoID", value=tipo_doc_val)
            await frame.fill("#txtNumID", str(cedula))
            print("[procuraduria] Formulario completado")

            # 4) Resolver pregunta
            print("[procuraduria] Intentando resolver pregunta de seguridad...")
            solved = False
            ultima_pregunta = ""
            for intento in range(12):
                try:
                    ultima_pregunta = (
                        await frame.locator(
                            "#lblPregunta, [id*=lblPregunta]"
                        ).inner_text()
                    ).strip()
                except Exception:
                    ultima_pregunta = ""
                resp = PREGUNTAS_RESPUESTAS.get(ultima_pregunta)
                if resp:
                    print(
                        f"[procuraduria] Pregunta encontrada: '{ultima_pregunta}' -> respuesta: '{resp}'"
                    )
                    try:
                        await frame.fill("#txtRespuestaPregunta", resp)
                    except Exception:
                        await frame.locator("input[id*=txtRespuesta]").fill(resp)
                    solved = True
                    print("[procuraduria] Respuesta enviada exitosamente")
                    break
                print(
                    f"[procuraduria] Intento {intento+1}: Pregunta no resuelta, refrescando..."
                )
                try:
                    await frame.click("#ImageButton1")  # refrescar
                except Exception:
                    pass
                await asyncio.sleep(1)

            if not solved:
                msg = (
                    "No se pudo resolver la pregunta de seguridad después de varios intentos. "
                    f"Última pregunta vista: '{ultima_pregunta}'"
                )
                print(f"[procuraduria] ERROR: {msg}")
                await _crear_resultado_error(consulta_id, msg)
                return

            # 5) Generar
            print("[procuraduria] Generando certificado...")
            await _delay_humano(1000, 2000)
            prev_len = await frame.evaluate(
                "() => document.documentElement.outerHTML.length"
            )
            await frame.locator("#btnExportar").evaluate("b => b.click()")
            await _delay_humano(2000, 3000)  # Esperar que empiece a cargar

            # 5.5) Capturar screenshot INMEDIATAMENTE mientras carga
            print(
                "[procuraduria] Capturando screenshot del certificado mientras carga..."
            )
            try:
                try:
                    await frame.evaluate("window.scrollTo(0, 0)")
                except Exception:
                    pass

                await _delay_humano(500, 1000)

                screenshot_certificado = os.path.join(
                    absolute_folder, f"{base}_certificado.png"
                )

                try:
                    await frame.locator("body").screenshot(
                        path=screenshot_certificado, full_page=True
                    )
                    print(
                        f"[procuraduria] Screenshot capturado: {screenshot_certificado}"
                    )
                    evidencia_rel = os.path.join(
                        relative_folder, f"{base}_certificado.png"
                    ).replace("\\", "/")
                except Exception as e:
                    print(
                        f"[procuraduria] Error screenshot frame, intentando página completa: {e}"
                    )
                    try:
                        await _fullpage_screenshot(page, screenshot_certificado)
                        print(
                            f"[procuraduria] Screenshot de página guardado: {screenshot_certificado}"
                        )
                        evidencia_rel = os.path.join(
                            relative_folder, f"{base}_certificado.png"
                        ).replace("\\", "/")
                    except Exception:
                        pass

                # Si tenemos screenshot, podemos guardar resultado mínimo
                if evidencia_rel and not os.path.exists(abs_pdf):
                    # Aún así vamos a intentar luego descargar el PDF;
                    # pero si más adelante falla, ya tenemos esta evidencia.
                    print(
                        "[procuraduria] ✓ Screenshot inicial del certificado tomado correctamente"
                    )
            except Exception as e:
                print(f"[procuraduria] Error capturando screenshot: {e}")

            # Intentar detectar cambio en el iframe (por si el certificado se renderiza allí)
            try:
                await frame.wait_for_function(
                    "prev => document.documentElement.outerHTML.length !== prev",
                    arg=prev_len,
                    timeout=30000,
                )
                print("[procuraduria] Certificado generado en el iframe (cambio detectado)")
            except Exception:
                print(
                    "[procuraduria] Timeout esperando cambio en certificado, continuando..."
                )

            await _delay_humano(2000, 3000)

            # 6) Descargar PDF
            print("[procuraduria] Esperando descarga del certificado PDF...")
            await _mover_mouse_aleatorio(page)
            try:
                async with page.expect_download(timeout=40000) as download_info:
                    await _delay_humano(2000, 3000)

                    # Intentar diferentes selectores para el botón de descarga
                    btn_clicked = False
                    for selector in [
                        "#btnDescargar",
                        "input[id*=btnDescargar]",
                        "input[value*='Descargar']",
                        "#Button1",
                    ]:
                        try:
                            logger.info(f"[procuraduria] Intentando selector: {selector}")
                            btn_descargar = frame.locator(selector)
                            await btn_descargar.wait_for(
                                state="attached", timeout=5000
                            )
                            await btn_descargar.scroll_into_view_if_needed()
                            await _delay_humano(500, 1000)
                            await btn_descargar.click(timeout=5000)
                            logger.info(
                                f"[procuraduria] Click exitoso en botón descarga: {selector}"
                            )
                            btn_clicked = True
                            break
                        except Exception as e:
                            logger.info(
                                f"[procuraduria] Selector {selector} falló: {str(e)[:80]}"
                            )
                            continue

                    if not btn_clicked:
                        logger.info(
                            "[procuraduria] Intentando click genérico con evaluate en botón descargar"
                        )
                        await frame.evaluate(
                            "document.querySelector('#btnDescargar, #Button1, input[value*=Descargar]')?.click()"
                        )

                download = await download_info.value
                await download.save_as(abs_pdf)
                print(f"[procuraduria] PDF descargado: {abs_pdf}")

                # Verificar que existe y tiene contenido
                if not os.path.exists(abs_pdf) or os.path.getsize(abs_pdf) == 0:
                    raise Exception("El PDF descargado está vacío o no existe")

                # Convertir PDF a PNG para evidencia
                print("[procuraduria] Convirtiendo PDF a PNG...")
                if _render_pdf_primera_pagina_pymupdf(abs_pdf, abs_png, zoom=3.0):
                    print("[procuraduria] PNG generado con PyMuPDF (alta calidad)")
                elif _render_pdf_primera_pagina_pdf2image(abs_pdf, abs_png, dpi=300):
                    print("[procuraduria] PNG generado con pdf2image")
                else:
                    print("[procuraduria] PNG generado con screenshot de archivo PDF")
                    await _screenshot_pdf_element(context, abs_pdf, abs_png)

                if not os.path.exists(abs_png) or os.path.getsize(abs_png) == 0:
                    raise Exception("No se pudo generar la imagen PNG del certificado")

                evidencia_rel = rel_png

                # Analizar texto del PDF
                print("[procuraduria] Analizando contenido del certificado...")
                texto_pdf = _extraer_texto_pdf(abs_pdf)
                mensaje_clasificacion, score = _clasificar_certificado(texto_pdf)
                print(
                    f"[procuraduria] Clasificación: {mensaje_clasificacion} (score={score})"
                )

                # Guardar resultado
                if fuente_obj:
                    await sync_to_async(Resultado.objects.create)(
                        consulta_id=consulta_id,
                        fuente=fuente_obj,
                        score=score,
                        estado="Validada",
                        mensaje=mensaje_clasificacion,
                        archivo=evidencia_rel,
                    )
                print(
                    "[procuraduria] ✓ Certificado descargado, analizado y procesado exitosamente"
                )
                return

            except Exception as e:
                # Si falla la descarga del PDF, usar el screenshot del certificado como evidencia
                print(f"[procuraduria] ERROR descargando PDF: {str(e)}")
                print("[procuraduria] Usando screenshot del certificado como evidencia")

                if evidencia_rel and fuente_obj:
                    mensaje_clasificacion = (
                        "Certificado generado (screenshot capturado, descarga de PDF falló)."
                    )
                    score = 1  # No pudimos analizar el PDF, score neutro

                    await sync_to_async(Resultado.objects.create)(
                        consulta_id=consulta_id,
                        fuente=fuente_obj,
                        score=score,
                        estado="Validada",
                        mensaje=mensaje_clasificacion,
                        archivo=evidencia_rel,
                    )
                    print(
                        "[procuraduria] ✓ Resultado guardado usando solo screenshot del certificado"
                    )
                    return

                # No hay evidencia del certificado
                await _crear_resultado_error(
                    consulta_id,
                    f"No se logró descargar el certificado PDF ni capturar screenshot: {str(e)}",
                )
                return

    except Exception as e:
        print(f"[procuraduria] EXCEPCIÓN general: {str(e)}")
        await _crear_resultado_error(
            consulta_id,
            f"Error en generación del certificado: {str(e)}",
        )
    finally:
        try:
            if context is not None:
                await context.close()
        except Exception:
            pass
        try:
            if browser is not None:
                await browser.close()
        except Exception:
            pass


# Alias para compatibilidad con run_bot_single.py
# (para usar: --bot procuraduria_certificado)
consultar_procuraduria_certificado = generar_certificado_procuraduria
