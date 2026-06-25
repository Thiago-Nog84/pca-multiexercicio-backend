from django.urls import path
from .views_template import DashboardPlanejamentoView

app_name = "planejamento"

urlpatterns = [
    path("", DashboardPlanejamentoView.as_view(), name="dashboard"),
]
