from django.urls import path

from .views_checklist import ChecklistInstrucaoView
from .views_dfd import DFDDetalheView, DFDListView
from .views_dod import DODCriarView, DODDetalheView
from .views_template import DashboardPlanejamentoView

app_name = "planejamento"
urlpatterns = [
    path("", DashboardPlanejamentoView.as_view(), name="dashboard"),
    path("dfds/", DFDListView.as_view(), name="dfds"),
    path("dfds/<int:pk>/", DFDDetalheView.as_view(), name="dfd_detalhe"),
    path("dods/novo/", DODCriarView.as_view(), name="dod_novo"),
    path("dods/<int:pk>/", DODDetalheView.as_view(), name="dod_detalhe"),
    path("checklist/", ChecklistInstrucaoView.as_view(), name="checklist_instrucao"),
]
