from django.conf import settings
from django.db import models

# Base legal: IN SEGES 65/2021 (opção do Ato PGJ 1382/2024)
# Dec. 21.872/2023, arts. 43–51 (subsidiário) | Acórdão TCU 1712/2025
# CGE-PI IN 01/2021 — pesquisa de preços (subsidiária)
# Para TI: Res. CNMP 283/2024, art. 10 (TCO) + art. 28 (estimativa de valor)


class PesquisaPrecos(models.Model):
    STATUS = [
        ("em_andamento", "Em andamento"),
        ("concluida", "Concluída"),
        ("aprovada", "Aprovada"),
    ]

    etp = models.OneToOneField("planejamento.ETP", on_delete=models.CASCADE, related_name="pesquisa_precos")
    numero_sei = models.CharField(max_length=30, blank=True)
    responsavel = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="pesquisas_responsavel"
    )
    # Metodologia declarada (IN 65/2021, art. 5º)
    metodologia = models.TextField(help_text="Justificativa da metodologia — IN SEGES 65/2021, art. 5º")
    normativo_base = models.CharField(max_length=50, default="IN SEGES 65/2021")
    status = models.CharField(max_length=15, choices=STATUS, default="em_andamento")
    criado_em = models.DateTimeField(auto_now_add=True)
    concluida_em = models.DateTimeField(null=True, blank=True)


class FontePreco(models.Model):
    """
    Fonte consultada.
    Fontes prioritárias (IN SEGES 65/2021 + Dec. 21.872/2023, art. 43):
    I — sistemas oficiais (PNCP, Painel de Preços, BEC-PI)
    II — contratos similares até 1 ano
    III — mídia especializada / tabelas aprovadas
    IV — notas fiscais eletrônicas
    V — pesquisa direta ≥3 fornecedores (com justificativa)
    Para obras: SINAPI, tabelas do SEINFRA-PI.
    """

    TIPOS = [
        ("pncp", "PNCP — Portal Nacional de Contratações Públicas"),
        ("painel_precos", "Painel de Preços Gov.br"),
        ("bec_pi", "BEC-PI — Bolsa Eletrônica de Compras do Piauí"),
        ("sinapi", "SINAPI"),
        ("contrato_similar", "Contrato similar (até 1 ano)"),
        ("nfe", "Nota Fiscal Eletrônica"),
        ("fornecedor", "Cotação direta de fornecedor (mín. 3)"),
        ("midia_especializada", "Mídia especializada / tabela aprovada"),
        ("outro", "Outro"),
    ]

    pesquisa = models.ForeignKey(PesquisaPrecos, on_delete=models.CASCADE, related_name="fontes")
    tipo = models.CharField(max_length=25, choices=TIPOS)
    identificador = models.CharField(max_length=300, help_text="Número do contrato, URL, cotação, NF-e etc.")
    data_referencia = models.DateField()
    descricao = models.TextField(blank=True)


class ItemCotacao(models.Model):
    """
    Item cotado com resultado do saneamento estatístico.
    Acórdão TCU 1712/2025: "cesta de preços" com múltiplas fontes.
    """

    pesquisa = models.ForeignKey(PesquisaPrecos, on_delete=models.CASCADE, related_name="itens")
    descricao = models.TextField()
    codigo_catmat_catser = models.CharField(max_length=20, blank=True)
    unidade_medida = models.CharField(max_length=30)
    quantidade = models.DecimalField(max_digits=14, decimal_places=4)
    precos_coletados = models.JSONField(
        default=list,
        help_text='[{"fonte_id": 1, "preco_unitario": 10.50, "excluido": false, "motivo_exclusao": ""}]',
    )
    # Resultado estatístico
    preco_medio = models.DecimalField(max_digits=14, decimal_places=2, null=True)
    preco_mediana = models.DecimalField(max_digits=14, decimal_places=2, null=True)
    preco_medio_saneado = models.DecimalField(
        max_digits=14, decimal_places=2, null=True, help_text="Média após remoção de outliers — metodologia TCU"
    )
    preco_referencia = models.DecimalField(
        max_digits=14, decimal_places=2, null=True, help_text="Preço adotado como referência para a licitação"
    )
    valor_total_estimado = models.DecimalField(max_digits=16, decimal_places=2, null=True)
    justificativa_preco = models.TextField(blank=True)
    # TCO para TI (Res. CNMP 283/2024, art. 10)
    tco_detalhamento = models.JSONField(
        null=True, blank=True, help_text="Componentes do TCO para contratações de TIC"
    )
