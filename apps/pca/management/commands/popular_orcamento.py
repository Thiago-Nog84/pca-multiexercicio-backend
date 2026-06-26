"""
Popula OrcamentoPlanejado com os tetos do PCA 2026 extraidos do documento oficial
"PCA 2026 - Versao 3.0 - MPPI" (Tabela 3, pg. 13).

Valores verificados contra totais por UO:
  PGJ   = R$ 15.413.886,66
  FMMP  = R$ 19.387.318,34
  FEPDC = R$  1.187.824,91
  TOTAL = R$ 35.989.029,91
"""

from decimal import Decimal

from django.core.management.base import BaseCommand, CommandError

from apps.core.models import UnidadeRequisitante
from apps.pca.models import OrcamentoPlanejado, PlanoContratacaoAnual

# Tetos por setor (PGJ, FMMP, FEPDC) -- extraidos e verificados do PCA 2026 v3.0
TETOS = {
    "CTI":  (Decimal("2959072.31"),  Decimal("12922349.47"), Decimal("0.00")),
    "CAA":  (Decimal("7998806.89"),  Decimal("3588756.59"),  Decimal("1006460.50")),
    "CPPT": (Decimal("2933849.89"),  Decimal("2409247.16"),  Decimal("0.00")),
    "CCS":  (Decimal("1080732.50"),  Decimal("101990.00"),   Decimal("0.00")),
    "GAECO":(Decimal("224057.10"),   Decimal("363616.32"),   Decimal("106301.00")),
    "CEAF": (Decimal("95000.00"),    Decimal("0.00"),        Decimal("0.00")),
    "GSI":  (Decimal("12287.97"),    Decimal("0.00"),        Decimal("70063.41")),
    "CCF":  (Decimal("41110.00"),    Decimal("1358.80"),     Decimal("5000.00")),
    "CLC":  (Decimal("36050.00"),    Decimal("0.00"),        Decimal("0.00")),
    "CRH":  (Decimal("30200.00"),    Decimal("0.00"),        Decimal("0.00")),
    "PLAN": (Decimal("2720.00"),     Decimal("0.00"),        Decimal("0.00")),
    # CONINT e PROCON nao constam no PCA 2026 v3.0 (sem demandas neste exercicio)
}


class Command(BaseCommand):
    help = "Popula OrcamentoPlanejado com os tetos do PCA 2026 (fonte: PCA 2026 v3.0, Tabela 3)"

    def add_arguments(self, parser):
        parser.add_argument(
            "--exercicio",
            type=int,
            default=2026,
            help="Exercicio do PCA a popular (default: 2026)",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Simula sem gravar no banco",
        )
        parser.add_argument(
            "--sobrescrever",
            action="store_true",
            help="Atualiza registros existentes (default: apenas cria novos)",
        )

    def handle(self, *args, **options):
        exercicio = options["exercicio"]
        dry_run   = options["dry_run"]
        sobrescrever = options["sobrescrever"]

        try:
            pca = PlanoContratacaoAnual.objects.get(exercicio=exercicio)
        except PlanoContratacaoAnual.DoesNotExist:
            raise CommandError(f"PCA {exercicio} nao encontrado. Crie-o no admin primeiro.")

        self.stdout.write(f"\nPCA {exercicio} encontrado: {pca}")
        if dry_run:
            self.stdout.write(self.style.WARNING("  [DRY RUN] Nenhuma alteracao sera gravada.\n"))

        criados = 0
        atualizados = 0
        ignorados = 0
        nao_encontrados = []

        for sigla, (pgj, fmmp, fepdc) in TETOS.items():
            try:
                unidade = UnidadeRequisitante.objects.get(sigla=sigla)
            except UnidadeRequisitante.DoesNotExist:
                self.stdout.write(self.style.WARNING(f"  [AVISO] UnidadeRequisitante '{sigla}' nao encontrada — pulando."))
                nao_encontrados.append(sigla)
                continue

            total = pgj + fmmp + fepdc
            exists = OrcamentoPlanejado.objects.filter(pca=pca, unidade=unidade).exists()

            if exists and not sobrescrever:
                self.stdout.write(f"  [SKIP]  {sigla:8s}  ja possui teto cadastrado (use --sobrescrever para atualizar)")
                ignorados += 1
                continue

            self.stdout.write(
                f"  {'[UPDATE]' if exists else '[CREATE]'} {sigla:8s} "
                f"PGJ={pgj:>16,.2f}  FMMP={fmmp:>16,.2f}  FEPDC={fepdc:>13,.2f}  "
                f"TOTAL={total:>16,.2f}"
            )

            if not dry_run:
                obj, created = OrcamentoPlanejado.objects.update_or_create(
                    pca=pca,
                    unidade=unidade,
                    defaults={
                        "valor_pgj":   pgj,
                        "valor_fmmp":  fmmp,
                        "valor_fepdc": fepdc,
                    },
                )
                if created:
                    criados += 1
                else:
                    atualizados += 1
            else:
                if exists:
                    atualizados += 1
                else:
                    criados += 1

        total_geral = sum(p + f + e for p, f, e in TETOS.values())
        self.stdout.write("\n" + "=" * 72)
        self.stdout.write(f"  PCA {exercicio} — Teto total: R$ {total_geral:,.2f}")
        self.stdout.write(f"    PGJ   = R$ {sum(p for p,_,_ in TETOS.values()):,.2f}")
        self.stdout.write(f"    FMMP  = R$ {sum(f for _,f,_ in TETOS.values()):,.2f}")
        self.stdout.write(f"    FEPDC = R$ {sum(e for _,_,e in TETOS.values()):,.2f}")
        self.stdout.write("=" * 72)
        self.stdout.write(
            self.style.SUCCESS(
                f"  Criados: {criados}  |  Atualizados: {atualizados}  |  "
                f"Ignorados: {ignorados}  |  Nao encontrados: {len(nao_encontrados)}"
            )
        )
        if nao_encontrados:
            self.stdout.write(
                self.style.WARNING(
                    f"  Setores nao encontrados no banco: {', '.join(nao_encontrados)}\n"
                    "  Verifique a sigla em Admin > Core > Unidades Requisitantes."
                )
            )
        if dry_run:
            self.stdout.write(self.style.WARNING("\n  [DRY RUN] Nenhuma alteracao foi gravada."))
