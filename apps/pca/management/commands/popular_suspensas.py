"""
Importa demandas suspensas/retidas do CSV relatorio_sobrestadas.csv.

Uso:
    python manage.py popular_suspensas --arquivo caminho/para/relatorio_sobrestadas.csv
    python manage.py popular_suspensas --arquivo ... --dry-run
    python manage.py popular_suspensas --arquivo ... --desfazer   (reverte para nao_iniciado)
"""
import csv
import os

from django.core.management.base import BaseCommand, CommandError

from apps.pca.models import ItemPCA


class Command(BaseCommand):
    help = "Marca itens do PCA como suspenso a partir do relatorio_sobrestadas.csv"

    def add_arguments(self, parser):
        parser.add_argument(
            "--arquivo",
            default="relatorio_sobrestadas.csv",
            help="Caminho para o CSV (default: relatorio_sobrestadas.csv no diretorio corrente)",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Apenas simula sem gravar",
        )
        parser.add_argument(
            "--desfazer",
            action="store_true",
            help="Reverte status para nao_iniciado e limpa tipo_suspensao",
        )

    def handle(self, *args, **options):
        arquivo = options["arquivo"]
        dry_run = options["dry_run"]
        desfazer = options["desfazer"]

        if not os.path.exists(arquivo):
            raise CommandError(f"Arquivo nao encontrado: {arquivo}")

        with open(arquivo, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            rows = list(reader)

        self.stdout.write(f"Lidos {len(rows)} registros do CSV.")

        nao_encontrados = []
        atualizados = 0
        ja_suspensos = 0

        for row in rows:
            codigo = row.get("Cod. PCA", "").strip().strip('"')
            tipo_raw = row.get("Tipo Sobrestamento", "").strip()
            tipo = "total" if tipo_raw.lower() == "total" else "parcial"

            try:
                item = ItemPCA.objects.get(codigo_pca=codigo)
            except ItemPCA.DoesNotExist:
                nao_encontrados.append(codigo)
                continue

            if desfazer:
                if not dry_run:
                    item.status = "nao_iniciado"
                    item.tipo_suspensao = None
                    item.save(update_fields=["status", "tipo_suspensao"])
                atualizados += 1
                self.stdout.write(f"  REVERTIDO: {codigo}")
            else:
                if item.status == "suspenso" and not dry_run:
                    ja_suspensos += 1
                if not dry_run:
                    item.status = "suspenso"
                    item.tipo_suspensao = tipo
                    item.save(update_fields=["status", "tipo_suspensao"])
                atualizados += 1
                label = "[DRY]" if dry_run else "OK"
                self.stdout.write(
                    f"  {label} {codigo} -> suspenso ({tipo}) | {row.get('Setor','')} | R$ {row.get('Valor Retido','')}"
                )

        self.stdout.write(self.style.SUCCESS(
            f"\nResumo: {atualizados} atualizados, "
            f"{ja_suspensos} ja estavam suspensos, "
            f"{len(nao_encontrados)} nao encontrados."
        ))
        if nao_encontrados:
            self.stdout.write(self.style.WARNING(
                f"Nao encontrados ({len(nao_encontrados)}): {', '.join(nao_encontrados[:20])}"
                + (" ..." if len(nao_encontrados) > 20 else "")
            ))
        if dry_run:
            self.stdout.write(self.style.WARNING("Modo DRY-RUN: nenhuma alteracao foi gravada."))
