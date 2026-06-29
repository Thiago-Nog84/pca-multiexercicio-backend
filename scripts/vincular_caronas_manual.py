"""
python manage.py shell -c "exec(open('scripts/vincular_caronas_manual.py', encoding='utf-8').read())"
"""
from decimal import Decimal
from apps.contratos.models import Contrato
from apps.srp.models import AtaRegistroPrecos, ARPExterna

# 1. 25017538 -> arp_origem = ARP 00034/2025
try:
    c = Contrato.objects.get(numero_contrato="25017538")
    arp = AtaRegistroPrecos.objects.get(numero_arp="00034/2025")
    c.arp_origem = arp
    c.save(update_fields=["arp_origem"])
    print("OK 25017538 -> arp_origem =", arp)
except Contrato.DoesNotExist:
    print("ERRO Contrato 25017538 nao encontrado")
except AtaRegistroPrecos.DoesNotExist:
    print("ERRO ARP 00034/2025 nao encontrada no banco")

def _get_valor(c):
    try:
        return Decimal(str(c.valor_atual or c.valor_inicial or 0))
    except Exception:
        return Decimal("0")

def _criar_arp_externa(numero_arp, orgao_nome, orgao_cnpj, objeto, contratos_numeros, reaproveitada=None):
    if reaproveitada:
        ext = reaproveitada
        print("  -> Reaproveitando ARPExterna:", ext.pk)
    else:
        c0 = Contrato.objects.get(numero_contrato=contratos_numeros[0])
        valor = _get_valor(c0)
        ext, criada = ARPExterna.objects.get_or_create(
            numero_arp_origem=numero_arp,
            orgao_gerenciador_nome=orgao_nome,
            defaults=dict(
                orgao_gerenciador_cnpj=orgao_cnpj,
                objeto=objeto,
                fornecedor_razao_social=c0.contratado_razao_social or "A identificar",
                fornecedor_cnpj_cpf=c0.contratado_cnpj_cpf or "00.000.000/0000-00",
                data_inicio_vigencia=c0.data_inicio_vigencia or c0.data_assinatura,
                data_fim_vigencia=c0.data_fim_vigencia or c0.data_assinatura,
                quantidade_autorizada=Decimal("1"),
                valor_unitario=valor,
                valor_total_autorizado=valor,
                status="ativa",
            ),
        )
        acao = "criada" if criada else "ja existia"
        print("  OK ARPExterna", numero_arp, "/", orgao_nome, "[" + acao + "] pk=" + str(ext.pk))

    for num in contratos_numeros:
        try:
            c = Contrato.objects.get(numero_contrato=num)
            c.arp_externa_origem = ext
            c.save(update_fields=["arp_externa_origem"])
            print("  OK", num, "-> arp_externa_origem pk=" + str(ext.pk))
        except Contrato.DoesNotExist:
            print("  ERRO Contrato", num, "nao encontrado")

    return ext

# 2. 25018799 -> ARP 20/2025
print("\n-- 25018799 (ARP 20/2025) --")
_criar_arp_externa(
    numero_arp="20/2025",
    orgao_nome="A identificar (ARP 20/2025)",
    orgao_cnpj="00.000.000/0000-00",
    objeto="Ata de Registro de Precos nr 20/2025 - orgao gerenciador a identificar",
    contratos_numeros=["25018799"],
)

# 3. 25018921 -> ARP 01/2025 SEAS-PI
print("\n-- 25018921 (ARP 01/2025 SEAS-PI) --")
_criar_arp_externa(
    numero_arp="01/2025",
    orgao_nome="SEAS-PI (Secretaria de Assistencia Social do Piaui)",
    orgao_cnpj="00.000.000/0000-00",
    objeto="Registro de precos para eventual aquisicao de veiculos automotores sedan - Pregao 001/2024/SASC-PI",
    contratos_numeros=["25018921"],
)

# 4. 64/2025/FMMP/PI -> ARP25CIN000024 (CIN)
print("\n-- 64/2025/FMMP/PI (ARP25CIN000024 / CIN) --")
_criar_arp_externa(
    numero_arp="ARP25CIN000024",
    orgao_nome="CIN (Conselho de Integracao Nacional)",
    orgao_cnpj="00.000.000/0000-00",
    objeto="Ata de Registro de Precos nr ARP25CIN000024 - CIN",
    contratos_numeros=["64/2025/FMMP/PI"],
)

# 5+6. 109/2025 PGJ e 2025NE00141 -> ARP 039/2024 (mesma ARPExterna)
print("\n-- 109/2025 PGJ + 2025NE00141 (ARP 039/2024) --")
ext_039 = _criar_arp_externa(
    numero_arp="039/2024",
    orgao_nome="A identificar (ARP 039/2024)",
    orgao_cnpj="00.000.000/0000-00",
    objeto="Ata de Registro de Precos nr 039/2024 - orgao gerenciador a identificar",
    contratos_numeros=["109/2025 PGJ", "2025NE00141"],
)

# Verificacao final
print("\n=== VERIFICACAO FINAL ===")
todos = ["25017538", "25018799", "25018921", "64/2025/FMMP/PI", "109/2025 PGJ", "2025NE00141"]
for num in todos:
    try:
        c = Contrato.objects.get(numero_contrato=num)
        arp_o = c.arp_origem.numero_arp if c.arp_origem else "-"
        arp_e = c.arp_externa_origem.numero_arp_origem if c.arp_externa_origem else "-"
        print(f"  {num:25s}  arp_origem={arp_o:15s}  arp_externa={arp_e}")
    except Contrato.DoesNotExist:
        print(f"  {num:25s}  NAO ENCONTRADO")
