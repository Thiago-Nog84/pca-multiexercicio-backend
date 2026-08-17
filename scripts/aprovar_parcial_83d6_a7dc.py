"""
Aprovacao PARCIAL dos codigos 83D6 e A7DC do PCA 2026.

Contexto: ambos tiveram o item do sistema identificado na segunda revisao das
pendencias (17/08/2026), mas a quantidade constante do PDF homologado e menor
que a cadastrada no sistema. Decisao do Thiago: aprovar PARCIALMENTE, isto e,
homologar o quantitativo do documento oficial e preservar o pedido original da
unidade nos campos *_solicitado -- exatamente a convencao usada pela tela
AnalisarItemPCAView (apps/pca/views_analise.py).

Rodar com:
    .\.venv\Scripts\python.exe manage.py shell -c "import runpy; runpy.run_path('scripts/aprovar_parcial_83d6_a7dc.py')"
"""

from decimal import Decimal

from django.contrib.auth.models import User
from django.db import transaction
from django.utils import timezone

from apps.pca.models import ItemPCA

MOTIVO = (
    "Aprovada parcialmente na conferencia contra o PCA 2026 Versao 3.0 "
    "(documento oficial homologado pela Procuradoria-Geral de Justica, PDF de "
    "15/06/2026): o documento homologa {qtd_pdf:g} unidade(s), enquanto o "
    "sistema tinha {qtd_sis:g} cadastradas. Aprovado o quantitativo do "
    "documento homologado; o valor unitario nao sofreu corte. Codigo no "
    "documento: {cod}. Revisao manual em 17/08/2026."
)

CASOS = [
    # (pk, codigo_no_pdf, quantidade_aprovada, valor_unitario_aprovado)
    (887, "83D6", Decimal("140"), Decimal("3.00")),
    (788, "A7DC", Decimal("100"), Decimal("6194.22")),
]

usuario = User.objects.get(id=1)
agora = timezone.now()

with transaction.atomic():
    for pk, cod, qtd, vu in CASOS:
        item = ItemPCA.objects.get(pk=pk)
        assert item.status_aprovacao == "pendente", (pk, item.status_aprovacao)

        # Preserva o pedido original apenas na primeira analise.
        if item.quantidade_solicitada is None:
            item.quantidade_solicitada = item.quantidade_estimada
        if item.valor_unitario_solicitado is None:
            item.valor_unitario_solicitado = item.valor_unitario_estimado

        assert qtd <= item.quantidade_solicitada, (pk, qtd, item.quantidade_solicitada)
        assert vu == item.valor_unitario_solicitado, (pk, vu, item.valor_unitario_solicitado)

        item.quantidade_estimada = qtd
        item.valor_unitario_estimado = vu
        item.valor_total_estimado = qtd * vu
        item.status_aprovacao = "aprovada_parcial"
        # normalize() evita "300.0000 cadastradas" no texto que a unidade le.
        item.motivo_analise = MOTIVO.format(
            qtd_pdf=qtd.normalize(),
            qtd_sis=item.quantidade_solicitada.normalize(),
            cod=cod,
        )
        item.analisado_por = usuario
        item.analisado_em = agora
        item.save()

        print(
            pk, item.codigo_pca, item.status_aprovacao,
            "| qtd", item.quantidade_solicitada, "->", item.quantidade_estimada,
            "| total", item.valor_total_estimado,
            "| houve_corte", item.houve_corte,
            "| valor_cortado", item.valor_cortado,
        )
