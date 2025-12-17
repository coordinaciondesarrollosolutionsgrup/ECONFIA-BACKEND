import sys
import os

# Asegura que la raíz del proyecto esté en el path
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "backend.settings")

import django
django.setup()

from core.models import Fuente, TipoFuente
from core.bots.plantilla import FUENTES

tipo_default, _ = TipoFuente.objects.get_or_create(nombre="General")

for nombre_bd in set(FUENTES.values()):
    obj, created = Fuente.objects.get_or_create(nombre=nombre_bd, defaults={'tipo': tipo_default})
    if created:
        print(f"Fuente creada: {nombre_bd}")
    else:
        print(f"Fuente ya existía: {nombre_bd}")