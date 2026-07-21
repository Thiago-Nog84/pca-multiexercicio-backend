"""
Saneia códigos CATMAT/CATSER do catálogo interno que vieram malformados
(dois códigos concatenados no formato "PDM (item)").

Cada correção foi conferida item a item contra a base oficial
(dadosabertos.compras.gov.br) em 2026-07-21 — a descrição oficial do código
mantido bate com a descrição do item no nosso catálogo.

Uso:
    python manage.py sanear_codigos_catalogo --dry-run
    python manage.py sanear_codigos_catalogo
"""

from django.core.management.base import BaseCommand
from django.db import transaction

from apps.pca.models import ItemCatalogo

# de (código atual) -> para (código correto). Justificativa ao lado.
CORRECOES = {
    # Grupo 1 — o 1º número (PDM) é o correto; remove o parêntese.
    "644 (19744)": "644",       # GÁS LIQUEFEITO DE PETRÓLEO - GLP
    "1341 (19744)": "1341",     # BOTIJÃO GÁS LIQUEFEITO
    "1281 (402921)": "1281",    # GARRAFÃO
    "2259 (429961)": "2259",    # ÁLCOOL ETÍLICO
    "2561 (269943)": "2561",    # ÁLCOOL GEL ANTISSÉPTICO
    "14403 (11903)": "14403",   # SACO DE LIXO
    "433 (30029)": "433",       # MÁSCARA CIRÚRGICA
    "13707 (20)": "13707",      # PASTA SANFONADA
    "13636 (820)": "13636",     # SERROTE
    # Grupo 2 — o 1º número estava ERRADO; o correto é o do parêntese.
    "11635 (11200)": "11200",   # 11635=REMOVEDOR DE NEVE (errado) -> 11200=SOLUÇÃO LIMPEZA MULTIUSO
    "764 (11495)": "11495",     # 764=BALDE (errado) -> 11495=LIXEIRA
    "11868 (11863)": "11863",   # 11868=SABÃO RALADO (errado) -> 11863=SABÃO BARRA
}


class Command(BaseCommand):
    help = "Corrige códigos CATMAT/CATSER malformados do catálogo interno."

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true",
                            help="Mostra o que seria alterado sem gravar.")

    def handle(self, *args, **opts):
        total_itens = 0
        with transaction.atomic():
            for de, para in CORRECOES.items():
                qs = ItemCatalogo.objects.filter(codigo_catmat_catser=de)
                n = qs.count()
                if not n:
                    self.stdout.write(f"  (nenhum item com código '{de}')")
                    continue
                total_itens += n
                self.stdout.write(
                    f"  '{de}' -> '{para}'  ({n} item{'ns' if n > 1 else ''})"
                )
                if not opts["dry_run"]:
                    qs.update(codigo_catmat_catser=para)

            if opts["dry_run"]:
                transaction.set_rollback(True)

        modo = "[DRY-RUN — nada gravado] " if opts["dry_run"] else ""
        self.stdout.write(self.style.SUCCESS(
            f"{modo}{len(CORRECOES)} código(s) distinto(s), {total_itens} item(ns) afetado(s)."
        ))
