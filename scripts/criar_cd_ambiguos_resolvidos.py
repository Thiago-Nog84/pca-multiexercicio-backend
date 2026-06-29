"""
Cria ContratacaoDecorrente para contratos ambiguos resolvidos matematicamente.

Cada entrada foi verificada: sum(qtd_i * vl_unit_i) == valor_contrato (centavo a centavo).

python manage.py shell -c "exec(open('scripts/criar_cd_ambiguos_resolvidos.py', encoding='utf-8').read())"
"""
from decimal import Decimal
from django.db.models import F
from apps.srp.models import AtaRegistroPrecos, ItemARP, ContratacaoDecorrente
from apps.contratos.models import Contrato

# Cada entrada: (numero_arp, numero_contrato, [(numero_item, quantidade)])
RESOLUCOES = [
    # ARP 00027/2025 — 200 all-in-one + 198 notebooks
    # 200 * 6130.00 + 198 * 6207.00 = 2.454.986,00 ✓
    ("00027/2025", "71/2025/FPDC", [
        (1, Decimal("200")),
        (2, Decimal("198")),
    ]),

    # ARP 00039/2025 — frigobares + refrigerador
    # 20 * 1215.23 + 4 * 2244.00 = 33.280,60 ✓
    ("00039/2025", "15/2026/FPDC", [
        (11, Decimal("20")),
        (12, Decimal("4")),
    ]),

    # ARP 00040/2025 — bebedouros + purificadores
    # 32 * 695.73 + 3 * 956.37 = 25.132,47 ✓
    ("00040/2025", "10/2026/FPDC", [
        (13, Decimal("32")),
        (14, Decimal("3")),
    ]),

    # ARP 00045/2025 — filtro de linha
    # 100 * 98.44 = 9.844,00 ✓
    ("00045/2025", "21/2026/FMMP/PI", [
        (9, Decimal("100")),
    ]),

    # ARP 00045/2025 — 100 estabilizadores + 100 filtros de linha
    # 100 * 286.00 + 100 * 98.44 = 38.444,00 ✓
    ("00045/2025", "112/2025/FMMP/PI", [
        (8, Decimal("100")),
        (9, Decimal("100")),
    ]),
]

criados_total = 0
erros = []

for numero_arp, numero_contrato, itens_qtd in RESOLUCOES:
    print(f"\n=== {numero_contrato} -> ARP {numero_arp} ===")

    try:
        arp = AtaRegistroPrecos.objects.get(numero_arp=numero_arp)
    except AtaRegistroPrecos.DoesNotExist:
        erros.append(f"ARP {numero_arp} nao encontrada")
        continue

    try:
        contrato = Contrato.objects.get(numero_contrato=numero_contrato)
    except Contrato.DoesNotExist:
        erros.append(f"Contrato {numero_contrato} nao encontrado")
        continue

    exercicio = contrato.data_assinatura.year if contrato.data_assinatura else 2025
    data_emissao = contrato.data_assinatura or arp.data_inicio_vigencia

    cd_objects = []
    item_updates = []

    for numero_item, qtd in itens_qtd:
        try:
            item = ItemARP.objects.get(arp=arp, numero_item=numero_item)
        except ItemARP.DoesNotExist:
            erros.append(f"  ItemARP {numero_item} da ARP {numero_arp} nao encontrado")
            continue

        if ContratacaoDecorrente.objects.filter(arp=arp, numero_pedido=numero_contrato, item_arp=item).exists():
            print(f"  [JA EXISTE] item={numero_item} qtd={qtd} — pulando")
            continue

        vl_total = (qtd * item.valor_unitario).quantize(Decimal("0.01"))
        print(f"  item={numero_item} qtd={qtd} x R${item.valor_unitario} = R${vl_total}")
        print(f"    {(item.descricao or '')[:80]}")

        cd_objects.append(ContratacaoDecorrente(
            arp=arp,
            item_arp=item,
            numero_pedido=numero_contrato,
            numero_sei="",
            exercicio=exercicio,
            quantidade=qtd,
            valor_unitario=item.valor_unitario,
            valor_total=vl_total,
            data_emissao=data_emissao,
            status="concluido",
            unidade_requisitante=contrato.unidade_requisitante,
        ))
        item_updates.append((item, qtd))

    if cd_objects:
        ContratacaoDecorrente.objects.bulk_create(cd_objects)
        for item, qtd in item_updates:
            ItemARP.objects.filter(pk=item.pk).update(
                quantidade_contratada=F("quantidade_contratada") + qtd
            )
        criados_total += len(cd_objects)
        print(f"  -> {len(cd_objects)} CD(s) criadas")

print(f"\n{'='*50}")
print(f"Total criado: {criados_total} ContratacaoDecorrente")
if erros:
    print("\nERROS:")
    for e in erros:
        print(f"  {e}")

# Verificacao
print("\n=== VERIFICACAO ===")
for numero_arp, numero_contrato, itens_qtd in RESOLUCOES:
    try:
        arp = AtaRegistroPrecos.objects.get(numero_arp=numero_arp)
        for numero_item, _ in itens_qtd:
            item = ItemARP.objects.get(arp=arp, numero_item=numero_item)
            print(f"  ARP {numero_arp} item={numero_item}: qtd_cont={item.quantidade_contratada} / {item.quantidade_registrada}")
    except Exception:
        pass
