from django.urls import path

from .views_checklist import ChecklistInstrucaoView
from .views_dfd import DFDDetalheView, DFDListView
from .views_dod import DODCriarView, DODDetalheView, DODEditarView
from .views_etp import ETPCriarView, ETPDetalheView
from .views_matriz_risco import (
    MatrizRiscoCriarView,
    MatrizRiscoDetalheView,
    RiscoItemExcluirView,
    RiscoItemFormView,
)
from .views_template import DashboardPlanejamentoView
from .views_termo_referencia import TermoReferenciaCriarView, TermoReferenciaDetalheView

app_name = "planejamento"
urlpatterns = [
    path("", DashboardPlanejamentoView.as_view(), name="dashboard"),
    path("dfds/", DFDListView.as_view(), name="dfds"),
    path("dfds/<int:pk>/", DFDDetalheView.as_view(), name="dfd_detalhe"),
    path("dods/novo/", DODCriarView.as_view(), name="dod_novo"),
    path("dods/<int:pk>/", DODDetalheView.as_view(), name="dod_detalhe"),
    path("dods/<int:pk>/editar/", DODEditarView.as_view(), name="dod_editar"),
    path("checklist/", ChecklistInstrucaoView.as_view(), name="checklist_instrucao"),
    path("etps/novo/", ETPCriarView.as_view(), name="etp_novo"),
    path("etps/<int:pk>/", ETPDetalheView.as_view(), name="etp_detalhe"),
    path("matriz-risco/novo/", MatrizRiscoCriarView.as_view(), name="matriz_risco_novo"),
    path("matriz-risco/<int:pk>/", MatrizRiscoDetalheView.as_view(), name="matriz_risco_detalhe"),
    path(
        "matriz-risco/<int:matriz_pk>/itens/novo/",
        RiscoItemFormView.as_view(),
        name="risco_item_novo",
    ),
    path(
        "matriz-risco/<int:matriz_pk>/itens/<int:pk>/editar/",
        RiscoItemFormView.as_view(),
        name="risco_item_editar",
    ),
    path(
        "matriz-risco/<int:matriz_pk>/itens/<int:pk>/excluir/",
        RiscoItemExcluirView.as_view(),
        name="risco_item_excluir",
    ),
    path("termos-referencia/novo/", TermoReferenciaCriarView.as_view(), name="tr_novo"),
    path("termos-referencia/<int:pk>/", TermoReferenciaDetalheView.as_view(), name="tr_detalhe"),
]
