"""
Views Django Templates — Módulo PCA

Rotas:
    /pca/            → DashboardPCAView   (visão geral do PCA)
    /pca/demandas/   → DemandasPCAView    (lista de DFDs e itens)
    /pca/item/<pk>/  → ItemPCADetalheView (detalhe de um item)
"""

from django.contrib.auth.decorators import login_required
from django.db.models import Count, Sum
from django.shortcuts import get_object_or_404, render
from django.utils.decorators import method_decorator
from django.views import View

from .models import DocumentoFormalizacaoDemanda, ItemPCA, PlanoContratacaoAnual


@method_decorator(login_required, name="dispatch")
class DashboardPCAView(View):
    template_name = "pca/dashboard.html"

    def get(self, request):
        # PCA do exercício corrente (mais recente)
        pca = PlanoContratacaoAnual.objects.order_by("-exercicio").first()

        if pca:
            dfds = DocumentoFormalizacaoDemanda.objects.filter(pca=pca)
            itens = ItemPCA.objects.filter(dfd__pca=pca)
        else:
            dfds = DocumentoFormalizacaoDemanda.objects.none()
            itens = ItemPCA.objects.none()

        # KPIs
        total_itens = itens.count()
        valor_total = itens.aggregate(total=Sum("valor_total_estimado"))["total"] or 0
        valor_empenhado = itens.aggregate(total=Sum("valor_empenhado"))["total"] or 0

        # Distribuição por status
        por_status = (
            itens.values("status")
            .annotate(qtd=Count("id"))
            .order_by("-qtd")
        )

        # Distribuição por categoria
        por_categoria = (
            itens.values("categoria")
            .annotate(qtd=Count("id"), valor=Sum("valor_total_estimado"))
            .order_by("-valor")
        )

        # Distribuição por modalidade
        por_modalidade = (
            itens.values("modalidade")
            .annotate(qtd=Count("id"))
            .order_by("-qtd")
        )

        # Itens suspensos
        suspensos = itens.filter(status="suspenso").count()

        # Itens concluídos
        concluidos = itens.filter(status="concluido").count()

        # Itens em andamento
        em_andamento = itens.filter(status__in=["em_andamento", "iniciado"]).count()

        context = {
            "pca": pca,
            "total_dfds": dfds.count(),
            "total_itens": total_itens,
            "valor_total": valor_total,
            "valor_empenhado": valor_empenhado,
            "pct_executado": int((valor_empenhado / valor_total * 100) if valor_total else 0),
            "suspensos": suspensos,
            "concluidos": concluidos,
            "em_andamento": em_andamento,
            "por_status": list(por_status),
            "por_categoria": list(por_categoria),
            "por_modalidade": list(por_modalidade),
        }
        return render(request, self.template_name, context)


@method_decorator(login_required, name="dispatch")
class DemandasPCAView(View):
    template_name = "pca/demandas.html"

    def get(self, request):
        pca = PlanoContratacaoAnual.objects.order_by("-exercicio").first()

        itens_qs = ItemPCA.objects.select_related(
            "dfd", "dfd__pca", "dfd__unidade"
        ).order_by("dfd__pca__exercicio", "dfd__numero_dfd", "numero_item")

        if pca:
            itens_qs = itens_qs.filter(dfd__pca=pca)

        # Filtros
        status_filtro = request.GET.get("status", "")
        categoria_filtro = request.GET.get("categoria", "")
        modalidade_filtro = request.GET.get("modalidade", "")
        busca = request.GET.get("q", "").strip()

        if status_filtro:
            itens_qs = itens_qs.filter(status=status_filtro)
        if categoria_filtro:
            itens_qs = itens_qs.filter(categoria=categoria_filtro)
        if modalidade_filtro:
            itens_qs = itens_qs.filter(modalidade=modalidade_filtro)
        if busca:
            itens_qs = itens_qs.filter(descricao__icontains=busca)

        context = {
            "pca": pca,
            "itens": itens_qs,
            "total": itens_qs.count(),
            "status_filtro": status_filtro,
            "categoria_filtro": categoria_filtro,
            "modalidade_filtro": modalidade_filtro,
            "busca": busca,
            "status_choices": ItemPCA.STATUS,
            "categoria_choices": ItemPCA.CATEGORIAS,
            "modalidade_choices": ItemPCA.MODALIDADE,
        }
        return render(request, self.template_name, context)


@method_decorator(login_required, name="dispatch")
class ItemPCADetalheView(View):
    template_name = "pca/item_detalhe.html"

    def get(self, request, pk):
        item = get_object_or_404(
            ItemPCA.objects.select_related("dfd", "dfd__pca", "dfd__unidade", "item_pai"),
            pk=pk,
        )
        context = {"item": item}
        return render(request, self.template_name, context)
