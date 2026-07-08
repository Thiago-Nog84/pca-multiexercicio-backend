"""
Painel de fases (workflow) do PCA — Ato PGJ 1381/2024, arts. 10-12.

Exibe o pipeline de status do PlanoContratacaoAnual como um stepper,
permite avançar/recuar a fase com justificativa e registra cada mudança
em HistoricoFasePCA (trilha de auditoria).

Permissão: apenas usuários com Perfil ativo "apg" ou "autoridade"
(ou superusuário) podem mudar a fase. Os demais visualizam o painel
em modo somente leitura.
"""

import datetime

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.db.models import Count
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.decorators import method_decorator
from django.views import View

from apps.core.models import Perfil

from .models import (
    DocumentoFormalizacaoDemanda,
    HistoricoFasePCA,
    ItemPCA,
    PlanoContratacaoAnual,
)
from .views_template import _resolver_pca

PERFIS_GESTORES = ("apg", "autoridade")

# Ordem canônica do pipeline (mesma ordem de PlanoContratacaoAnual.STATUS)
_ORDEM = [chave for chave, _ in PlanoContratacaoAnual.STATUS]


def _pode_mudar_fase(user):
    if user.is_superuser:
        return True
    return Perfil.objects.filter(
        usuario=user, perfil__in=PERFIS_GESTORES, ativo=True
    ).exists()


@method_decorator(login_required, name="dispatch")
class WorkflowPCAView(View):
    template_name = "pca/workflow.html"

    def get(self, request):
        todos_pcas_qs = PlanoContratacaoAnual.objects.order_by("-exercicio")
        pca = _resolver_pca(request, todos_pcas_qs)

        fases = []
        idx_atual = _ORDEM.index(pca.status) if pca else -1
        if pca:
            for i, (chave, label) in enumerate(PlanoContratacaoAnual.STATUS):
                fases.append({
                    "chave": chave,
                    "label": label,
                    "estado": (
                        "concluida" if i < idx_atual
                        else "atual" if i == idx_atual
                        else "futura"
                    ),
                })

        # Situação dos DFDs e itens — contexto para decidir se avança
        dfd_labels = dict(DocumentoFormalizacaoDemanda.STATUS)
        item_labels = dict(ItemPCA.STATUS)
        dfds_por_status = [
            {"label": dfd_labels.get(d["status"], d["status"]), "qtd": d["qtd"]}
            for d in DocumentoFormalizacaoDemanda.objects.filter(pca=pca)
            .values("status").annotate(qtd=Count("id")).order_by("-qtd")
        ] if pca else []
        itens_por_status = [
            {"label": item_labels.get(i["status"], i["status"]), "qtd": i["qtd"]}
            for i in ItemPCA.objects.filter(dfd__pca=pca)
            .values("status").annotate(qtd=Count("id")).order_by("-qtd")
        ] if pca else []

        historico = (
            HistoricoFasePCA.objects.filter(pca=pca)
            .select_related("usuario")[:30]
        ) if pca else []

        pode_mudar = _pode_mudar_fase(request.user)

        context = {
            "pca": pca,
            "todos_pcas": todos_pcas_qs,
            "fases": fases,
            "fase_anterior": _ORDEM[idx_atual - 1] if pca and idx_atual > 0 else None,
            "fase_seguinte": _ORDEM[idx_atual + 1] if pca and idx_atual < len(_ORDEM) - 1 else None,
            "dfds_por_status": dfds_por_status,
            "itens_por_status": itens_por_status,
            "historico": historico,
            "pode_mudar": pode_mudar,
        }
        return render(request, self.template_name, context)

    def post(self, request):
        pca = get_object_or_404(PlanoContratacaoAnual, pk=request.POST.get("pca_id"))

        if not _pode_mudar_fase(request.user):
            messages.error(
                request,
                "Você não tem permissão para mudar a fase do PCA "
                "(requer perfil APG ou Autoridade Competente).",
            )
            return redirect(f"{request.path}?pca_id={pca.pk}")

        acao = request.POST.get("acao")
        observacao = (request.POST.get("observacao") or "").strip()
        idx = _ORDEM.index(pca.status)

        if acao == "avancar" and idx < len(_ORDEM) - 1:
            novo_status = _ORDEM[idx + 1]
        elif acao == "recuar" and idx > 0:
            if not observacao:
                messages.error(request, "Justificativa é obrigatória para recuar de fase.")
                return redirect(f"{request.path}?pca_id={pca.pk}")
            novo_status = _ORDEM[idx - 1]
        else:
            messages.error(request, "Ação inválida para a fase atual.")
            return redirect(f"{request.path}?pca_id={pca.pk}")

        with transaction.atomic():
            HistoricoFasePCA.objects.create(
                pca=pca,
                de_status=pca.status,
                para_status=novo_status,
                usuario=request.user,
                observacao=observacao,
            )
            pca.status = novo_status
            if novo_status == "aprovado" and not pca.data_aprovacao_pgj:
                pca.data_aprovacao_pgj = datetime.date.today()
                pca.aprovado_por = request.user
            pca.save()

        messages.success(
            request,
            f"PCA {pca.exercicio} movido para a fase “{pca.get_status_display()}”.",
        )
        return redirect(f"{request.path}?pca_id={pca.pk}")
