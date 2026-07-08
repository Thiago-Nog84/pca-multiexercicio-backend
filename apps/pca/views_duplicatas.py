"""
Relatorio de deduplicacao de itens do PCA.

Detecta possiveis itens duplicados/semelhantes cadastrados por unidades
diferentes (ou pela mesma unidade) no mesmo PCA, para consolidacao antes
do fechamento do plano. Duas estrategias, da mais forte para a mais fraca:

1. Mesmo codigo CATMAT/CATSER (nao vazio) — sinal forte de item identico.
2. Mesma descricao normalizada (minusculas, sem acentos, sem pontuacao,
   conjunto de palavras significativas ordenado) — captura variacoes de
   digitacao como "Cafe torrado e moido" vs "cafe moido torrado".

Grupos com itens de MAIS de uma unidade sao os candidatos classicos a
consolidacao (StartGov chama isso de "deduplicacao na consolidacao");
grupos dentro da mesma unidade tambem sao exibidos, com destaque menor.
"""

import re
import unicodedata
from collections import defaultdict

from django.contrib.auth.decorators import login_required
from django.db.models import Sum
from django.shortcuts import render
from django.utils.decorators import method_decorator
from django.views import View

from .models import ItemPCA, PlanoContratacaoAnual
from .views_template import _resolver_pca

# Palavras sem valor discriminante para comparacao de descricoes
_STOPWORDS = {
    "a", "o", "e", "de", "da", "do", "das", "dos", "em", "na", "no",
    "para", "com", "sem", "por", "um", "uma", "tipo", "cor", "ou",
    "ate", "sob", "sobre", "entre", "the",
}

_MIN_TOKENS = 2  # descricoes com menos tokens significativos nao agrupam


def _normalizar(texto):
    """minusculas + sem acentos + so alfanumerico + espacos unicos."""
    texto = unicodedata.normalize("NFKD", texto or "")
    texto = texto.encode("ascii", "ignore").decode("ascii").lower()
    texto = re.sub(r"[^a-z0-9 ]+", " ", texto)
    return re.sub(r"\s+", " ", texto).strip()


def _chave_descricao(descricao):
    """Conjunto ordenado de tokens significativos — invariante a ordem."""
    tokens = [
        t for t in _normalizar(descricao).split()
        if t not in _STOPWORDS and len(t) > 1
    ]
    if len(tokens) < _MIN_TOKENS:
        return None
    return " ".join(sorted(set(tokens)))


@method_decorator(login_required, name="dispatch")
class DuplicatasPCAView(View):
    template_name = "pca/duplicatas.html"

    def get(self, request):
        todos_pcas_qs = PlanoContratacaoAnual.objects.order_by("-exercicio")
        pca = _resolver_pca(request, todos_pcas_qs)
        so_entre_unidades = request.GET.get("entre_unidades", "") == "1"

        itens = (
            ItemPCA.objects.filter(dfd__pca=pca)
            .exclude(status="suspenso")
            .select_related("dfd__unidade")
            .order_by("dfd__unidade__sigla", "numero_item")
        ) if pca else ItemPCA.objects.none()

        por_catmat = defaultdict(list)
        por_descricao = defaultdict(list)

        for item in itens:
            catmat = (item.codigo_catmat_catser or "").strip()
            if catmat:
                por_catmat[catmat].append(item)
            chave = _chave_descricao(item.descricao)
            if chave:
                por_descricao[chave].append(item)

        def _montar_grupos(mapa, criterio):
            grupos = []
            for chave, membros in mapa.items():
                if len(membros) < 2:
                    continue
                unidades = {
                    m.dfd.unidade.sigla if m.dfd and m.dfd.unidade else "?"
                    for m in membros
                }
                if so_entre_unidades and len(unidades) < 2:
                    continue
                grupos.append({
                    "criterio": criterio,
                    "chave": chave,
                    "itens": membros,
                    "qtd_itens": len(membros),
                    "unidades": sorted(unidades),
                    "entre_unidades": len(unidades) > 1,
                    "valor_total": sum(
                        (m.valor_total_estimado or 0) for m in membros
                    ),
                })
            return grupos

        grupos_catmat = _montar_grupos(por_catmat, "catmat")

        # Evita repetir no criterio fraco grupos ja capturados pelo CATMAT:
        # um grupo por descricao so entra se tiver algum PAR de itens que
        # nao esteja junto em nenhum grupo de CATMAT.
        ids_em_grupo_catmat = {
            frozenset(m.pk for m in g["itens"]) for g in grupos_catmat
        }
        grupos_descricao = [
            g for g in _montar_grupos(por_descricao, "descricao")
            if frozenset(m.pk for m in g["itens"]) not in ids_em_grupo_catmat
        ]

        grupos = sorted(
            grupos_catmat + grupos_descricao,
            key=lambda g: (not g["entre_unidades"], -g["qtd_itens"]),
        )

        context = {
            "pca": pca,
            "todos_pcas": todos_pcas_qs,
            "grupos": grupos,
            "total_grupos": len(grupos),
            "grupos_entre_unidades": sum(1 for g in grupos if g["entre_unidades"]),
            "itens_envolvidos": len({m.pk for g in grupos for m in g["itens"]}),
            "so_entre_unidades": so_entre_unidades,
        }
        return render(request, self.template_name, context)
