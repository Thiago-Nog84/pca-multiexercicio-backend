"""
Management command: resincronizar_contrato_siafe
=====================================================
Refaz a busca de UM contrato específico (por pk) na API do SIAFE-PI usando
o codigo_siafe já cadastrado, e corrige os campos que tiverem divergido do
que o SIAFE realmente diz — valor, numero_sei (a partir de numProcesso),
data_assinatura, data_inicio_vigencia, data_fim_vigencia.

Nasceu do caso pk=155 (auditoria [duplicados], grupo CNPJ 02687493000105):
dois contratos DIFERENTES da mesma empresa (camisetas × brindes) foram
agrupados como "possível duplicata" porque o valor e o numero_sei do
contrato de camisetas (pk=155) estavam, por engano, com os dados do
contrato de brindes (pk=163) — objeto e numero_contrato/codigo_siafe
estavam corretos, só valor/SEI/data é que vieram trocados. Este comando
resolve esse tipo de inconsistência re-perguntando ao SIAFE.

Por segurança, só sobrescreve numero_sei se estiver vazio (a menos que
--force). valor_inicial/valor_atual/datas são sempre atualizados para o
valor oficial do SIAFE (mostra o diff antes de aplicar).

Uso:
  python manage.py resincronizar_contrato_siafe --pk 155 --exercicio 2025 --dry-run
  python manage.py resincronizar_contrato_siafe --pk 155 --exercicio 2025
"""

from django.core.management.base import BaseCommand, CommandError

from apps.contratos.management.commands.importar_contratos_siafe_api import _map_contrato_siafe
from apps.contratos.models import Contrato
from apps.siafe.client import SiafeClient, SiafeAPIError


class Command(BaseCommand):
    help = "Ressincroniza os campos de UM contrato com os dados oficiais do SIAFE (por pk)"

    def add_arguments(self, parser):
        parser.add_argument("--pk", type=int, required=True)
        parser.add_argument("--exercicio", type=int, required=True)
        parser.add_argument("--dry-run", action="store_true")
        parser.add_argument("--force", action="store_true", help="Sobrescreve numero_sei mesmo se já preenchido")

    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        force = options["force"]

        try:
            c = Contrato.objects.get(pk=options["pk"])
        except Contrato.DoesNotExist:
            raise CommandError(f"Contrato pk={options['pk']} não existe")

        if not c.codigo_siafe:
            raise CommandError(f"Contrato pk={c.pk} não tem codigo_siafe cadastrado")

        client = SiafeClient()
        try:
            data = client.contrato(options["exercicio"], c.codigo_siafe)
        except SiafeAPIError as exc:
            raise CommandError(f"Erro consultando SIAFE: {exc}")

        if not isinstance(data, dict) or not data:
            raise CommandError("SIAFE devolveu resposta vazia")

        mapeado = _map_contrato_siafe(data, c.codigo_siafe)
        numero_sei_siafe = (data.get("numProcesso") or "").strip()

        if dry_run:
            self.stdout.write(self.style.WARNING("*** DRY-RUN — nenhuma alteração será salva ***\n"))

        self.stdout.write(f"Contrato pk={c.pk} ({c.numero_contrato}) — objeto: {(c.objeto or '')[:60]}")

        mudou = False
        campos = {}

        if c.valor_inicial != mapeado["valor"]:
            self.stdout.write(f"  valor_inicial: {c.valor_inicial} -> {mapeado['valor']}")
            campos["valor_inicial"] = mapeado["valor"]
            if c.valor_atual == c.valor_inicial:
                campos["valor_atual"] = mapeado["valor"]
            if c.saldo_disponivel == c.valor_inicial:
                campos["saldo_disponivel"] = mapeado["valor"]
            mudou = True

        if c.data_assinatura != mapeado["data_assinatura"]:
            self.stdout.write(f"  data_assinatura: {c.data_assinatura} -> {mapeado['data_assinatura']}")
            campos["data_assinatura"] = mapeado["data_assinatura"]
            mudou = True

        if c.data_inicio_vigencia != mapeado["data_inicio_vigencia"]:
            self.stdout.write(f"  data_inicio_vigencia: {c.data_inicio_vigencia} -> {mapeado['data_inicio_vigencia']}")
            campos["data_inicio_vigencia"] = mapeado["data_inicio_vigencia"]
            mudou = True

        if c.data_fim_vigencia != mapeado["data_fim_vigencia"]:
            self.stdout.write(f"  data_fim_vigencia: {c.data_fim_vigencia} -> {mapeado['data_fim_vigencia']}")
            campos["data_fim_vigencia"] = mapeado["data_fim_vigencia"]
            mudou = True

        if numero_sei_siafe and (not c.numero_sei or force):
            if c.numero_sei != numero_sei_siafe:
                self.stdout.write(f"  numero_sei: {c.numero_sei!r} -> {numero_sei_siafe!r}")
                campos["numero_sei"] = numero_sei_siafe
                mudou = True

        if not mudou:
            self.stdout.write(self.style.SUCCESS("Nada divergente — já está igual ao SIAFE."))
            return

        if not dry_run:
            for k, v in campos.items():
                setattr(c, k, v)
            c.save(update_fields=list(campos.keys()))
            self.stdout.write(self.style.SUCCESS(f"\n{len(campos)} campo(s) corrigido(s)."))
        else:
            self.stdout.write(self.style.WARNING(f"\n{len(campos)} campo(s) seriam corrigidos."))
