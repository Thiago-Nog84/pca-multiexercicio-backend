"""
Reconcilia ItemARP.quantidade_contratada com a soma das Contratações
Decorrentes (pedidos) de cada item.

Contexto do bug: `ItemARP.quantidade_contratada` é um campo armazenado que
deveria ser incrementado a cada ContratacaoDecorrente. Quando os pedidos são
importados em lote (bulk), o `save()` que incrementa esse campo é ignorado,
então ele fica ZERADO mesmo havendo contratação real. O dashboard SRP calcula
o % de consumo a partir desse campo — logo, mostra 0% indevidamente.

Até agora esse campo só era corrigido de forma preguiçosa quando alguém abria
a página de detalhe de CADA ARP (ARPDetalheView faz o mesmo cálculo). Este
comando aplica a correção a TODAS as ARPs de uma vez.

Regra conservadora: só AUMENTA o valor (nunca reduz), espelhando a lógica já
existente na ARPDetalheView (`if soma_pedidos > quantidade_contratada`). Assim
não zera itens cujo contratado venha de outra fonte (ex.: ContratoARP).

Uso:
    python manage.py reconciliar_contratada_arp [--dry-run]
"""

from django.core.management.base import BaseCommand
from django.db import transaction
from django.db.models import Sum

from apps.srp.models import ItemARP


class Command(BaseCommand):
    help = "Sincroniza ItemARP.quantidade_contratada com a soma dos pedidos (ContratacaoDecorrente)."

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args, **opts):
        itens = ItemARP.objects.filter(contratacoes__isnull=False).distinct()
        total = itens.count()
        self.stdout.write(f"Analisando {total} item(ns) com contratações decorrentes...\n")

        corrigidos = 0
        arps = set()
        with transaction.atomic():
            for item in itens.select_related("arp"):
                soma = item.contratacoes.aggregate(s=Sum("quantidade"))["s"] or 0
                if float(soma) > float(item.quantidade_contratada) + 0.0001:
                    arps.add(item.arp.numero_arp)
                    self.stdout.write(
                        f"  ARP {item.arp.numero_arp} item {item.numero_item}: "
                        f"{item.quantidade_contratada} -> {soma}"
                    )
                    corrigidos += 1
                    if not opts["dry_run"]:
                        item.quantidade_contratada = soma
                        item.save(update_fields=["quantidade_contratada"])

            if opts["dry_run"]:
                transaction.set_rollback(True)

        modo = "[DRY-RUN — nada gravado] " if opts["dry_run"] else ""
        self.stdout.write(self.style.SUCCESS(
            f"\n{modo}{corrigidos} item(ns) corrigido(s) em {len(arps)} ARP(s)."
        ))
