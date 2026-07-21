"""
Infere a fonte orçamentária (unidade gestora) dos contratos a partir do
sufixo do número, que no MPPI já embute essa informação:

    "28/2026 PGJ"      → pgj
    "12/2026 FMMPPI"   → fmmp   (variações: FMMP, FMMPI)
    "05/2026/FPDC"     → fepdc  (variações: FEPDC, FPROCON*)

* FPROCON tratado como o fundo do consumidor (FEPDC). Se estiver errado,
  ajustar o MAPA e re-rodar — o comando só preenche campos vazios, então
  correções manuais no admin nunca são sobrescritas.

Números sem sufixo reconhecível (empenhos "26000311", "2025NE00139",
"49/2025" etc.) ficam sem fonte e são listados no relatório.

Uso:
    python manage.py inferir_fonte_contratos --dry-run
    python manage.py inferir_fonte_contratos
"""

import re
from collections import Counter

from django.core.management.base import BaseCommand
from django.db import transaction

from apps.contratos.models import Contrato

MAPA = {
    "PGJ": "pgj",
    "FMMPPI": "fmmp",
    "FMMP": "fmmp",
    "FMMPI": "fmmp",
    "FPDC": "fepdc",
    "FEPDC": "fepdc",
    "FPROCON": "fepdc",
}

PADRAO_SUFIXO = re.compile(r"\d{4}\s*[/\s-]+\s*([A-Za-z]+)")


class Command(BaseCommand):
    help = "Infere unidade_orcamentaria dos contratos pelo sufixo do número."

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args, **opts):
        inferidos = Counter()
        sem_padrao = []
        ja_preenchidos = 0

        with transaction.atomic():
            for contrato in Contrato.objects.all():
                if contrato.unidade_orcamentaria:
                    ja_preenchidos += 1
                    continue  # nunca sobrescreve decisão manual

                m = PADRAO_SUFIXO.search(contrato.numero_contrato or "")
                sufixo = m.group(1).upper() if m else None
                fonte = MAPA.get(sufixo) if sufixo else None

                if fonte:
                    inferidos[fonte] += 1
                    if not opts["dry_run"]:
                        contrato.unidade_orcamentaria = fonte
                        contrato.save(update_fields=["unidade_orcamentaria"])
                else:
                    sem_padrao.append(contrato.numero_contrato)

            if opts["dry_run"]:
                transaction.set_rollback(True)

        modo = "[DRY-RUN — nada gravado] " if opts["dry_run"] else ""
        self.stdout.write(self.style.SUCCESS(
            f"{modo}Inferidos: {sum(inferidos.values())} "
            f"(pgj={inferidos['pgj']}, fmmp={inferidos['fmmp']}, fepdc={inferidos['fepdc']}) | "
            f"Já preenchidos (mantidos): {ja_preenchidos} | Sem padrão: {len(sem_padrao)}"
        ))
        if sem_padrao:
            self.stdout.write("\nSem sufixo reconhecível (preencher manualmente no admin):")
            for n in sem_padrao[:30]:
                self.stdout.write(f"  {n}")
            if len(sem_padrao) > 30:
                self.stdout.write(f"  ... e mais {len(sem_padrao) - 30}")
