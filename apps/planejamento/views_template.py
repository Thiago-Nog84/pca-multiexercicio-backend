"""Views Django Templates — Módulo Planejamento (Artefatos: DFD, ETP, TR)."""

from django.contrib.auth.decorators import login_required
from django.db.models import Count
from django.shortcuts import render
from django.utils.decorators import method_decorator
from django.views import View

from apps.pca.models import DocumentoFormalizacaoDemanda

from .models import ETP, TermoReferencia


@method_decorator(login_required, name="dispatch")
class DashboardPlanejamentoView(View):
    template_name = "planejamento/dashboard.html"

    def get(self, request):
        etps = ETP.objects.select_related("dod").order_by("-id")
        trs = TermoReferencia.objects.select_related("etp__dod").order_by("-id")
        dfds = DocumentoFormalizacaoDemanda.objects.select_related("pca", "unidade").order_by("-criado_em")

        etps_por_status = (
            etps.values("status").annotate(qtd=Count("id")).order_by("-qtd")
        )
        dfds_por_status = (
            dfds.values("status").annotate(qtd=Count("id")).order_by("-qtd")
        )

        context = {
            "total_etps": etps.count(),
            "total_trs": trs.count(),
            "etps_aprovados": etps.filter(status="aprovado").count(),
            "etps_rascunho": etps.filter(status="rascunho").count(),
            "etps_por_status": list(etps_por_status),
            "ultimos_etps": etps[:10],
            "total_dfds": dfds.count(),
            "dfds_enviados": dfds.filter(status="enviado").count(),
            "dfds_rascunho": dfds.filter(status="rascunho").count(),
            "dfds_por_status": list(dfds_por_status),
            "ultimos_dfds": dfds[:10],
        }
        return render(request, self.template_name, context)
