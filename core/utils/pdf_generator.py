import io
from reportlab.lib.pagesizes import A4
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, Image
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet
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
    static_img = os.path.join(settings.STATIC_ROOT, "img")
    logo_path = os.path.join(static_img, "logo.jpg")

    styles = getSampleStyleSheet()
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4)
    elements = []

    # --- Logo ---
    if os.path.exists(logo_path):
        elements.append(Image(logo_path, width=100, height=100))
    elements.append(Spacer(1, 12))

    # --- Datos del candidato ---
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

    # --- Imagen del candidato según sexo/riesgo ---
    if getattr(candidato, "sexo", "").lower() in ["femenino", "f", "mujer"]:
        foto_path = os.path.join(static_img, "placeholder_femenino_gris.png")
    else:
        foto_path = os.path.join(static_img, "placeholder_verde.png")
    if not os.path.exists(foto_path):
        foto_path = os.path.join(static_img, "placeholder.png")
    if os.path.exists(foto_path):
        elements.append(Image(foto_path, width=100, height=100))
        elements.append(Spacer(1, 12))

    # --- QR (si existe) ---
    if hasattr(consulta, "consolidado") and consulta.consolidado and getattr(consulta.consolidado, "qr", None):
        qr_path = consulta.consolidado.qr.path
        if os.path.exists(qr_path):
            elements.append(Image(qr_path, width=100, height=100))
            elements.append(Spacer(1, 12))

    # --- Matriz de calor y bubble chart (usando funciones reales) ---
    # Matriz de calor
    mapa_b64 = generar_mapa_calor_interno(consulta_id)
    mapa_img = BytesIO(base64.b64decode(mapa_b64))
    elements.append(Paragraph("<b>Mapa de calor</b>", styles["Heading3"]))
    elements.append(Image(mapa_img, width=250, height=180))
    elements.append(Spacer(1, 12))
    # Bubble chart
    bubble_b64 = generar_bubble_chart_interno(consulta_id)
    bubble_img = BytesIO(base64.b64decode(bubble_b64))
    elements.append(Paragraph("<b>Bubble chart</b>", styles["Heading3"]))
    elements.append(Image(bubble_img, width=250, height=180))
    elements.append(Spacer(1, 12))

    # --- Tabla de resultados ---
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

    # --- Capturas de imágenes de los resultados (si existen) ---
    for r in resultados:
        archivo = r.get("archivo")
        if archivo and os.path.exists(archivo):
            elements.append(Paragraph(f"Captura de {r['fuente']}", styles["Heading3"]))
            elements.append(Image(archivo, width=250, height=180))
            elements.append(Spacer(1, 12))

    doc.build(elements)
    buffer.seek(0)
    return buffer
