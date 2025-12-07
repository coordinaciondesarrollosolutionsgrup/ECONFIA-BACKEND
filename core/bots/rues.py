import os
from datetime import datetime
from playwright.async_api import async_playwright
from django.conf import settings
from asgiref.sync import sync_to_async
from core.models import Resultado, Fuente
from PIL import Image

nombre_sitio = "rues"
MAX_INTENTOS = 3

async def consultar_rues(cedula, consulta_id):
    url = f"https://www.rues.org.co/buscar/RM/{cedula}"
    
    # Carpeta de resultados
    relative_folder = os.path.join('resultados', str(consulta_id))
    absolute_folder = os.path.join(settings.MEDIA_ROOT, relative_folder)
    os.makedirs(absolute_folder, exist_ok=True)
    
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    hallazgos_count = 0

    fuente_obj = await sync_to_async(Fuente.objects.filter(nombre=nombre_sitio).first)()

    for intento in range(1, MAX_INTENTOS + 1):
        try:
            async with async_playwright() as p:
                navegador = await p.chromium.launch(headless=True)
                pagina = await navegador.new_page()
                await pagina.goto(url)

                # 1) Obtener todas las opciones del select
                select = pagina.locator("select.select-type-index").first
                opciones = await select.locator("option").all_text_contents()

                for opcion in opciones[:-1]:  # excluye la última
                    await select.select_option(label=opcion)
                    await pagina.wait_for_timeout(500)
                    btn_buscar = pagina.locator("button.btn-busqueda:visible")
                    await btn_buscar.scroll_into_view_if_needed()
                    await btn_buscar.click()
                    await pagina.wait_for_timeout(3000)

                    # Verificar si hay mensaje de "No se encontraron resultados"
                    no_result = await pagina.locator(
                        "div.alert.alert-info:has-text('No se encontraron resultados')"
                    ).count()

                    if no_result:
                        mensaje = f"No se encontraron hallazgos en {opcion}."
                        score = 0
                    else:
                        mensaje = f"Se encontraron hallazgos en {opcion}."
                        hallazgos_count += 1
                        score = 10

                    # Tomar pantallazo individual
                    temp_name = f"{nombre_sitio}_{cedula}_{opcion}_{timestamp}.png"
                    temp_path = os.path.join(absolute_folder, temp_name)
                    await pagina.screenshot(path=temp_path)
                    relative_path = os.path.join(relative_folder, temp_name)

                    # Guardar cada resultado individualmente
                    if fuente_obj:
                        await sync_to_async(Resultado.objects.create)(
                            consulta_id=consulta_id,
                            fuente=fuente_obj,
                            score=score,
                            estado="Validado",
                            mensaje=mensaje,
                            archivo=relative_path
                        )

                await navegador.close()
                break  # si tuvo éxito, salimos del bucle de intentos

        except Exception as e:
            # Guardar pantallazo del error
            error_name = f"{nombre_sitio}_{cedula}_{timestamp}_error.png"
            error_path = os.path.join(absolute_folder, error_name)
            if 'pagina' in locals():
                try:
                    await pagina.screenshot(path=error_path)
                except Exception:
                    error_path = ""
            if intento == MAX_INTENTOS:
                if fuente_obj:
                    await sync_to_async(Resultado.objects.create)(
                        consulta_id=consulta_id,
                        fuente=fuente_obj,
                        score=0,
                        estado="Sin validar",
                        mensaje=f"Fallo después de {MAX_INTENTOS} intentos: {str(e)}",
                        archivo=error_path
                    )
