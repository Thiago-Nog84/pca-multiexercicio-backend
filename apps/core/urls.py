from django.urls import path

from .views import MeView, OrgaoListView, UnidadeRequisitanteListView

urlpatterns = [
    path("me/", MeView.as_view(), name="me"),
    path("orgaos/", OrgaoListView.as_view(), name="orgao-list"),
    path("unidades/", UnidadeRequisitanteListView.as_view(), name="unidade-list"),
]
