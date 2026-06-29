"""
Serializers DRF para o módulo SRP — Sistema de Registro de Preços.

Hierarquia de leitura:
  AtaRegistroPrecos
    └── ItemARP  (com propriedades de valor e quantidade)
          ├── VinculoPCAItemARP  (comprometimento PCA)
          ├── ContratacaoDecorrente  (pedidos de fornecimento)
          └── AdesaoARP  (caronas cedidas)

Todos os serializers de escrita chamam full_clean() via Model.save(),
então as validações de negócio (limite 50%, vigência, lote) são aplicadas
automaticamente — não é necessário duplicá-las nos serializers.
"""

from decimal import Decimal

from rest_framework import serializers

from .models import (
    AdesaoARP,
    AtaRegistroPrecos,
    ContratacaoDecorrente,
    ItemARP,
    VinculoARPUnidade,
    VinculoPCAItemARP,
)


# ---------------------------------------------------------------------------
# ItemARP — leitura (com propriedades computadas)
# ---------------------------------------------------------------------------

class ItemARPListSerializer(serializers.ModelSerializer):
    """Versão compacta para listagem dentro de uma ARP."""
    quantidade_disponivel = serializers.DecimalField(
        max_digits=14, decimal_places=4, read_only=True,
    )
    valor_total_registrado = serializers.DecimalField(
        max_digits=16, decimal_places=2, read_only=True,
    )
    valor_disponivel = serializers.DecimalField(
        max_digits=16, decimal_places=2, read_only=True,
    )

    class Meta:
        model = ItemARP
        fields = [
            "id", "numero_item", "numero_lote", "descricao",
            "unidade_fornecimento", "quantidade_registrada",
            "quantidade_contratada", "quantidade_cedida_carona",
            "quantidade_disponivel",
            "valor_unitario",
            "valor_total_registrado", "valor_disponivel",
            "maximo_adesao_api",
        ]
        read_only_fields = fields


class ItemARPDetailSerializer(serializers.ModelSerializer):
    """Versão completa com todas as propriedades financeiras e de quantidade."""
    # Propriedades de quantidade
    quantidade_disponivel          = serializers.DecimalField(max_digits=14, decimal_places=4, read_only=True)
    quantidade_comprometida_pca    = serializers.DecimalField(max_digits=14, decimal_places=4, read_only=True)
    quantidade_disponivel_eventual = serializers.DecimalField(max_digits=14, decimal_places=4, read_only=True)

    # Propriedades de valor R$
    valor_total_registrado         = serializers.DecimalField(max_digits=16, decimal_places=2, read_only=True)
    valor_total_contratado         = serializers.DecimalField(max_digits=16, decimal_places=2, read_only=True)
    valor_cedido_carona            = serializers.DecimalField(max_digits=16, decimal_places=2, read_only=True)
    valor_disponivel               = serializers.DecimalField(max_digits=16, decimal_places=2, read_only=True)
    valor_comprometido_pca         = serializers.DecimalField(max_digits=16, decimal_places=2, read_only=True)
    valor_disponivel_eventual      = serializers.DecimalField(max_digits=16, decimal_places=2, read_only=True)

    # Limite de carona (50%)
    limite_carona_por_aderente     = serializers.DecimalField(max_digits=14, decimal_places=4, read_only=True)

    class Meta:
        model = ItemARP
        fields = [
            "id", "arp", "numero_item", "numero_lote", "descricao",
            "unidade_fornecimento",
            # Quantidades
            "quantidade_registrada", "quantidade_contratada",
            "quantidade_cedida_carona", "quantidade_disponivel",
            "quantidade_comprometida_pca", "quantidade_disponivel_eventual",
            # Valores R$
            "valor_unitario", "valor_total_registrado", "valor_total_contratado",
            "valor_cedido_carona", "valor_disponivel",
            "valor_comprometido_pca", "valor_disponivel_eventual",
            # Compras.gov
            "maximo_adesao_api", "limite_carona_por_aderente",
        ]


class ItemARPWriteSerializer(serializers.ModelSerializer):
    """Serializer de escrita para criação/edição de itens."""
    class Meta:
        model = ItemARP
        fields = [
            "arp", "numero_item", "numero_lote", "descricao",
            "unidade_fornecimento", "quantidade_registrada",
            "valor_unitario", "maximo_adesao_api",
        ]


# ---------------------------------------------------------------------------
# AtaRegistroPrecos
# ---------------------------------------------------------------------------

class AtaRegistroPrecosListSerializer(serializers.ModelSerializer):
    """Versão compacta para listagem."""
    esta_vigente = serializers.BooleanField(read_only=True)
    orgao_sigla  = serializers.CharField(source="orgao_gerenciador.sigla", read_only=True)
    total_itens  = serializers.IntegerField(source="itens.count", read_only=True)

    class Meta:
        model = AtaRegistroPrecos
        fields = [
            "id", "numero_arp", "orgao_gerenciador", "orgao_sigla",
            "objeto", "fornecedor_razao_social", "fornecedor_cnpj_cpf",
            "modalidade_origem", "status", "esta_vigente",
            "data_inicio_vigencia", "data_fim_vigencia",
            "usa_lotes", "link_documento_mppi", "total_itens",
        ]
        read_only_fields = ["esta_vigente", "orgao_sigla", "total_itens"]


class AtaRegistroPrecosDetailSerializer(serializers.ModelSerializer):
    """Versão completa com itens embutidos."""
    esta_vigente = serializers.BooleanField(read_only=True)
    orgao_sigla  = serializers.CharField(source="orgao_gerenciador.sigla", read_only=True)
    itens        = ItemARPListSerializer(many=True, read_only=True)

    class Meta:
        model = AtaRegistroPrecos
        fields = [
            "id", "numero_arp", "orgao_gerenciador", "orgao_sigla",
            "objeto", "modalidade_origem",
            "fornecedor_razao_social", "fornecedor_cnpj_cpf",
            "data_assinatura", "data_inicio_vigencia", "data_fim_vigencia",
            "status", "esta_vigente",
            "processo_licitatorio", "numero_sei",
            "usa_lotes", "link_documento_mppi",
            "observacoes", "criado_em",
            "itens",
        ]
        read_only_fields = ["esta_vigente", "orgao_sigla", "criado_em"]


class AtaRegistroPrecosWriteSerializer(serializers.ModelSerializer):
    class Meta:
        model = AtaRegistroPrecos
        fields = [
            "orgao_gerenciador", "numero_arp", "objeto", "modalidade_origem",
            "fornecedor_razao_social", "fornecedor_cnpj_cpf",
            "data_assinatura", "data_inicio_vigencia", "data_fim_vigencia",
            "status", "processo_licitatorio", "numero_sei",
            "usa_lotes", "link_documento_mppi", "observacoes",
        ]


# ---------------------------------------------------------------------------
# VinculoPCAItemARP
# ---------------------------------------------------------------------------

class VinculoPCAItemARPSerializer(serializers.ModelSerializer):
    item_pca_descricao = serializers.CharField(
        source="item_pca.descricao", read_only=True,
    )
    item_arp_descricao = serializers.CharField(
        source="item_arp.descricao", read_only=True,
    )

    class Meta:
        model = VinculoPCAItemARP
        fields = [
            "id", "item_pca", "item_pca_descricao",
            "item_arp", "item_arp_descricao",
            "quantidade_comprometida", "observacoes",
            "criado_por", "criado_em",
        ]
        read_only_fields = ["criado_em", "item_pca_descricao", "item_arp_descricao"]


# ---------------------------------------------------------------------------
# ContratacaoDecorrente
# ---------------------------------------------------------------------------

class ContratacaoDecorenteSerializer(serializers.ModelSerializer):
    arp_numero = serializers.CharField(source="arp.numero_arp", read_only=True)
    item_descricao = serializers.CharField(source="item_arp.descricao", read_only=True)

    class Meta:
        model = ContratacaoDecorrente
        fields = [
            "id", "arp", "arp_numero", "item_arp", "item_descricao",
            "numero_pedido", "numero_contrato", "exercicio", "numero_sei",
            "quantidade", "valor_unitario", "valor_total",
            "data_emissao", "data_entrega_prevista",
            "status", "unidade_requisitante", "observacoes",
            "criado_por", "criado_em",
        ]
        read_only_fields = ["arp_numero", "item_descricao", "exercicio", "criado_em"]

    def validate(self, attrs):
        # exercicio é preenchido automaticamente em save() — não bloquear se ausente
        return attrs


# ---------------------------------------------------------------------------
# AdesaoARP (carona cedida)
# ---------------------------------------------------------------------------

class AdesaoARPSerializer(serializers.ModelSerializer):
    arp_numero = serializers.CharField(source="arp.numero_arp", read_only=True)
    item_descricao = serializers.CharField(source="item_arp.descricao", read_only=True)
    limite_aderente = serializers.SerializerMethodField()

    class Meta:
        model = AdesaoARP
        fields = [
            "id", "arp", "arp_numero", "item_arp", "item_descricao",
            "orgao_aderente_nome", "orgao_aderente_cnpj",
            "quantidade_solicitada", "valor_unitario", "valor_total",
            "data_solicitacao", "data_autorizacao",
            "status", "numero_sei_autorizacao",
            "limite_aderente", "observacoes",
            "autorizado_por", "criado_em",
        ]
        read_only_fields = ["arp_numero", "item_descricao", "limite_aderente", "criado_em"]

    def get_limite_aderente(self, obj) -> Decimal:
        """50% do quantitativo registrado no item."""
        return obj.item_arp.limite_carona_por_aderente


# ---------------------------------------------------------------------------
# VinculoARPUnidade — quais unidades gerem / usam cada ARP
# ---------------------------------------------------------------------------

class VinculoARPUnidadeSerializer(serializers.ModelSerializer):
    """Leitura e escrita de vínculos ARP × Unidade Requisitante."""
    arp_numero       = serializers.CharField(source="arp.numero_arp",   read_only=True)
    arp_objeto       = serializers.CharField(source="arp.objeto",       read_only=True)
    arp_status       = serializers.CharField(source="arp.status",       read_only=True)
    unidade_sigla    = serializers.CharField(source="unidade.sigla",    read_only=True)
    unidade_nome     = serializers.CharField(source="unidade.nome",     read_only=True)
    papel_display    = serializers.CharField(source="get_papel_display", read_only=True)

    class Meta:
        model = VinculoARPUnidade
        fields = [
            "id", "arp", "arp_numero", "arp_objeto", "arp_status",
            "unidade", "unidade_sigla", "unidade_nome",
            "papel", "papel_display", "observacoes", "criado_em",
        ]
        read_only_fields = [
            "arp_numero", "arp_objeto", "arp_status",
            "unidade_sigla", "unidade_nome", "papel_display", "criado_em",
        ]


# ---------------------------------------------------------------------------
# ARPResumoUnidadeSerializer — para o dashboard por unidade
# Inclui contagens de contratos e saldo consolidado dos itens.
# ---------------------------------------------------------------------------

class ARPResumoUnidadeSerializer(serializers.ModelSerializer):
    """
    Resumo de uma ARP com métricas calculadas, usado no dashboard por unidade.
    Retornado pela action /api/srp/arps/por-unidade/?sigla=CAA
    """
    esta_vigente            = serializers.BooleanField(read_only=True)
    papel_unidade           = serializers.SerializerMethodField()
    total_itens             = serializers.IntegerField(source="itens.count", read_only=True)
    valor_total_registrado  = serializers.SerializerMethodField()
    valor_total_disponivel  = serializers.SerializerMethodField()
    valor_comprometido_pca  = serializers.SerializerMethodField()
    total_contratacoes_dec  = serializers.SerializerMethodField()
    total_contratos_api     = serializers.SerializerMethodField()
    percentual_consumido    = serializers.SerializerMethodField()

    class Meta:
        model = AtaRegistroPrecos
        fields = [
            "id", "numero_arp", "objeto",
            "fornecedor_razao_social", "fornecedor_cnpj_cpf",
            "data_inicio_vigencia", "data_fim_vigencia",
            "status", "esta_vigente",
            "usa_lotes", "link_documento_mppi",
            "papel_unidade",
            "total_itens",
            "valor_total_registrado",
            "valor_total_disponivel",
            "valor_comprometido_pca",
            "total_contratacoes_dec",
            "total_contratos_api",
            "percentual_consumido",
        ]

    def _unidade_sigla(self):
        return self.context.get("unidade_sigla", "")

    def get_papel_unidade(self, obj) -> str:
        """Papel da unidade requisitante nesta ARP (gestora/demandante)."""
        sigla = self._unidade_sigla()
        vinculo = obj.vinculos_unidades.filter(unidade__sigla=sigla).first()
        return vinculo.papel if vinculo else ""

    def get_valor_total_registrado(self, obj) -> str:
        total = sum(i.quantidade_registrada * i.valor_unitario for i in obj.itens.all())
        return str(total)

    def get_valor_total_disponivel(self, obj) -> str:
        total = sum(i.valor_disponivel for i in obj.itens.all())
        return str(total)

    def get_valor_comprometido_pca(self, obj) -> str:
        total = sum(i.valor_comprometido_pca for i in obj.itens.all())
        return str(total)

    def get_total_contratacoes_dec(self, obj) -> int:
        return obj.contratacoes_decorrentes.count()

    def get_total_contratos_api(self, obj) -> int:
        return obj.contratos_arp.count()

    def get_percentual_consumido(self, obj) -> float:
        """% do valor registrado já consumido (contratado + cedido em carona)."""
        registrado = sum(i.valor_total_registrado for i in obj.itens.all())
        if not registrado:
            return 0.0
        consumido = sum(
            i.valor_total_contratado + i.valor_cedido_carona
            for i in obj.itens.all()
        )
        return round(float(consumido / registrado) * 100, 1)


# ---------------------------------------------------------------------------
# ItemARPDisponivelSerializer — para seleção no PCA 2027
# Lista itens de ARPs vigentes com saldo disponível para comprometimento.
# ---------------------------------------------------------------------------

class ItemARPDisponivelSerializer(serializers.ModelSerializer):
    """
    Usado em GET /api/srp/itens/disponiveis-pca/?unidade=CAA
    para mostrar ao requisitante quais itens de ARP ainda têm saldo
    e podem ser referenciados em demandas do PCA.
    """
    arp_numero              = serializers.CharField(source="arp.numero_arp",  read_only=True)
    arp_objeto              = serializers.CharField(source="arp.objeto",      read_only=True)
    arp_vigencia_fim        = serializers.DateField(source="arp.data_fim_vigencia", read_only=True)
    arp_fornecedor          = serializers.CharField(source="arp.fornecedor_razao_social", read_only=True)

    quantidade_disponivel          = serializers.DecimalField(max_digits=14, decimal_places=4, read_only=True)
    quantidade_comprometida_pca    = serializers.DecimalField(max_digits=14, decimal_places=4, read_only=True)
    quantidade_disponivel_eventual = serializers.DecimalField(max_digits=14, decimal_places=4, read_only=True)
    valor_total_registrado         = serializers.DecimalField(max_digits=16, decimal_places=2, read_only=True)
    valor_disponivel               = serializers.DecimalField(max_digits=16, decimal_places=2, read_only=True)
    valor_disponivel_eventual      = serializers.DecimalField(max_digits=16, decimal_places=2, read_only=True)
    valor_comprometido_pca         = serializers.DecimalField(max_digits=16, decimal_places=2, read_only=True)

    class Meta:
        model = ItemARP
        fields = [
            "id", "arp", "arp_numero", "arp_objeto", "arp_vigencia_fim", "arp_fornecedor",
            "numero_item", "numero_lote", "descricao",
            "unidade_fornecimento", "valor_unitario",
            "quantidade_registrada", "quantidade_contratada", "quantidade_cedida_carona",
            "quantidade_disponivel", "quantidade_comprometida_pca", "quantidade_disponivel_eventual",
            "valor_total_registrado", "valor_disponivel", "valor_comprometido_pca",
            "valor_disponivel_eventual",
        ]
        read_only_fields = fields
