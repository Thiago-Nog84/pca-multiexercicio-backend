"""Views Django Templates — Módulo Jurídico."""

from django.contrib.auth.decorators import login_required
from django.shortcuts import render
from django.utils.decorators import method_decorator
from django.views import View


@method_decorator(login_required, name="dispatch")
class DashboardJuridicoView(View):
    template_name = "juridico/dashboard.html"

    def get(self, request):
        return render(request, self.template_name, {})
