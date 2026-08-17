"""Views Django Templates — DFDs (Documento de Formalização de Demanda), dentro de Artefatos.

O modelo DocumentoFormalizacaoDemanda mora em apps.pca (é criado junto com os
ItemPCA pela tela de cadastro em grupo, ver apps/pca/views_cadastro.py) — mas a
gestão dele como "artefato" formal do planejamento (junto de ETP e TR) fica
aqui em planejamento, respeitando a divisão pedida por Thiago em 2026-08-17.
"""

from decimal import Decimal

from django.contrib.auth.decorators import login_required
from django.db.models import Count, Q, Sum
from django.shortcuts import get_object_or_404, render
from django.utils.decorators import method_decorator
from django.views import View

from apps.core.models import UnidadeRequisitante
from apps.pca.models import DocumentoFormalizacaoDemanda, PlanoContratacaoAnual

from .models import DocumentoOficializacaoDemanda


def _resolver_pca(request, todos_pcas):
    """Respeita ?pca_id= na querystring; senão cai no exercício mais recente."""
    pca_id = request.GET.get("pca_id")
    if pca_id:
        pca_selecionado = todos_pcas.filter(pk=pca_id).first()
        if pca_selecionado:
            return pca_selecionado
    return todos_pcas.first()


@method_decorator(login_required, name="dispatch")
class DFDListView(View):
    template_name = "planejamento/dfds.html"

    def get(self, request):
        todos_pcas_qs = PlanoContratacaoAnual.objects.order_by("-exercicio")
        pca = _resolver_pca(request, todos_pcas_qs)

        dfds_qs = (
            DocumentoFormalizacaoDemanda.objects
            .select_related("pca", "unidade", "requisitante")
            .annotate(
                qtd_itens=Count("itens", distinct=True),
                valor_total=Sum("itens__valor_total_estimado"),
            )
            .order_by("-criado_em")
        )
        if pca:
            dfds_qs = dfds_qs.filter(pca=pca)

        status_filtro = request.GET.get("status", "")
        if status_filtro:
            dfds_qs = dfds_qs.filter(status=status_filtro)

        unidade_filtro = request.GET.get("unidade", "")
        if unidade_filtro:
            dfds_qs = dfds_qs.filter(unidade_id=unidade_filtro)

        prioridade_filtro = request.GET.get("prioridade", "")
        if prioridade_filtro:
            dfds_qs = dfds_qs.filter(grau_prioridade=prioridade_filtro)

        busca = request.GET.get("q", "").strip()
        if busca:
            dfds_qs = dfds_qs.filter(
                Q(numero_dfd__icontains=busca)
                | Q(numero_sei__icontains=busca)
                | Q(descricao_objeto__icontains=busca)
            )

        # Só unidades que têm DFD no PCA exibido — evita opção que filtra para vazio
        unidades_qs = UnidadeRequisitante.objects.order_by("sigla")
        if pca:
            unidades_qs = unidades_qs.filter(
                documentoformalizacaodemanda__pca=pca
            ).distinct()

        context = {
            "pca": pca,
            "todos_pcas": todos_pcas_qs,
            "dfds": dfds_qs,
            "total": dfds_qs.count(),
            "status_filtro": status_filtro,
            "unidade_filtro": unidade_filtro,
            "prioridade_filtro": prioridade_filtro,
            "busca": busca,
            "status_choices": DocumentoFormalizacaoDemanda.STATUS,
            "unidades": unidades_qs,
        }
        return render(request, self.template_name, context)


@method_decorator(login_required, name="dispatch")
class DFDDetalheView(View):
    template_name = "planejamento/dfd_detalhe.html"

    def get(self, request, pk):
        dfd = get_object_or_404(
            DocumentoFormalizacaoDemanda.objects.select_related(
                "pca", "unidade", "requisitante"
            ),
            pk=pk,
        )
        itens = list(dfd.itens.order_by("numero_item"))

        # DFD não liga direto em ETP — o vínculo passa pelo DOD (Documento
        # de Oficialização da Demanda, apps/planejamento), que agrupa os
        # itens já aprovados no PCA que serão instruídos juntos. Um item
        # pode (ainda) não estar em nenhum DOD.
        dods_por_item = {}
        if itens:
            dods = (
                DocumentoOficializacaoDemanda.objects.filter(itens__in=itens)
                .select_related("etp")
                .prefetch_related("itens")
                .distinct()
            )
            for dod in dods:
                for item in dod.itens.all():
                    dods_por_item.setdefault(item.pk, dod)

        for item in itens:
            dod = dods_por_item.get(item.pk)
            item.dod_vinculado = dod
            item.etp_vinculado = getattr(dod, "etp", None) if dod else None

        valor_total = sum((item.valor_total_estimado for item in itens), Decimal("0"))

        # Itens deste DFD que já podem entrar num DOD novo (aprovados no PCA e
        # ainda sem DOD aberto) — usado pelo atalho "Iniciar DOD com estes
        # itens" no template, que pré-marca só esses na tela de criação.
        itens_elegiveis_dod = [
            item for item in itens
            if item.status_aprovacao in ("aprovada_integral", "aprovada_parcial") and not item.dod_vinculado
        ]
        itens_elegiveis_dod_ids = ",".join(str(item.pk) for item in itens_elegiveis_dod)

        context = {
            "dfd": dfd,
            "itens": itens,
            "valor_total": valor_total,
            "itens_elegiveis_dod_ids": itens_elegiveis_dod_ids,
            "qtd_itens_elegiveis_dod": len(itens_elegiveis_dod),
        }
        return render(request, self.template_name, context)
