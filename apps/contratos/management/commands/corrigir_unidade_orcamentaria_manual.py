"""
Management command: corrigir_unidade_orcamentaria_manual
====================================================
Preenche `Contrato.unidade_orcamentaria` para contratos confirmados
manualmente (numero_contrato sem sufixo reconhecível pelo
`inferir_fonte_contratos`, então precisam de decisão explícita, com fonte
documentada no comentário do dict abaixo).

Nunca sobrescreve um valor já preenchido — mesma trava de segurança do
`inferir_fonte_contratos`.

Uso:
  python manage.py corrigir_unidade_orcamentaria_manual --dry-run
  python manage.py corrigir_unidade_orcamentaria_manual
"""

from django.core.management.base import BaseCommand

from apps.contratos.models import Contrato

# numero_contrato -> unidade_orcamentaria, com a fonte da confirmação.
CORRECOES_MANUAIS = {
    # Achado via conciliar_tcepi (2026-07-29): credor EPSG EMPRESA DE
    # PORTARIA E SERVICOS GERAIS LTDA ME (CNPJ 04276973000109) tem 3
    # contratos no MPPI; a soma bruta dos 3 (R$545.495,59) bate EXATAMENTE
    # com o total "empenhado" desse credor no TCE-PI para a UG 250101 (PGJ)
    # no exercício 2026 — confirmando que os 3 são PGJ, incluindo estes 2
    # que ficaram sem sufixo reconhecível no número (pk=230 e pk=238).
    "23002407": "pgj",
    "21/2024": "pgj",
}


class Command(BaseCommand):
    help = "Preenche unidade_orcamentaria de contratos confirmados manualmente (nunca sobrescreve valor já preenchido)"

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        aplicados = 0
        ja_preenchidos = 0
        nao_encontrados = []

        for numero, fonte in CORRECOES_MANUAIS.items():
            contrato = Contrato.objects.filter(numero_contrato=numero).first()
            if not contrato:
                nao_encontrados.append(numero)
                continue

            if contrato.unidade_orcamentaria:
                ja_preenchidos += 1
                self.stdout.write(
                    f"  [ja preenchido, mantido] pk={contrato.pk} {numero!r}: "
                    f"unidade_orcamentaria={contrato.unidade_orcamentaria!r} (dict pedia {fonte!r})"
                )
                continue

            self.stdout.write(f"  pk={contrato.pk} {numero!r}: (vazio) -> {fonte!r}")
            if not dry_run:
                contrato.unidade_orcamentaria = fonte
                contrato.save(update_fields=["unidade_orcamentaria"])
            aplicados += 1

        if nao_encontrados:
            self.stdout.write(self.style.WARNING(f"\nNão encontrados no banco: {nao_encontrados}"))

        modo = "[DRY-RUN — nada gravado] " if dry_run else ""
        self.stdout.write(self.style.SUCCESS(
            f"\n{modo}Aplicados: {aplicados} | Já preenchidos (mantidos): {ja_preenchidos}"
        ))
