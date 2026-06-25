from rest_framework import generics, permissions
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import Orgao, UnidadeRequisitante
from .serializers import OrgaoSerializer, UnidadeRequisitanteSerializer, UserMeSerializer


class MeView(APIView):
    """Retorna o usuário autenticado com seus perfis."""

    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        serializer = UserMeSerializer(request.user)
        return Response(serializer.data)


class OrgaoListView(generics.ListAPIView):
    queryset = Orgao.objects.filter(ativo=True)
    serializer_class = OrgaoSerializer
    permission_classes = [permissions.IsAuthenticated]


class UnidadeRequisitanteListView(generics.ListAPIView):
    serializer_class = UnidadeRequisitanteSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        qs = UnidadeRequisitante.objects.filter(ativo=True).select_related("orgao")
        orgao_id = self.request.query_params.get("orgao")
        if orgao_id:
            qs = qs.filter(orgao_id=orgao_id)
        return qs
