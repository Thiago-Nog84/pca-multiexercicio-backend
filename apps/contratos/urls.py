from django.urls import path
from .views_template import DashboardContratosView, EmpenhosSIAFEView

app_name = "contratos"

urlpatterns = [
    path("", DashboardContratosView.as_view(), name="dashboard"),
    path("empenhos/", EmpenhosSIAFEView.as_view(), name="empenhos"),
]
