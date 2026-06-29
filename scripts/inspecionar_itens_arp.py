from apps.srp.models import AtaRegistroPrecos, ItemARP, ContratacaoDecorrente
from apps.contratos.models import Contrato

arps_inspecionar = [
    '00014/2025', '00027/2025', '00039/2025',
    '00040/2025', '00045/2025', '00015/2025',
]

for num in arps_inspecionar:
    try:
        a = AtaRegistroPrecos.objects.get(numero_arp=num)
    except AtaRegistroPrecos.DoesNotExist:
        print(f'ARP {num} nao encontrada')
        continue

    itens = list(ItemARP.objects.filter(arp=a).order_by('numero_item'))
    contratos = list(Contrato.objects.filter(arp_origem=a))
    print(f'\n=== ARP {num} ({len(itens)} itens, {len(contratos)} contratos) ===')
    for i in itens:
        print(f'  item={i.numero_item} vl_unit={i.valor_unitario} qtd_reg={i.quantidade_registrada} qtd_cont={i.quantidade_contratada}')
        print(f'    {(i.descricao or "")[:90]}')
    print('  Contratos vinculados:')
    for c in contratos:
        valor = c.valor_atual or c.valor_inicial or 0
        print(f'    {c.numero_contrato:30s} valor={valor} | {(c.objeto or "")[:60]}')
