"""Views Django Templates — Módulo Planejamento (ETPs e TRs)."""

from django.contrib.auth.decorators import login_required
from django.db.models import Count
from django.shortcuts import render
from django.utils.decorators import method_decorator
from django.views import View

from .models import ETP, TermoReferencia


@method_decorator(login_required, name="dispatch")
class DashboardPlanejamentoView(View):
    template_name = "planejamento/dashboard.html"

    def get(self, request):
        etps = ETP.objects.select_related("item_pca").order_by("-id")
        trs = TermoReferencia.objects.select_related("item_pca").order_by("-id")

        etps_por_status = (
            etps.values("status").annotate(qtd=Count("id")).order_by("-qtd")
        )

        context = {
            "total_etps": etps.count(),
            "total_trs": trs.count(),
            "etps_aprovados": etps.filter(status="aprovado").count(),
            "etps_rascunho": etps.filter(status="rascunho").count(),
            "etps_por_status": list(etps_por_status),
            "ultimos_etps": etps[:10],
        }
        return render(request, self.template_name, context)
