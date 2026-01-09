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

    # --- Logo como base64 ---
    def file_to_base64(path):
        try:
            with open(path, "rb") as f:
                return base64.b64encode(f.read()).decode()
        except Exception as e:
            print(f"[WARN] No se pudo abrir {path}: {e}")
            return ""
    logo_b64 = file_to_base64(logo_path) if os.path.exists(logo_path) else ""

    # --- Avatar como base64 ---
    sexo = (getattr(candidato, "sexo", "") or "").lower()
    if sexo in ["femenino", "f", "mujer"]:
        foto = "placeholder_femenino_gris.png"
    elif sexo in ["masculino", "m", "hombre"]:
        foto = "placeholder_verde.png"
    else:
        foto = "placeholder.png"
    foto_path = os.path.join(BASE_STATIC_IMG, foto)
    print(f"[PDF] Ruta avatar: {foto_path}")
    avatar_b64 = file_to_base64(foto_path) if os.path.exists(foto_path) else ""

    styles = getSampleStyleSheet()
    buffer_pdf_base = io.BytesIO()
    doc = SimpleDocTemplate(buffer_pdf_base, pagesize=A4)
    elements = []

    # --- Solo texto: datos del candidato y tabla ---
    datos = f"""
    <b>{candidato.nombre} {candidato.apellido}</b><br/>
    Cédula: {candidato.cedula}<br/>
    Sexo: {getattr(candidato, 'sexo', '')}<br/>
    Fecha de nacimiento: {getattr(candidato, 'fecha_nacimiento', '')}<br/>
    Fecha expedición: {getattr(candidato, 'fecha_expedicion', '')}<br/>
    Tipo persona: {getattr(candidato, 'tipo_persona', '')}<br/>
    """
    elements.append(Paragraph(datos, styles["Normal"]))
    elements.append(Spacer(1, 12))

    elements.append(Paragraph("<b>Resultados</b>", styles["Heading2"]))
    data = [["Fuente", "Tipo", "Estado", "Score", "Mensaje"]]
    for r in resultados:
        data.append([r["fuente"], r["tipo_fuente"], r["estado"], str(r["score"]), r["mensaje"]])
    table = Table(data, colWidths=[100, 80, 100, 50, 200])
    table.setStyle(TableStyle([
        ("BACKGROUND", (0,0), (-1,0), colors.grey),
        ("TEXTCOLOR", (0,0), (-1,0), colors.whitesmoke),
        ("ALIGN", (0,0), (-1,-1), "CENTER"),
        ("GRID", (0,0), (-1,-1), 0.5, colors.black),
        ("FONTNAME", (0,0), (-1,0), "Helvetica-Bold"),
    ]))
    elements.append(table)

    doc.build(elements)
    buffer_pdf_base.seek(0)

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
    pdf_merger.append(buffer_pdf_base)

    # Logo y avatar ahora están disponibles como logo_b64 y avatar_b64 para usar en HTML/PDF como data:image/png;base64

    # --- QR (si existe) ---
    if hasattr(consulta, "consolidado") and consulta.consolidado and getattr(consulta.consolidado, "qr", None):
        qr_path = consulta.consolidado.qr.path
        if os.path.exists(qr_path):
            print(f"[PDF] QR encontrado y agregado: {qr_path}")
            pdf_merger.append(imagen_a_pdf_buffer(qr_path))
        else:
            print(f"[PDF] QR NO encontrado: {qr_path}")

    # --- Matriz de calor y bubble chart (usando funciones reales) ---
    mapa_b64 = generar_mapa_calor_interno(consulta_id)
    print(f"[PDF] matriz de calor base64: {len(mapa_b64) if mapa_b64 else 0} bytes")
    if mapa_b64:
        try:
            pdf_merger.append(b64img_a_pdf_buffer(mapa_b64))
            print("[PDF] Matriz de calor agregada al PDF")
        except Exception as e:
            print(f"[PDF] ERROR agregando matriz de calor: {e}")
    else:
        print("[PDF] matriz de calor VACÍA o nula")

    bubble_b64 = generar_bubble_chart_interno(consulta_id)
    print(f"[PDF] bubble chart base64: {len(bubble_b64) if bubble_b64 else 0} bytes")
    if bubble_b64:
        try:
            pdf_merger.append(b64img_a_pdf_buffer(bubble_b64))
            print("[PDF] Bubble chart agregado al PDF")
        except Exception as e:
            print(f"[PDF] ERROR agregando bubble chart: {e}")
    else:
        print("[PDF] bubble chart VACÍO o nulo")

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