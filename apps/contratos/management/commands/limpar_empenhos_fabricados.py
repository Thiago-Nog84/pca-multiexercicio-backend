"""
Management command: limpar_empenhos_fabricados
====================================================
Remove registros de `Empenho` cadastrados manualmente (`importado_siafe=False`)
cujo `numero_empenho` foi FABRICADO a partir do número do contrato, e não
corresponde a nenhuma Nota de Empenho real do SIAFE.

Origem do problema (achado em 2026-07-29/30): o antigo `vincular_empenhos_siafe`
tinha um dict `EMPENHOS_CONHECIDOS` hardcoded que gerava o "número da NE" a
partir do número do contrato:

    contrato '56/2025 PGJ'  -> numero_empenho '2025NE00056'
    contrato '120/2025'     -> numero_empenho '2025NE00120'
    contrato '25017488'     -> numero_empenho '25017488'  (codigo_siafe copiado)
    contrato '58/2025/PGJ'  -> numero_empenho '2025NE00058A'  (sufixo inventado)
    contrato '2025NR00104'  -> numero_empenho '2025NR00104'  (nota de RESERVA)

Por coincidência, NEs com esses números existem no SIAFE — mas pertencem a
outros credores (diárias, suprimento de fundos, folha de pagamento). O
`valor_empenhado` desses registros também não corresponde a empenho nenhum:
parece ser o valor do CONTRATO. Resultado: inflam o empenhado do credor errado e
quebram a conciliação com o TCE.

Caso comprovado por documento: pk=26, NE `2026NE00010`, R$25.132,47, registrado
como SORELLE no contrato `10/2026/FPDC`. A NE `2026NE00010` real da UG 250102 é
de L H C HAIDAR SOUSA, R$7.672,50, contrato SIAFE `26100660` (projetos de
incêndio) — credor, órgão, objeto e valor diferentes.

## Critério de exclusão (conservador — exige AS DUAS condições)

1. **Não confere com o SIAFE**: nenhuma NE de mesmo número, em nenhuma UG do
   MPPI no exercício, tem o mesmo CNPJ/CPF do registro local.
2. **Padrão de fabricação detectado**: o `numero_empenho` é derivável do
   `numero_contrato` (ver `_ne_derivada_do_contrato`).

Registros que falham só na condição 1 (não confere, mas sem padrão claro de
fabricação) são classificados como REVISAR e **nunca apagados automaticamente**.

Após apagar, o `valor_empenhado` dos contratos afetados é recalculado a partir
dos `Empenho` que sobraram (líquido de anulações). Rode
`importar_empenhos_siafe --exercicio <ano>` em seguida para repovoar com dado
real do SIAFE.

Uso:
  python manage.py limpar_empenhos_fabricados --exercicio 2025 --dry-run
  python manage.py limpar_empenhos_fabricados --exercicio 2025
  python manage.py limpar_empenhos_fabricados --exercicio 2026 --dry-run
"""

import re
from decimal import Decimal

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from apps.contratos.models import Contrato, Empenho
from apps.siafe.client import SiafeAPIError, SiafeClient

UGS_MPPI = ["250101", "250102", "250104"]


def _digitos(valor) -> str:
    return re.sub(r"\D", "", str(valor or ""))


def _ne_derivada_do_contrato(numero_contrato: str, numero_empenho: str):
    """
    Retorna uma string explicando o padrão de fabricação, ou None se o
    `numero_empenho` NÃO parece derivado do `numero_contrato`.
    """
    ne = (numero_empenho or "").strip().upper()
    nc = (numero_contrato or "").strip().upper()
    if not ne or not nc:
        return None

    # Caso 1: número do empenho é literalmente igual ao número do contrato
    # (ex: codigo_siafe '25017488' ou nota de reserva '2025NR00104' copiados).
    if ne == nc:
        return f"numero_empenho identico ao numero_contrato ({nc!r})"

    # Caso 2: contrato no formato NNN/AAAA (com ou sem sufixo de fonte) gerando
    # AAAANE00NNN — com variações de sufixo 'A' e de tipo 'NR'.
    m = re.search(r"(\d{1,4})\s*/\s*(\d{4})", nc)
    if m:
        seq, ano = m.group(1), m.group(2)
        candidatos = {
            f"{ano}NE{int(seq):05d}": "padrao NNN/AAAA -> AAAANE00NNN",
            f"{ano}NE{int(seq):05d}A": "padrao NNN/AAAA -> AAAANE00NNN + sufixo 'A' inventado",
            f"{ano}NR{int(seq):05d}": "padrao NNN/AAAA -> AAAANR00NNN (nota de RESERVA, nao empenho)",
        }
        if ne in candidatos:
            return f"{candidatos[ne]} — contrato {nc!r} gerou {ne!r}"

    return None


class Command(BaseCommand):
    help = "Remove Empenhos manuais com numero fabricado a partir do numero do contrato (nao existem no SIAFE)"

    def add_arguments(self, parser):
        parser.add_argument("--exercicio", type=int, default=timezone.now().year)
        parser.add_argument("--ug", type=str, nargs="+", default=UGS_MPPI)
        parser.add_argument("--dry-run", action="store_true")
        parser.add_argument("--saida", type=str, default=None)

    def handle(self, *args, **options):
        arquivo_saida = None
        if options.get("saida"):
            arquivo_saida = open(options["saida"], "w", encoding="utf-8")
            escrever_original = self.stdout.write

            def escrever_e_gravar(msg="", *a, **kw):
                escrever_original(msg, *a, **kw)
                arquivo_saida.write(str(msg) + "\n")

            self.stdout.write = escrever_e_gravar

        exercicio = options["exercicio"]
        dry_run = options["dry_run"]
        client = SiafeClient()

        manuais = list(
            Empenho.objects.filter(importado_siafe=False, ano_exercicio=exercicio)
            .select_related("contrato")
            .order_by("numero_empenho")
        )
        if not manuais:
            self.stdout.write(self.style.SUCCESS(
                f"Nenhum Empenho manual no exercício {exercicio} — nada a fazer."
            ))
            if arquivo_saida:
                arquivo_saida.close()
            return

        self.stdout.write(f"{len(manuais)} empenho(s) manual(is) no exercício {exercicio}.\n")

        # Índice das NEs reais do SIAFE: numero -> lista de (ug, ne)
        nes_siafe = {}
        for ug in options["ug"]:
            self.stdout.write(f"Buscando NEs da UG {ug}...")
            try:
                nes = client.nota_empenho_por_ug(exercicio, ug)
            except SiafeAPIError as exc:
                self.stdout.write(self.style.ERROR(
                    f"  [ERRO] UG {ug}: {exc}\n"
                    f"  ABORTANDO — sem a lista completa do SIAFE não é seguro apagar nada."
                ))
                if arquivo_saida:
                    arquivo_saida.close()
                return
            self.stdout.write(f"  {len(nes)} NEs recebidas")
            for ne in nes:
                numero = (ne.get("codigo") or "").strip().upper()
                if numero:
                    nes_siafe.setdefault(numero, []).append((ug, ne))

        manter, apagar, revisar = [], [], []

        for e in manuais:
            numero = (e.numero_empenho or "").strip().upper()
            cnpj_local = _digitos(e.cnpj_favorecido)

            # Condição 1: confere com o SIAFE? (mesmo número E mesmo credor,
            # em qualquer UG — o número de NE é sequencial POR UG, então o
            # credor é que desempata)
            confere = any(
                _digitos(ne.get("cnpjCredor") or ne.get("cpfCredor")) == cnpj_local
                for _, ne in nes_siafe.get(numero, [])
                if cnpj_local
            )
            if confere:
                manter.append(e)
                continue

            # Condição 2: padrão de fabricação
            padrao = _ne_derivada_do_contrato(e.contrato.numero_contrato, numero)
            if padrao:
                apagar.append((e, padrao))
            else:
                revisar.append(e)

        # ------------------------------------------------------------------
        self.stdout.write(self.style.MIGRATE_HEADING(
            f"\n=== MANTER (confere com o SIAFE) — {len(manter)} ==="
        ))
        for e in manter:
            self.stdout.write(
                f"  pk={e.pk} NE={e.numero_empenho!r} R$ {e.valor_empenhado:,.2f} — "
                f"{e.contrato.numero_contrato!r}"
            )

        self.stdout.write(self.style.MIGRATE_HEADING(
            f"\n=== APAGAR (não confere + padrão de fabricação) — {len(apagar)} ==="
        ))
        contratos_afetados = set()
        for e, padrao in apagar:
            contratos_afetados.add(e.contrato_id)
            self.stdout.write(self.style.ERROR(
                f"  pk={e.pk} NE={e.numero_empenho!r} R$ {e.valor_empenhado:,.2f} | "
                f"contrato {e.contrato.numero_contrato!r} (pk={e.contrato_id}) | "
                f"credor local {e.cnpj_favorecido} {e.nome_favorecido[:35]}"
            ))
            self.stdout.write(f"      motivo: {padrao}")

        self.stdout.write(self.style.MIGRATE_HEADING(
            f"\n=== REVISAR (não confere, mas SEM padrão de fabricação) — {len(revisar)} ==="
        ))
        if revisar:
            self.stdout.write(
                "  Estes NÃO são apagados automaticamente — precisam de conferência manual."
            )
            for e in revisar:
                self.stdout.write(self.style.WARNING(
                    f"  pk={e.pk} NE={e.numero_empenho!r} R$ {e.valor_empenhado:,.2f} | "
                    f"contrato {e.contrato.numero_contrato!r} | credor {e.cnpj_favorecido}"
                ))
        else:
            self.stdout.write("  (nenhum)")

        # ------------------------------------------------------------------
        if not apagar:
            self.stdout.write(self.style.SUCCESS("\nNada a apagar."))
            if arquivo_saida:
                arquivo_saida.close()
            return

        total_removido = sum(e.valor_empenhado for e, _ in apagar)

        if dry_run:
            self.stdout.write(self.style.WARNING(
                f"\n[DRY-RUN — nada gravado] Seriam apagados {len(apagar)} registro(s), "
                f"somando R$ {total_removido:,.2f}, afetando {len(contratos_afetados)} contrato(s)."
            ))
            if arquivo_saida:
                arquivo_saida.close()
            return

        with transaction.atomic():
            pks = [e.pk for e, _ in apagar]
            Empenho.objects.filter(pk__in=pks).delete()

            # Recalcula valor_empenhado dos contratos afetados a partir do que sobrou
            recalculados = 0
            for contrato_id in contratos_afetados:
                contrato = Contrato.objects.filter(pk=contrato_id).first()
                if not contrato:
                    continue
                total = Decimal("0")
                for emp in Empenho.objects.filter(contrato=contrato):
                    total += -emp.valor_empenhado if emp.tipo == "anulacao" else emp.valor_empenhado
                contrato.valor_empenhado = total
                contrato.save(update_fields=["valor_empenhado"])
                recalculados += 1

        self.stdout.write(self.style.SUCCESS(
            f"\nApagados: {len(apagar)} registro(s), somando R$ {total_removido:,.2f}. "
            f"valor_empenhado recalculado em {recalculados} contrato(s)."
        ))
        self.stdout.write(self.style.WARNING(
            f"\nAgora rode:\n"
            f"  python manage.py importar_empenhos_siafe --exercicio {exercicio}\n"
            f"  python manage.py conciliar_tcepi --exercicio {exercicio} --orgao pgj fmmp fepdc"
        ))

        if arquivo_saida:
            arquivo_saida.close()
