from django.urls import path
from .views_template import DashboardLicitacaoView

app_name = "licitacao"

urlpatterns = [
    path("", DashboardLicitacaoView.as_view(), name="dashboard"),
]
