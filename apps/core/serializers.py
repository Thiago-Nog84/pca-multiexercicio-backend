from django.contrib.auth import get_user_model
from rest_framework import serializers

from .models import Orgao, Perfil, UnidadeRequisitante

User = get_user_model()


class OrgaoSerializer(serializers.ModelSerializer):
    class Meta:
        model = Orgao
        fields = ["id", "nome", "sigla", "cnpj", "pncp_codigo_orgao", "uf", "esfera", "ativo"]


class UnidadeRequisitanteSerializer(serializers.ModelSerializer):
    orgao_sigla = serializers.CharField(source="orgao.sigla", read_only=True)

    class Meta:
        model = UnidadeRequisitante
        fields = ["id", "orgao", "orgao_sigla", "sigla", "nome", "responsavel", "ativo"]
        read_only_fields = ["orgao_sigla"]


class PerfilSerializer(serializers.ModelSerializer):
    class Meta:
        model = Perfil
        fields = ["id", "usuario", "orgao", "perfil", "unidade", "ativo"]


class UserMeSerializer(serializers.ModelSerializer):
    perfis = PerfilSerializer(many=True, source="perfil_set", read_only=True)

    class Meta:
        model = User
        fields = ["id", "username", "email", "first_name", "last_name", "perfis"]
