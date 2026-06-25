from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import ConformidadeItemViewSet, DFDViewSet, ItemPCAViewSet, PlanoContratacaoAnualViewSet
from .views_template import DashboardPCAView, DemandasPCAView, ItemPCADetalheView

# ── REST API ───────────────────────────────────────────────────
router = DefaultRouter()
router.register("planos", PlanoContratacaoAnualViewSet, basename="plano")
router.register("dfds", DFDViewSet, basename="dfd")
router.register("itens", ItemPCAViewSet, basename="item")
router.register("conformidade", ConformidadeItemViewSet, basename="conformidade")

app_name = "pca"

urlpatterns = [
    # Django Templates
    path("", DashboardPCAView.as_view(), name="dashboard"),
    path("demandas/", DemandasPCAView.as_view(), name="demandas"),
    path("item/<int:pk>/", ItemPCADetalheView.as_view(), name="item_detalhe"),
    # REST API
    path("api/", include(router.urls)),
]
