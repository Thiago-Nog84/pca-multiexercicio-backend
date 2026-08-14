"""
Views Django Templates - Modulo PCA
"""

import datetime
from datetime import timedelta


def _pca_default(todos_pcas):
    """Retorna o PCA do ano corrente; se nao existir, o mais recente."""
    ano = datetime.date.today().year
    return todos_pcas.filter(exercicio=ano).first() or todos_pcas.first()


def _resolver_pca(request, todos_pcas):
    """
    Resolve qual PCA exibir: respeita ?pca_id=<id> se presente na querystring
    (selecionado manualmente pelo usuario, ex: PCA 2027 recem-criado), senao
    cai no padrao do ano corrente (_pca_default). Sem isso, telas como
    Dashboard e Demandas ficam presas no ano corrente e escondem PCAs de
    exercicios futuros mesmo que ja tenham itens cadastrados.
    """
    pca_id = request.GET.get("pca_id")
    if pca_id:
        pca_selecionado = todos_pcas.filter(pk=pca_id).first()
        if pca_selecionado:
            return pca_selecionado
    return _pca_default(todos_pcas)

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.db.models import Count, F, Max, Q, Sum
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.decorators import method_decorator
from django.views import View

from .models import (
    DocumentoFormalizacaoDemanda,
    ItemCatalogo,
    ItemPCA,
    OrcamentoPlanejado,
    PlanoContratacaoAnual,
)


@method_decorator(login_required, name="dispatch")
class DashboardPCAView(View):
    template_name = "pca/dashboard.html"

    def get(self, request):
        todos_pcas_qs = PlanoContratacaoAnual.objects.order_by("-exercicio")
        pca = _resolver_pca(request, todos_pcas_qs)

        if pca:
            dfds = DocumentoFormalizacaoDemanda.objects.filter(pca=pca)
            itens = ItemPCA.objects.filter(dfd__pca=pca)
        else:
            dfds = DocumentoFormalizacaoDemanda.objects.none()
            itens = ItemPCA.objects.none()

        total_itens = itens.count()
        valor_total = itens.aggregate(total=Sum("valor_total_estimado"))["total"] or 0
        valor_empenhado = itens.aggregate(total=Sum("valor_empenhado"))["total"] or 0

        suspensos    = itens.filter(status="suspenso").count()
        concluidos   = itens.filter(status="concluido").count()
        em_andamento = itens.filter(status__in=["em_andamento", "iniciado"]).count()
        nao_iniciados       = itens.filter(status="nao_iniciado").count()
        pendentes_validacao = itens.filter(status="pendente_validacao").count()
        em_diligencia       = itens.filter(status="em_diligencia").count()

        # ---------- alertas de prazo ----------
        hoje = datetime.date.today()
        ativos = itens.exclude(status__in=["concluido", "suspenso"])

        # ---------- cards macro do topo (demandas/valor ATIVOS, exclui concluído/suspenso) ----------
        total_ativas = ativos.count()
        valor_pca_ativo = ativos.aggregate(total=Sum("valor_total_estimado"))["total"] or 0

        atrasados   = ativos.filter(data_pretendida_conclusao__lt=hoje).count()
        vencendo_30 = ativos.filter(
            data_pretendida_conclusao__gte=hoje,
            data_pretendida_conclusao__lte=hoje + timedelta(days=30),
        ).count()
        vencendo_90 = ativos.filter(
            data_pretendida_conclusao__gte=hoje,
            data_pretendida_conclusao__lte=hoje + timedelta(days=90),
        ).count()
        sem_prazo   = ativos.filter(data_pretendida_conclusao__isnull=True).count()

        # ---------- SRP ----------
        itens_srp  = itens.filter(is_srp=True).count()
        valor_srp  = itens.filter(is_srp=True).aggregate(
            total=Sum("valor_total_estimado")
        )["total"] or 0

        # ---------- 5 itens mais urgentes (vencendo em breve, ativos) ----------
        urgentes = list(
            ativos.filter(data_pretendida_conclusao__isnull=False)
            .select_related("dfd__unidade")
            .order_by("data_pretendida_conclusao")[:5]
        )

        pct_executado = int((valor_empenhado / valor_total * 100) if valor_total else 0)

        # ---------- dados por item para o explorador interativo (client-side) ----------
        # Serializa cada demanda em tipos JSON simples. O template filtra,
        # agrega e desenha os graficos no navegador (sem recarregar a pagina).
        itens_raw = (
            itens.annotate(unidade_sigla=F("dfd__unidade__sigla"))
            .values(
                "pk", "codigo_pca", "descricao", "categoria", "modalidade",
                "status", "unidade_orcamentaria", "tipo_demanda",
                "valor_total_estimado", "valor_empenhado", "is_srp",
                "data_pretendida_conclusao", "unidade_sigla",
            )
        )
        itens_data = [
            {
                "codigo": d["codigo_pca"] or f"#{d['pk']}",
                "url": reverse("pca:item_detalhe", args=[d["pk"]]),
                "desc": (d["descricao"] or "")[:160],
                "unidade": d["unidade_sigla"] or "—",
                "categoria": d["categoria"] or "",
                "modalidade": d["modalidade"] or "",
                "status": d["status"] or "",
                "uo": d["unidade_orcamentaria"] or "",
                "tipo": d["tipo_demanda"] or "",
                "valor": float(d["valor_total_estimado"] or 0),
                "empenhado": float(d["valor_empenhado"] or 0),
                "srp": bool(d["is_srp"]),
                "prazo": d["data_pretendida_conclusao"].isoformat()
                if d["data_pretendida_conclusao"] else None,
            }
            for d in itens_raw
        ]

        context = {
            "pca": pca,
            "todos_pcas": todos_pcas_qs,
            "itens_data": itens_data,
            "total_dfds": dfds.count(),
            "total_itens": total_itens,
            "total_ativas": total_ativas,
            "valor_total": valor_total,
            "valor_pca_ativo": valor_pca_ativo,
            "valor_empenhado": valor_empenhado,
            "valor_disponivel": (valor_total or 0) - (valor_empenhado or 0),
            "pct_executado": pct_executado,
            "suspensos": suspensos,
            "concluidos": concluidos,
            "em_andamento": em_andamento,
            "nao_iniciados": nao_iniciados,
            "pendentes_validacao": pendentes_validacao,
            "em_diligencia": em_diligencia,
            # alertas
            "hoje": hoje,
            "atrasados": atrasados,
            "vencendo_30": vencendo_30,
            "vencendo_90": vencendo_90,
            "sem_prazo": sem_prazo,
            # srp
            "itens_srp": itens_srp,
            "valor_srp": valor_srp,
            "urgentes": urgentes,
        }
        return render(request, self.template_name, context)


def filtrar_demandas(request, pca):
    """
    Aplica os filtros da querystring ao conjunto de demandas do PCA.

    Compartilhado entre a tela (DemandasPCAView) e a exportação em PDF
    (ExportarDemandasPDFView) — assim o relatório reflete EXATAMENTE o que
    o usuário está vendo na tela, sem risco de as regras divergirem.

    Retorna (queryset, dicionario_de_filtros_aplicados).
    """
    itens_qs = ItemPCA.objects.select_related(
        "dfd", "dfd__pca", "dfd__unidade"
    ).order_by("dfd__pca__exercicio", "numero_lote_pca", "dfd__numero_dfd", "numero_item")

    if pca:
        itens_qs = itens_qs.filter(dfd__pca=pca)

    filtros = {
        "status": request.GET.get("status", ""),
        "categoria": request.GET.get("categoria", ""),
        "modalidade": request.GET.get("modalidade", ""),
        "unidade": request.GET.get("unidade", ""),
        "aprovacao": request.GET.get("aprovacao", ""),
        "q": request.GET.get("q", "").strip(),
    }

    if filtros["status"]:
        itens_qs = itens_qs.filter(status=filtros["status"])
    if filtros["aprovacao"]:
        itens_qs = itens_qs.filter(status_aprovacao=filtros["aprovacao"])
    if filtros["categoria"]:
        itens_qs = itens_qs.filter(categoria=filtros["categoria"])
    if filtros["modalidade"]:
        itens_qs = itens_qs.filter(modalidade=filtros["modalidade"])
    if filtros["unidade"]:
        itens_qs = itens_qs.filter(dfd__unidade_id=filtros["unidade"])
    if filtros["q"]:
        itens_qs = itens_qs.filter(descricao__unaccent__icontains=filtros["q"])

    return itens_qs, filtros


@method_decorator(login_required, name="dispatch")
class DemandasPCAView(View):
    template_name = "pca/demandas.html"

    def get(self, request):
        todos_pcas_qs = PlanoContratacaoAnual.objects.order_by("-exercicio")
        pca = _resolver_pca(request, todos_pcas_qs)

        itens_qs, filtros = filtrar_demandas(request, pca)

        status_filtro     = filtros["status"]
        categoria_filtro  = filtros["categoria"]
        modalidade_filtro = filtros["modalidade"]
        unidade_filtro    = filtros["unidade"]
        aprovacao_filtro  = filtros["aprovacao"]
        busca             = filtros["q"]

        # So unidades que tem DFD no PCA exibido — evita opcoes que filtram para vazio
        from apps.core.models import UnidadeRequisitante
        unidades_qs = UnidadeRequisitante.objects.order_by("sigla")
        if pca:
            unidades_qs = unidades_qs.filter(
                documentoformalizacaodemanda__pca=pca
            ).distinct()

        # Resumo da analise para os cards de situacao (respeita os filtros ativos)
        from django.db.models import Count
        from .views_analise import pode_analisar

        resumo_aprovacao = {
            linha["status_aprovacao"]: linha["n"]
            for linha in itens_qs.values("status_aprovacao").annotate(n=Count("id"))
        }

        context = {
            "pca": pca,
            "todos_pcas": todos_pcas_qs,
            "itens": itens_qs,
            "total": itens_qs.count(),
            "status_filtro": status_filtro,
            "categoria_filtro": categoria_filtro,
            "modalidade_filtro": modalidade_filtro,
            "unidade_filtro": unidade_filtro,
            "aprovacao_filtro": aprovacao_filtro,
            "unidades": unidades_qs,
            "busca": busca,
            "status_choices": ItemPCA.STATUS,
            "categoria_choices": ItemPCA.CATEGORIAS,
            "modalidade_choices": ItemPCA.MODALIDADE,
            "aprovacao_choices": ItemPCA.STATUS_APROVACAO,
            "resumo_aprovacao": resumo_aprovacao,
            "pode_analisar": pode_analisar(request.user),
        }
        return render(request, self.template_name, context)


@method_decorator(login_required, name="dispatch")
class ItemPCADetalheView(View):
    template_name = "pca/item_detalhe.html"

    def get(self, request, pk):
        item = get_object_or_404(
            ItemPCA.objects
            .select_related("dfd", "dfd__pca", "dfd__unidade", "item_pai", "contrato_vigente")
            .prefetch_related("vinculos_arp__item_arp__arp"),
            pk=pk,
        )
        context = {
            "item": item,
            "vinculo_arp": item.vinculos_arp.select_related("item_arp__arp").first(),
        }
        return render(request, self.template_name, context)


# --- Catalogo (AJAX) --------------------------------------------------------

@method_decorator(login_required, name="dispatch")
class CatalogoSearchView(View):
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


# --- Renovacao Multiexercicio ------------------------------------------------

@method_decorator(login_required, name="dispatch")
class RenovacaoExercicioView(View):
    template_name = "pca/renovacao.html"

    def get(self, request):
        pca_atual = PlanoContratacaoAnual.objects.order_by("-exercicio").first()
        todos_pcas = PlanoContratacaoAnual.objects.order_by("-exercicio")

        ids_param = request.GET.get("ids", "")
        ids_pre = [int(i) for i in ids_param.split(",") if i.strip().isdigit()]

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
                ja_existe = ItemPCA.objects.filter(
                    origem_item=item, dfd__pca=pca_destino
                ).exists()
                if ja_existe:
                    ignorados += 1
                    continue

                dfd_destino, _ = DocumentoFormalizacaoDemanda.objects.get_or_create(
                    pca=pca_destino,
                    unidade=item.dfd.unidade,
                    numero_dfd=f"REN-{pca_destino.exercicio}-{item.dfd.unidade_id}",
                    defaults={
                        "descricao_objeto": (
                            f"Renovacao de contratacoes continuas"
                            f" - {item.dfd.unidade} - exercicio {pca_destino.exercicio}"
                        ),
                        "justificativa": (
                            f"Renovacao automatica de itens classificados como continuos"
                            f" conforme Ato PGJ 1.415/2024, originados do PCA"
                            f" {item.dfd.pca.exercicio}."
                        ),
                        "prazo_necessidade": datetime.date(pca_destino.exercicio, 12, 31),
                        "grau_prioridade": item.dfd.grau_prioridade,
                        "status": "rascunho",
                        "requisitante": request.user,
                    },
                )

                ultimo_num = (
                    ItemPCA.objects.filter(dfd=dfd_destino)
                    .aggregate(m=Max("numero_item"))["m"]
                ) or 0

                ItemPCA.objects.create(
                    dfd=dfd_destino,
                    numero_item=ultimo_num + 1,
                    origem_item=item,
                    item_catalogo=item.item_catalogo,
                    classificacao_continuidade=item.classificacao_continuidade,
                    categoria=item.categoria,
                    codigo_catmat_catser=item.codigo_catmat_catser,
                    descricao=item.descricao,
                    unidade_fornecimento=item.unidade_fornecimento,
                    quantidade_estimada=item.quantidade_estimada,
                    valor_unitario_estimado=item.valor_unitario_estimado,
                    valor_total_estimado=item.valor_total_estimado,
                    tipo_demanda="renovacao",
                    modalidade=item.modalidade,
                    normativo=item.normativo,
                    unidade_orcamentaria=item.unidade_orcamentaria,
                    is_srp=item.is_srp,
                    numero_lote_pca=item.numero_lote_pca,
                    status="nao_iniciado",
                    observacoes=(
                        f"Renovado automaticamente a partir de {item.codigo_pca}"
                        f" (PCA {item.dfd.pca.exercicio})."
                    ),
                )
                criados += 1

        if criados:
            messages.success(
                request,
                f"{criados} item(ns) renovado(s) com sucesso para o PCA {pca_destino.exercicio}."
                + (f" {ignorados} ja existia(m) e foram ignorados." if ignorados else ""),
            )
        else:
            messages.warning(
                request,
                f"Nenhum item novo criado - todos os {ignorados} selecionados ja haviam sido renovados.",
            )

        return redirect("pca:demandas")


# --- Orcamento Planejado ----------------------------------------------------

@method_decorator(login_required, name="dispatch")
class OrcamentoView(View):
    template_name = "pca/orcamento.html"

    def get(self, request):
        exercicio_param = request.GET.get("exercicio")
        todos_pcas = PlanoContratacaoAnual.objects.order_by("-exercicio")

        if exercicio_param:
            pca = PlanoContratacaoAnual.objects.filter(exercicio=exercicio_param).first()
        else:
            pca = _pca_default(todos_pcas)

        orcamentos = []
        totais = {"aprovado": 0, "comprometido": 0}

        if pca:
            qs = (
                OrcamentoPlanejado.objects
                .filter(pca=pca)
                .select_related("unidade", "pca")
                .order_by("unidade__sigla")
            )
            for orc in qs:
                comprometido = orc.valor_comprometido()
                total_aprov = orc.valor_total
                saldo = total_aprov - comprometido
                pct = orc.percentual_comprometido()
                orcamentos.append({
                    "obj": orc,
                    "comprometido": comprometido,
                    "saldo": saldo,
                    "pct": pct,
                    "alerta": pct >= 90,
                })
                totais["aprovado"] += total_aprov
                totais["comprometido"] += comprometido

        totais["saldo"] = totais["aprovado"] - totais["comprometido"]
        totais["pct"] = (
            round(totais["comprometido"] / totais["aprovado"] * 100, 1)
            if totais["aprovado"] else 0
        )

        setores_com_itens = set(
            ItemPCA.objects
            .filter(dfd__pca=pca)
            .values_list("dfd__unidade__sigla", flat=True)
            .distinct()
        ) if pca else set()
        setores_com_orc = {o["obj"].unidade.sigla for o in orcamentos}
        setores_sem_orc = setores_com_itens - setores_com_orc

        context = {
            "pca": pca,
            "todos_pcas": todos_pcas,
            "orcamentos": orcamentos,
            "totais": totais,
            "setores_sem_orc": sorted(setores_sem_orc),
        }
        return render(request, self.template_name, context)


# --- Clonar PCA completo -------------------------------------------------------

@method_decorator(login_required, name="dispatch")
class ClonarPCAView(View):
    """
    Clona todos os itens de um PCA de origem para um PCA de destino.
    Cria o PCA de destino se necessario.
    """

    def post(self, request):
        pca_origem_id = request.POST.get("pca_origem_id")
        pca_destino_id = request.POST.get("pca_destino_id", "")
        so_ativos = bool(request.POST.get("so_ativos"))

        pca_origem = get_object_or_404(PlanoContratacaoAnual, pk=pca_origem_id)
        proximo_exercicio = pca_origem.exercicio + 1

        # Destino: existente ou novo
        if pca_destino_id.startswith("novo_"):
            exercicio_novo = int(pca_destino_id.split("_")[1])
            pca_destino, criado = PlanoContratacaoAnual.objects.get_or_create(
                orgao=pca_origem.orgao,
                exercicio=exercicio_novo,
                defaults={"status": "coleta"},
            )
        else:
            pca_destino = get_object_or_404(PlanoContratacaoAnual, pk=pca_destino_id)

        qs = ItemPCA.objects.filter(dfd__pca=pca_origem).select_related(
            "dfd", "dfd__unidade", "item_catalogo"
        )
        if so_ativos:
            qs = qs.exclude(status="suspenso")

        CAMPOS = [
            "item_catalogo", "classificacao_continuidade", "categoria",
            "codigo_catmat_catser", "descricao", "unidade_fornecimento",
            "quantidade_estimada", "valor_unitario_estimado", "valor_total_estimado",
            "tipo_demanda", "modalidade", "normativo", "unidade_orcamentaria",
            "is_srp", "numero_lote_pca", "tipo_suspensao",
        ]

        criados = ignorados = 0
        dfds_cache = {}

        with transaction.atomic():
            for item in qs.order_by("dfd__unidade__sigla", "numero_item"):
                ja_existe = ItemPCA.objects.filter(
                    origem_item=item, dfd__pca=pca_destino
                ).exists()
                if ja_existe:
                    ignorados += 1
                    continue

                unidade = item.dfd.unidade
                if unidade.pk not in dfds_cache:
                    dfd_num = f"DFD-{pca_destino.exercicio}-{unidade.sigla}"
                    dfd_destino, _ = DocumentoFormalizacaoDemanda.objects.get_or_create(
                        pca=pca_destino,
                        unidade=unidade,
                        numero_dfd=dfd_num,
                        defaults={
                            "descricao_objeto": (
                                f"Demandas de {unidade.sigla} — PCA {pca_destino.exercicio} "
                                f"(importadas do PCA {pca_origem.exercicio})"
                            ),
                            "justificativa": (
                                f"Clonagem automatica do PCA {pca_origem.exercicio}. "
                                f"Setor deve validar cada item."
                            ),
                            "prazo_necessidade": datetime.date(pca_destino.exercicio, 12, 31),
                            "grau_prioridade": item.dfd.grau_prioridade,
                            "status": "rascunho",
                            "requisitante": request.user,
                        },
                    )
                    dfds_cache[unidade.pk] = dfd_destino

                dfd_destino = dfds_cache[unidade.pk]
                ultimo = (
                    ItemPCA.objects.filter(dfd=dfd_destino)
                    .aggregate(m=Max("numero_item"))["m"]
                ) or 0

                status_destino = "suspenso" if item.status == "suspenso" else "pendente_validacao"

                kwargs = {field: getattr(item, field) for field in CAMPOS}
                kwargs.update({
                    "dfd": dfd_destino,
                    "numero_item": ultimo + 1,
                    "origem_item": item,
                    "status": status_destino,
                    "observacoes": (
                        f"Importado do PCA {pca_origem.exercicio} ({item.codigo_pca}). "
                        f"Pendente de validacao pelo setor requisitante."
                    ),
                    "data_pretendida_conclusao": None,
                    "data_envio_pgea": None,
                    "data_finalizacao_licitacao": None,
                    "data_conclusao_efetiva": None,
                    "valor_empenhado": 0,
                })
                ItemPCA.objects.create(**kwargs)
                criados += 1

        msg = (
            f"{criados} item(ns) clonado(s) com sucesso para o PCA {pca_destino.exercicio}."
        )
        if ignorados:
            msg += f" {ignorados} ja existia(m) e foram ignorados."
        if criados:
            messages.success(request, msg)
        else:
            messages.warning(request, f"Nenhum item novo: {msg}")

        return redirect("pca:renovacao")
