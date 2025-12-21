import os

# Ruta base del proyecto (ajusta si tu estructura cambia)
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATIC_IMG_DIR = os.path.join(BASE_DIR, 'core', 'static', 'img')

archivos = [
    'logo-removebg-preview.png',
    'placeholder_verde.png',
    'placeholder_femenino_gris.png',
    'placeholder.png',
]

print(f"Buscando archivos en: {STATIC_IMG_DIR}\n")
for archivo in archivos:
    ruta = os.path.join(STATIC_IMG_DIR, archivo)
    if os.path.exists(ruta):
        print(f"[OK] {archivo} encontrado.")
    else:
        print(f"[FALTA] {archivo} NO encontrado.")
