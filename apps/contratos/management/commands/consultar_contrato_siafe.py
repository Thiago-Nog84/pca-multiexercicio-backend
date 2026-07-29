"""
Management command: consultar_contrato_siafe
=================================================
Utilitário de investigação (somente leitura, não toca no banco): consulta
a API do SIAFE-PI para um ou mais codigo_siafe e imprime TODOS os campos
brutos devolvidos — inclui `processo`, datas, situação, parcelas, aditivos
etc. Útil pra resolver casos de auditoria sem precisar abrir o dashboard
do SIAFE.

Uso:
  python manage.py consultar_contrato_siafe --codigo 25018267 --exercicio 2025
  python manage.py consultar_contrato_siafe --codigo 25018267 25017590 --exercicio 2025
  python manage.py consultar_contrato_siafe --pk 106       # pega codigo_siafe/exercicio do próprio Contrato
  python manage.py consultar_contrato_siafe --pk 106 161 176
"""

from django.core.management.base import BaseCommand, CommandError

from apps.contratos.models import Contrato
from apps.siafe.client import SiafeClient, SiafeAPIError


class Command(BaseCommand):
    help = "Consulta e imprime os campos brutos de um contrato no SIAFE (somente leitura)"

    def add_arguments(self, parser):
        parser.add_argument("--codigo", nargs="+", help="Um ou mais codigo_siafe")
        parser.add_argument("--exercicio", type=int, help="Obrigatório se usar --codigo")
        parser.add_argument("--pk", type=int, nargs="+", help="Um ou mais pk de Contrato (pega codigo_siafe/exercício sozinho)")

    def handle(self, *args, **options):
        client = SiafeClient()

        consultas = []  # (label, codigo, exercicio)

        if options["pk"]:
            for pk in options["pk"]:
                try:
                    c = Contrato.objects.get(pk=pk)
                except Contrato.DoesNotExist:
                    self.stdout.write(self.style.WARNING(f"pk={pk} não existe"))
                    continue
                if not c.codigo_siafe:
                    self.stdout.write(self.style.WARNING(f"pk={pk} ({c.numero_contrato}) não tem codigo_siafe"))
                    continue
                exercicio = c.data_assinatura.year if c.data_assinatura else c.exercicio
                consultas.append((f"pk={pk} ({c.numero_contrato})", c.codigo_siafe, exercicio))

        if options["codigo"]:
            if not options["exercicio"]:
                raise CommandError("--exercicio é obrigatório junto com --codigo")
            for codigo in options["codigo"]:
                consultas.append((f"codigo={codigo}", codigo, options["exercicio"]))

        if not consultas:
            raise CommandError("Use --pk ou --codigo/--exercicio")

        for label, codigo, exercicio in consultas:
            self.stdout.write(self.style.MIGRATE_HEADING(f"\n=== {label} — codigo_siafe={codigo} (exercício {exercicio}) ==="))
            try:
                data = client.contrato(exercicio, codigo)
            except SiafeAPIError as exc:
                self.stdout.write(self.style.WARNING(f"ERRO API: {exc}"))
                continue
            if not isinstance(data, dict) or not data:
                self.stdout.write(self.style.WARNING("resposta vazia"))
                continue
            for k, v in data.items():
                self.stdout.write(f"  {k}: {v!r}")
