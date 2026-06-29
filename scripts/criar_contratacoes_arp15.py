"""
Cria ContratacaoDecorrente para a NE 2025NE00392 (ARP 00015/2025).

python manage.py shell -c "exec(open('scripts/criar_contratacoes_arp15.py', encoding='utf-8').read())"
"""
from decimal import Decimal
from datetime import date
from apps.srp.models import AtaRegistroPrecos, ItemARP, ContratacaoDecorrente
from apps.core.models import UnidadeRequisitante

arp = AtaRegistroPrecos.objects.get(numero_arp="00015/2025")
print("ARP:", arp.pk, arp.numero_arp, arp.status)

# Mostra todos os itens da ARP para conferencia
print("\n-- ITENS DA ARP NO BANCO --")
itens_arp = list(ItemARP.objects.filter(arp=arp).order_by("numero_lote", "numero_item"))
for it in itens_arp:
    print(f"  pk={it.pk} lote={it.numero_lote or '-'} item={it.numero_item} "
          f"vl_unit={it.valor_unitario} qtd_reg={it.quantidade_registrada} "
          f"qtd_cont={it.quantidade_contratada}")
    print(f"    {it.descricao[:90]}")

# Dados extraidos da NE 2025NE00392 (09/04/2025)
# Matchados por valor_unitario (unico por item nesta ARP)
ne_itens = [
    {"vl": Decimal("21.50"),  "qtd": Decimal("80"),    "desc": "Garrafa 500ml"},
    {"vl": Decimal("24.70"),  "qtd": Decimal("90"),    "desc": "Garrafa 1L"},
    {"vl": Decimal("74.00"),  "qtd": Decimal("15"),    "desc": "Garrafa 1.8L inox"},
    {"vl": Decimal("3.00"),   "qtd": Decimal("160"),   "desc": "Coador papel 103"},
    {"vl": Decimal("6.80"),   "qtd": Decimal("15"),    "desc": "Coador tecido"},
    {"vl": Decimal("4.60"),   "qtd": Decimal("500"),   "desc": "Biscoito"},
    {"vl": Decimal("7.30"),   "qtd": Decimal("55"),    "desc": "Adocante"},
    {"vl": Decimal("3.80"),   "qtd": Decimal("4000"),  "desc": "Acucar cristal"},
    {"vl": Decimal("10.30"),  "qtd": Decimal("12000"), "desc": "Cafe em po 250g"},
    {"vl": Decimal("20.70"),  "qtd": Decimal("250"),   "desc": "Cappuccino 400g"},
]

# Unidade requisitante
try:
    unidade = UnidadeRequisitante.objects.get(sigla="CAA")
    print("\nUnidade requisitante:", unidade)
except UnidadeRequisitante.DoesNotExist:
    unidade = None
    print("\nATENCAO: unidade CAA nao encontrada — ContratacaoDecorrente sera criada sem unidade")

# Indexa itens da ARP por valor_unitario
idx_arp = {}
for it in itens_arp:
    vl = it.valor_unitario.quantize(Decimal("0.01"))
    if vl in idx_arp:
        print(f"  AVISO: dois itens com mesmo valor_unitario={vl} — usando o primeiro")
    else:
        idx_arp[vl] = it

print("\n-- PREVIEW ContratacaoDecorrente a criar --")
erros = []
matches = []
for ni in ne_itens:
    vl = ni["vl"]
    it = idx_arp.get(vl)
    if it is None:
        erros.append(f"  ERRO: nenhum ItemARP com valor_unitario={vl} ({ni['desc']})")
        continue
    vl_total = (vl * ni["qtd"]).quantize(Decimal("0.01"))
    print(f"  [{ni['desc']}] ItemARP pk={it.pk} | qtd={ni['qtd']} x R${vl} = R${vl_total}")
    matches.append((it, ni["qtd"], vl, vl_total))

for e in erros:
    print(e)

if erros:
    print("\nHa erros — nenhuma ContratacaoDecorrente criada. Resolva os erros acima.")
else:
    print("\nCriando ContratacaoDecorrente...")
    ja_existe = ContratacaoDecorrente.objects.filter(
        arp=arp, numero_pedido="2025NE00392"
    ).exists()
    if ja_existe:
        print("  AVISO: ja existem registros com numero_pedido=2025NE00392. Pulando.")
    else:
        from django.db.models import F

        # bulk_create pula full_clean() do ItemARP (que exige unidade_fornecimento)
        cd_objects = [
            ContratacaoDecorrente(
                arp=arp,
                item_arp=it,
                numero_pedido="2025NE00392",
                numero_sei="19.21.0428.0000510/2025-66",
                exercicio=2025,
                quantidade=qtd,
                valor_unitario=vl_unit,
                valor_total=vl_total,
                data_emissao=date(2025, 4, 9),
                status="concluido",
                unidade_requisitante=unidade,
            )
            for it, qtd, vl_unit, vl_total in matches
        ]
        criados = ContratacaoDecorrente.objects.bulk_create(cd_objects)
        print(f"  {len(criados)} ContratacaoDecorrente criadas")

        # Atualiza quantidade_contratada em cada ItemARP via UPDATE direto
        for it, qtd, vl_unit, vl_total in matches:
            ItemARP.objects.filter(pk=it.pk).update(
                quantidade_contratada=F("quantidade_contratada") + qtd
            )
            print(f"  ItemARP pk={it.pk} item={it.numero_item}: +{qtd} contratada")

        print("\n-- VERIFICACAO FINAL --")
        for it in ItemARP.objects.filter(arp=arp).order_by("numero_lote", "numero_item"):
            print(f"  item={it.numero_item} qtd_reg={it.quantidade_registrada} "
                  f"qtd_cont={it.quantidade_contratada} "
                  f"saldo={it.quantidade_disponivel}")
