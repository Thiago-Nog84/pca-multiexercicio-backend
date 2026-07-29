"""
Management command: encerrar_arps_vencidas
=============================================
Atualiza o status de AtaRegistroPrecos de 'vigente' para 'encerrada' quando
data_fim_vigencia já passou — achado pela auditoria (auditar_consistencia_srp,
checagem [vigencia]): 50 ARPs marcadas como vigentes com vigência expirada.

Não mexe em ARPs 'suspensa' ou 'cancelada' (só reclassifica quem está
'vigente' e venceu). Não apaga nem altera saldo/itens — é só o status.

Uso:
    python manage.py encerrar_arps_vencidas --dry-run
    python manage.py encerrar_arps_vencidas
"""

from datetime import date

from django.core.management.base import BaseCommand

from apps.srp.models import AtaRegistroPrecos


class Command(BaseCommand):
    help = "Marca como 'encerrada' as ARPs com status 'vigente' cuja data_fim_vigencia já passou"

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true", help="Simula sem salvar no banco")

    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        hoje = date.today()

        if dry_run:
            self.stdout.write(self.style.WARNING("*** DRY-RUN — nenhuma alteração será salva ***\n"))

        vencidas = (
            AtaRegistroPrecos.objects
            .filter(status="vigente", data_fim_vigencia__lt=hoje)
            .order_by("data_fim_vigencia")
        )

        total = vencidas.count()
        if total == 0:
            self.stdout.write(self.style.SUCCESS("Nenhuma ARP vigente com vigência vencida encontrada."))
            return

        for arp in vencidas:
            dias_vencida = (hoje - arp.data_fim_vigencia).days
            self.stdout.write(
                f"  ARP {arp.numero_arp} ({arp.fornecedor_razao_social[:40]}): "
                f"venceu em {arp.data_fim_vigencia:%d/%m/%Y} ({dias_vencida} dias) — "
                f"vigente -> encerrada"
            )
            if not dry_run:
                arp.status = "encerrada"
                arp.save(update_fields=["status"])

        self.stdout.write(self.style.SUCCESS(f"\n{total} ARP(s) {'seriam marcadas' if dry_run else 'marcadas'} como encerradas."))
