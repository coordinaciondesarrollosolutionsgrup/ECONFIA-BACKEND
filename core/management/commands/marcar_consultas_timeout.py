from django.core.management.base import BaseCommand
from django.utils import timezone
from core.models import Consulta
from datetime import timedelta

class Command(BaseCommand):
    help = 'Marca como fallidas las consultas que llevan demasiado tiempo en estado en_proceso.'

    def add_arguments(self, parser):
        parser.add_argument('--timeout', type=int, default=11, help='Tiempo máximo en minutos para una consulta en_proceso (default: 11)')

    def handle(self, *args, **options):
        timeout_min = options['timeout']
        limite = timezone.now() - timedelta(minutes=timeout_min)
        consultas = Consulta.objects.filter(estado='en_proceso', fecha__lt=limite)
        total = consultas.count()
        for consulta in consultas:
            consulta.estado = 'fallida'
            consulta.save(update_fields=['estado'])
        self.stdout.write(self.style.SUCCESS(f'{total} consultas marcadas como fallidas por timeout de {timeout_min} minutos.'))
