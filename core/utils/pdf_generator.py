import io

from reportlab.lib.pagesizes import A4
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, Image
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.utils import ImageReader
from PyPDF2 import PdfMerger
from PIL import Image as PILImage
from django.conf import settings
import os

def generar_pdf_consolidado(resultados, consulta_id):
    from core.models import Consulta
    from core.views import generar_mapa_calor_interno, generar_bubble_chart_interno, calcular_riesgo_interno
    import base64
    from io import BytesIO

    consulta = Consulta.objects.select_related('candidato').get(id=consulta_id)
    candidato = consulta.candidato
    BASE_STATIC_IMG = os.path.join(settings.BASE_DIR, "core", "static", "img")
    logo_path = os.path.join(BASE_STATIC_IMG, "logo-removebg-preview.png")
    print(f"[PDF] Ruta logo: {logo_path}")
    print(f"[PDF] Ruta logo: {logo_path}")


    # --- NUEVO: Portada y layout principal con WeasyPrint (consolidado.html + style.css) ---
    from django.template.loader import render_to_string
    from django.contrib.staticfiles import finders
    from weasyprint import HTML, CSS

    css_path = os.path.join(settings.STATIC_ROOT, "css", "style.css")
    if not os.path.exists(css_path):
        raise FileNotFoundError(f"CSS no encontrado en {css_path}")

    riesgo = calcular_riesgo_interno(consulta_id)
    mapa_riesgo = generar_mapa_calor_interno(consulta_id) or ""
    bubble_chart = generar_bubble_chart_interno(consulta_id) or ""

    # Color de riesgo simple (ajústalo como tú lo manejas)
    categoria = (riesgo.get("categoria") or "").lower()
    if "alto" in categoria:
        color_riesgo = "red"
    elif "medio" in categoria:
        color_riesgo = "yellow"
    else:
        color_riesgo = "green"

    html = render_to_string(
        "reportes/consolidado.html",
        {
            "consulta_id": consulta_id,
            "consolidado_id": getattr(getattr(consulta, "consolidado", None), "id", ""),
            "candidato": candidato,
            "resultados": resultados,
            "riesgo": riesgo,
            "color_riesgo": color_riesgo,
            "mapa_riesgo": mapa_riesgo,
            "bubble_chart": bubble_chart,
            # El QR y las capturas se anexan después, no aquí
            "qr_url": "",
            "tipo_reporte": "Consolidado General",
            "fecha_generacion": getattr(consulta, "fecha", None),
            "fecha_actualizacion": getattr(consulta, "fecha", None),
        },
    )

    pdf_html_buffer = io.BytesIO()
    HTML(string=html, base_url=settings.BASE_DIR).write_pdf(
        pdf_html_buffer,
        stylesheets=[CSS(filename=css_path)],
    )
    pdf_html_buffer.seek(0)

    # --- Utilidad: imagen a PDF (Pillow) ---
    def imagen_a_pdf_buffer(path_img):
        img = PILImage.open(path_img).convert("RGB")
        buf = io.BytesIO()
        img.save(buf, format="PDF", resolution=150)
        buf.seek(0)
        return buf

    # --- Utilidad: imagen base64 a PDF (Pillow) ---
    def b64img_a_pdf_buffer(b64data):
        img = PILImage.open(BytesIO(base64.b64decode(b64data))).convert("RGB")
        buf = io.BytesIO()
        img.save(buf, format="PDF", resolution=150)
        buf.seek(0)
        return buf

    pdf_merger = PdfMerger()
    pdf_merger.append(pdf_html_buffer)

    # --- Logo ---
    print(f"[DEBUG] Intentando abrir logo en: {logo_path}")
    if os.path.exists(logo_path):
        print(f"[PDF] Logo encontrado y agregado: {logo_path}")
        pdf_merger.append(imagen_a_pdf_buffer(logo_path))
    else:
        print(f"[PDF] Logo NO encontrado: {logo_path}")

    # --- Avatar según nivel y sexo ---
    sexo = (getattr(candidato, "sexo", "") or "").lower()
    if sexo in ["femenino", "f", "mujer"]:
        foto = "placeholder_femenino_gris.png"
    elif sexo in ["masculino", "m", "hombre"]:
        foto = "placeholder_verde.png"
    else:
        foto = "placeholder.png"
    foto_path = os.path.join(BASE_STATIC_IMG, foto)
    print(f"[DEBUG] Intentando abrir avatar en: {foto_path}")
    if os.path.exists(foto_path):
        print(f"[PDF] Avatar encontrado y agregado: {foto_path}")
        pdf_merger.append(imagen_a_pdf_buffer(foto_path))
    else:
        print(f"[PDF] Avatar NO encontrado: {foto_path}")

    # --- QR (si existe) ---
    if hasattr(consulta, "consolidado") and consulta.consolidado and getattr(consulta.consolidado, "qr", None):
        qr_path = consulta.consolidado.qr.path
        if os.path.exists(qr_path):
            print(f"[PDF] QR encontrado y agregado: {qr_path}")
            pdf_merger.append(imagen_a_pdf_buffer(qr_path))
        else:
            print(f"[PDF] QR NO encontrado: {qr_path}")

    # --- Matriz de calor y bubble chart (usando funciones reales) ---
    import base64
    from PIL import Image as PILImage, ImageDraw, ImageFont

    def imagen_sin_datos(texto="Sin datos"):
        # Crea una imagen PNG simple con el texto "Sin datos"
        img = PILImage.new("RGB", (400, 200), color=(240, 240, 240))
        d = ImageDraw.Draw(img)
        try:
            font = ImageFont.truetype("arial.ttf", 24)
        except Exception:
            font = ImageFont.load_default()
        w, h = d.textsize(texto, font=font)
        d.text(((400-w)/2, (200-h)/2), texto, fill=(80, 80, 80), font=font)
        buf = BytesIO()
        img.save(buf, format="PNG")
        buf.seek(0)
        return base64.b64encode(buf.read()).decode("utf-8")

    # --- Matriz de calor ---
    mapa_b64 = generar_mapa_calor_interno(consulta_id)
    print(f"[DEBUG] Consolidado - mapa_b64: {mapa_b64[:60] if mapa_b64 else 'VACÍO'}")
    if mapa_b64 and mapa_b64.strip() and mapa_b64[:10] == "iVBORw0KGg":
        try:
            pdf_merger.append(b64img_a_pdf_buffer(mapa_b64))
            print("[PDF] Matriz de calor agregada al PDF")
        except Exception as e:
            print(f"[PDF] ERROR agregando matriz de calor: {e}")
    else:
        print("[PDF] matriz de calor VACÍA, nula o inválida. Se agrega imagen de Sin datos.")
        try:
            sin_datos_b64 = imagen_sin_datos("Sin datos - Mapa de calor")
            pdf_merger.append(b64img_a_pdf_buffer(sin_datos_b64))
        except Exception as e:
            print(f"[PDF] ERROR agregando imagen de Sin datos (mapa de calor): {e}")

    # --- Bubble chart ---
    bubble_b64 = generar_bubble_chart_interno(consulta_id)
    print(f"[DEBUG] Consolidado - bubble_b64: {bubble_b64[:60] if bubble_b64 else 'VACÍO'}")
    if bubble_b64 and bubble_b64.strip() and bubble_b64[:10] == "iVBORw0KGg":
        try:
            pdf_merger.append(b64img_a_pdf_buffer(bubble_b64))
            print("[PDF] Bubble chart agregado al PDF")
        except Exception as e:
            print(f"[PDF] ERROR agregando bubble chart: {e}")
    else:
        print("[PDF] bubble chart VACÍO, nulo o inválido. Se agrega imagen de Sin datos.")
        try:
            sin_datos_b64 = imagen_sin_datos("Sin datos - Bubble chart")
            pdf_merger.append(b64img_a_pdf_buffer(sin_datos_b64))
        except Exception as e:
            print(f"[PDF] ERROR agregando imagen de Sin datos (bubble chart): {e}")

    # --- Capturas de imágenes de los resultados ---
    for r in resultados:
        archivo = r.get("archivo")
        if archivo:
            archivo_abs = os.path.join(settings.MEDIA_ROOT, archivo)
            if os.path.exists(archivo_abs):
                print(f"[PDF] Captura encontrada y agregada: {archivo_abs}")
                pdf_merger.append(imagen_a_pdf_buffer(archivo_abs))
            else:
                print(f"[PDF] Captura NO encontrada: {archivo_abs}")

    final_buffer = io.BytesIO()
    pdf_merger.write(final_buffer)
    pdf_merger.close()
    final_buffer.seek(0)
    return final_buffer
