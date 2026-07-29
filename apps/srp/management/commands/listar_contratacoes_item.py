"""
Management command: listar_contratacoes_item
====================================================
SOMENTE LEITURA. Lista todas as ContratacaoDecorrente vinculadas a um item
específico de uma ARP — usado para entender por que um item aparece
"saturado" (quantidade_contratada == quantidade_registrada) e se alguma
das contratações que o saturaram também é fruto do fallback de
similaridade/valor (e portanto pode estar errada).

Uso:
  python manage.py listar_contratacoes_item --arp 00029/2025 --item 8 [--saida arquivo.txt]
"""

from django.core.management.base import BaseCommand

from apps.contratos.models import Contrato
from apps.srp.models import AtaRegistroPrecos, ContratacaoDecorrente


class Command(BaseCommand):
    help = "Lista todas as ContratacaoDecorrente de um item de ARP (somente leitura)"

    def add_arguments(self, parser):
        parser.add_argument("--arp", type=str, required=True)
        parser.add_argument("--item", type=int, required=True)
        parser.add_argument("--saida", type=str, default=None)

    def handle(self, *args, **options):
        arquivo_saida = None
        if options.get("saida"):
            arquivo_saida = open(options["saida"], "w", encoding="utf-8")
            escrever_original = self.stdout.write

            def escrever_e_gravar(msg="", **kwargs):
                escrever_original(msg, **kwargs)
                arquivo_saida.write(str(msg) + "\n")

            self.stdout.write = escrever_e_gravar

        arp = AtaRegistroPrecos.objects.filter(numero_arp__icontains=options["arp"]).first()
        if not arp:
            self.stdout.write(self.style.ERROR("ARP não encontrada."))
            if arquivo_saida:
                arquivo_saida.close()
            return

        item = arp.itens.filter(numero_item=options["item"]).first()
        if not item:
            self.stdout.write(self.style.ERROR("Item não encontrado."))
            if arquivo_saida:
                arquivo_saida.close()
            return

        self.stdout.write(
            f"Item {item.numero_item} — {item.descricao[:100]}\n"
            f"qtd_registrada={item.quantidade_registrada} | qtd_contratada={item.quantidade_contratada}\n"
        )

        cds = ContratacaoDecorrente.objects.filter(arp=arp, item_arp=item).order_by("data_emissao")
        for cd in cds:
            contrato = Contrato.objects.filter(numero_contrato=cd.numero_pedido).first()
            valor_contrato = contrato.valor_inicial if contrato else "—"
            self.stdout.write(
                f"  pedido={cd.numero_pedido!r} | quantidade={cd.quantidade} | "
                f"valor_unitario={cd.valor_unitario} | valor_total={cd.valor_total} | "
                f"data_emissao={cd.data_emissao} | valor_inicial_contrato={valor_contrato}"
            )

        if arquivo_saida:
            arquivo_saida.close()
