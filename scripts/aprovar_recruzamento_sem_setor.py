"""
Aprova as 9 demandas encontradas ao refazer o cruzamento SEM restringir por
unidade requisitante (ver scripts/diagnostico_34_sem_item.py).

Tres grupos, conforme decisao do Thiago em 17/08/2026:

  A) casamento exato (texto, quantidade e valor) -> aprovacao INTEGRAL.
     O cruzamento original falhou apenas porque o PDF atribui a demanda a
     ASSESPPLAGES e o sistema, a APG.

  B) PDF homologa quantidade MAIOR que a cadastrada -> aprovacao INTEGRAL do
     que esta cadastrado. Aprovar menos que o autorizado esta dentro do limite
     da PGJ; o sistema tambem nao aceita aprovar acima do solicitado.

  C) PDF homologa quantidade MENOR que a cadastrada -> aprovacao PARCIAL, pela
     mesma convencao de AnalisarItemPCAView ja usada em 83D6 e A7DC.

Rodar com:
    .\.venv\Scripts\python.exe manage.py shell -c "import runpy; runpy.run_path('scripts/aprovar_recruzamento_sem_setor.py')"
"""

from decimal import Decimal

from django.contrib.auth.models import User
from django.db import transaction
from django.utils import timezone

from apps.pca.models import ItemPCA

MOTIVO_EXATO = (
    "Aprovada na revisao manual de 17/08/2026 contra o PCA 2026 Versao 3.0 "
    "(documento homologado pela Procuradoria-Geral de Justica, PDF de "
    "15/06/2026). O cruzamento automatico inicial nao encontrou este item "
    "porque so comparava candidatos da mesma unidade requisitante: o documento "
    "atribui a demanda a ASSESPPLAGES e o sistema, a APG. Texto, quantidade e "
    "valor unitario conferem integralmente. Codigo no documento: {cod}."
)

MOTIVO_PDF_MAIOR = (
    "Aprovada integralmente na revisao manual de 17/08/2026 contra o PCA 2026 "
    "Versao 3.0 (documento homologado pela Procuradoria-Geral de Justica, PDF "
    "de 15/06/2026). O documento autoriza {qtd_pdf:g} unidade(s) e a unidade "
    "requisitante cadastrou {qtd_sis:g} -- aprovado todo o quantitativo "
    "cadastrado, que esta dentro do limite autorizado. A diferenca nao consta "
    "do sistema; se for necessaria, cabe nova demanda. Codigo no documento: {cod}."
)

MOTIVO_PARCIAL = (
    "Aprovada parcialmente na revisao manual de 17/08/2026 contra o PCA 2026 "
    "Versao 3.0 (documento homologado pela Procuradoria-Geral de Justica, PDF "
    "de 15/06/2026): o documento homologa {qtd_pdf:g} unidade(s), enquanto o "
    "sistema tinha {qtd_sis:g} cadastradas. Aprovado o quantitativo do "
    "documento homologado; o valor unitario nao sofreu corte. Codigo no "
    "documento: {cod}."
)

# (pk, codigo_no_pdf)
EXATOS = [(1072, "7CEA"), (1071, "944D")]

# (pk, codigo_no_pdf, quantidade_autorizada_no_pdf)
PDF_MAIOR = [(884, "CA01", Decimal("70")), (744, "CA35", Decimal("10"))]

# (pk, codigo_no_pdf, quantidade_aprovada, valor_unitario)
PARCIAIS = [
    (885, "4F3A", Decimal("60"), Decimal("24.70")),
    (886, "601D", Decimal("15"), Decimal("74.00")),
    (754, "1471", Decimal("8"), Decimal("2000.00")),
    (745, "6507", Decimal("8"), Decimal("850.00")),
    (799, "44AA", Decimal("8"), Decimal("720.00")),
]


usuario = User.objects.get(id=1)
agora = timezone.now()


def marcar(item, status, motivo):
    item.status_aprovacao = status
    item.motivo_analise = motivo
    item.analisado_por = usuario
    item.analisado_em = agora
    item.save()
    print(f"  {item.pk} {item.codigo_pca} -> {item.status_aprovacao} "
          f"| qtd {item.quantidade_estimada} | total {item.valor_total_estimado}")


with transaction.atomic():
    print("A) casamento exato -> integral")
    for pk, cod in EXATOS:
        item = ItemPCA.objects.get(pk=pk)
        assert item.status_aprovacao == "pendente", (pk, item.status_aprovacao)
        marcar(item, "aprovada_integral", MOTIVO_EXATO.format(cod=cod))

    print("B) PDF autoriza mais que o cadastrado -> integral do cadastrado")
    for pk, cod, qtd_pdf in PDF_MAIOR:
        item = ItemPCA.objects.get(pk=pk)
        assert item.status_aprovacao == "pendente", (pk, item.status_aprovacao)
        assert qtd_pdf > item.quantidade_estimada, (pk, qtd_pdf, item.quantidade_estimada)
        marcar(item, "aprovada_integral", MOTIVO_PDF_MAIOR.format(
            qtd_pdf=qtd_pdf.normalize(),
            qtd_sis=item.quantidade_estimada.normalize(),
            cod=cod,
        ))

    print("C) PDF homologa menos que o cadastrado -> parcial")
    for pk, cod, qtd, vu in PARCIAIS:
        item = ItemPCA.objects.get(pk=pk)
        assert item.status_aprovacao == "pendente", (pk, item.status_aprovacao)

        if item.quantidade_solicitada is None:
            item.quantidade_solicitada = item.quantidade_estimada
        if item.valor_unitario_solicitado is None:
            item.valor_unitario_solicitado = item.valor_unitario_estimado

        assert qtd < item.quantidade_solicitada, (pk, qtd, item.quantidade_solicitada)
        assert vu == item.valor_unitario_solicitado, (pk, vu, item.valor_unitario_solicitado)

        item.quantidade_estimada = qtd
        item.valor_unitario_estimado = vu
        item.valor_total_estimado = qtd * vu
        marcar(item, "aprovada_parcial", MOTIVO_PARCIAL.format(
            qtd_pdf=qtd.normalize(),
            qtd_sis=item.quantidade_solicitada.normalize(),
            cod=cod,
        ))

print("\nintegral:", ItemPCA.objects.filter(status_aprovacao="aprovada_integral").count(),
      "| parcial:", ItemPCA.objects.filter(status_aprovacao="aprovada_parcial").count())
