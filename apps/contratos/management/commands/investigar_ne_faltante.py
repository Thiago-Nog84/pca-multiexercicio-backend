"""
Management command: investigar_ne_faltante
====================================================
SOMENTE LEITURA. Busca no SIAFE TODAS as Notas de Empenho de um credor
(CNPJ/CPF) num exercício e mostra, para cada uma, se ela foi importada
localmente como `Empenho` — e se não foi, por quê (mesma lógica de
`importar_empenhos_siafe`: o vínculo é por `codContrato` da NE batendo com
`Contrato.codigo_siafe`; se não bater, a NE fica de fora silenciosamente).

Usado para investigar divergências achadas por `conciliar_tcepi` onde o
total local fica ABAIXO do TCE (indício de NE não importada).

Uso:
  python manage.py investigar_ne_faltante --cnpj 39853645000102 --exercicio 2026 --saida arquivo.txt
  python manage.py investigar_ne_faltante --cnpj 86781069000115 --exercicio 2026 --ug 250101
"""

import re

from django.core.management.base import BaseCommand

from apps.contratos.models import Contrato, Empenho
from apps.siafe.client import SiafeAPIError, SiafeClient

UGS_MPPI = ["250101", "250102", "250104"]


def _digitos(valor) -> str:
    return re.sub(r"\D", "", str(valor or ""))


class Command(BaseCommand):
    help = "Busca no SIAFE todas as NEs de um credor e mostra quais não foram importadas localmente, e por quê (somente leitura)"

    def add_arguments(self, parser):
        parser.add_argument("--cnpj", type=str, required=True)
        parser.add_argument("--exercicio", type=int, required=True)
        parser.add_argument("--ug", type=str, nargs="+", default=UGS_MPPI)
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

        digitos_cnpj = _digitos(options["cnpj"])
        exercicio = options["exercicio"]
        client = SiafeClient()

        idx_contratos = {
            c.codigo_siafe.strip(): c
            for c in Contrato.objects.exclude(codigo_siafe="").exclude(codigo_siafe__isnull=True)
        }
        nes_locais = set(
            Empenho.objects.filter(ano_exercicio=exercicio).values_list("numero_empenho", flat=True)
        )

        total_encontradas = 0
        for ug in options["ug"]:
            self.stdout.write(self.style.MIGRATE_HEADING(f"\n=== UG {ug} — exercício {exercicio} ==="))
            try:
                nes = client.nota_empenho_por_ug(exercicio, ug)
            except SiafeAPIError as exc:
                self.stdout.write(self.style.ERROR(f"  Erro ao consultar SIAFE: {exc}"))
                continue

            do_credor = [
                ne for ne in nes
                if _digitos(ne.get("cnpjCredor") or ne.get("cpfCredor")) == digitos_cnpj
            ]
            if not do_credor:
                self.stdout.write(f"  Nenhuma NE deste credor na UG {ug}.")
                continue

            total_encontradas += len(do_credor)
            for ne in do_credor:
                numero = (ne.get("codigo") or "").strip()
                cod_contrato = (ne.get("codContrato") or "").strip()
                valor = ne.get("valor")
                tipo_alt = (ne.get("tipoAlteracaoNE") or "NENHUMA").upper()

                existe_local = numero in nes_locais
                contrato_local = idx_contratos.get(cod_contrato)

                self.stdout.write(
                    f"  NE={numero!r} | valor={valor} | tipo={tipo_alt} | codContrato SIAFE={cod_contrato!r}"
                )
                if existe_local:
                    self.stdout.write(self.style.SUCCESS("    -> já importada localmente (Empenho existe)."))
                elif contrato_local:
                    self.stdout.write(self.style.ERROR(
                        f"    -> NAO IMPORTADA, mas codContrato BATE com contrato local pk={contrato_local.pk} "
                        f"({contrato_local.numero_contrato!r}). Bug de importação — rodar importar_empenhos_siafe de novo deveria resolver."
                    ))
                else:
                    self.stdout.write(self.style.WARNING(
                        f"    -> NAO IMPORTADA — codContrato {cod_contrato!r} NÃO bate com nenhum "
                        f"Contrato.codigo_siafe local. Precisa achar/cadastrar o contrato certo, ou "
                        f"corrigir o codigo_siafe do contrato existente que deveria receber esta NE."
                    ))

        if total_encontradas == 0:
            self.stdout.write(self.style.WARNING("\nNenhuma NE encontrada para este CNPJ em nenhuma UG informada."))

        self.stdout.write(self.style.WARNING("\nSomente leitura — nenhuma alteração foi feita."))

        if arquivo_saida:
            arquivo_saida.close()
