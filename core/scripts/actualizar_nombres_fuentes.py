"""
Script para actualizar los nombres de las fuentes en la base de datos.
Mapea nombres técnicos a nombres oficiales/legibles.
"""

from core.models import Fuente

# Mapeo de nombres técnicos a nombres oficiales
NOMBRES_FUENTES = {
    # ... (mapeo completo, copiar del original) ...
}

def actualizar_nombres_fuentes(dry_run=True):
    fuentes_actualizadas = 0
    fuentes_no_encontradas = []
    print(f"\n{'=' * 80}")
    print(f"{'MODO DRY RUN - SOLO VISTA PREVIA' if dry_run else 'MODO ACTUALIZACIÓN - APLICANDO CAMBIOS'}")
    print(f"{'=' * 80}\n")
    for nombre_tecnico, nombre_oficial in NOMBRES_FUENTES.items():
        try:
            fuente = Fuente.objects.get(nombre=nombre_tecnico)
            nombre_anterior = fuente.nombre_pila
            if nombre_anterior != nombre_oficial:
                print(f"✓ {nombre_tecnico}")
                print(f"  Anterior: {nombre_anterior}")
                print(f"  Nuevo:    {nombre_oficial}")
                print()
                if not dry_run:
                    fuente.nombre_pila = nombre_oficial
                    fuente.save()
                fuentes_actualizadas += 1
        except Fuente.DoesNotExist:
            fuentes_no_encontradas.append(nombre_tecnico)
    print(f"\n{'=' * 80}")
    print(f"RESUMEN:")
    print(f"  - Fuentes actualizadas: {fuentes_actualizadas}")
    print(f"  - Fuentes no encontradas en BD: {len(fuentes_no_encontradas)}")
    if fuentes_no_encontradas and len(fuentes_no_encontradas) <= 20:
        print(f"\nFuentes no encontradas:")
        for nombre in fuentes_no_encontradas:
            print(f"  - {nombre}")
    print(f"{'=' * 80}\n")
    return fuentes_actualizadas, fuentes_no_encontradas

# Función para django-extensions

def run():
    # Aplica los cambios solo para los nombres técnicos que están en el mapeo oficial
    fuentes_actualizadas = 0
    fuentes_no_encontradas = []
    for nombre_tecnico, nombre_oficial in NOMBRES_FUENTES.items():
        try:
            fuente = Fuente.objects.get(nombre=nombre_tecnico)
            if fuente.nombre_pila != nombre_oficial:
                fuente.nombre_pila = nombre_oficial
                fuente.save()
                fuentes_actualizadas += 1
        except Fuente.DoesNotExist:
            fuentes_no_encontradas.append(nombre_tecnico)
    print(f"Fuentes actualizadas: {fuentes_actualizadas}")
    if fuentes_no_encontradas:
        print(f"Fuentes no encontradas en BD: {len(fuentes_no_encontradas)}")
