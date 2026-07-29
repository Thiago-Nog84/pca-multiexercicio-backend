"""
Management command: contar_itens_arp
========================================
Utilitário rápido (só banco local, sem rede): conta quantos ItemARP cada
ARP informada tem, e lista em ordem crescente. Serve pra decidir por qual
ARP começar quando for rodar algo caro em rede (ex: conciliar_dashboard_srp)
pra várias ARPs — começar pelas menores é bem mais rápido.

Uso:
  python manage.py contar_itens_arp --arp 00014/2026 00008/2025 00010/2025 ...
"""

from django.core.management.base import BaseCommand

from apps.srp.models import AtaRegistroPrecos


class Command(BaseCommand):
    help = "Conta ItemARP por ARP informada e ordena crescente (somente leitura, sem rede)"

    def add_arguments(self, parser):
        parser.add_argument("--arp", type=str, nargs="+", required=True)

    def handle(self, *args, **options):
        from django.db.models import Q

        q = Q()
        for numero in options["arp"]:
            q |= Q(numero_arp__icontains=numero)

        contagens = []
        for arp in AtaRegistroPrecos.objects.filter(q).prefetch_related("itens"):
            contagens.append((arp.itens.count(), arp.numero_arp))

        contagens.sort()
        for n_itens, numero_arp in contagens:
            self.stdout.write(f"  {n_itens:4d} itens — {numero_arp}")

        self.stdout.write(f"\nOrdem sugerida (--arp): {' '.join(numero for _, numero in contagens)}")
