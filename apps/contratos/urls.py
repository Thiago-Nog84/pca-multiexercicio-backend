from django.urls import path
from .views_template import (
    DashboardContratosView,
    EmpenhosSIAFEView,
    SincronizarExecucaoSIAFEView,
)

app_name = "contratos"

urlpatterns = [
    path("", DashboardContratosView.as_view(), name="dashboard"),
    path("empenhos/", EmpenhosSIAFEView.as_view(), name="empenhos"),
    path("sincronizar-siafe/", SincronizarExecucaoSIAFEView.as_view(), name="sincronizar_siafe"),
]
