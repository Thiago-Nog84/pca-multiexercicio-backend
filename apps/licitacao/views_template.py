"""Views Django Templates — Módulo Licitação."""

from decimal import Decimal
from django.contrib.auth.decorators import login_required
from django.db.models import Sum, Count
from django.shortcuts import render
from django.utils.decorators import method_decorator
from django.views import View
from apps.licitacao.models import ProcessoLicitatorio


@method_decorator(login_required, name="dispatch")
class DashboardLicitacaoView(View):
    template_name = "licitacao/dashboard.html"

    def get(self, request):
        processos = ProcessoLicitatorio.objects.all().order_by("-ano", "-id")
        total_processos = processos.count()
        
        agg = processos.aggregate(
            tot_est=Sum("valor_estimado"),
            tot_hom=Sum("valor_homologado"),
        )
        total_estimado = agg["tot_est"] or Decimal("0.00")
        total_homologado = agg["tot_hom"] or Decimal("0.00")

        pregoes = processos.filter(modalidade__in=[ProcessoLicitatorio.Modalidade.PREGAO_ELETRONICO, ProcessoLicitatorio.Modalidade.PREGAO_PRESENCIAL]).count()
        concorrencias = processos.filter(modalidade__in=[ProcessoLicitatorio.Modalidade.CONCORRENCIA_ELETRONICA, ProcessoLicitatorio.Modalidade.CONCORRENCIA_PRESENCIAL]).count()
        dispensas = processos.filter(modalidade=ProcessoLicitatorio.Modalidade.DISPENSA).count()
        inexigibilidades = processos.filter(modalidade=ProcessoLicitatorio.Modalidade.INEXIGIBILIDADE).count()

        # Filtros de ano se houver na request
        ano_sel = request.GET.get("ano")
        if ano_sel and ano_sel.isdigit():
            processos = processos.filter(ano=int(ano_sel))

        context = {
            "processos": processos[:100],  # Limita aos últimos 100 para performance na interface
            "total_processos": total_processos,
            "total_estimado": total_estimado,
            "total_homologado": total_homologado,
            "pregoes": pregoes,
            "concorrencias": concorrencias,
            "dispensas": dispensas,
            "inexigibilidades": inexigibilidades,
            "ano_selecionado": ano_sel or "",
        }
        return render(request, self.template_name, context)
