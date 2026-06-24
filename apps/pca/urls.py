from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import DFDViewSet, ItemPCAViewSet, PlanoContratacaoAnualViewSet

router = DefaultRouter()
router.register("planos", PlanoContratacaoAnualViewSet, basename="plano")
router.register("dfds", DFDViewSet, basename="dfd")
router.register("itens", ItemPCAViewSet, basename="item")

urlpatterns = [
    path("", include(router.urls)),
]
