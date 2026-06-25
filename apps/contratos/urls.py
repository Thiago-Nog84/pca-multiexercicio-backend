from django.urls import path
from .views_template import DashboardContratosView

app_name = "contratos"

urlpatterns = [
    path("", DashboardContratosView.as_view(), name="dashboard"),
]
