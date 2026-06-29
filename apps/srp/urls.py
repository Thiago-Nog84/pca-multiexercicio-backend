from django.urls import path

from .views import ARPDetalheView, DashboardSRPView, ImportarARPView, SRPUnidadeView

app_name = "srp"

urlpatterns = [
    path("", DashboardSRPView.as_view(), name="dashboard"),
    path("arp/<int:pk>/", ARPDetalheView.as_view(), name="arp_detalhe"),
    path("importar/", ImportarARPView.as_view(), name="importar_arp"),
    path("unidade/<str:sigla>/", SRPUnidadeView.as_view(), name="unidade_dashboard"),
]
