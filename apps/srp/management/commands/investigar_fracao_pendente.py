"""
Management command: investigar_fracao_pendente
====================================================
SOMENTE LEITURA. Mostra, para cada caso de quantidade fracionária ainda sem
resolver automático (achados da re-execução de conciliar_dashboard_srp em
2026-07-29, após o fix do orçamento de nós em _resolver_combinacao_unica),
todos os dados necessários pra decidir se é:

  (a) erro real (ex: sobra do fallback de similaridade/valor dividindo
      errado) -> precisa de OFFICIAL_CONTRACT_ITEMS manual ou correção; ou
  (b) fração legítima (item com unidade_fornecimento contínua tipo m², kg,
      hora, diária -> fração é normal e não precisa de correção).

Para cada item mostra: descrição, unidade de fornecimento, quantidade
registrada e valor unitário na ARP; e para cada ContratacaoDecorrente
vinculada, número do pedido, quantidade (a fracionária), valor unitário e
total — e, se achar um Contrato local com numero_contrato/numero_pedido
correspondente, o objeto, contratado e número de processo/SEI.

Uso:
  python manage.py investigar_fracao_pendente
"""

import re
from decimal import Decimal

from django.core.management.base import BaseCommand

from apps.contratos.models import Contrato
from apps.srp.models import AtaRegistroPrecos, ContratacaoDecorrente


# (numero_arp, numero_item) — casos "[fallback - similaridade/valor]" que
# sobraram após rodar todas as 31 ARPs da lista de fração (2026-07-29).
CASOS = [
    ("00022/2025", 109),
    ("00046/2025", 7),
    ("00023/2025", 6),
    ("00018/2025", 14),
    ("00011/2024", 35),
    ("00043/2025", 4),
    ("00048/2025", 1),
    ("00049/2025", 2),
    ("00035/2025", 4),
    ("00029/2025", 9),
    ("00024/2025", 15),
    ("00019/2025", 4),
    ("00016/2025", 9),
]


def _digitos(valor) -> str:
    return re.sub(r"\D", "", str(valor or ""))


class Command(BaseCommand):
    help = "Mostra detalhes completos dos casos de fração pendente para decidir correção manual (somente leitura)"

    def add_arguments(self, parser):
        parser.add_argument(
            "--saida",
            type=str,
            default=None,
            help="Caminho de arquivo para gravar a saída em UTF-8 (evita mojibake do PowerShell).",
        )

    def handle(self, *args, **options):
        arquivo_saida = None
        if options.get("saida"):
            arquivo_saida = open(options["saida"], "w", encoding="utf-8")
            escrever_original = self.stdout.write

            def escrever_e_gravar(msg="", **kwargs):
                escrever_original(msg, **kwargs)
                arquivo_saida.write(str(msg) + "\n")

            self.stdout.write = escrever_e_gravar

        for numero_arp, numero_item in CASOS:
            self.stdout.write(self.style.MIGRATE_HEADING(f"\n=== ARP {numero_arp} — item {numero_item} ==="))

            arp = AtaRegistroPrecos.objects.filter(numero_arp=numero_arp).first()
            if not arp:
                self.stdout.write(self.style.ERROR("  ARP não encontrada."))
                continue

            item = arp.itens.filter(numero_item=numero_item).first()
            if not item:
                self.stdout.write(self.style.ERROR("  ItemARP não encontrado."))
                continue

            self.stdout.write(f"  descrição: {item.descricao[:120]}")
            self.stdout.write(
                f"  unidade_fornecimento={item.unidade_fornecimento or '(vazio)'!r} | "
                f"quantidade_registrada={item.quantidade_registrada} | "
                f"valor_unitario={item.valor_unitario}"
            )

            cds = ContratacaoDecorrente.objects.filter(arp=arp, item_arp=item)
            if not cds:
                self.stdout.write(self.style.WARNING("  Nenhuma ContratacaoDecorrente encontrada para este item."))
                continue

            for cd in cds:
                fracionaria = cd.quantidade != cd.quantidade.to_integral_value()
                self.stdout.write(
                    f"  -> pedido={cd.numero_pedido!r} | quantidade={cd.quantidade}"
                    + ("  ⚠ FRACIONÁRIA" if fracionaria else "")
                    + f" | valor_unitario={cd.valor_unitario} | valor_total={cd.valor_total}"
                )

                # Tenta achar o Contrato local correspondente (por numero_contrato
                # ou codigo_siafe batendo com numero_pedido, texto cru).
                contrato = Contrato.objects.filter(numero_contrato=cd.numero_pedido).first()
                if not contrato:
                    contrato = Contrato.objects.filter(codigo_siafe=cd.numero_pedido).first()
                if not contrato:
                    digitos_pedido = _digitos(cd.numero_pedido)
                    if digitos_pedido:
                        contrato = Contrato.objects.filter(codigo_siafe__icontains=digitos_pedido).first()

                if contrato:
                    self.stdout.write(
                        f"     contrato pk={contrato.pk} | numero_contrato={contrato.numero_contrato!r} | "
                        f"contratado={contrato.contratado_razao_social or '—'} | "
                        f"valor_inicial={contrato.valor_inicial} | numero_sei={contrato.numero_sei or '—'}"
                    )
                    self.stdout.write(f"     objeto: {(contrato.objeto or '')[:150]}")

                    # produtos[] do SIAFE (ver importar_empenhos_siafe) — quando
                    # existe, traz quantidade/unidade item a item da própria NE,
                    # sem depender de caçar PDF no SEI.
                    itens = list(
                        contrato.empenhos.prefetch_related("produtos")
                        .values_list("numero_empenho", "produtos__nome_produto",
                                      "produtos__quantidade", "produtos__unidade_fornecimento",
                                      "produtos__preco_unitario")
                    )
                    itens = [i for i in itens if i[1] is not None]
                    if itens:
                        self.stdout.write("     produtos[] do SIAFE (NE → produto → quantidade/unidade):")
                        for ne_num, nome, qtd, unid, preco_unit in itens:
                            self.stdout.write(
                                f"       {ne_num} | {nome[:60] if nome else '—'} | "
                                f"qtd={qtd} {unid or ''} | preco_unit={preco_unit}"
                            )
                    else:
                        self.stdout.write(
                            "     (sem produtos[] importados para este contrato — rode "
                            "importar_empenhos_siafe de novo, ou este empenho não tinha o bloco)"
                        )
                else:
                    self.stdout.write(self.style.WARNING("     (Contrato local não encontrado para este pedido)"))

        self.stdout.write(self.style.WARNING(
            "\nSomente leitura — nenhuma alteração foi feita. Analise unidade_fornecimento "
            "(m², kg, hora, diária = fração pode ser legítima) e o objeto do contrato pra "
            "decidir, caso a caso, se corrige ou documenta como fração legítima."
        ))

        if arquivo_saida:
            arquivo_saida.close()
