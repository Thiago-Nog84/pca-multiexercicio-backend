"""
Management command: dump_ne_siafe
====================================================
SOMENTE LEITURA. Despeja o JSON BRUTO de uma Nota de Empenho do SIAFE-PI,
exatamente como a API devolve — sem nenhum mapeamento nosso.

Serve para dois fins:
  1. Descobrir quais campos a API realmente expõe (o PDF da NE mostra
     blocos como "Produtos" — produto/quantidade/unidade/preço unitário —,
     nota de reserva, modalidade de licitação e processo SEI, que hoje não
     são importados; é preciso confirmar se vêm no payload ou se só existem
     na renderização do PDF).
  2. Conferir uma NE específica sem depender do PDF.

IMPORTANTE — número de NE NÃO é único entre UGs: o mesmo número
(ex: 2026NE00010) existe em UGs diferentes para credores diferentes.
Por isso este comando varre TODAS as UGs do MPPI e mostra TODAS as
ocorrências, identificando a UG de cada uma.

Uso:
  python manage.py dump_ne_siafe --numero 2026NE00010 --exercicio 2026
  python manage.py dump_ne_siafe --numero 2026NE00010 --exercicio 2026 --saida ne.json
  python manage.py dump_ne_siafe --numero 2026NE00010 --exercicio 2026 --so-chaves
"""

import json

from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.siafe.client import SiafeAPIError, SiafeClient

UGS_MPPI = ["250101", "250102", "250104"]


class Command(BaseCommand):
    help = "Despeja o JSON bruto de uma NE do SIAFE, em todas as UGs do MPPI (somente leitura)"

    def add_arguments(self, parser):
        parser.add_argument("--numero", type=str, required=True, help="Ex: 2026NE00010")
        parser.add_argument("--exercicio", type=int, default=timezone.now().year)
        parser.add_argument("--ug", type=str, nargs="+", default=UGS_MPPI)
        parser.add_argument(
            "--so-chaves", action="store_true",
            help="Mostra apenas os nomes dos campos (útil para ver o que a API expõe).",
        )
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

        numero = options["numero"].strip().upper()
        exercicio = options["exercicio"]
        client = SiafeClient()

        encontradas = 0
        for ug in options["ug"]:
            self.stdout.write(f"Buscando NEs da UG {ug} — exercício {exercicio}...")
            try:
                nes = client.nota_empenho_por_ug(exercicio, ug)
            except SiafeAPIError as exc:
                self.stdout.write(self.style.ERROR(f"  [ERRO] UG {ug}: {exc}"))
                continue

            achadas = [ne for ne in nes if (ne.get("codigo") or "").strip().upper() == numero]
            if not achadas:
                self.stdout.write(f"  (não encontrada nesta UG — {len(nes)} NEs lidas)")
                continue

            for ne in achadas:
                encontradas += 1
                self.stdout.write(self.style.MIGRATE_HEADING(
                    f"\n=== {numero} — UG {ug} — ocorrência {encontradas} ==="
                ))
                self.stdout.write(
                    f"  resumo: credor={ne.get('cnpjCredor') or ne.get('cpfCredor')} "
                    f"{ne.get('nomeCredor')} | valor={ne.get('valor')} | "
                    f"codContrato={ne.get('codContrato')!r}"
                )

                if options["so_chaves"]:
                    self.stdout.write("\n  campos disponíveis no payload:")
                    for chave in sorted(ne.keys()):
                        valor = ne[chave]
                        tipo = type(valor).__name__
                        if isinstance(valor, (list, dict)):
                            tamanho = len(valor)
                            self.stdout.write(f"    {chave} ({tipo}, {tamanho} item(ns))")
                        else:
                            amostra = str(valor)[:60]
                            self.stdout.write(f"    {chave} ({tipo}) = {amostra}")
                else:
                    self.stdout.write("\n  JSON bruto:")
                    self.stdout.write(json.dumps(ne, indent=2, ensure_ascii=False))

        if encontradas == 0:
            self.stdout.write(self.style.WARNING(
                f"\nNenhuma NE {numero} encontrada nas UGs {options['ug']} no exercício {exercicio}."
            ))
        else:
            self.stdout.write(self.style.SUCCESS(
                f"\n{encontradas} ocorrência(s) de {numero} encontrada(s)."
            ))
            if encontradas > 1:
                self.stdout.write(self.style.WARNING(
                    "  ATENÇÃO: o mesmo número de NE existe em mais de uma UG — a numeração "
                    "é sequencial POR UG, não global. Qualquer casamento por número de NE "
                    "precisa levar a UG em conta."
                ))

        if arquivo_saida:
            arquivo_saida.close()
