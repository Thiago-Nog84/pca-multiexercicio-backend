"""URLs mínimas para testes — inclui apenas apps já implementados."""
from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/siafe/", include(("apps.siafe.urls", "siafe"))),
    path("pca/",   include(("apps.pca.urls",  "pca"))),
    path("srp/",   include(("apps.srp.urls",  "srp"))),
]
