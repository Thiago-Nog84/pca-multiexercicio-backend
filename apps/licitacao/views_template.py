"""Views Django Templates — Módulo Licitação."""

from django.contrib.auth.decorators import login_required
from django.shortcuts import render
from django.utils.decorators import method_decorator
from django.views import View


@method_decorator(login_required, name="dispatch")
class DashboardLicitacaoView(View):
    template_name = "licitacao/dashboard.html"

    def get(self, request):
        return render(request, self.template_name, {})
