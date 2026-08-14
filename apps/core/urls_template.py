from django.urls import path

from .views_template import NotificacoesView

app_name = "core"

urlpatterns = [
    path("", NotificacoesView.as_view(), name="notificacoes"),
]
