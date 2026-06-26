from django.contrib import admin
from django.urls import include, path
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView

urlpatterns = [
    path("admin/", admin.site.urls),

    # JWT auth
    path("api/auth/token/", TokenObtainPairView.as_view(), name="token_obtain_pair"),
    path("api/auth/token/refresh/", TokenRefreshView.as_view(), name="token_refresh"),

    # API REST
    path("api/core/", include("apps.core.urls")),
    path("api/siafe/", include(("apps.siafe.urls", "siafe"))),

    # Django Templates - modulos PCA
    path("pca/",          include(("apps.pca.urls",          "pca"))),
    path("planejamento/", include(("apps.planejamento.urls", "planejamento"))),
    path("cotacao/",      include(("apps.cotacao.urls",      "cotacao"))),
    path("licitacao/",    include(("apps.licitacao.urls",    "licitacao"))),
    path("srp/",          include(("apps.srp.urls",          "srp"))),
    path("contratos/",    include(("apps.contratos.urls",    "contratos"))),
    path("juridico/",     include(("apps.juridico.urls",     "juridico"))),
]
