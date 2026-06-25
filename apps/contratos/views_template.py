"""Views Django Templates — Módulo Contratos."""

from datetime import date, timedelta

from django.contrib.auth.decorators import login_required
from django.db.models import Count, Q
from django.shortcuts import render
from django.utils.decorators import method_decorator
from django.views import View

from .models import Aditivo, Contrato


@method_decorator(login_required, name="dispatch")
class DashboardContratosView(View):
    template_name = "contratos/dashboard.html"

    def get(self, request):
        hoje = date.today()
        d90 = hoje + timedelta(days=90)
        d30 = hoje + timedelta(days=30)

        contratos = Contrato.objects.all()
        total = contratos.count()
        vigentes = contratos.filter(status="vigente").count()
        vencendo_90 = contratos.filter(
            status="vigente", data_fim_vigencia__lte=d90, data_fim_vigencia__gte=hoje
        ).count()
        vencendo_30 = contratos.filter(
            status="vigente", data_fim_vigencia__lte=d30, data_fim_vigencia__gte=hoje
        ).count()

        por_tipo = (
            contratos.filter(status="vigente")
            .values("tipo")
            .annotate(qtd=Count("id"))
            .order_by("-qtd")
        )

        # Últimos contratos + alertas
        alertas = contratos.filter(
            status="vigente", data_fim_vigencia__lte=d90, data_fim_vigencia__gte=hoje
        ).order_by("data_fim_vigencia")[:10]

        recentes = contratos.order_by("-criado_em")[:10]

        context = {
            "total": total,
            "vigentes": vigentes,
            "vencendo_90": vencendo_90,
            "vencendo_30": vencendo_30,
            "por_tipo": list(por_tipo),
            "alertas": alertas,
            "recentes": recentes,
            "hoje": hoje,
        }
        return render(request, self.template_name, context)
