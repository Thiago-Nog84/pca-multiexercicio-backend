from django.urls import path

from .views import (
    ARPDetalheView,
    ContratacoesDecorrentesView,
    DashboardSRPView,
    ImportarARPView,
    SincronizarARPPNCPView,
    SRPUnidadeView,
    proxy_ata_pdf,
    proxy_contrato_pncp_pdf,
)

app_name = "srp"

urlpatterns = [
    path("", DashboardSRPView.as_view(), name="dashboard"),
    path("contratacoes/", ContratacoesDecorrentesView.as_view(), name="contratacoes_decorrentes"),
    path("arp/<int:pk>/", ARPDetalheView.as_view(), name="arp_detalhe"),
    path("arp/<int:pk>/sincronizar-pncp/", SincronizarARPPNCPView.as_view(), name="arp_sincronizar_pncp"),
    path("arp/<int:pk>/ata-pdf/", proxy_ata_pdf, name="ata_pdf"),
    path("contrato-pncp-pdf/<str:tipo>/<int:pk>/", proxy_contrato_pncp_pdf, name="contrato_pncp_pdf"),
    path("importar/", ImportarARPView.as_view(), name="importar_arp"),
    path("unidade/<str:sigla>/", SRPUnidadeView.as_view(), name="unidade_dashboard"),
]
