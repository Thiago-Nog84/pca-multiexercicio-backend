"""
Valida os códigos PDM/CATSER do catálogo interno contra a base oficial
do Governo Federal (dadosabertos.compras.gov.br).

Apoia a curadoria feita pelo setor de licitações: aponta códigos que não
existem na base oficial, e mostra a descrição/classe oficial de cada um para
conferência com a descrição que usamos internamente.

Uso:
    python manage.py validar_codigos_catalogo                 # todos os ativos
    python manage.py validar_codigos_catalogo --so-invalidos  # só o que falhou
    python manage.py validar_codigos_catalogo --limite 50
    python manage.py validar_codigos_catalogo --csv relatorio.csv

Observação: a API não faz busca por descrição livre, então a validação é
por código. Materiais são conferidos primeiro como PDM (nível que o nosso
catálogo usa) e depois como item CATMAT; serviços, como CATSER.
"""

import csv
import time

from django.core.management.base import BaseCommand

from apps.pca.models import ItemCatalogo
from apps.pca.services.catalogo_gov import CatalogoGovIndisponivel, validar_codigo

# Categorias que são inequivocamente serviço → validar só no CATSER.
# "software" fica DE FORA de propósito: licença de software é frequentemente
# catalogada como produto CATMAT (ex.: PDM 16431 "SOFTWARE APLICATIVO"), então
# para software deixamos o validador tentar CATMAT e CATSER (tipo=None).
CATEGORIAS_SERVICO = {
    "servico", "servico_engenharia", "servico_terceirizado",
    "treinamento", "publicidade",
}


class Command(BaseCommand):
    help = "Valida os códigos do catálogo interno contra o CATMAT/CATSER oficial."

    def add_arguments(self, parser):
        parser.add_argument("--limite", type=int, default=0,
                            help="Valida apenas os N primeiros (0 = todos).")
        parser.add_argument("--so-invalidos", action="store_true",
                            help="Exibe apenas os códigos com problema.")
        parser.add_argument("--incluir-inativos", action="store_true",
                            help="Inclui itens marcados como inativos.")
        parser.add_argument("--so-com-codigo", action="store_true",
                            help="Ignora itens sem código preenchido (ex: catálogo legado).")
        parser.add_argument("--csv", dest="csv_path", default="",
                            help="Grava o resultado completo em CSV.")
        parser.add_argument("--pausa", type=float, default=0.4,
                            help=("Pausa entre chamadas à API, em segundos. "
                                  "A API oficial aplica rate limit (HTTP 429) — "
                                  "valores baixos disparam espera automática."))

    def handle(self, *args, **opts):
        qs = ItemCatalogo.objects.all().order_by("codigo_catalogo")
        if not opts["incluir_inativos"]:
            qs = qs.filter(ativo=True)
        if opts["so_com_codigo"]:
            qs = qs.exclude(codigo_catmat_catser="")
        if opts["limite"]:
            qs = qs[: opts["limite"]]

        total = qs.count() if hasattr(qs, "count") else len(qs)
        self.stdout.write(f"Validando {total} item(ns) do catálogo interno...\n")

        linhas = []
        validos = invalidos = sem_codigo = indisponivel = 0

        for item in qs:
            codigo = (item.codigo_catmat_catser or "").strip()
            if not codigo:
                sem_codigo += 1
                linhas.append({
                    "codigo_catalogo": item.codigo_catalogo,
                    "descricao_interna": item.descricao_padrao,
                    "codigo": "",
                    "situacao": "SEM CÓDIGO",
                    "nivel": "",
                    "descricao_oficial": "",
                    "classe_oficial": "",
                })
                if not opts["so_invalidos"]:
                    continue
                self.stdout.write(self.style.WARNING(
                    f"  [SEM CÓDIGO] {item.codigo_catalogo} — {item.descricao_padrao[:60]}"
                ))
                continue

            tipo = "CATSER" if item.categoria in CATEGORIAS_SERVICO else None
            try:
                r = validar_codigo(codigo, tipo)
            except CatalogoGovIndisponivel as e:
                indisponivel += 1
                self.stderr.write(f"  API indisponível em {codigo}: {e}")
                continue

            if r.get("encontrado") is None:
                indisponivel += 1
                situacao = "API INDISPONÍVEL"
            elif r.get("encontrado"):
                validos += 1
                situacao = "OK"
            else:
                invalidos += 1
                situacao = "NÃO ENCONTRADO"

            linhas.append({
                "codigo_catalogo": item.codigo_catalogo,
                "descricao_interna": item.descricao_padrao,
                "codigo": codigo,
                "situacao": situacao,
                "nivel": r.get("nivel", ""),
                "descricao_oficial": r.get("descricao", ""),
                "classe_oficial": r.get("classe", ""),
            })

            if situacao == "OK" and not opts["so_invalidos"]:
                extra = ""
                if r.get("nivel") == "pdm":
                    extra = f" ({r.get('itens_no_pdm')} itens no PDM)"
                self.stdout.write(
                    f"  [OK] {codigo:>8} {r.get('nivel',''):<12} "
                    f"{r.get('descricao','')[:45]}{extra}"
                )
            elif situacao != "OK":
                self.stdout.write(self.style.ERROR(
                    f"  [{situacao}] {codigo:>8} — {item.descricao_padrao[:55]}"
                ))

            if opts["pausa"]:
                time.sleep(opts["pausa"])

        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS(
            f"Válidos: {validos} | Não encontrados: {invalidos} | "
            f"Sem código: {sem_codigo} | API indisponível: {indisponivel}"
        ))

        if opts["csv_path"]:
            with open(opts["csv_path"], "w", newline="", encoding="utf-8-sig") as f:
                writer = csv.DictWriter(f, fieldnames=[
                    "codigo_catalogo", "descricao_interna", "codigo", "situacao",
                    "nivel", "descricao_oficial", "classe_oficial",
                ])
                writer.writeheader()
                writer.writerows(linhas)
            self.stdout.write(f"Relatório gravado em {opts['csv_path']}")
