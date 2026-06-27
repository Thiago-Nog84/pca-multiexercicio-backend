from django.contrib import admin
from django.urls import include, path
from django.views.generic import RedirectView
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView

from apps.siafe.views_template import NotasEmpenhoUGView

urlpatterns = [
    path("", RedirectView.as_view(url="/pca/", permanent=False)),
    path("admin/", admin.site.urls),

    # JWT auth
    path("api/auth/token/", TokenObtainPairView.as_view(), name="token_obtain_pair"),
    path("api/auth/token/refresh/", TokenRefreshView.as_view(), name="token_refresh"),

    # Swagger / OpenAPI
    path("api/schema/", SpectacularAPIView.as_view(), name="schema"),
    path("api/schema/swagger-ui/", SpectacularSwaggerView.as_view(url_name="schema"), name="swagger-ui"),

    # API REST
    path("api/core/", include("apps.core.urls")),
    path("api/siafe/", include(("apps.siafe.urls", "siafe"))),
    path("api/srp/",  include("apps.srp.api_urls")),

    # Django Templates - SIAFE
    path("siafe/nota-empenho/<int:exercicio>/<str:codigo_ug>/",
         NotasEmpenhoUGView.as_view(), name="siafe-ne-ug"),

    # Django Templates - modulos PCA
    path("pca/",          include(("apps.pca.urls",          "pca"))),
    path("planejamento/", include(("apps.planejamento.urls", "planejamento"))),
    path("cotacao/",      include(("apps.cotacao.urls",      "cotacao"))),
    path("licitacao/",    include(("apps.licitacao.urls",    "licitacao"))),
    path("srp/",          include(("apps.srp.urls",          "srp"))),
    path("contratos/",    include(("apps.contratos.urls",    "contratos"))),
    path("juridico/",     include(("apps.juridico.urls",     "juridico"))),
]
