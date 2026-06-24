from rest_framework import permissions, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.viewsets import ModelViewSet

from .models import ConformidadeItem, DocumentoFormalizacaoDemanda, ItemPCA, PlanoContratacaoAnual
from .serializers import (
    ConformidadeItemSerializer,
    DocumentoFormalizacaoDemandaSerializer,
    ItemPCASerializer,
    PlanoContratacaoAnualDetalhadoSerializer,
    PlanoContratacaoAnualSerializer,
)


class PlanoContratacaoAnualViewSet(ModelViewSet):
    """
    CRUD do PCA.
    GET  /api/pca/planos/                    → lista
    GET  /api/pca/planos/{id}/               → detalhe com DFDs e itens
    POST /api/pca/planos/                    → cria
    PATCH /api/pca/planos/{id}/              → atualiza
    POST /api/pca/planos/{id}/avancar_status/ → avança status
    """

    permission_classes = [permissions.IsAuthenticated]

    FLUXO_STATUS = [
        "coleta",
        "consolidacao",
        "aprovacao",
        "aprovado",
        "publicado_pncp",
        "revisao_out",
        "revisao_loa",
    ]

    def get_queryset(self):
        return PlanoContratacaoAnual.objects.select_related("orgao", "aprovado_por").all()

    def get_serializer_class(self):
        if self.action == "retrieve":
            return PlanoContratacaoAnualDetalhadoSerializer
        return PlanoContratacaoAnualSerializer

    @action(detail=True, methods=["post"])
    def avancar_status(self, request, pk=None):
        pca = self.get_object()
        try:
            idx = self.FLUXO_STATUS.index(pca.status)
        except ValueError:
            return Response({"detail": "Status desconhecido."}, status=status.HTTP_400_BAD_REQUEST)

        if idx >= len(self.FLUXO_STATUS) - 1:
            return Response(
                {"detail": "PCA já está no status final."}, status=status.HTTP_400_BAD_REQUEST
            )

        proximo = self.FLUXO_STATUS[idx + 1]
        if proximo == "aprovado":
            pca.aprovado_por = request.user

        pca.status = proximo
        pca.save(update_fields=["status", "aprovado_por"] if proximo == "aprovado" else ["status"])
        return Response(PlanoContratacaoAnualSerializer(pca).data)


class DFDViewSet(ModelViewSet):
    """
    GET /api/pca/dfds/?pca=<id>  → lista DFDs de um PCA
    GET /api/pca/dfds/{id}/      → detalhe com itens
    """

    serializer_class = DocumentoFormalizacaoDemandaSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        qs = DocumentoFormalizacaoDemanda.objects.select_related(
            "pca", "unidade", "requisitante"
        ).prefetch_related("itens")
        pca_id = self.request.query_params.get("pca")
        if pca_id:
            qs = qs.filter(pca_id=pca_id)
        return qs


class ItemPCAViewSet(ModelViewSet):
    """
    GET /api/pca/itens/?dfd=<id>  → lista itens de um DFD
    """

    serializer_class = ItemPCASerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        qs = ItemPCA.objects.select_related("dfd")
        dfd_id = self.request.query_params.get("dfd")
        if dfd_id:
            qs = qs.filter(dfd_id=dfd_id)
        return qs


class ConformidadeItemViewSet(ModelViewSet):
    """
    Checklist de conformidade por item do PCA.
    GET  /api/pca/conformidade/?item=<id>  → lista (ou filtra por item)
    POST /api/pca/conformidade/            → cria OU atualiza (upsert por item)
    """

    serializer_class = ConformidadeItemSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        qs = ConformidadeItem.objects.select_related("item", "avaliado_por")
        item_id = self.request.query_params.get("item")
        if item_id:
            qs = qs.filter(item_id=item_id)
        return qs

    def create(self, request, *args, **kwargs):
        item_id = request.data.get("item")
        existente = ConformidadeItem.objects.filter(item_id=item_id).first()
        if existente:
            serializer = self.get_serializer(existente, data=request.data, partial=True)
            serializer.is_valid(raise_exception=True)
            serializer.save(avaliado_por=request.user)
            return Response(serializer.data)

        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save(avaliado_por=request.user)
        return Response(serializer.data, status=status.HTTP_201_CREATED)
