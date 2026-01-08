import os
import asyncio
import itertools
import inspect
from playwright.async_api import async_playwright
from django.conf import settings
from celery import shared_task
from core.models import Consulta, Resultado, Fuente
from .bots.bot_configs import get_bot_configs
from .bots.bot_configs_contratista import get_bot_configs_contratista
from asgiref.sync import async_to_sync
import requests
import httpx
from time import perf_counter



# General bot runner with hard timeout (customizable)
async def run_bot(bot, timeout=90):
    start = perf_counter()
    try:
        func = bot["func"]
        kwargs = dict(bot.get("kwargs", {}))
        sig = inspect.signature(func)
        if "browser" in sig.parameters:
            kwargs["browser"] = bot.get("browser")
        await asyncio.wait_for(
            func(**kwargs),
            timeout=timeout
        )
    except asyncio.TimeoutError:
        print(f"⛔ BOT {bot.get('name', func.__name__)} cancelado por timeout ({timeout}s)")
    except Exception as e:
        print(f"❌ Error en bot {bot.get('name', func.__name__)}: {e}")
    finally:
        elapsed = perf_counter() - start
        print(f"[BOT] {bot.get('name', func.__name__)} → {elapsed:.2f}s")
  
def chunked(iterable, size):
    """Divide un iterable en listas de tamaño 'size'."""
    it = iter(iterable)
    while True:
        chunk = list(itertools.islice(it, size))
        if not chunk:
            break
        yield chunk

@shared_task
def procesar_consulta(consulta_id, datos):

    def chunked(iterable, size):
        it = iter(iterable)
        while True:
            chunk = list(itertools.islice(it, size))
            if not chunk:
                break
            yield chunk

    consulta = Consulta.objects.get(id=consulta_id)

    if not datos:
        # fallback por si algo falla
        from .consultar_registraduria import consultar_registraduria
        datos = async_to_sync(consultar_registraduria)(consulta.candidato.cedula)

    if not datos:
        consulta.estado = 'no_encontrado'
        consulta.save()
        return

    folder = os.path.join(settings.MEDIA_ROOT, 'resultados', str(consulta_id))
    os.makedirs(folder, exist_ok=True)

    datos.setdefault('rutas', {})


    # --- EJECUTAR TODOS LOS BOTS EN PARALELO EN LOTES, IGUAL QUE CONTRATISTA ---
    bot_configs_all = get_bot_configs(consulta_id, datos)
    total_start = perf_counter()
    async def main_bots():
        try:
            batch_size = int(os.environ.get('BOT_BATCH_SIZE', '50')) if os.environ.get('BOT_BATCH_SIZE') else 50
        except Exception:
            batch_size = 50
        print(f"[task] Ejecutando TODOS los bots en lotes de tamaño={batch_size}")
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            for batch in chunked(bot_configs_all, batch_size):
                batch_start = perf_counter()
                await asyncio.gather(
                    *(run_bot({**bot, "browser": browser}, timeout=60) for bot in batch)
                )
                print(f"[BATCH] terminó en {perf_counter() - batch_start:.2f}s")
            await browser.close()

    async_to_sync(main_bots)()
    print(f"[CONSULTA {consulta_id}] TOTAL → {perf_counter() - total_start:.2f}s")

    # --- SOLO AHORA marcar consulta como completada y generar el PDF/consolidado ---
    consulta = Consulta.objects.get(id=consulta_id)
    consulta.estado = 'completado'
    consulta.save()
    try:
        token = datos.get("duenio_token")
        print(f"[DEBUG] Token recibido para consulta {consulta_id}: '{token}' (procesar_consulta)")
        if not token:
            print(f"[Consolidado] ⚠️ No se encontró 'duenio_token' en datos para consulta {consulta_id}. Usando token vacío.")
        _llamar_consolidado_sincrono(consulta_id, token)
    except Exception as e:
        print(f"[Consolidado] Error general llamando a las APIs de consolidado para consulta {consulta_id}: {e}")
@shared_task


def ejecutar_bot_lento(bot_name, consulta_id, datos):
    """Ejecuta un bot lento en background con timeout duro."""
    import asyncio, inspect
    from time import perf_counter
    from playwright.async_api import async_playwright
    from .bots.bot_configs import get_bot_configs

    # Obtener la instancia de Consulta
    consulta = Consulta.objects.get(id=consulta_id)

    # Reconstruir el bot usando el nombre
    bot_configs = get_bot_configs(consulta_id, datos)
    bot = next((b for b in bot_configs if b["name"] == bot_name), None)
    if not bot:
        print(f"❌ No se encontró configuración para el bot '{bot_name}' en consulta {consulta_id}")
        return

    async def run():
        start = perf_counter()
        try:
            func = bot["func"]
            kwargs = dict(bot.get("kwargs", {}))
            sig = inspect.signature(func)
            async with async_playwright() as p:
                browser = await p.chromium.launch(headless=True)
                if "browser" in sig.parameters:
                    kwargs["browser"] = browser
                await asyncio.wait_for(
                    func(**kwargs),
                    timeout=180
                )
                await browser.close()
        except asyncio.TimeoutError:
            print(f"⛔ BOT {bot.get('name', func.__name__)} cancelado por timeout (180s)")
        except Exception as e:
            print(f"❌ Error en bot {bot.get('name', func.__name__)}: {e}")
        finally:
            elapsed = perf_counter() - start
            print(f"[BOT-LENTO] {bot.get('name', func.__name__)} → {elapsed:.2f}s")
    asyncio.run(run())

    consulta.estado = 'completado'
    consulta.save()

    # Llamada robusta y única a la generación automática del consolidado
    try:
        token = datos.get("duenio_token")
        print(f"[DEBUG] Token recibido para consulta {consulta_id}: '{token}' (procesar_consulta_por_nombres)")
        if not token:
            print(f"[Consolidado] ⚠️ No se encontró 'duenio_token' en datos para consulta {consulta_id}. Usando token vacío.")
        _llamar_consolidado_sincrono(consulta_id, token)
    except Exception as e:
        print(f"[Consolidado] Error general llamando a las APIs de consolidado para consulta {consulta_id}: {e}")
        
@shared_task
def procesar_consulta_por_nombres(consulta_id, datos, lista_nombres):
    def chunked(iterable, size):
        it = iter(iterable)
        while True:
            chunk = list(itertools.islice(it, size))
            if not chunk:
                break
            yield chunk

    consulta = Consulta.objects.get(id=consulta_id)

    if not datos:
        # fallback por si algo falla
        from .consultar_registraduria import consultar_registraduria
        datos = async_to_sync(consultar_registraduria)(consulta.candidato.cedula)

    if not datos:
        consulta.estado = 'no_encontrado'
        consulta.save()
        return

    folder = os.path.join(settings.MEDIA_ROOT, 'resultados', str(consulta_id))
    os.makedirs(folder, exist_ok=True)

    datos.setdefault('rutas', {})

    # Traemos todos los bots
    bot_configs = get_bot_configs(consulta_id, datos)

    # Filtramos por lista de nombres
    bot_configs = [bot for bot in bot_configs if bot["name"] in lista_nombres]

    total_start = perf_counter()
    async def main_bots():
        # Puedes ajustar BOT_BATCH_SIZE en tu entorno para controlar cuántos bots se lanzan en paralelo
        try:
            batch_size = int(os.environ.get('BOT_BATCH_SIZE', '30'))  # Valor por defecto aumentado a 30
        except Exception:
            batch_size = 30
        print(f"[task] Ejecutando bots en lotes de tamaño={batch_size}")
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            for batch in chunked(bot_configs, batch_size):
                batch_start = perf_counter()
                await asyncio.gather(
                    *(run_bot({**bot, "browser": browser}) for bot in batch)
                )
                print(f"[BATCH] terminó en {perf_counter() - batch_start:.2f}s")
            await browser.close()

# === OPTIMIZACIÓN CELERY ===
# Para aprovechar PostgreSQL y hardware moderno, puedes lanzar Celery con más concurrencia:
# celery -A backend worker --loglevel=info --pool=threads --concurrency=8
# O más, según tu CPU/RAM. Ajusta BOT_BATCH_SIZE y la concurrencia de Celery para máximo rendimiento.

    async_to_sync(main_bots)()
    print(f"[CONSULTA {consulta_id}] TOTAL → {perf_counter() - total_start:.2f}s")

    consulta.estado = 'completado'
    consulta.save()



    async def llamar_consolidado( token: str = None):
        headers = {
            "Authorization": f"Token {token}" if token else ""
        }
        print(f"\n\n[DEBUG CONSOLIDADO] Header Authorization que se enviará: '{headers['Authorization']}' para consulta {consulta_id}\n\n")
        urls = [
            f"http://127.0.0.1:8000/api/generar_consolidado/{consulta_id}/1/",
            f"http://127.0.0.1:8000/api/generar_consolidado/{consulta_id}/3/",
        ]
        async with httpx.AsyncClient(timeout=9999) as client:
            results = await asyncio.gather(
                *(client.post(url, headers=headers) for url in urls),
                return_exceptions=True
            )
            for url, r in zip(urls, results):
                if isinstance(r, Exception):
                    print(f"Error llamando a {url}: {r}")
                else:
                    print(f"Consolidado generado en {url}: {r.json()}")

    try:
        token = datos.get("duenio_token")
        async_to_sync(llamar_consolidado)(token)
    except Exception as e:
        print(f"Error general llamando a las APIs: {e}")

        
from celery import shared_task
import asyncio
import httpx
from asgiref.sync import async_to_sync
from django.db import transaction

from core.models import Resultado


@shared_task
def reintentar_bot(resultado_id):
    original = Resultado.objects.get(id=resultado_id)
    consulta = original.consulta
    candidato = consulta.candidato

    # Límite de reintentos
    MAX_REINTENTOS = 2
    if original.intentos >= MAX_REINTENTOS:
        original.estado = "fallido"
        original.mensaje = f"Se alcanzó el máximo de reintentos ({MAX_REINTENTOS}) para este bot."
        original.save()
        return original.mensaje

    # ============================
    # 🔥 FIX 1 — Validar fuente antes de usarla
    # ============================
    if not original.fuente:
        original.estado = "fallido"
        original.mensaje = "El resultado no tiene fuente asignada. No se puede reintentar el bot."
        original.save()
        return original.mensaje

    nombre_fuente = (original.fuente.nombre or "").strip().lower()
    # ============================

    datos = {
        "cedula": candidato.cedula or "",
        "tipo_doc": candidato.tipo_doc or "",
        "nombre": candidato.nombre or "",
        "apellido": candidato.apellido or "",
        "fecha_nacimiento": (
            candidato.fecha_nacimiento.strftime("%Y-%m-%d")
            if getattr(candidato, "fecha_nacimiento", None) else ""
        ),
        "fecha_expedicion": (
            candidato.fecha_expedicion.strftime("%Y-%m-%d")
            if getattr(candidato, "fecha_expedicion", None) else ""
        ),
        "tipo_persona": getattr(candidato, "tipo_persona", "") or "",
        "sexo": getattr(candidato, "sexo", "") or "",
        "email": getattr(candidato, "email", "") or "",
        "error": ""
    }

    bot_configs = get_bot_configs(consulta.id, datos)

    # ============================
    # 🔥 FIX 2 — Comparación segura del nombre del bot
    # ============================
    bot = next((b for b in bot_configs
                if (b.get("name") or "").strip().lower() == nombre_fuente), None)
    # ============================

    # ============================
    # 🔥 FIX 3 — Soporte a bots contratistas (seguro si no existen)
    # ============================
    if not bot:
        try:
            alt_configs = get_bot_configs_contratista(consulta.id, datos)
        except NameError:
            alt_configs = []
        bot = next((b for b in alt_configs
                    if (b.get("name") or "").strip().lower() == nombre_fuente), None)
    # ============================

    # ============================
    # 🔥 FIX 4 — Manejo si no se encuentra config para este bot
    # ============================
    if not bot:
        original.estado = "fallido"
        original.mensaje = (
            f"No se encontró configuración para la fuente '{nombre_fuente}' "
            f"ni en get_bot_configs ni en get_bot_configs_contratista."
        )
        original.save()
        return original.mensaje
    # ============================

    existentes = set(
        Resultado.objects
        .filter(consulta=consulta, fuente=original.fuente)
        .values_list("id", flat=True)
    )

    mensaje_final = ""
    try:
        # Incrementar el contador de reintentos
        original.intentos += 1
        original.save()

        async_to_sync(bot["func"])(**(bot.get("kwargs") or {}))

        nuevos_qs = Resultado.objects.filter(
            consulta=consulta,
            fuente=original.fuente
        ).exclude(id__in=existentes)

        if nuevos_qs.exists():
            nuevo = nuevos_qs.last()
            with transaction.atomic():
                original.delete()
            mensaje_final = f"Se reintentó el bot {nuevo.fuente.nombre}. ID nuevo: {nuevo.id}"
        else:
            original.estado = "fallido"
            original.mensaje = "No se generó un nuevo resultado en el reintento."
            original.save()
            mensaje_final = f"No se creó un nuevo resultado en reintento para {nombre_fuente}"

    except Exception as e:
        original.estado = "fallido"
        original.mensaje = str(e)
        original.save()
        mensaje_final = f"Error al reintentar bot {nombre_fuente}: {e}"

    return mensaje_final


def _llamar_consolidado_sincrono(consulta_id: int, token: str = None):
    """Wrapper síncrono para lanzar las llamadas async a los consolidados."""
    try:
        async_to_sync(_llamar_consolidado_async)(consulta_id, token)
    except Exception as e:
        # No levantamos excepción para no romper la tarea; sólo logueamos.
        print(f"Error general llamando a las APIs de consolidado para consulta {consulta_id}: {e}")


async def _llamar_consolidado_async(consulta_id: int, token: str = None):
    headers = {
        "Authorization": f"Token {token}" if token else ""
    }
    if not token:
        print(f"[Consolidado] ⚠️ No se recibió token para consulta {consulta_id}. El header irá vacío.")
    print(f"\n\n[DEBUG CONSOLIDADO] Header Authorization que se enviará: '{headers['Authorization']}' para consulta {consulta_id}\n\n")
    urls = [
        f"http://127.0.0.1:8000/api/generar_consolidado/{consulta_id}/1/",
        f"http://127.0.0.1:8000/api/generar_consolidado/{consulta_id}/3/",
    ]
    async with httpx.AsyncClient(timeout=600) as client:
        print(f"[DEBUG] Header Authorization enviado: {headers['Authorization']}")
        tasks = [client.post(url, headers=headers) for url in urls]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        for url, r in zip(urls, results):
            if isinstance(r, Exception):
                print(f"[Consolidado] Error llamando a {url}: {r}")
            else:
                try:
                    print(f"[Consolidado] OK {url}: {r.json()}")
                except Exception:
                    print(f"[Consolidado] OK {url}: {r.status_code}")

@shared_task
def procesar_consulta_contratista_por_nombres(consulta_id, datos, lista_nombres):
    async def run_bot(bot):
        try:
            await bot["func"](**bot["kwargs"])
        except Exception as e:
            print(f"Error en bot {bot['func'].__name__}: {e}")

    def chunked(iterable, size):
        it = iter(iterable)
        while True:
            chunk = list(itertools.islice(it, size))
            if not chunk:
                break
            yield chunk

    consulta = Consulta.objects.get(id=consulta_id)
    print(f"[DEBUG TASK] Token recibido en task procesar_consulta_contratista_por_nombres: '{datos.get('duenio_token')}' para consulta {consulta_id}")

    # Fallback si no recibimos datos
    if not datos:
        from .consultar_registraduria import consultar_registraduria
        datos = async_to_sync(consultar_registraduria)(consulta.candidato.cedula)

    if not datos:
        consulta.estado = "no_encontrado"
        consulta.save()
        return

    # Asegurar carpeta de salida
    folder = os.path.join(settings.MEDIA_ROOT, "resultados", str(consulta_id))
    os.makedirs(folder, exist_ok=True)

    datos.setdefault("rutas", {})

    # 1) Traer bots desde la factory de CONTRATISTA
    bot_configs = get_bot_configs_contratista(consulta_id, datos)

    # 2) Filtrar por nombres solicitados
    if lista_nombres:
        bot_configs = [b for b in bot_configs if b["name"] in lista_nombres]

    # 3) Ejecutar en lotes (concurrency control)
    async def main_bots():
        for batch in chunked(bot_configs, 30):
            await asyncio.gather(*(run_bot(b) for b in batch))

    async_to_sync(main_bots)()

    # 4) Marcar consulta como completada
    consulta.estado = "completado"
    consulta.save()

    # Llamada robusta y única a la generación automática del consolidado
    try:
        token = datos.get("duenio_token")
        print(f"[DEBUG] Token recibido para consulta {consulta_id}: '{token}'")
        if not token:
            print(f"[Consolidado] ⚠️ No se encontró 'duenio_token' en datos para consulta {consulta_id}. Usando token vacío.")
        _llamar_consolidado_sincrono(consulta_id, token)
    except Exception as e:
        print(f"[Consolidado] Error general llamando a las APIs de consolidado para consulta {consulta_id}: {e}")