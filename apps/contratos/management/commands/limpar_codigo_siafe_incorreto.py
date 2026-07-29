"""
Management command: limpar_codigo_siafe_incorreto
======================================================
Zera o campo codigo_siafe de um Contrato quando ele foi confirmado (por
consultar_contrato_siafe) como apontando pra um contrato ERRADO no SIAFE —
ou seja, o numeroOriginal/objeto/CNPJ devolvido pela API não tem nada a ver
com o registro local, apesar do numero_contrato às vezes coincidir em
texto com outro contrato real e completamente diferente.

Achado em 2026-07-29: pk=106 (33/2026/FPDC, equipamentos de filmagem) e
pk=176 (10/2026/FPDC, bebedouros) tinham codigo_siafe apontando pra
contratos de outras empresas/objetos (seguro de veículo Gente Seguradora
e material permanente Sorelle, respectivamente). Provavelmente entrada
manual equivocada em algum momento. Como o resto do registro (valor, SEI,
objeto) já estava confirmado por outras fontes (PNCP/planilha), a correção
segura é só desvincular do SIAFE errado — não reimportar nada por cima.

Uso:
  python manage.py limpar_codigo_siafe_incorreto --pk 106 176 --dry-run
  python manage.py limpar_codigo_siafe_incorreto --pk 106 176
"""

from django.core.management.base import BaseCommand

from apps.contratos.models import Contrato


class Command(BaseCommand):
    help = "Zera codigo_siafe de contratos confirmados como incorretamente vinculados"

    def add_arguments(self, parser):
        parser.add_argument("--pk", type=int, nargs="+", required=True)
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        if dry_run:
            self.stdout.write(self.style.WARNING("*** DRY-RUN — nenhuma alteração será salva ***\n"))

        for pk in options["pk"]:
            try:
                c = Contrato.objects.get(pk=pk)
            except Contrato.DoesNotExist:
                self.stdout.write(self.style.WARNING(f"pk={pk} não existe"))
                continue
            self.stdout.write(
                f"pk={c.pk} {c.numero_contrato}: codigo_siafe {c.codigo_siafe!r} -> '' "
                f"(objeto: {(c.objeto or '')[:50]})"
            )
            if not dry_run:
                c.codigo_siafe = ""
                c.save(update_fields=["codigo_siafe"])

        if not dry_run:
            self.stdout.write(self.style.SUCCESS("\nAplicado."))
