"""
Management command: listar_itens_arp_completo
====================================================
SOMENTE LEITURA. Lista todos os ItemARP de uma ARP com descrição completa,
unidade de fornecimento, valor unitário e quantidades — usado para achar
qual item corresponde a um produto específico (ex: "headset") quando o
[fallback - similaridade/valor] vinculou um contrato ao item errado.

Uso:
  python manage.py listar_itens_arp_completo --arp 00029/2025 [--saida arquivo.txt]
"""

from django.core.management.base import BaseCommand

from apps.srp.models import AtaRegistroPrecos


class Command(BaseCommand):
    help = "Lista todos os itens de uma ARP com descrição completa (somente leitura)"

    def add_arguments(self, parser):
        parser.add_argument("--arp", type=str, required=True)
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

        self.stdout.write(f"ARP {arp.numero_arp} — {arp.itens.count()} item(ns):\n")
        for item in arp.itens.all().order_by("numero_item"):
            self.stdout.write(
                f"  Item {item.numero_item:3d} | qtd_registrada={item.quantidade_registrada} | "
                f"qtd_contratada={item.quantidade_contratada} | valor_unitario={item.valor_unitario} | "
                f"unidade={item.unidade_fornecimento or '(vazio)'}"
            )
            self.stdout.write(f"           {item.descricao[:140]}")

        if arquivo_saida:
            arquivo_saida.close()
