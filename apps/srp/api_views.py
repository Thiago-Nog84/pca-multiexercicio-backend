"""
ViewSets DRF para o módulo SRP.

Endpoints gerados pelo DefaultRouter:

  GET    /api/srp/arps/                      → lista ARPs
  POST   /api/srp/arps/                      → cria ARP
  GET    /api/srp/arps/{pk}/                 → detalhe ARP (com itens)
  PUT    /api/srp/arps/{pk}/                 → atualiza ARP
  PATCH  /api/srp/arps/{pk}/                 → atualiza parcial
  DELETE /api/srp/arps/{pk}/                 → remove ARP

  GET    /api/srp/arps/{pk}/itens/           → itens da ARP
  GET    /api/srp/arps/{pk}/contratacoes/    → pedidos de fornecimento
  GET    /api/srp/arps/{pk}/caronas/         → adesões à ARP

  GET    /api/srp/itens/                     → todos os itens (filtráveis)
  GET    /api/srp/itens/{pk}/                → detalhe item (com financeiro)

  GET    /api/srp/vinculos-pca/              → vínculos PCA × ARP
  POST   /api/srp/vinculos-pca/             → cria vínculo
  DELETE /api/srp/vinculos-pca/{pk}/        → remove vínculo

  GET    /api/srp/contratacoes/              → todas as contratações
  POST   /api/srp/contratacoes/             → cria contratação

  GET    /api/srp/caronas/                   → todas as caronas cedidas
  POST   /api/srp/caronas/                  → registra carona
"""

from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from .models import (
    AdesaoARP,
    AtaRegistroPrecos,
    ContratacaoDecorrente,
    ItemARP,
    VinculoPCAItemARP,
)
from .serializers import (
    AdesaoARPSerializer,
    AtaRegistroPrecosDetailSerializer,
    AtaRegistroPrecosListSerializer,
    AtaRegistroPrecosWriteSerializer,
    ContratacaoDecorenteSerializer,
    ItemARPDetailSerializer,
    ItemARPListSerializer,
    ItemARPWriteSerializer,
    VinculoPCAItemARPSerializer,
)


# ---------------------------------------------------------------------------
# AtaRegistroPrecos
# ---------------------------------------------------------------------------

class AtaRegistroPrecosViewSet(viewsets.ModelViewSet):
    """
    CRUD de Atas de Registro de Preços.

    Filtros via query params:
      ?status=vigente
      ?vigente=true   → apenas ARPs com esta_vigente=True
      ?exercicio=2026 → filtra por ano de início de vigência
    """
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        qs = AtaRegistroPrecos.objects.select_related(
            "orgao_gerenciador",
        ).prefetch_related("itens").order_by("-data_inicio_vigencia")

        # Filtros opcionais
        status_param = self.request.query_params.get("status")
        if status_param:
            qs = qs.filter(status=status_param)

        exercicio = self.request.query_params.get("exercicio")
        if exercicio:
            qs = qs.filter(data_inicio_vigencia__year=exercicio)

        vigente = self.request.query_params.get("vigente", "").lower()
        if vigente == "true":
            from datetime import date
            qs = qs.filter(status="vigente", data_fim_vigencia__gte=date.today())
        elif vigente == "false":
            from datetime import date
            qs = qs.exclude(status="vigente", data_fim_vigencia__gte=date.today())

        return qs

    def get_serializer_class(self):
        if self.action == "list":
            return AtaRegistroPrecosListSerializer
        if self.action in ("create", "update", "partial_update"):
            return AtaRegistroPrecosWriteSerializer
        return AtaRegistroPrecosDetailSerializer

    def perform_create(self, serializer):
        serializer.save(criado_por=self.request.user)

    # ------------------------------------------------------------------ #
    # Ações aninhadas                                                      #
    # ------------------------------------------------------------------ #

    @action(detail=True, methods=["get"], url_path="itens")
    def itens(self, request, pk=None):
        """Lista itens da ARP com propriedades de quantidade."""
        arp = self.get_object()
        serializer = ItemARPListSerializer(
            arp.itens.all(), many=True, context={"request": request},
        )
        return Response(serializer.data)

    @action(detail=True, methods=["get"], url_path="contratacoes")
    def contratacoes(self, request, pk=None):
        """Lista pedidos de fornecimento decorrentes da ARP."""
        arp = self.get_object()
        qs = arp.contratacoes_decorrentes.select_related(
            "item_arp", "unidade_requisitante", "criado_por",
        ).order_by("-data_emissao")
        serializer = ContratacaoDecorenteSerializer(
            qs, many=True, context={"request": request},
        )
        return Response(serializer.data)

    @action(detail=True, methods=["get"], url_path="caronas")
    def caronas(self, request, pk=None):
        """Lista adesões (caronas cedidas) à ARP."""
        arp = self.get_object()
        qs = arp.adesoes.select_related("item_arp", "autorizado_por").order_by(
            "-data_solicitacao",
        )
        serializer = AdesaoARPSerializer(
            qs, many=True, context={"request": request},
        )
        return Response(serializer.data)


# ---------------------------------------------------------------------------
# ItemARP
# ---------------------------------------------------------------------------

class ItemARPViewSet(
    mixins.CreateModelMixin,
    mixins.RetrieveModelMixin,
    mixins.UpdateModelMixin,
    mixins.ListModelMixin,
    viewsets.GenericViewSet,
):
    """
    Itens de ARP — sem DELETE (integridade do histórico).

    Filtros:
      ?arp=<pk>
      ?disponivel=true  → apenas itens com quantidade_disponivel > 0
    """
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        qs = ItemARP.objects.select_related("arp").order_by("arp", "numero_item")

        arp_pk = self.request.query_params.get("arp")
        if arp_pk:
            qs = qs.filter(arp_id=arp_pk)

        if self.request.query_params.get("disponivel", "").lower() == "true":
            # Filtra itens com saldo positivo (quantidade_registrada > contratada + carona)
            from django.db.models import F
            qs = qs.filter(
                quantidade_registrada__gt=F("quantidade_contratada") + F("quantidade_cedida_carona")
            )

        return qs

    def get_serializer_class(self):
        if self.action in ("create", "update", "partial_update"):
            return ItemARPWriteSerializer
        if self.action == "retrieve":
            return ItemARPDetailSerializer
        return ItemARPListSerializer


# ---------------------------------------------------------------------------
# VinculoPCAItemARP
# ---------------------------------------------------------------------------

class VinculoPCAItemARPViewSet(
    mixins.CreateModelMixin,
    mixins.RetrieveModelMixin,
    mixins.DestroyModelMixin,
    mixins.ListModelMixin,
    viewsets.GenericViewSet,
):
    """
    Comprometimento de demandas do PCA com itens de ARP.

    Filtros:
      ?item_arp=<pk>
      ?item_pca=<pk>
    """
    permission_classes = [IsAuthenticated]
    serializer_class = VinculoPCAItemARPSerializer

    def get_queryset(self):
        qs = VinculoPCAItemARP.objects.select_related(
            "item_pca", "item_arp", "criado_por",
        )
        item_arp = self.request.query_params.get("item_arp")
        if item_arp:
            qs = qs.filter(item_arp_id=item_arp)
        item_pca = self.request.query_params.get("item_pca")
        if item_pca:
            qs = qs.filter(item_pca_id=item_pca)
        return qs

    def perform_create(self, serializer):
        serializer.save(criado_por=self.request.user)


# ---------------------------------------------------------------------------
# ContratacaoDecorrente
# ---------------------------------------------------------------------------

class ContratacaoDecorenteViewSet(
    mixins.CreateModelMixin,
    mixins.RetrieveModelMixin,
    mixins.ListModelMixin,
    viewsets.GenericViewSet,
):
    """
    Pedidos de fornecimento decorrentes de ARP própria.
    Sem UPDATE/DELETE — alterações são feitas via campos opcionais (numero_contrato, status).

    Filtros:
      ?arp=<pk>
      ?status=emitido|em_execucao|concluido|cancelado
      ?exercicio=2026
    """
    permission_classes = [IsAuthenticated]
    serializer_class = ContratacaoDecorenteSerializer

    def get_queryset(self):
        qs = ContratacaoDecorrente.objects.select_related(
            "arp", "item_arp", "unidade_requisitante", "criado_por",
        ).order_by("-data_emissao")

        arp_pk = self.request.query_params.get("arp")
        if arp_pk:
            qs = qs.filter(arp_id=arp_pk)

        status_param = self.request.query_params.get("status")
        if status_param:
            qs = qs.filter(status=status_param)

        exercicio = self.request.query_params.get("exercicio")
        if exercicio:
            qs = qs.filter(exercicio=exercicio)

        return qs

    def perform_create(self, serializer):
        serializer.save(criado_por=self.request.user)

    @action(detail=True, methods=["patch"], url_path="status")
    def atualizar_status(self, request, pk=None):
        """PATCH /api/srp/contratacoes/{pk}/status/ — atualiza status sem reprocessar débito."""
        contratacao = self.get_object()
        novo_status = request.data.get("status")
        choices_validos = [c[0] for c in ContratacaoDecorrente.STATUS]
        if novo_status not in choices_validos:
            return Response(
                {"status": f"Valor inválido. Opções: {choices_validos}"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        ContratacaoDecorrente.objects.filter(pk=contratacao.pk).update(status=novo_status)
        contratacao.refresh_from_db()
        return Response(ContratacaoDecorenteSerializer(contratacao).data)


# ---------------------------------------------------------------------------
# AdesaoARP (carona cedida)
# ---------------------------------------------------------------------------

class AdesaoARPViewSet(
    mixins.CreateModelMixin,
    mixins.RetrieveModelMixin,
    mixins.ListModelMixin,
    viewsets.GenericViewSet,
):
    """
    Caronas cedidas — adesões de outros órgãos à ARP do MPPI.

    Filtros:
      ?arp=<pk>
      ?status=solicitada|autorizada|recusada|cancelada
      ?cnpj=<cnpj_aderente>
    """
    permission_classes = [IsAuthenticated]
    serializer_class = AdesaoARPSerializer

    def get_queryset(self):
        qs = AdesaoARP.objects.select_related(
            "arp", "item_arp", "autorizado_por",
        ).order_by("-data_solicitacao")

        arp_pk = self.request.query_params.get("arp")
        if arp_pk:
            qs = qs.filter(arp_id=arp_pk)

        status_param = self.request.query_params.get("status")
        if status_param:
            qs = qs.filter(status=status_param)

        cnpj = self.request.query_params.get("cnpj")
        if cnpj:
            qs = qs.filter(orgao_aderente_cnpj=cnpj)

        return qs

    @action(detail=True, methods=["patch"], url_path="autorizar")
    def autorizar(self, request, pk=None):
        """PATCH /api/srp/caronas/{pk}/autorizar/ — autoriza uma adesão."""
        from datetime import date
        adesao = self.get_object()
        if adesao.status != "solicitada":
            return Response(
                {"detail": "Apenas adesões com status 'solicitada' podem ser autorizadas."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        AdesaoARP.objects.filter(pk=adesao.pk).update(
            status="autorizada",
            data_autorizacao=date.today(),
            autorizado_por=request.user,
        )
        adesao.refresh_from_db()
        return Response(AdesaoARPSerializer(adesao).data)
