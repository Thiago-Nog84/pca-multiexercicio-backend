"""
URLs da API REST do módulo SRP — montadas em /api/srp/ pelo config/urls.py.
Separado de urls.py para não misturar com as rotas de template Django.
"""
from rest_framework.routers import DefaultRouter

from .api_views import (
    AdesaoARPViewSet,
    AtaRegistroPrecosViewSet,
    ContratacaoDecorenteViewSet,
    ItemARPViewSet,
    VinculoARPUnidadeViewSet,
    VinculoPCAItemARPViewSet,
)

router = DefaultRouter()
router.register(r"arps",               AtaRegistroPrecosViewSet,   basename="arp")
router.register(r"itens",              ItemARPViewSet,             basename="item-arp")
router.register(r"vinculos-arp-unidade", VinculoARPUnidadeViewSet, basename="vinculo-arp-unidade")
router.register(r"vinculos-pca",       VinculoPCAItemARPViewSet,   basename="vinculo-pca")
router.register(r"contratacoes",       ContratacaoDecorenteViewSet, basename="contratacao")
router.register(r"caronas",            AdesaoARPViewSet,           basename="adesao")

urlpatterns = router.urls
