"""
Vincula cada ItemPCA ao seu ItemCatalogo correspondente, preenchendo a FK
`ItemPCA.item_catalogo` (que existe no modelo desde sempre, mas nenhum dos
comandos de importacao preenche — ate hoje so era possivel setar a mao pelo
admin).

Para que serve
--------------
1. VISUALIZACAO: o ItemPCA nao tem nome curto — so `descricao`, o texto longo
   que veio da planilha do PCA (media de ~115 caracteres). O nome curto existe
   no catalogo (`ItemCatalogo.descricao_padrao`, media de ~22 caracteres).
   Com a FK preenchida, as telas passam a poder exibir o nome do catalogo e
   deixar a descricao completa no tooltip/detalhe.
2. CONTINUIDADE: a classificacao do Ato PGJ 1.415/2024 e a proposta automatica
   de renovacao para o exercicio seguinte dependem do vinculo com o catalogo.

Como o pareamento e feito
-------------------------
Em ordem decrescente de confianca, parando no primeiro que casar:

    exato   descricao do item == descricao_detalhada do catalogo
            (comparacao normalizada: minusculas, sem acento, espacos
            colapsados). E o caso mais forte — as duas bases costumam ter
            sido alimentadas pelo mesmo texto de origem.
    alta    codigo CATMAT/CATSER igual E similaridade >= 0.85
    media   codigo CATMAT/CATSER igual E similaridade >= --limiar (0.60)
    baixa   sem codigo em comum, mas similaridade >= --limiar-sem-codigo (0.90)

Abaixo disso o item fica SEM vinculo — de proposito. Um vinculo errado e pior
que vinculo nenhum: ele faria a tela exibir o nome de outro item.

A similaridade e o `difflib.SequenceMatcher` sobre os textos normalizados,
comparando a descricao do ItemPCA com a descricao_detalhada do catalogo e,
como alternativa, com a descricao_padrao — vale a maior das duas.

Uso:
    # 1. ver a taxa de acerto sem gravar nada
    python manage.py vincular_itens_catalogo --dry-run

    # 2. gerar planilha para conferir item a item antes de decidir
    python manage.py vincular_itens_catalogo --dry-run --csv vinculos.csv

    # 3. gravar
    python manage.py vincular_itens_catalogo

    # opcionais
    --exercicio 2026        so os itens do PCA daquele exercicio
    --limiar 0.70           exige mais similaridade quando o codigo bate
    --limiar-sem-codigo 0.95
    --refazer               revincula tambem os itens que ja tem FK preenchida
    --incluir-inativos      considera itens de catalogo marcados como inativos
"""

import csv
import unicodedata
from difflib import SequenceMatcher

from django.core.management.base import BaseCommand
from django.db import transaction

from apps.pca.models import ItemCatalogo, ItemPCA

# Comparar textos gigantes deixa o SequenceMatcher quadratico sem ganho de
# precisao — o inicio da descricao ja identifica o item.
MAX_CHARS_COMPARACAO = 200


def _normalizar(texto):
    """Minusculas, sem acento, espacos colapsados — para comparacao."""
    texto = (texto or "").strip()
    texto = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode("ascii")
    return " ".join(texto.lower().split())


class Command(BaseCommand):
    help = "Vincula ItemPCA ao ItemCatalogo correspondente (preenche a FK item_catalogo)."

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true",
                            help="Mostra o que seria vinculado sem gravar.")
        parser.add_argument("--exercicio", type=int, default=0,
                            help="Limita aos itens do PCA deste exercicio (0 = todos).")
        parser.add_argument("--limiar", type=float, default=0.60,
                            help="Similaridade minima quando o codigo CATMAT/CATSER bate (padrao 0.60).")
        parser.add_argument("--limiar-sem-codigo", type=float, default=0.90,
                            dest="limiar_sem_codigo",
                            help="Similaridade minima quando nao ha codigo em comum (padrao 0.90).")
        parser.add_argument("--refazer", action="store_true",
                            help="Revincula tambem itens que ja tem item_catalogo preenchido.")
        parser.add_argument("--incluir-inativos", action="store_true",
                            help="Considera tambem itens de catalogo inativos.")
        parser.add_argument("--csv", dest="csv_path", default="",
                            help="Grava planilha de conferencia com o resultado item a item.")

    # ------------------------------------------------------------------
    def _melhor_similaridade(self, matcher, candidato):
        """Maior similaridade entre o texto do ItemPCA (ja em `matcher`) e o candidato."""
        melhor = 0.0
        for texto in (candidato["detalhada_norm"], candidato["padrao_norm"]):
            if not texto:
                continue
            matcher.set_seq1(texto[:MAX_CHARS_COMPARACAO])
            # Filtros baratos antes do ratio() — descartam a maioria dos pares.
            if matcher.real_quick_ratio() <= melhor:
                continue
            if matcher.quick_ratio() <= melhor:
                continue
            melhor = max(melhor, matcher.ratio())
        return melhor

    # ------------------------------------------------------------------
    def handle(self, *args, **opts):
        dry_run = opts["dry_run"]
        limiar = opts["limiar"]
        limiar_sem_codigo = opts["limiar_sem_codigo"]

        # --- catalogo em memoria (1.2k itens, cabe tranquilo) -------------
        cat_qs = ItemCatalogo.objects.all()
        if not opts["incluir_inativos"]:
            cat_qs = cat_qs.filter(ativo=True)

        catalogo = []
        por_codigo = {}
        por_detalhada = {}
        for c in cat_qs:
            registro = {
                "obj": c,
                "padrao_norm": _normalizar(c.descricao_padrao),
                "detalhada_norm": _normalizar(c.descricao_detalhada),
                "codigo": (c.codigo_catmat_catser or "").strip(),
            }
            catalogo.append(registro)
            if registro["codigo"]:
                por_codigo.setdefault(registro["codigo"], []).append(registro)
            # O primeiro a ocupar a chave vence — descricoes detalhadas
            # repetidas no catalogo sao itens duplicados de qualquer forma.
            if registro["detalhada_norm"]:
                por_detalhada.setdefault(registro["detalhada_norm"], registro)

        if not catalogo:
            self.stderr.write("Nenhum item de catalogo encontrado — nada a fazer.")
            return

        self.stdout.write(f"Catalogo carregado: {len(catalogo)} item(ns).")

        # --- itens do PCA -------------------------------------------------
        itens = ItemPCA.objects.select_related("item_catalogo", "dfd", "dfd__pca")
        if opts["exercicio"]:
            itens = itens.filter(dfd__pca__exercicio=opts["exercicio"])
        if not opts["refazer"]:
            itens = itens.filter(item_catalogo__isnull=True)
        itens = itens.order_by("codigo_pca")

        total = itens.count()
        self.stdout.write(f"Itens do PCA a processar: {total}\n")
        if not total:
            self.stdout.write(self.style.WARNING(
                "Nada a processar. Use --refazer para revincular itens que ja tem FK."
            ))
            return

        linhas = []
        contagem = {"exato": 0, "alta": 0, "media": 0, "baixa": 0, "sem_vinculo": 0}

        with transaction.atomic():
            for item in itens.iterator(chunk_size=200):
                desc_norm = _normalizar(item.descricao)
                codigo = (item.codigo_catmat_catser or "").strip()

                escolhido = None
                confianca = ""
                score = 0.0

                # 1. Casamento exato pela descricao detalhada.
                exato = por_detalhada.get(desc_norm)
                if exato:
                    escolhido, confianca, score = exato, "exato", 1.0

                if escolhido is None:
                    matcher = SequenceMatcher(None, "", desc_norm[:MAX_CHARS_COMPARACAO])

                    # 2/3. Mesmo codigo CATMAT/CATSER — universo pequeno e confiavel.
                    if codigo and codigo in por_codigo:
                        melhor_reg, melhor_score = None, 0.0
                        for candidato in por_codigo[codigo]:
                            s = self._melhor_similaridade(matcher, candidato)
                            if s > melhor_score:
                                melhor_reg, melhor_score = candidato, s
                        if melhor_reg is not None and melhor_score >= limiar:
                            escolhido = melhor_reg
                            score = melhor_score
                            confianca = "alta" if melhor_score >= 0.85 else "media"

                    # 4. Sem codigo em comum — varredura completa, exigencia alta.
                    if escolhido is None:
                        melhor_reg, melhor_score = None, 0.0
                        for candidato in catalogo:
                            s = self._melhor_similaridade(matcher, candidato)
                            if s > melhor_score:
                                melhor_reg, melhor_score = candidato, s
                        if melhor_reg is not None and melhor_score >= limiar_sem_codigo:
                            escolhido, confianca, score = melhor_reg, "baixa", melhor_score

                if escolhido is None:
                    contagem["sem_vinculo"] += 1
                    linhas.append({
                        "codigo_pca": item.codigo_pca,
                        "descricao_pca": item.descricao[:150],
                        "codigo_catmat_catser": codigo,
                        "confianca": "SEM VINCULO",
                        "similaridade": "",
                        "codigo_catalogo": "",
                        "nome_catalogo": "",
                    })
                    continue

                contagem[confianca] += 1
                alvo = escolhido["obj"]
                linhas.append({
                    "codigo_pca": item.codigo_pca,
                    "descricao_pca": item.descricao[:150],
                    "codigo_catmat_catser": codigo,
                    "confianca": confianca,
                    "similaridade": f"{score:.3f}",
                    "codigo_catalogo": alvo.codigo_catalogo,
                    "nome_catalogo": alvo.descricao_padrao,
                })

                if not dry_run:
                    item.item_catalogo = alvo
                    item.save(update_fields=["item_catalogo"])

            if dry_run:
                transaction.set_rollback(True)

        # --- relatorio ----------------------------------------------------
        vinculados = total - contagem["sem_vinculo"]
        modo = "[DRY-RUN — nada gravado] " if dry_run else ""

        self.stdout.write("")
        self.stdout.write("Distribuicao por confianca:")
        for chave, rotulo in [
            ("exato", "exato   (descricao identica)"),
            ("alta", "alta    (codigo bate + sim. >= 0.85)"),
            ("media", f"media   (codigo bate + sim. >= {limiar:.2f})"),
            ("baixa", f"baixa   (sem codigo + sim. >= {limiar_sem_codigo:.2f})"),
            ("sem_vinculo", "sem vinculo"),
        ]:
            self.stdout.write(f"  {rotulo}: {contagem[chave]}")

        pct = (vinculados / total * 100) if total else 0
        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS(
            f"{modo}Vinculados: {vinculados}/{total} ({pct:.1f}%) | "
            f"Sem vinculo: {contagem['sem_vinculo']}"
        ))

        if contagem["baixa"]:
            self.stdout.write(self.style.WARNING(
                f"Atencao: {contagem['baixa']} vinculo(s) de confianca BAIXA "
                "(casaram so por similaridade textual, sem codigo em comum). "
                "Vale conferir esses na planilha antes de gravar."
            ))

        if opts["csv_path"]:
            with open(opts["csv_path"], "w", newline="", encoding="utf-8-sig") as f:
                writer = csv.DictWriter(f, fieldnames=[
                    "codigo_pca", "descricao_pca", "codigo_catmat_catser",
                    "confianca", "similaridade", "codigo_catalogo", "nome_catalogo",
                ])
                writer.writeheader()
                writer.writerows(linhas)
            self.stdout.write(f"Planilha de conferencia gravada em {opts['csv_path']}")
