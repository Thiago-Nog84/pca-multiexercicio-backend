from django.contrib import admin
from django.urls import include, path
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView

urlpatterns = [
    path("admin/", admin.site.urls),

    # JWT auth
    path("api/auth/token/", TokenObtainPairView.as_view(), name="token_obtain_pair"),
    path("api/auth/token/refresh/", TokenRefreshView.as_view(), name="token_refresh"),

    # Apps — API REST
    path("api/core/", include("apps.core.urls")),
    path("api/pca/", include("apps.pca.urls")),

    # Dashboard SRP (Django Templates)
    path("srp/", include("apps.srp.urls")),
]
