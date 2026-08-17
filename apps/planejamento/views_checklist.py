"""Views Django Templates — Checklist de instrução dos processos de contratação.

Tela combinada (decidido com Thiago em 2026-08-17, "as duas visões na mesma
tela"), com duas seções na mesma página:

1. Backlog: itens já aprovados no PCA que ainda não têm um DOD "aberto"
   vinculado, agrupados por unidade requisitante — cada grupo tem um atalho
   "Iniciar DOD" que já leva os itens pré-selecionados pra
   `planejamento:dod_novo` (mesmo padrão de querystring usado em
   dfd_detalhe.html: ?pca_id=&unidade_id=&itens=1,2,3).

   Regra de "tem DOD aberto" replicada de `views_dod._itens_elegiveis` —
   NÃO de `DFDDetalheView.itens_elegiveis_dod` (que usa "qualquer DOD",
   mais restritivo). A fonte de verdade de negócio é o signal
   `validar_itens_dod` (apps/planejamento/models.py), que só bloqueia por
   DOD com status "aberto" — o backlog segue essa mesma regra pra não
   mostrar "ainda no backlog" um item que na hora de tentar abrir o DOD
   seria aceito, ou vice-versa.

2. Checklist por processo: cada DOD do PCA selecionado, com o status dos
   artefatos que dependem dele — Equipe de Planejamento, ETP, Matriz de
   Risco, Termo de Referência — conforme art. 20 do Decreto 21.872/2023 e
   Ato PGJ 1381/2024. Hoje (2026-08-17) fica vazia: 0 DODs cadastrados
   ainda no sistema, é esperado.
"""

from decimal import Decimal

from django.contrib.auth.decorators import login_required
from django.utils.decorators import method_decorator
from django.views import View
from django.shortcuts import render

from apps.pca.models import ItemPCA, PlanoContratacaoAnual

from .models import DocumentoOficializacaoDemanda
from .views_dfd import _resolver_pca


@method_decorator(login_required, name="dispatch")
class ChecklistInstrucaoView(View):
    template_name = "planejamento/checklist_instrucao.html"

    def get(self, request):
        todos_pcas_qs = PlanoContratacaoAnual.objects.order_by("-exercicio")
        pca = _resolver_pca(request, todos_pcas_qs)

        backlog = self._montar_backlog(pca)
        processos = self._montar_processos(pca)

        context = {
            "pca": pca,
            "todos_pcas": todos_pcas_qs,
            "backlog": backlog,
            "total_itens_backlog": sum(g["qtd_itens"] for g in backlog),
            "processos": processos,
            "total_processos": len(processos),
        }
        return render(request, self.template_name, context)

    def _montar_backlog(self, pca):
        if not pca:
            return []

        itens = list(
            ItemPCA.objects
            .filter(dfd__pca=pca, status_aprovacao__in=["aprovada_integral", "aprovada_parcial"])
            .exclude(documentos_oficializacao__status="aberto")
            .select_related("dfd", "dfd__unidade")
            .order_by("dfd__unidade__sigla", "codigo_pca")
        )

        grupos = {}
        for item in itens:
            unidade = item.dfd.unidade if item.dfd_id else None
            sigla = unidade.sigla if unidade else "—"
            grupo = grupos.setdefault(sigla, {
                "unidade": unidade,
                "sigla": sigla,
                "itens": [],
                "valor_total": Decimal("0"),
            })
            grupo["itens"].append(item)
            grupo["valor_total"] += item.valor_total_estimado or Decimal("0")

        for grupo in grupos.values():
            grupo["qtd_itens"] = len(grupo["itens"])
            grupo["itens_ids_csv"] = ",".join(str(i.pk) for i in grupo["itens"])

        return sorted(grupos.values(), key=lambda g: g["sigla"])

    def _montar_processos(self, pca):
        if not pca:
            return []

        dods = (
            DocumentoOficializacaoDemanda.objects
            .filter(pca=pca)
            .select_related("etp", "etp__matriz_risco", "etp__termo_referencia", "equipe_planejamento_ti")
            .prefetch_related("itens__dfd")
            .order_by("-criado_em")
        )

        processos = []
        for dod in dods:
            etp = getattr(dod, "etp", None)
            equipe = getattr(dod, "equipe_planejamento_ti", None)
            matriz = getattr(etp, "matriz_risco", None) if etp else None
            termo_referencia = getattr(etp, "termo_referencia", None) if etp else None

            dfds = {item.dfd for item in dod.itens.all() if item.dfd_id}

            processos.append({
                "dod": dod,
                "dfds": sorted(dfds, key=lambda d: d.numero_dfd or ""),
                "equipe": equipe,
                "etp": etp,
                "matriz_risco": matriz,
                "termo_referencia": termo_referencia,
            })

        return processos
