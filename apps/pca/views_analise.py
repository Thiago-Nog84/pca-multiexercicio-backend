"""
Análise das demandas do PCA — workflow de aprovação item a item.

A unidade requisitante PROPÕE; a área gestora (APG/Autoridade) DISPÕE.
Três vereditos possíveis por item:

    aprovada_integral  — aceita como enviada
    aprovada_parcial   — aceita com redução de quantidade e/ou valor unitário
    nao_aprovada       — indeferida

Regra central (transparência): o sistema NÃO permite corte silencioso.
Aprovação parcial e não aprovação exigem `motivo` preenchido — a unidade
requisitante vê esse motivo na tela de demandas ("Ver motivo").

Depois do veredito o item deixa de ser editável pela unidade
(`ItemPCA.editavel_pela_unidade`), pois passa a integrar oficialmente o plano.

Permissão: mesma regra do painel de fases — Perfil ativo "apg" ou
"autoridade", ou superusuário.
"""

import datetime
from decimal import Decimal, InvalidOperation

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect
from django.utils import timezone
from django.utils.decorators import method_decorator
from django.views import View

from apps.core.models import Perfil

from .models import ItemPCA

PERFIS_GESTORES = ("apg", "autoridade")


def pode_analisar(user):
    """Somente APG/Autoridade (ou superusuário) emitem veredito."""
    if user.is_superuser:
        return True
    return Perfil.objects.filter(
        usuario=user, perfil__in=PERFIS_GESTORES, ativo=True
    ).exists()


def _decimal(valor, default=None):
    if valor in (None, ""):
        return default
    try:
        return Decimal(str(valor).replace(",", "."))
    except InvalidOperation:
        return default


@method_decorator(login_required, name="dispatch")
class AnalisarItemPCAView(View):
    """
    POST /pca/demandas/<pk>/analisar/

    Campos esperados:
        decisao  — aprovada_integral | aprovada_parcial | nao_aprovada | reabrir
        motivo   — obrigatório em aprovada_parcial e nao_aprovada
        quantidade_aprovada / valor_unitario_aprovado — só em aprovada_parcial
    """

    def post(self, request, pk):
        item = get_object_or_404(
            ItemPCA.objects.select_related("dfd__pca", "dfd__unidade"), pk=pk
        )
        destino = request.POST.get("next") or "pca:demandas"

        if not pode_analisar(request.user):
            messages.error(
                request,
                "Você não tem permissão para analisar demandas "
                "(requer perfil APG ou Autoridade Competente).",
            )
            return redirect(destino)

        decisao = (request.POST.get("decisao") or "").strip()
        motivo = (request.POST.get("motivo") or "").strip()

        if decisao not in {
            "aprovada_integral",
            "aprovada_parcial",
            "nao_aprovada",
            "reabrir",
        }:
            messages.error(request, "Decisão inválida.")
            return redirect(destino)

        # Motivo obrigatório sempre que a decisão for desfavorável à unidade.
        if decisao in {"aprovada_parcial", "nao_aprovada"} and not motivo:
            messages.error(
                request,
                "Informe o motivo da decisão. Cortes de quantidade/valor e "
                "reprovações precisam ser justificados para a unidade requisitante.",
            )
            return redirect(destino)

        try:
            with transaction.atomic():
                if decisao == "reabrir":
                    # Volta o item para a fila de análise e devolve os valores
                    # originalmente pedidos pela unidade, se houver corte gravado.
                    if item.quantidade_solicitada is not None:
                        item.quantidade_estimada = item.quantidade_solicitada
                    if item.valor_unitario_solicitado is not None:
                        item.valor_unitario_estimado = item.valor_unitario_solicitado
                    item.valor_total_estimado = (
                        item.quantidade_estimada * item.valor_unitario_estimado
                    )
                    item.quantidade_solicitada = None
                    item.valor_unitario_solicitado = None
                    item.status_aprovacao = "pendente"
                    item.motivo_analise = ""
                    item.analisado_por = None
                    item.analisado_em = None
                    item.save()
                    messages.success(
                        request,
                        f"Demanda {item.codigo_pca} reaberta para análise "
                        f"(quantidade e valor originais restaurados).",
                    )
                    return redirect(destino)

                if decisao == "aprovada_parcial":
                    qtd = _decimal(request.POST.get("quantidade_aprovada"))
                    vu = _decimal(request.POST.get("valor_unitario_aprovado"))
                    if qtd is None or vu is None:
                        messages.error(
                            request,
                            "Aprovação parcial exige quantidade e valor unitário aprovados.",
                        )
                        return redirect(destino)
                    if qtd <= 0 or vu <= 0:
                        messages.error(
                            request, "Quantidade e valor aprovados devem ser maiores que zero."
                        )
                        return redirect(destino)

                    # Preserva o pedido original apenas na primeira análise —
                    # reanálises não devem sobrescrever o valor pedido pela unidade.
                    if item.quantidade_solicitada is None:
                        item.quantidade_solicitada = item.quantidade_estimada
                    if item.valor_unitario_solicitado is None:
                        item.valor_unitario_solicitado = item.valor_unitario_estimado

                    if qtd > item.quantidade_solicitada:
                        messages.error(
                            request,
                            f"A quantidade aprovada ({qtd}) não pode ser maior que a "
                            f"solicitada ({item.quantidade_solicitada}). Para ampliar, "
                            f"a unidade deve cadastrar nova demanda.",
                        )
                        return redirect(destino)

                    item.quantidade_estimada = qtd
                    item.valor_unitario_estimado = vu
                    item.valor_total_estimado = qtd * vu

                item.status_aprovacao = decisao
                item.motivo_analise = motivo
                item.analisado_por = request.user
                item.analisado_em = timezone.now()
                item.save()

        except Exception as e:  # noqa: BLE001 — devolve erro legível ao usuário
            messages.error(request, f"Não foi possível registrar a análise: {e}")
            return redirect(destino)

        rotulos = {
            "aprovada_integral": "aprovada integralmente",
            "aprovada_parcial": "aprovada parcialmente",
            "nao_aprovada": "não aprovada",
        }
        messages.success(
            request, f"Demanda {item.codigo_pca} {rotulos[decisao]}."
        )
        return redirect(destino)


@method_decorator(login_required, name="dispatch")
class AnalisarLoteItensPCAView(View):
    """
    POST /pca/demandas/analisar-lote/

    Aprovação integral em massa (caso de uso mais comum na consolidação:
    "aprovar tudo que não tem ressalva"). Só aceita aprovação integral —
    cortes e reprovações são individuais, pois exigem motivo específico.
    """

    def post(self, request):
        destino = request.POST.get("next") or "pca:demandas"

        if not pode_analisar(request.user):
            messages.error(
                request,
                "Você não tem permissão para analisar demandas "
                "(requer perfil APG ou Autoridade Competente).",
            )
            return redirect(destino)

        ids = request.POST.getlist("itens")
        if not ids:
            messages.error(request, "Selecione ao menos uma demanda para aprovar.")
            return redirect(destino)

        agora = timezone.now()
        with transaction.atomic():
            qtd = (
                ItemPCA.objects.filter(pk__in=ids, status_aprovacao="pendente")
                .update(
                    status_aprovacao="aprovada_integral",
                    motivo_analise="",
                    analisado_por=request.user,
                    analisado_em=agora,
                )
            )

        if qtd:
            messages.success(request, f"{qtd} demanda(s) aprovada(s) integralmente.")
        else:
            messages.info(
                request,
                "Nenhuma demanda foi alterada — as selecionadas já haviam sido analisadas.",
            )
        return redirect(destino)
