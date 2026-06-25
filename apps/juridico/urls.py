from django.urls import path
from .views_template import DashboardJuridicoView

app_name = "juridico"

urlpatterns = [
    path("", DashboardJuridicoView.as_view(), name="dashboard"),
]
