"""
Management command: mesclar_contratos_duplicados
=====================================================
Aplica a decisão manual de um grupo duplicado (ver revisar_duplicatas_contrato):
apaga os registros indicados em --apagar, mantendo o de --manter. Decisão
SEMPRE explícita por PK — este comando nunca escolhe sozinho quem é o
"certo", só executa o que já foi confirmado por Thiago caso a caso.

Segurança:
  - Recusa apagar um registro que já tenha ContratacaoDecorrente vinculada
    (numero_pedido = numero_contrato) a menos que --force seja passado —
    nesse caso raro, avalie manualmente pra onde essas CDs devem apontar
    antes de forçar.
  - --dry-run mostra o que seria feito sem apagar nada.

Uso:
  python manage.py mesclar_contratos_duplicados --manter 257 --apagar 258 --dry-run
  python manage.py mesclar_contratos_duplicados --manter 257 --apagar 258
  python manage.py mesclar_contratos_duplicados --manter 253 --apagar 109
  python manage.py mesclar_contratos_duplicados --manter 120 --apagar 121 122
  python manage.py mesclar_contratos_duplicados --manter 106 --apagar 130
"""

from django.core.management.base import BaseCommand, CommandError

from apps.contratos.models import Contrato
from apps.srp.models import ContratacaoDecorrente


class Command(BaseCommand):
    help = "Apaga contratos duplicados por PK, mantendo o registro indicado (decisão manual, confirmada caso a caso)"

    def add_arguments(self, parser):
        parser.add_argument("--manter", type=int, required=True, help="PK do Contrato a manter")
        parser.add_argument("--apagar", type=int, nargs="+", required=True, help="PK(s) do(s) Contrato(s) a apagar")
        parser.add_argument("--dry-run", action="store_true")
        parser.add_argument("--force", action="store_true", help="Apaga mesmo se houver ContratacaoDecorrente vinculada")

    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        force = options["force"]

        try:
            manter = Contrato.objects.get(pk=options["manter"])
        except Contrato.DoesNotExist:
            raise CommandError(f"Contrato pk={options['manter']} não existe")

        if dry_run:
            self.stdout.write(self.style.WARNING("*** DRY-RUN — nenhuma alteração será salva ***\n"))

        self.stdout.write(f"MANTÉM: pk={manter.pk} {manter.numero_contrato!r} — {(manter.objeto or '')[:60]}")

        for pk_apagar in options["apagar"]:
            try:
                c = Contrato.objects.get(pk=pk_apagar)
            except Contrato.DoesNotExist:
                self.stdout.write(self.style.WARNING(f"  [pulado] pk={pk_apagar} não existe"))
                continue

            n_cds = ContratacaoDecorrente.objects.filter(numero_pedido=c.numero_contrato).count()
            if n_cds and not force:
                self.stdout.write(self.style.ERROR(
                    f"  [RECUSADO] pk={c.pk} ({c.numero_contrato!r}) tem {n_cds} ContratacaoDecorrente "
                    "vinculada(s) — avalie manualmente e use --force se realmente quiser apagar"
                ))
                continue

            self.stdout.write(f"  APAGA: pk={c.pk} {c.numero_contrato!r} — {(c.objeto or '')[:60]}")
            if not dry_run:
                c.delete()

        if not dry_run:
            self.stdout.write(self.style.SUCCESS("\nMesclagem aplicada."))
