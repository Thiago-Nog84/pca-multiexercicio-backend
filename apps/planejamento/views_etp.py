"""Views Django Templates — Estudo Técnico Preliminar (ETP).

Mesmo padrão de apps/planejamento/views_dod.py: view simples, extração
manual de request.POST, transaction.atomic() e full_clean() explícito —
sem Django Forms/ModelForms, por consistência com o resto do sistema.

O ETP é OneToOne com o DOD (art. 18 da NLLC + IN SEGES 58/2022) — só existe
um ETP por processo. Antes desta tela (2026-08-18) o único jeito de criar
um era pelo admin do Django, com `admin.site.register(ETP)` nu (sem
fieldsets), sem nenhuma tela do sistema pra ver depois de criado.

Nota sobre `etp_dispensado`: o model tem esse campo (e `fundamento_dispensa_etp`)
mas NENHUM dos campos de conteúdo (necessidade_contratacao, requisitos_contratacao
etc.) tem `blank=True` — ou seja, mesmo um ETP dispensado ainda exige, hoje,
que todos os campos narrativos sejam preenchidos pra passar em full_clean().
Isso é uma lacuna do model, não desta tela — fica documentado aqui e na
memória do projeto em vez de "consertado" por conta própria (mudaria o
contrato do model sem decisão do Thiago).
"""

from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.decorators import method_decorator
from django.views import View

from .models import ETP, DocumentoOficializacaoDemanda

Usuario = get_user_model()


@method_decorator(login_required, name="dispatch")
class ETPCriarView(View):
    """
    GET  /planejamento/etps/novo/?dod=<id>  -> formulário
    POST /planejamento/etps/novo/           -> cria o ETP

    Se o DOD já tiver um ETP (OneToOne), redireciona direto pro detalhe —
    clicar em "Iniciar" de novo não deve tentar criar um segundo.
    """

    template_name = "planejamento/etp_form.html"

    def get(self, request):
        dod = get_object_or_404(DocumentoOficializacaoDemanda, pk=request.GET.get("dod"))
        etp_existente = getattr(dod, "etp", None)
        if etp_existente:
            return redirect("planejamento:etp_detalhe", pk=etp_existente.pk)

        context = {
            "dod": dod,
            "status_choices": ETP.STATUS,
            "usuarios": Usuario.objects.filter(is_active=True).order_by("first_name", "username"),
        }
        return render(request, self.template_name, context)

    def post(self, request):
        dod = get_object_or_404(DocumentoOficializacaoDemanda, pk=request.POST.get("dod"))
        if getattr(dod, "etp", None):
            messages.error(request, "Este DOD já tem um ETP cadastrado.")
            return redirect("planejamento:dod_detalhe", pk=dod.pk)

        def texto(campo):
            return request.POST.get(campo, "").strip()

        def decimal(campo):
            valor = texto(campo).replace(",", ".")
            return valor or None

        try:
            with transaction.atomic():
                etp = ETP(
                    dod=dod,
                    numero_sei=texto("numero_sei"),
                    numero_etp=texto("numero_etp"),
                    is_ti=request.POST.get("is_ti") == "1",
                    necessidade_contratacao=texto("necessidade_contratacao"),
                    requisitos_contratacao=texto("requisitos_contratacao"),
                    levantamento_mercado=texto("levantamento_mercado"),
                    descricao_solucao=texto("descricao_solucao"),
                    estimativa_quantidade=texto("estimativa_quantidade"),
                    estimativa_custo=decimal("estimativa_custo"),
                    justificativa_parcelamento=texto("justificativa_parcelamento"),
                    contratacoes_correlatas=texto("contratacoes_correlatas"),
                    alinhamento_pca=texto("alinhamento_pca"),
                    resultados_pretendidos=texto("resultados_pretendidos"),
                    providencias_previas=texto("providencias_previas"),
                    impactos_ambientais=texto("impactos_ambientais"),
                    declaracao_viabilidade=request.POST.get("declaracao_viabilidade") == "1",
                    tco_total=decimal("tco_total"),
                    solucao_em_outros_orgaos=texto("solucao_em_outros_orgaos"),
                    software_livre_avaliado=request.POST.get("software_livre_avaliado") == "1",
                    gerado_por_ia=request.POST.get("gerado_por_ia") == "1",
                    ia_modelo_utilizado=texto("ia_modelo_utilizado"),
                    ia_revisado_por_id=request.POST.get("ia_revisado_por") or None,
                    status=texto("status") or "rascunho",
                    etp_dispensado=request.POST.get("etp_dispensado") == "1",
                    fundamento_dispensa_etp=texto("fundamento_dispensa_etp"),
                )
                etp.full_clean()
                etp.save()
        except ValidationError as e:
            detalhe = "; ".join(e.messages) if hasattr(e, "messages") else str(e)
            messages.error(request, f"ETP não cadastrado: {detalhe}")
            return redirect(f"/planejamento/etps/novo/?dod={dod.pk}")

        messages.success(request, f"ETP \"{etp.numero_etp}\" cadastrado.")
        return redirect("planejamento:etp_detalhe", pk=etp.pk)


@method_decorator(login_required, name="dispatch")
class ETPDetalheView(View):
    """GET /planejamento/etps/<pk>/ — ficha do ETP já cadastrado."""

    template_name = "planejamento/etp_detalhe.html"

    def get(self, request, pk):
        etp = get_object_or_404(
            ETP.objects.select_related(
                "dod", "dod__pca", "ia_revisado_por", "matriz_risco", "termo_referencia"
            ),
            pk=pk,
        )
        # Blocos de texto do estudo, na ordem do IN SEGES 58/2022 — lista de
        # tuplas pra o template só iterar, mesmo padrão de dod_detalhe.html.
        campos_texto = [
            ("Necessidade da contratação", etp.necessidade_contratacao),
            ("Requisitos da contratação", etp.requisitos_contratacao),
            ("Levantamento de mercado", etp.levantamento_mercado),
            ("Descrição da solução", etp.descricao_solucao),
            ("Solução em outros órgãos", etp.solucao_em_outros_orgaos),
            ("Estimativa de quantidade", etp.estimativa_quantidade),
            ("Justificativa do parcelamento", etp.justificativa_parcelamento),
            ("Contratações correlatas", etp.contratacoes_correlatas),
            ("Alinhamento ao PCA", etp.alinhamento_pca),
            ("Resultados pretendidos", etp.resultados_pretendidos),
            ("Providências prévias", etp.providencias_previas),
            ("Impactos ambientais", etp.impactos_ambientais),
        ]

        context = {
            "etp": etp,
            "dod": etp.dod,
            "campos_texto": campos_texto,
            "matriz_risco": getattr(etp, "matriz_risco", None),
            "termo_referencia": getattr(etp, "termo_referencia", None),
        }
        return render(request, self.template_name, context)
