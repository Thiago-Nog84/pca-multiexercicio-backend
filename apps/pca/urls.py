from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import ConformidadeItemViewSet, DFDViewSet, ItemPCAViewSet, PlanoContratacaoAnualViewSet
from .views_template import (
    CatalogoSearchView,
    DashboardPCAView,
    DemandasPCAView,
    ItemPCADetalheView,
    RenovacaoExercicioView,
)

router = DefaultRouter()
router.register("planos", PlanoContratacaoAnualViewSet, basename="plano")
router.register("dfds", DFDViewSet, basename="dfd")
router.register("itens", ItemPCAViewSet, basename="item")
router.register("conformidade", ConformidadeItemViewSet, basename="conformidade")

app_name = "pca"

urlpatterns = [
    path("", DashboardPCAView.as_view(), name="dashboard"),
    path("demandas/", DemandasPCAView.as_view(), name="demandas"),
    path("item/<int:pk>/", ItemPCADetalheView.as_view(), name="item_detalhe"),
    path("renovacao/", RenovacaoExercicioView.as_view(), name="renovacao"),
    path("api/catalogo/", CatalogoSearchView.as_view(), name="catalogo_search"),
    path("api/", include(router.urls)),
]
