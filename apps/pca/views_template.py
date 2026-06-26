"""
Views Django Templates — Módulo PCA

Rotas:
    /pca/                → DashboardPCAView        (visão geral do PCA)
    /pca/demandas/       → DemandasPCAView         (lista de DFDs e itens)
    /pca/item/<pk>/      → ItemPCADetalheView      (detalhe de um item)
    /pca/renovacao/      → RenovacaoExercicioView  (fluxo de renovação multiexercício)
    /pca/api/catalogo/   → CatalogoSearchView      (JSON — busca de itens do catálogo)
"""

import datetime

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.db.models import Count, Max, Q, Sum
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.decorators import method_decorator
from django.views import View

from .models import (
    DocumentoFormalizacaoDemanda,
    ItemCatalogo,
    ItemPCA,
    PlanoContratacaoAnual,
)


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
        ).order_by("dfd__pca__exercicio", "numero_lote_pca", "dfd__numero_dfd", "numero_item")

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


# ─────────────────────────────────────────────────────────────
# Catálogo — endpoint JSON para busca (AJAX)
# ─────────────────────────────────────────────────────────────

@method_decorator(login_required, name="dispatch")
class CatalogoSearchView(View):
    """
    GET /pca/api/catalogo/?q=...&classificacao=...
    Retorna até 20 itens do catálogo em JSON para uso em formulários.
    """

    def get(self, request):
        q = request.GET.get("q", "").strip()
        classificacao = request.GET.get("classificacao", "").strip()

        qs = ItemCatalogo.objects.filter(ativo=True)
        if q:
            qs = qs.filter(
                Q(descricao_padrao__icontains=q)
                | Q(codigo_catalogo__icontains=q)
                | Q(codigo_catmat_catser__icontains=q)
            )
        if classificacao:
            qs = qs.filter(classificacao=classificacao)

        results = list(
            qs.values(
                "id", "codigo_catalogo", "descricao_padrao",
                "categoria", "classificacao", "codigo_catmat_catser",
                "unidade_medida_padrao", "modalidade_sugerida", "base_normativa",
            )[:20]
        )
        return JsonResponse({"results": results})


# ─────────────────────────────────────────────────────────────
# Renovação Multiexercício
# ─────────────────────────────────────────────────────────────

@method_decorator(login_required, name="dispatch")
class RenovacaoExercicioView(View):
    """
    GET  /pca/renovacao/         — mostra itens contínuos para seleção
    GET  /pca/renovacao/?ids=... — pré-seleciona IDs vindos da action do Admin
    POST /pca/renovacao/         — executa a renovação
    """

    template_name = "pca/renovacao.html"

    def get(self, request):
        pca_atual = PlanoContratacaoAnual.objects.order_by("-exercicio").first()
        todos_pcas = PlanoContratacaoAnual.objects.order_by("-exercicio")

        # Itens selecionados via Admin action (query-string ?ids=1,2,3)
        ids_param = request.GET.get("ids", "")
        ids_pre = [int(i) for i in ids_param.split(",") if i.strip().isdigit()]

        # Itens contínuos do PCA atual disponíveis para renovação
        qs = (
            ItemPCA.objects
            .filter(dfd__pca=pca_atual, classificacao_continuidade__startswith="continuo_")
            .select_related("dfd", "dfd__unidade", "dfd__pca", "item_catalogo")
            .order_by("classificacao_continuidade", "dfd__unidade__nome", "descricao")
        ) if pca_atual else ItemPCA.objects.none()

        context = {
            "pca_atual": pca_atual,
            "todos_pcas": todos_pcas,
            "itens": qs,
            "ids_pre": ids_pre,
            "proximo_exercicio": (pca_atual.exercicio + 1) if pca_atual else None,
        }
        return render(request, self.template_name, context)

    def post(self, request):
        ids_sel = request.POST.getlist("itens_sel")
        pca_destino_id = request.POST.get("pca_destino")

        if not ids_sel:
            messages.error(request, "Selecione ao menos um item para renovar.")
            return redirect("pca:renovacao")

        if not pca_destino_id:
            messages.error(request, "Selecione o PCA de destino.")
            return redirect("pca:renovacao")

        pca_destino = get_object_or_404(PlanoContratacaoAnual, pk=pca_destino_id)
        itens_origem = ItemPCA.objects.filter(
            pk__in=ids_sel
        ).select_related("dfd", "dfd__unidade", "dfd__pca")

        criados = 0
        ignorados = 0

        with transaction.atomic():
            for item in itens_origem:
                # Verifica se já existe uma renovação deste item no PCA destino
                ja_existe = ItemPCA.objects.filter(
                    origem_item=item, dfd__pca=pca_destino
                ).exists()
                if ja_existe:
                    ignorados += 1
                    continue

                # Obtém ou cria um DFD genérico de renovação para a unidade no PCA destino
                dfd_destino, _ = DocumentoFormalizacaoDemanda.objects.get_or_create(
                    pca=pca_destino,
                    unidade=item.dfd.unidade,
                    numero_dfd=f"REN-{pca_destino.exercicio}-{item.dfd.unidade_id}",
                    defaults={
                        "descricao_objeto": (
                            f"Renovação de contratações contínuas — "
                            f"{item.dfd.unidade} — exercício {pca_destino.exercicio}"
                        ),
                        "justificativa": (
                            f"Renovação automática de itens classificados como contínuos "
                            f"conforme Ato PGJ 1.415/2024, originados do PCA "
                            f"{item.dfd.pca.exercicio}."
                        ),
                        "prazo_necessidade": datetime.date(pca_destino.exercicio, 12, 31),
                        "grau_prioridade": item.dfd.grau_prioridade,
                        "status": "rascunho",
                        "requisitante": request.user,
                    },
                )

                # Calcula próximo número de item no DFD destino
                ultimo_num = (
                    ItemPCA.objects.filter(dfd=dfd_destino)
                    .aggregate(m=Max("numero_item"))["m"]
                ) or 0

                ItemPCA.objects.create(
                    dfd=dfd_destino,
                    numero_item=ultimo_num + 1,
                    # Vinculação ao exercício anterior e ao catálogo
                    origem_item=item,
                    item_catalogo=item.item_catalogo,
                    classificacao_continuidade=item.classificacao_continuidade,
                    # Cópia dos dados do objeto
                    categoria=item.categoria,
                    codigo_catmat_catser=item.codigo_catmat_catser,
                    descricao=item.descricao,
                    unidade_fornecimento=item.unidade_fornecimento,
                    quantidade_estimada=item.quantidade_estimada,
                    valor_unitario_estimado=item.valor_unitario_estimado,
                    valor_total_estimado=item.valor_total_estimado,
                    # Tipo e modalidade mantidos
                    tipo_demanda="renovacao",
                    modalidade=item.modalidade,
                    normativo=item.normativo,
                    unidade_orcamentaria=item.unidade_orcamentaria,
                    is_srp=item.is_srp,
                    numero_lote_pca=item.numero_lote_pca,
                    # Status inicial
                    status="nao_iniciado",
                    observacoes=(
                        f"Renovado automaticamente a partir de {item.codigo_pca} "
                        f"(PCA {item.dfd.pca.exercicio})."
                    ),
                )
                criados += 1

        if criados:
            messages.success(
                request,
                f"{criados} item(ns) renovado(s) com sucesso para o PCA {pca_destino.exercicio}."
                + (f" {ignorados} já existia(m) e foram ignorados." if ignorados else ""),
            )
        else:
            messages.warning(
                request,
                f"Nenhum item novo criado — todos os {ignorados} selecionados já haviam sido renovados.",
            )

        return redirect("pca:demandas")
