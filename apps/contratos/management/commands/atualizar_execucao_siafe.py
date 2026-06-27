"""
Management command: atualizar_execucao_siafe

Busca todas as Notas de Empenho das UGs do MPPI no SIAFE-PI,
filtra as vinculadas a contratos (numOriginalContrato preenchido),
agrupa por contrato e atualiza o campo valor_empenhado no banco local.

Uso:
  python manage.py atualizar_execucao_siafe
  python manage.py atualizar_execucao_siafe --exercicio 2025
  python manage.py atualizar_execucao_siafe --ug 250101
  python manage.py atualizar_execucao_siafe --dry-run

Lógica de cálculo:
  - Empenhos normais (tipoAlteracaoNE != ANULACAO) somam ao total.
  - Anulações (tipoAlteracaoNE == ANULACAO) subtraem (estorno).
  - O resultado é o valor líquido empenhado por contrato.
"""

import re
from datetime import date
from decimal import Decimal, InvalidOperation

from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.contratos.models import Contrato
from apps.siafe.client import SiafeClient, SiafeAPIError

UGS_MPPI = ["250101", "250102", "250104"]


def _parse_valor_siafe(valor_str) -> Decimal:
    """'2.216,5' ou 2216.5 (float) → Decimal('2216.50')"""
    if valor_str is None:
        return Decimal("0")
    if isinstance(valor_str, (int, float)):
        return Decimal(str(valor_str))
    limpo = re.sub(r"[R$\s]", "", str(valor_str)).replace(".", "").replace(",", ".")
    try:
        return Decimal(limpo)
    except InvalidOperation:
        return Decimal("0")


class Command(BaseCommand):
    help = "Sincroniza valor empenhado do SIAFE-PI com os contratos locais"

    def add_arguments(self, parser):
        parser.add_argument(
            "--exercicio", type=int, default=date.today().year,
            help="Exercício fiscal (padrão: ano atual)",
        )
        parser.add_argument(
            "--ug", type=str, default=None,
            help="Processar apenas uma UG (ex: 250101)",
        )
        parser.add_argument(
            "--dry-run", action="store_true",
            help="Exibe sem salvar",
        )
        parser.add_argument(
            "--debug", action="store_true",
            help="Exibe os primeiros 3 NEs de cada UG para inspecionar campos",
        )

    def handle(self, *args, **options):
        exercicio = options["exercicio"]
        ug_filtro = options["ug"]
        dry_run   = options["dry_run"]
        debug     = options["debug"]

        ugs = [ug_filtro] if ug_filtro else UGS_MPPI
        client  = SiafeClient()

        # ----------------------------------------------------------------
        # 1. Buscar todas as NEs das UGs e acumular por numOriginalContrato
        # ----------------------------------------------------------------
        empenhado: dict[str, Decimal] = {}
        total_nes = 0
        vinculadas = 0

        for ug in ugs:
            self.stdout.write(f"Buscando NEs da UG {ug} — exercício {exercicio}...")
            try:
                nes = client.nota_empenho_por_ug(exercicio, ug)
            except SiafeAPIError as exc:
                self.stderr.write(self.style.WARNING(f"  [ERRO] UG {ug}: {exc}"))
                continue

            self.stdout.write(f"  {len(nes)} NEs recebidas")
            total_nes += len(nes)

            if debug and nes:
                import json
                self.stdout.write("  --- DEBUG: campos do primeiro NE ---")
                ne0 = nes[0]
                for k, v in ne0.items():
                    self.stdout.write(f"    {k}: {repr(v)[:80]}")
                # Mostrar NEs com codContrato != 00000000
                com_contrato = [n for n in nes if n.get("codContrato", "00000000") != "00000000"]
                self.stdout.write(f"  NEs com codContrato != 00000000: {len(com_contrato)}")
                com_num = [n for n in nes if (n.get("numOriginalContrato") or "").strip()]
                self.stdout.write(f"  NEs com numOriginalContrato preenchido: {len(com_num)}")
                if com_contrato:
                    self.stdout.write("  Exemplo com contrato:")
                    for k, v in com_contrato[0].items():
                        self.stdout.write(f"    {k}: {repr(v)[:80]}")
                self.stdout.write("  ---")

            for ne in nes:
                # Link via codContrato (código automático SIAFE de 8 dígitos)
                # numOriginalContrato é sempre None na API do SIAFE-PI
                cod_contrato = (ne.get("codContrato") or "").strip()
                if not cod_contrato or cod_contrato in ("0", "00000000"):
                    continue

                valor    = _parse_valor_siafe(ne.get("valor"))
                tipo_alt = (ne.get("tipoAlteracaoNE") or "NENHUMA").upper()

                # Anulações reduzem o empenhado
                if tipo_alt == "ANULACAO":
                    empenhado[cod_contrato] = empenhado.get(cod_contrato, Decimal("0")) - valor
                else:
                    empenhado[cod_contrato] = empenhado.get(cod_contrato, Decimal("0")) + valor

                vinculadas += 1

        self.stdout.write(
            f"\nTotal NEs processadas: {total_nes} | Vinculadas a contratos: {vinculadas} "
            f"| Contratos únicos: {len(empenhado)}"
        )

        # ----------------------------------------------------------------
        # 2. Atualizar contratos locais
        # ----------------------------------------------------------------
        atualizados = nao_encontrados = 0
        agora = timezone.now()

        self.stdout.write("\nCruzando com contratos locais...")
        for num_contrato, total in sorted(empenhado.items()):
            # Busca pelo código automático SIAFE (campo codigo_siafe)
            qs = Contrato.objects.filter(codigo_siafe=num_contrato)
            if not qs.exists():
                self.stdout.write(
                    self.style.WARNING(f"  [N/F] {num_contrato:30s}  R$ {total:>14,.2f} — não cadastrado localmente")
                )
                nao_encontrados += 1
                continue

            if dry_run:
                c = qs.first()
                pct = (total / c.valor_atual * 100) if c.valor_atual else Decimal("0")
                self.stdout.write(
                    f"  [DRY] {num_contrato:30s}  empenhado R$ {total:>14,.2f} "
                    f"/ contratual R$ {c.valor_atual:>14,.2f}  ({pct:.1f}%)"
                )
                atualizados += 1
            else:
                qs.update(valor_empenhado=total, ultima_atualizacao_siafe=agora)
                c = qs.first()
                pct = (total / c.valor_atual * 100) if c.valor_atual else Decimal("0")
                self.stdout.write(
                    self.style.SUCCESS(
                        f"  [OK]  {num_contrato:30s}  R$ {total:>14,.2f} / R$ {c.valor_atual:>14,.2f}  ({pct:.1f}%)"
                    )
                )
                atualizados += 1

        self.stdout.write("\n" + "=" * 70)
        if dry_run:
            self.stdout.write(self.style.WARNING(
                f"DRY RUN — {atualizados} seriam atualizados, {nao_encontrados} não localizados."
            ))
        else:
            self.stdout.write(self.style.SUCCESS(
                f"Concluído: {atualizados} contratos atualizados, {nao_encontrados} não localizados localmente."
            ))
