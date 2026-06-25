from django.urls import path
from .views_template import DashboardCotacaoView

app_name = "cotacao"

urlpatterns = [
    path("", DashboardCotacaoView.as_view(), name="dashboard"),
]
