"""Views Django Templates — Matriz de Risco (e seus RiscoItem).

Mesmo padrão de views_dod.py/views_etp.py: sem Forms/ModelForms, extração
manual de request.POST, full_clean() explícito.

MatrizRisco é OneToOne com o ETP e tem um único campo próprio (`fase_atual`)
— o conteúdo de verdade mora nos RiscoItem (FK), cada um um risco
identificado. Por isso a "criação" da matriz é quase um clique (só escolhe
a fase); o trabalho real é adicionar/editar/remover itens de risco na tela
de detalhe, cada ação sua própria view pequena.
"""

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.decorators import method_decorator
from django.views import View

from .models import ETP, MatrizRisco, RiscoItem


@method_decorator(login_required, name="dispatch")
class MatrizRiscoCriarView(View):
    """
    GET  /planejamento/matriz-risco/novo/?etp=<id>  -> formulário (fase_atual)
    POST /planejamento/matriz-risco/novo/           -> cria a MatrizRisco
    """

    template_name = "planejamento/matriz_risco_form.html"

    def get(self, request):
        etp = get_object_or_404(ETP, pk=request.GET.get("etp"))
        matriz_existente = getattr(etp, "matriz_risco", None)
        if matriz_existente:
            return redirect("planejamento:matriz_risco_detalhe", pk=matriz_existente.pk)

        context = {"etp": etp, "fase_choices": MatrizRisco._meta.get_field("fase_atual").choices}
        return render(request, self.template_name, context)

    def post(self, request):
        etp = get_object_or_404(ETP, pk=request.POST.get("etp"))
        if getattr(etp, "matriz_risco", None):
            messages.error(request, "Este ETP já tem uma Matriz de Risco cadastrada.")
            return redirect("planejamento:etp_detalhe", pk=etp.pk)

        try:
            with transaction.atomic():
                matriz = MatrizRisco(
                    etp=etp,
                    fase_atual=request.POST.get("fase_atual", "planejamento").strip(),
                )
                matriz.full_clean()
                matriz.save()
        except ValidationError as e:
            detalhe = "; ".join(e.messages) if hasattr(e, "messages") else str(e)
            messages.error(request, f"Matriz de Risco não cadastrada: {detalhe}")
            return redirect(f"/planejamento/matriz-risco/novo/?etp={etp.pk}")

        messages.success(request, "Matriz de Risco criada. Agora adicione os riscos identificados.")
        return redirect("planejamento:matriz_risco_detalhe", pk=matriz.pk)


@method_decorator(login_required, name="dispatch")
class MatrizRiscoDetalheView(View):
    """GET /planejamento/matriz-risco/<pk>/ — ficha da matriz + itens de risco."""

    template_name = "planejamento/matriz_risco_detalhe.html"

    def get(self, request, pk):
        matriz = get_object_or_404(
            MatrizRisco.objects.select_related("etp", "etp__dod"), pk=pk
        )
        itens = list(matriz.itens.order_by("-nivel_risco"))
        context = {
            "matriz": matriz,
            "etp": matriz.etp,
            "itens": itens,
            "criticos": sum(1 for i in itens if i.nivel_risco >= 15),
        }
        return render(request, self.template_name, context)


@method_decorator(login_required, name="dispatch")
class RiscoItemFormView(View):
    """
    GET/POST /planejamento/matriz-risco/<matriz_pk>/itens/novo/         -> cria
    GET/POST /planejamento/matriz-risco/<matriz_pk>/itens/<pk>/editar/  -> edita

    Uma view só para os dois casos (pk=None cria, pk preenchido edita) —
    o formulário é idêntico, só muda se parte de um RiscoItem em branco ou
    de um já existente.
    """

    template_name = "planejamento/risco_item_form.html"

    def get(self, request, matriz_pk, pk=None):
        matriz = get_object_or_404(MatrizRisco, pk=matriz_pk)
        item = get_object_or_404(RiscoItem, pk=pk, matriz=matriz) if pk else None
        context = {
            "matriz": matriz,
            "item": item,
            "probabilidade_choices": RiscoItem.PROBABILIDADE,
            "impacto_choices": RiscoItem.IMPACTO,
            "responsavel_choices": RiscoItem.RESPONSAVEL,
        }
        return render(request, self.template_name, context)

    def post(self, request, matriz_pk, pk=None):
        matriz = get_object_or_404(MatrizRisco, pk=matriz_pk)
        item = get_object_or_404(RiscoItem, pk=pk, matriz=matriz) if pk else RiscoItem(matriz=matriz)

        def texto(campo):
            return request.POST.get(campo, "").strip()

        try:
            with transaction.atomic():
                item.descricao_risco = texto("descricao_risco")
                item.causa = texto("causa")
                item.consequencia = texto("consequencia")
                probabilidade = request.POST.get("probabilidade", "")
                impacto = request.POST.get("impacto", "")
                # Convertidos aqui (não deixados como string) porque
                # RiscoItem.save() faz `probabilidade * impacto` pra
                # calcular nivel_risco — full_clean() sozinho não
                # normaliza o tipo do atributo, só valida.
                item.probabilidade = int(probabilidade) if probabilidade.isdigit() else None
                item.impacto = int(impacto) if impacto.isdigit() else None
                item.responsavel = texto("responsavel")
                item.acao_preventiva = texto("acao_preventiva")
                item.acao_contingencia = texto("acao_contingencia")
                item.full_clean(exclude=["nivel_risco"])
                item.save()  # save() recalcula nivel_risco = probabilidade * impacto
        except ValidationError as e:
            detalhe = "; ".join(e.messages) if hasattr(e, "messages") else str(e)
            messages.error(request, f"Risco não salvo: {detalhe}")
            destino = f"/planejamento/matriz-risco/{matriz.pk}/itens/"
            destino += f"{pk}/editar/" if pk else "novo/"
            return redirect(destino)

        messages.success(request, "Risco salvo.")
        return redirect("planejamento:matriz_risco_detalhe", pk=matriz.pk)


@method_decorator(login_required, name="dispatch")
class RiscoItemExcluirView(View):
    """POST /planejamento/matriz-risco/<matriz_pk>/itens/<pk>/excluir/ — remove um risco."""

    def post(self, request, matriz_pk, pk):
        item = get_object_or_404(RiscoItem, pk=pk, matriz_id=matriz_pk)
        item.delete()
        messages.success(request, "Risco removido.")
        return redirect("planejamento:matriz_risco_detalhe", pk=matriz_pk)
