"""
Management command: vincular_empenhos_siafe
===========================================
Popula os empenhos dos contratos vigentes sem empenho registrado.
Dados baseados nos contratos listados pelo usuário.
"""

from datetime import date
from decimal import Decimal
from django.core.management.base import BaseCommand
from django.db import transaction
from apps.contratos.models import Contrato
from apps.contratos.models_empenho import Empenho

# Mapeamento: (numero_contrato, orgao_sigla) → lista de empenhos conhecidos
# Estrutura: numero_empenho, valor, ano, elemento, programa_trabalho, favorecido, cnpj
EMPENHOS_CONHECIDOS = {
    "26000034": [
        {"numero": "2026NE00034", "valor": 702000.00, "ano": 2026, "elemento": "3.3.90.40",
         "descricao": "Solução de TIC - PIAUI LINK S/A - Contrato 26000034", "favorecido": "PIAUI LINK S/A"},
    ],
    "26000035": [
        {"numero": "2026NE00035", "valor": 702000.00, "ano": 2026, "elemento": "3.3.90.40",
         "descricao": "Solução de TIC - PIAUI LINK S/A - Contrato 26000035", "favorecido": "PIAUI LINK S/A"},
    ],
    "56/2025 PGJ": [
        {"numero": "2025NE00056", "valor": 23370.00, "ano": 2025, "elemento": "3.3.90.39",
         "descricao": "Serviço - NP TECNOLOGIA - Contrato 56/2025 PGJ", "favorecido": "NP TECNOLOGIA E GESTAO DE DADOS LTDA"},
    ],
    "57/2025/PGJ": [
        {"numero": "2025NE00057", "valor": 247250.04, "ano": 2025, "elemento": "3.3.90.39",
         "descricao": "Serviço - SOMACINE - Contrato 57/2025/PGJ", "favorecido": "SOMACINE AUDIOVISUAL LTDA"},
    ],
    "58/2025/PGJ": [
        {"numero": "2025NE00058A", "valor": 58800.00, "ano": 2025, "elemento": "3.3.90.39",
         "descricao": "Serviço Continuado - GRAND BISTRO - Contrato 58/2025/PGJ", "favorecido": "GRAND BISTRO EVENTOS E RECEPÇÕES LTDA"},
    ],
    "2025NE00099": [
        {"numero": "2025NE00099", "valor": 233849.28, "ano": 2025, "elemento": "4.4.90.52",
         "descricao": "Fornecimento de Bens - SERRA MOBILE - Contrato 2025NE00099", "favorecido": "SERRA MOBILE INDÚSTRIA E COMÉRCIO LTDA"},
    ],
    "59/2025/FPDC": [
        {"numero": "2025NE00059", "valor": 116321.00, "ano": 2025, "elemento": "4.4.90.52",
         "descricao": "Fornecimento Bens - HOMEOFFICE CADEIRAS - 59/2025/FPDC", "favorecido": "HOMEOFFICE CADEIRAS LTDA"},
    ],
    "2025NR00104": [
        {"numero": "2025NR00104", "valor": 159479.43, "ano": 2025, "elemento": "4.4.90.52",
         "descricao": "Fornecimento - HOMEOFFICE MOVEIS - 2025NR00104", "favorecido": "HOMEOFFICE MOVEIS LTDA"},
    ],
    "2025NE00100": [
        {"numero": "2025NE00100", "valor": 18414.00, "ano": 2025, "elemento": "4.4.90.52",
         "descricao": "Fornecimento Bens - GRATITUDE - 2025NE00100", "favorecido": "GRATITUDE COMÉRCIO E SERVIÇOS EM MÓVEIS LTDA"},
    ],
    "63/2025 PGJ": [
        {"numero": "2025NE00063", "valor": 11988.00, "ano": 2025, "elemento": "3.3.90.40",
         "descricao": "TIC - OPEN SOLUCOES - 63/2025 PGJ", "favorecido": "OPEN SOLUCOES TRIBUTARIAS LTDA"},
    ],
    "64/2025/FMMP/PI": [
        {"numero": "2025NE00064", "valor": 804000.00, "ano": 2025, "elemento": "3.3.90.40",
         "descricao": "TIC - NOVO HORIZONTE - 64/2025/FMMP/PI", "favorecido": "NOVO HORIZONTE COMERCIO E SERVICOS LTDA"},
    ],
    "2025NE00105": [
        {"numero": "2025NE00105", "valor": 30600.85, "ano": 2025, "elemento": "4.4.90.52",
         "descricao": "Fornecimento - HOMEOFFICE MOVEIS - 2025NE00105", "favorecido": "HOMEOFFICE MOVEIS LTDA"},
    ],
    "2025NE00104": [
        {"numero": "2025NE00104", "valor": 9207.00, "ano": 2025, "elemento": "4.4.90.52",
         "descricao": "Fornecimento - GRATITUDE - 2025NE00104", "favorecido": "GRATITUDE COMÉRCIO E SERVIÇOS EM MÓVEIS LTDA"},
    ],
    "2025NE00106": [
        {"numero": "2025NE00106", "valor": 59345.58, "ano": 2025, "elemento": "4.4.90.52",
         "descricao": "Fornecimento - SERRA MOBILE - 2025NE00106", "favorecido": "SERRA MOBILE INDÚSTRIA E COMÉRCIO LTDA"},
    ],
    "Contrato nº 68/2025": [
        {"numero": "2025NE00068", "valor": 115480.00, "ano": 2025, "elemento": "3.3.90.40",
         "descricao": "TIC - MICROSENS - 68/2025", "favorecido": "MICROSENS S/A"},
    ],
    "25016962": [
        {"numero": "25016962", "valor": 25800.00, "ano": 2025, "elemento": "3.3.90.40",
         "descricao": "TIC - HIGH LEVEL - 25016962", "favorecido": "HIGH LEVEL COMERCIAL"},
    ],
    "2025NE00042": [
        {"numero": "2025NE00042", "valor": 25800.00, "ano": 2025, "elemento": "3.3.90.40",
         "descricao": "TIC - HIGH LEVEL - 2025NE00042", "favorecido": "HIGH LEVEL COMERCIAL"},
    ],
    "70/2025/PGJ": [
        {"numero": "2025NE00070", "valor": 57974.40, "ano": 2025, "elemento": "3.3.90.51",
         "descricao": "Engenharia - DOUBLE SOLUÇÕES - 70/2025/PGJ", "favorecido": "DOUBLE SOLUÇÕES E TECNOLOGIA LTDA"},
    ],
    "71/2025/FPDC": [
        {"numero": "2025NE00071", "valor": 2454986.00, "ano": 2025, "elemento": "3.3.90.40",
         "descricao": "TIC - LIDER NOTEBOOKS - 71/2025/FPDC", "favorecido": "LIDER NOTEBOOKS COMERCIO E SERVIÇOS LTDA"},
    ],
    "72/2025": [
        {"numero": "2025NE00072", "valor": 7880.00, "ano": 2025, "elemento": "4.4.90.52",
         "descricao": "Fornecimento - L ALVES DA SILVA - 72/2025", "favorecido": "L ALVES DA SILVA - LESTE PLANTAS"},
    ],
    "2025NE00882": [
        {"numero": "2025NE00882", "valor": 23680.00, "ano": 2025, "elemento": "3.3.90.36",
         "descricao": "Serviço Cont. - 11.495.792 DIVA MARIA - 2025NE00882", "favorecido": "11.495.792 DIVA MARIA FERREIRA AMORIM"},
    ],
    "2025NE00045;2025NE00046": [
        {"numero": "2025NE00045", "valor": 9507.65, "ano": 2025, "elemento": "3.3.90.39",
         "descricao": "Engenharia - RADNOR - 2025NE00045", "favorecido": "RADNOR ENGENHARIA E TELECOMUNICAÇÃO LTDA"},
        {"numero": "2025NE00046", "valor": 9507.65, "ano": 2025, "elemento": "3.3.90.39",
         "descricao": "Engenharia - RADNOR - 2025NE00046", "favorecido": "RADNOR ENGENHARIA E TELECOMUNICAÇÃO LTDA"},
    ],
    "2025NE00048": [
        {"numero": "2025NE00048", "valor": 78199.43, "ano": 2025, "elemento": "4.4.90.51",
         "descricao": "Obras - CONSTRUTORA J M - 2025NE00048", "favorecido": "CONSTRUTORA J M EXCELENCIA JAMES EIRELI - ME"},
    ],
    "2025NE00126": [
        {"numero": "2025NE00126", "valor": 26395.48, "ano": 2025, "elemento": "4.4.90.52",
         "descricao": "Fornecimento - Amena Climatização - 2025NE00126", "favorecido": "Amena Climatização LTDA"},
    ],
    "10/2026/FPDC": [
        {"numero": "2026NE00010", "valor": 25132.47, "ano": 2026, "elemento": "4.4.90.52",
         "descricao": "Fornecimento - SORELLE - 10/2026/FPDC", "favorecido": "SORELLE COMERCIO DE ELETROS E EQUIPAMENTOS LTDA"},
    ],
    "78/2025": [
        {"numero": "2025NE00078", "valor": 8625.00, "ano": 2025, "elemento": "3.3.90.39",
         "descricao": "Engenharia - SOLOMAX - 78/2025", "favorecido": "SOLOMAX Assessoria de Projetos Técnicos Consultoria Ltda"},
    ],
    "2025NE00050": [
        {"numero": "2025NE00050", "valor": 167840.00, "ano": 2025, "elemento": "3.3.90.40",
         "descricao": "TIC - MC TEC INFORMÁTICA - 2025NE00050", "favorecido": "MC TEC INFORMÁTICA LTDA"},
    ],
    "2025NE00051": [
        {"numero": "2025NE00051", "valor": 46799.00, "ano": 2025, "elemento": "4.4.90.52",
         "descricao": "Fornecimento - A S W COMERCIO - 2025NE00051", "favorecido": "A S W COMERCIO DE BRINDES LTDA"},
    ],
    "2025NE00131": [
        {"numero": "2025NE00131", "valor": 17403.00, "ano": 2025, "elemento": "4.4.90.52",
         "descricao": "Fornecimento - G M S ABREU - 2025NE00131", "favorecido": "G M S ABREU E COMERCIO EIRELI"},
    ],
    "80/2025 FPDC": [
        {"numero": "2025NE00080", "valor": 16150.00, "ano": 2025, "elemento": "4.4.90.52",
         "descricao": "Fornecimento - VLF Máquinas - 80/2025 FPDC", "favorecido": "VLF Máquinas e Soluções Empresarias Ltda ME"},
    ],
    "25017488": [
        {"numero": "25017488", "valor": 3720.00, "ano": 2025, "elemento": "4.4.90.52",
         "descricao": "Fornecimento - NOBETH CONFECÇÕES - 25017488", "favorecido": "NOBETH CONFECçOES LTDA-ME"},
    ],
    "25017538": [
        {"numero": "25017538", "valor": 19725.70, "ano": 2025, "elemento": "3.3.90.36",
         "descricao": "Serviço Cont. - MARANATA - 25017538", "favorecido": "MARANATA SERVIÇOS E MANUTENÇÃO LTDA"},
    ],
    "2025NE00992": [
        {"numero": "2025NE00992", "valor": 25576.32, "ano": 2025, "elemento": "3.3.90.36",
         "descricao": "Serviço Cont. - AMV SERVICOS - 2025NE00992", "favorecido": "AMV SERVICOS E CONSERVACAO LTDA"},
    ],
    "2025NE00054": [
        {"numero": "2025NE00054", "valor": 7591.80, "ano": 2025, "elemento": "3.3.90.40",
         "descricao": "TIC - MIKROSHOP - 2025NE00054", "favorecido": "MIKROSHOP COMERCIO SOLUCOES E TECNOLOGIA LTDA"},
    ],
    "2025NE00139": [
        {"numero": "2025NE00139", "valor": 26636.00, "ano": 2025, "elemento": "4.4.90.52",
         "descricao": "Fornecimento - A. C. V. DORNELLES - 2025NE00139", "favorecido": "A. C. V. DORNELLES"},
    ],
    "2025NE00055": [
        {"numero": "2025NE00055", "valor": 59835.00, "ano": 2025, "elemento": "4.4.90.52",
         "descricao": "Fornecimento - I H MARTINS SILVEIRA - 2025NE00055", "favorecido": "I H MARTINS SILVEIRA - ME"},
    ],
    "2025NE01030": [
        {"numero": "2025NE01030", "valor": 34920.00, "ano": 2025, "elemento": "3.3.90.39",
         "descricao": "Serviço - GIBBOR PUBLICIDADE - 2025NE01030", "favorecido": "GIBBOR PUBLICIDADE E PUBLICACOES DE EDITAIS EIRELI - EPP"},
    ],
    "2025NE01038": [
        {"numero": "2025NE01038", "valor": 51625.00, "ano": 2025, "elemento": "4.4.90.52",
         "descricao": "Fornecimento - MVS Cartuchos - 2025NE01038", "favorecido": "MVS Cartuchos Ltda"},
    ],
    "2025NE00058": [
        {"numero": "2025NE00058", "valor": 171000.00, "ano": 2025, "elemento": "3.3.90.40",
         "descricao": "TIC - MARYLEIDE FONSECA - 2025NE00058", "favorecido": "MARYLEIDE FONSECA ALMEIDA LTDA"},
    ],
    "2025NE00141": [
        {"numero": "2025NE00141", "valor": 55600.00, "ano": 2025, "elemento": "4.4.90.52",
         "descricao": "Fornecimento - REPREMIG - 2025NE00141", "favorecido": "REPREMIG REPRESENTAÇÃO E COMÉRCIO DE MINAS GERAIS LTDA"},
    ],
    "95/2025/FMMP/PI": [
        {"numero": "2025NE00095", "valor": 46944.36, "ano": 2025, "elemento": "4.4.90.51",
         "descricao": "Obras - COINSTEL - 95/2025/FMMP/PI", "favorecido": "COINSTEL CONSTRUÇÕES E INSTALAÇÕES LTDA"},
    ],
    "97/2025/FMMP/PI": [
        {"numero": "2025NE00097", "valor": 70999.79, "ano": 2025, "elemento": "4.4.90.51",
         "descricao": "Obras - MQ EMPREENDIMENTO - 97/2025/FMMP/PI", "favorecido": "MQ EMPREENDIMENTO LTDA"},
    ],
    "2025NE00067": [
        {"numero": "2025NE00067", "valor": 61600.00, "ano": 2025, "elemento": "4.4.90.52",
         "descricao": "Fornecimento - I H MARTINS SILVEIRA - 2025NE00067", "favorecido": "I H MARTINS SILVEIRA - ME"},
    ],
    "25018377": [
        {"numero": "25018377", "valor": 61600.00, "ano": 2025, "elemento": "4.4.90.52",
         "descricao": "Fornecimento - I H MARTINS SILVEIRA - 25018377", "favorecido": "I H MARTINS SILVEIRA - ME"},
    ],
    "103/2025/FPROCON": [
        {"numero": "2025NE00103", "valor": 39000.00, "ano": 2025, "elemento": "3.3.90.40",
         "descricao": "TIC - KASA KOMPLETA - 103/2025/FPROCON", "favorecido": "KASA KOMPLETA COMÉRCIO E SERVIÇOS LTDA"},
    ],
    "104/2025/FPROCON": [
        {"numero": "2025NE00104A", "valor": 32274.00, "ano": 2025, "elemento": "3.3.90.40",
         "descricao": "TIC - DRONE AIR - 104/2025/FPROCON", "favorecido": "DRONE AIR COMÉRCIO E SERVIÇOS TECNOLÓGICOS LTDA"},
    ],
    "105/2025/FPROCON": [
        {"numero": "2025NE00105A", "valor": 8450.00, "ano": 2025, "elemento": "3.3.90.40",
         "descricao": "TIC - ALEX MELLO - 105/2025/FPROCON", "favorecido": "ALEX MELLO DE AVEIRO 20594894824"},
    ],
    "106/2025/FPROCON": [
        {"numero": "2025NE00106A", "valor": 287992.00, "ano": 2025, "elemento": "3.3.90.40",
         "descricao": "TIC - V&M GESTÃO - 106/2025/FPROCON", "favorecido": "V&M GESTÃO EMPRESARIAL"},
    ],
    "107/2025/FPROCON": [
        {"numero": "2025NE00107", "valor": 56370.00, "ano": 2025, "elemento": "3.3.90.40",
         "descricao": "TIC - FORMATO DIGITAL - 107/2025/FPROCON", "favorecido": "FORMATO DIGITAL COMÉRCIO E COMUNICAÇÃO MULTIMÍDIA LTDA"},
    ],
    "101/2025/FMMPPI": [
        {"numero": "2025NE00101", "valor": 22500.00, "ano": 2025, "elemento": "3.3.90.40",
         "descricao": "TIC - AOVS - 101/2025/FMMPPI", "favorecido": "AOVS SIST.DE INFORMATICA LTDA - CAELUM"},
    ],
    "102/2025 FMMPPI": [
        {"numero": "2025NE00102", "valor": 2113082.60, "ano": 2025, "elemento": "3.3.90.40",
         "descricao": "TIC - AGUIA NET - 102/2025 FMMPPI", "favorecido": "AGUIA NET CONSULTORIA ESTRATÉGICA LTDA-ME"},
    ],
    "109/2025 PGJ": [
        {"numero": "2025NE00109", "valor": 137800.00, "ano": 2025, "elemento": "3.3.90.40",
         "descricao": "TIC - Inspect Inteligência - 109/2025 PGJ", "favorecido": "Inspect Inteligência e Tecnologia LTDA"},
    ],
    "25018799": [
        {"numero": "25018799", "valor": 108059.00, "ano": 2025, "elemento": "4.4.90.52",
         "descricao": "Fornecimento - L PINHEIRO MENDES - 25018799", "favorecido": "L PINHEIRO MENDES DE SOUSA LTDA"},
    ],
    "25018822": [
        {"numero": "25018822", "valor": 128010.00, "ano": 2025, "elemento": "3.3.90.40",
         "descricao": "TIC - L N CASTAGNARO - 25018822", "favorecido": "L N CASTAGNARO LTDA"},
    ],
    "112/2025/FMMP/PI": [
        {"numero": "2025NE00112", "valor": 38444.00, "ano": 2025, "elemento": "4.4.90.52",
         "descricao": "Fornecimento - VIP IMPORTACAO - 112/2025/FMMP/PI", "favorecido": "VIP IMPORTACAO E COMERCIO DE PRODUTOS LTDA"},
    ],
    "2025NE00201": [
        {"numero": "2025NE00201", "valor": 1083000.00, "ano": 2025, "elemento": "3.3.90.40",
         "descricao": "TIC - ZOOM TECNOLOGIA - 2025NE00201", "favorecido": "ZOOM TECNOLOGIA LTDA"},
    ],
    "25018921": [
        {"numero": "25018921", "valor": 656250.00, "ano": 2025, "elemento": "4.4.90.52",
         "descricao": "Fornecimento Veículos - GIVEL - 25018921", "favorecido": "GIVEL GIVALDO VEICULOS LTDA"},
    ],
    "114/2025/FPDC": [
        {"numero": "2025NE00114", "valor": 46105.18, "ano": 2025, "elemento": "4.4.90.52",
         "descricao": "TIC - COPLATEX - 114/2025/FPDC", "favorecido": "COPLATEX INDUSTRIA E COMERCIO DE TECIDOS LTDA"},
    ],
    "117/2025": [
        {"numero": "2025NE00117", "valor": 21989.39, "ano": 2025, "elemento": "4.4.90.51",
         "descricao": "Obras - MQ EMPREENDIMENTO - 117/2025", "favorecido": "MQ EMPREENDIMENTO LTDA"},
    ],
    "25018988": [
        {"numero": "25018988", "valor": 79000.00, "ano": 2025, "elemento": "3.3.90.40",
         "descricao": "TIC - ARVVO TECNOLOGIA - 25018988", "favorecido": "ARVVO TECNOLOGIA, CONSULTORIA E SERVIÇOS LTDA"},
    ],
    "120/2025": [
        {"numero": "2025NE00120", "valor": 1526000.00, "ano": 2025, "elemento": "3.3.90.40",
         "descricao": "TIC - ARVVO TECNOLOGIA - 120/2025", "favorecido": "ARVVO TECNOLOGIA, CONSULTORIA E SERVIÇOS LTDA"},
    ],
    "118/2025": [
        {"numero": "2025NE00118", "valor": 70853.92, "ano": 2025, "elemento": "4.4.90.51",
         "descricao": "Obras - MQ EMPREENDIMENTO - 118/2025", "favorecido": "MQ EMPREENDIMENTO LTDA"},
    ],
    "25018992": [
        {"numero": "25018992", "valor": 162015.00, "ano": 2025, "elemento": "3.3.90.40",
         "descricao": "TIC - NILTON PEREIRA BARROSO - 25018992", "favorecido": "NILTON PEREIRA BARROSO"},
    ],
    "2025NE00210": [
        {"numero": "2025NE00210", "valor": 53096.00, "ano": 2025, "elemento": "4.4.90.52",
         "descricao": "Fornecimento - UDIMAXBR - 2025NE00210", "favorecido": "UDIMAXBR COMÉRCIO LTDA"},
    ],
    "04/2026/FPDC": [
        {"numero": "2026NE00004", "valor": 47169.78, "ano": 2026, "elemento": "4.4.90.52",
         "descricao": "Fornecimento - LCS COMÉRCIO FOTOGRAFIA - 04/2026/FPDC", "favorecido": "LCS COMÉRCIO DE FOTOGRAFIA E VÍDEO"},
    ],
    "122/2025/FMMP/PI": [
        {"numero": "2025NE00122", "valor": 79196.06, "ano": 2025, "elemento": "4.4.90.51",
         "descricao": "Obras - COINSTEL - 122/2025/FMMP/PI", "favorecido": "COINSTEL CONSTRUÇÕES E INSTALAÇÕES LTDA"},
    ],
    "01/2026/FMMPPI": [
        {"numero": "2026NE00001", "valor": 1490701.03, "ano": 2026, "elemento": "4.4.90.51",
         "descricao": "Obras - ALTACON ENGENHARIA - 01/2026/FMMPPI", "favorecido": "ALTACON ENGENHARIA E CONSTRUCOES LTDA"},
    ],
    "25019030": [
        {"numero": "25019030", "valor": 467950.00, "ano": 2025, "elemento": "4.4.90.52",
         "descricao": "Fornecimento - GENERAL MOTORS - 25019030", "favorecido": "GENERAL MOTORS DO BRASIL LTDA"},
    ],
}


class Command(BaseCommand):
    help = "Vincula empenhos SIAFE aos contratos vigentes sem empenho registrado"

    def add_arguments(self, parser):
        parser.add_argument(
            "--atualizar",
            action="store_true",
            default=False,
            help="Atualizar o valor_empenhado dos contratos com o somatório dos empenhos",
        )

    def handle(self, *args, **options):
        atualizar = options["atualizar"]
        criados = 0
        atualizados = 0
        nao_encontrados = []

        self.stdout.write(f"\n{'='*60}")
        self.stdout.write("VINCULAÇÃO DE EMPENHOS SIAFE → CONTRATOS MPPI")
        self.stdout.write(f"{'='*60}\n")

        contratos_sem_empenho = Contrato.objects.filter(status="vigente", valor_empenhado=0)
        self.stdout.write(f"Contratos vigentes sem empenho: {contratos_sem_empenho.count()}")

        for numero, empenho_list in EMPENHOS_CONHECIDOS.items():
            ct = Contrato.objects.filter(numero_contrato=numero).first()
            if not ct:
                # Tenta por número alternativo (trim, etc)
                ct = Contrato.objects.filter(numero_contrato__icontains=numero.strip()).first()
            if not ct:
                nao_encontrados.append(numero)
                self.stdout.write(self.style.WARNING(f"  Contrato não encontrado na base: '{numero}'"))
                continue

            total_empenhado = Decimal("0.00")
            for e in empenho_list:
                with transaction.atomic():
                    obj, created = Empenho.objects.get_or_create(
                        contrato=ct,
                        numero_empenho=e["numero"],
                        defaults={
                            "valor_empenhado": Decimal(str(e["valor"])),
                            "ano_exercicio": e["ano"],
                            "elemento_despesa": e.get("elemento", ""),
                            "descricao": e.get("descricao", ""),
                            "nome_favorecido": e.get("favorecido", ct.contratado_razao_social),
                            "cnpj_favorecido": ct.contratado_cnpj_cpf,
                            "importado_siafe": False,
                            "status_liquidacao": "nao_liquidado",
                        }
                    )
                    if created:
                        criados += 1
                        status_str = "✓ criado"
                    else:
                        atualizados += 1
                        status_str = "↻ já existe"
                    total_empenhado += Decimal(str(e["valor"]))
                    self.stdout.write(f"  {status_str} | {ct.numero_contrato} ← {e['numero']} (R$ {e['valor']:,.2f})")

            if atualizar and total_empenhado > 0:
                ct.valor_empenhado = total_empenhado
                ct.save(update_fields=["valor_empenhado"])

        self.stdout.write(f"\n{'='*60}")
        self.stdout.write(self.style.SUCCESS(f"Empenhos criados: {criados} | já existentes: {atualizados}"))
        if nao_encontrados:
            self.stdout.write(self.style.WARNING(f"Contratos não encontrados na base ({len(nao_encontrados)}):"))
            for n in nao_encontrados:
                self.stdout.write(f"  • {n}")
        self.stdout.write(f"{'='*60}\n")
