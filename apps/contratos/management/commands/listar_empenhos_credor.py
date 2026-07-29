"""
Management command: listar_empenhos_credor
====================================================
SOMENTE LEITURA. Lista todos os registros locais de `Empenho` de um credor
(CNPJ/CPF) num exercício, lado a lado com o contrato vinculado — usado para
investigar divergências encontradas por `conciliar_tcepi` (ex: soma local
muito maior/menor que o TCE, possível duplicidade ou anulação não
descontada).

Uso:
  python manage.py listar_empenhos_credor --cnpj 05564043000113 --exercicio 2026 --saida arquivo.txt
"""

import re
from decimal import Decimal

from django.core.management.base import BaseCommand

from apps.contratos.models_empenho import Empenho


def _digitos(valor) -> str:
    return re.sub(r"\D", "", str(valor or ""))


class Command(BaseCommand):
    help = "Lista todos os Empenho locais de um CNPJ/CPF num exercício, com contrato vinculado (somente leitura)"

    def add_arguments(self, parser):
        parser.add_argument("--cnpj", type=str, required=True)
        parser.add_argument("--exercicio", type=int, required=True)
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

        digitos = _digitos(options["cnpj"])
        exercicio = options["exercicio"]

        empenhos = list(
            Empenho.objects.filter(
                ano_exercicio=exercicio,
                cnpj_favorecido__icontains=digitos[-8:],
            )
            .select_related("contrato")
            .order_by("numero_empenho")
        )

        if not empenhos:
            self.stdout.write(self.style.ERROR(f"Nenhum Empenho encontrado para CNPJ {digitos} em {exercicio}."))
            if arquivo_saida:
                arquivo_saida.close()
            return

        self.stdout.write(f"{len(empenhos)} empenho(s) — {empenhos[0].nome_favorecido or '(sem nome)'} — CNPJ {digitos} — {exercicio}\n")

        total_empenhado = Decimal("0")
        total_liquido = Decimal("0")  # NEs tipo=anulacao subtraem, não somam
        vistos = {}
        for e in empenhos:
            duplicado = e.numero_empenho in vistos
            vistos.setdefault(e.numero_empenho, []).append(e.pk)
            total_empenhado += e.valor_empenhado
            total_liquido += -e.valor_empenhado if e.tipo == "anulacao" else e.valor_empenhado

            marca = "  ⚠ NUMERO REPETIDO" if duplicado else ""
            if e.tipo == "anulacao":
                marca += "  (ANULACAO — subtrai do total líquido)"
            self.stdout.write(
                f"  pk={e.pk:5d} | NE={e.numero_empenho!r:16s} | tipo={e.tipo:10s} | natureza={e.natureza:12s} | "
                f"valor_empenhado=R$ {e.valor_empenhado:>14,.2f} | valor_liquidado=R$ {e.valor_liquidado:>12,.2f}{marca}"
            )
            self.stdout.write(
                f"           contrato pk={e.contrato_id} | numero_contrato={e.contrato.numero_contrato!r} | "
                f"unidade_orcamentaria={e.contrato.unidade_orcamentaria!r} | importado_siafe={e.importado_siafe}"
            )

        self.stdout.write(f"\nTOTAL bruto (soma simples, sem descontar anulação): R$ {total_empenhado:,.2f}")
        self.stdout.write(f"TOTAL líquido (anulação subtraída — comparável ao TCE/conciliar_tcepi): R$ {total_liquido:,.2f}")

        repetidos = {k: v for k, v in vistos.items() if len(v) > 1}
        if repetidos:
            self.stdout.write(self.style.ERROR(
                f"\n⚠ {len(repetidos)} número(s) de NE aparecem em mais de um registro local (pks): {repetidos}"
            ))
            self.stdout.write(self.style.ERROR(
                "Isso indica duplicidade — o mesmo empenho pode estar sendo contado mais de uma vez na soma."
            ))
        else:
            self.stdout.write(self.style.WARNING(
                "\nNenhum número de NE repetido — a duplicidade, se houver, não é por linha duplicada simples "
                "(pode ser NE de REFORCO/ANULACAO não compensada, ou empenho vinculado ao contrato errado)."
            ))

        if arquivo_saida:
            arquivo_saida.close()
