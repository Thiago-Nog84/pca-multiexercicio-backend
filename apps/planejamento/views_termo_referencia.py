"""Views Django Templates — Termo de Referência (TR).

Mesmo padrão de views_dod.py/views_etp.py: sem Forms/ModelForms, extração
manual de request.POST, full_clean() explícito.

TR é OneToOne com o ETP. `modalidade_remuneracao_ti` só faz sentido quando
`etp.is_ti` — o campo continua opcional no model (blank=True) pra não
travar TRs de naturezas comuns; a tela só destaca/oferece esse bloco quando
o ETP de origem é de TI.
"""

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.decorators import method_decorator
from django.views import View

from .models import ETP, TermoReferencia


@method_decorator(login_required, name="dispatch")
class TermoReferenciaCriarView(View):
    """
    GET  /planejamento/termos-referencia/novo/?etp=<id>  -> formulário
    POST /planejamento/termos-referencia/novo/           -> cria o TR
    """

    template_name = "planejamento/termo_referencia_form.html"

    def get(self, request):
        etp = get_object_or_404(ETP, pk=request.GET.get("etp"))
        tr_existente = getattr(etp, "termo_referencia", None)
        if tr_existente:
            return redirect("planejamento:tr_detalhe", pk=tr_existente.pk)

        context = {
            "etp": etp,
            "status_choices": TermoReferencia.STATUS,
            "criterio_choices": TermoReferencia._meta.get_field("criterio_julgamento").choices,
            "modalidade_ti_choices": TermoReferencia._meta.get_field("modalidade_remuneracao_ti").choices,
        }
        return render(request, self.template_name, context)

    def post(self, request):
        etp = get_object_or_404(ETP, pk=request.POST.get("etp"))
        if getattr(etp, "termo_referencia", None):
            messages.error(request, "Este ETP já tem um Termo de Referência cadastrado.")
            return redirect("planejamento:etp_detalhe", pk=etp.pk)

        def texto(campo):
            return request.POST.get(campo, "").strip()

        def inteiro(campo):
            valor = texto(campo)
            return int(valor) if valor.isdigit() else None

        try:
            with transaction.atomic():
                tr = TermoReferencia(
                    etp=etp,
                    numero_sei=texto("numero_sei"),
                    objeto=texto("objeto"),
                    fundamentacao_legal=texto("fundamentacao_legal"),
                    descricao_solucao=texto("descricao_solucao"),
                    requisitos_habilitacao=texto("requisitos_habilitacao"),
                    criterio_julgamento=texto("criterio_julgamento"),
                    prazo_execucao=inteiro("prazo_execucao"),
                    local_execucao=texto("local_execucao"),
                    obrigacoes_contratante=texto("obrigacoes_contratante"),
                    obrigacoes_contratado=texto("obrigacoes_contratado"),
                    criterios_medicao=texto("criterios_medicao"),
                    is_servico_continuo=request.POST.get("is_servico_continuo") == "1",
                    prazo_inicial_meses=inteiro("prazo_inicial_meses"),
                    prazo_maximo_meses=inteiro("prazo_maximo_meses"),
                    is_srp=request.POST.get("is_srp") == "1",
                    justificativa_srp=texto("justificativa_srp"),
                    modalidade_remuneracao_ti=texto("modalidade_remuneracao_ti"),
                    vedacoes_ti_observadas=request.POST.get("vedacoes_ti_observadas") == "1",
                    gerado_por_ia=request.POST.get("gerado_por_ia") == "1",
                    modelo_agu_base=texto("modelo_agu_base"),
                    status=texto("status") or "rascunho",
                )
                tr.full_clean()
                tr.save()
        except ValidationError as e:
            detalhe = "; ".join(e.messages) if hasattr(e, "messages") else str(e)
            messages.error(request, f"Termo de Referência não cadastrado: {detalhe}")
            return redirect(f"/planejamento/termos-referencia/novo/?etp={etp.pk}")

        messages.success(request, "Termo de Referência cadastrado.")
        return redirect("planejamento:tr_detalhe", pk=tr.pk)


@method_decorator(login_required, name="dispatch")
class TermoReferenciaDetalheView(View):
    """GET /planejamento/termos-referencia/<pk>/ — ficha do TR já cadastrado."""

    template_name = "planejamento/termo_referencia_detalhe.html"

    def get(self, request, pk):
        tr = get_object_or_404(
            TermoReferencia.objects.select_related("etp", "etp__dod"), pk=pk
        )
        campos_texto = [
            ("Objeto", tr.objeto),
            ("Fundamentação legal", tr.fundamentacao_legal),
            ("Descrição da solução", tr.descricao_solucao),
            ("Requisitos de habilitação", tr.requisitos_habilitacao),
            ("Critérios de medição", tr.criterios_medicao),
            ("Obrigações do contratante", tr.obrigacoes_contratante),
            ("Obrigações do contratado", tr.obrigacoes_contratado),
        ]
        context = {"tr": tr, "etp": tr.etp, "dod": tr.etp.dod, "campos_texto": campos_texto}
        return render(request, self.template_name, context)
