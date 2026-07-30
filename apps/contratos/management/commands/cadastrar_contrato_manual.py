"""
Management command: cadastrar_contrato_manual
====================================================
Cadastra contratos confirmados via documento fonte (SEI/PNCP/SIAFE) que
foram achados como genuinamente FALTANTES no banco local — geralmente
descobertos por uma NE do SIAFE cujo `codContrato` não bate com nenhum
`Contrato.codigo_siafe` existente (ver `investigar_ne_faltante`).

Idempotente: usa `get_or_create` por (orgao, numero_contrato) — nunca cria
duplicata se rodado de novo. Nunca atualiza um contrato já existente (se
achar, só avisa e não mexe — evita sobrescrever correções manuais feitas
depois pelo usuário).

Após cadastrar, rode `importar_empenhos_siafe --exercicio <ano>` de novo —
agora que o `codigo_siafe` bate, a NE que estava "sem contrato local" vai
ser importada automaticamente como `Empenho`.

Uso:
  python manage.py cadastrar_contrato_manual --dry-run
  python manage.py cadastrar_contrato_manual
"""

import re
from datetime import date
from decimal import Decimal

from django.core.management.base import BaseCommand

from apps.contratos.models import Contrato
from apps.core.models import Orgao
from apps.srp.models import AtaRegistroPrecos

CNPJ_MPPI = "05805924000189"


def _digitos(valor) -> str:
    return re.sub(r"\D", "", str(valor or ""))

# Cada entrada: dict completo de campos do Contrato + numero_arp_origem
# (opcional, string a buscar em AtaRegistroPrecos.numero_arp).
CONTRATOS_MANUAIS = [
    {
        # Fonte: PDF SEI 19.21.0428.0012055/2026-09 (Contrato 13/2026/PGJ,
        # pg. 26/30 — Termo de Contrato + Apêndice/Memória de Cálculo) e
        # Nota de Empenho 2026NE00165 (pg. 24) — achado via investigar_ne_faltante
        # (2026-07-29): NE com codContrato=26100672 não batia com nenhum
        # contrato local, porque este contrato nunca tinha sido cadastrado.
        "numero_contrato": "13/2026/PGJ",
        "numero_sei": "19.21.0428.0002645/2026-36",  # PGA original do contrato
        "tipo": "fornecimento",
        "objeto": (
            "Aquisição de material de higiene e limpeza para o MP-PI "
            "(copos descartáveis, limpadores, sabonetes líquidos, inseticidas, "
            "aromatizadores de ambientes, soda cáustica), conforme condições, "
            "quantidades e exigências estabelecidas no Termo de Referência e "
            "no Apêndice (Tabela 1) deste instrumento."
        ),
        "contratado_razao_social": "Laís G de Sousa – Eireli",
        "contratado_cnpj_cpf": "39.853.645/0001-02",
        "valor_inicial": Decimal("34966.00"),   # total da contratação, 24 meses (lotes 5 e 7)
        "valor_atual": Decimal("34966.00"),
        "saldo_disponivel": Decimal("12465.00"),  # "SALDO A EMPENHAR" citado no doc, pg. 53
        "valor_empenhado": Decimal("22501.00"),   # NE 2026NE00165 — valor para o exercício de 2026
        "codigo_siafe": "26100672",
        "data_assinatura": date(2026, 2, 19),
        "data_inicio_vigencia": date(2026, 2, 19),
        "data_fim_vigencia": date(2028, 2, 19),
        "unidade_orcamentaria": "pgj",
        "numero_arp_origem": "51/2025",  # ARP Nº 51/2025, Pregão Eletrônico nº 90023/2025, Lotes 05 e 07
    },
    {
        # Fonte: 4 documentos do SEI 19.21.0010.0018316/2024-04, fornecidos em
        # 2026-07-30 — Contrato (0795673), Apostilamento 01 (0953619),
        # Apostilamento 02 (1053628) e Termo Aditivo 01 (1222671).
        # Achado via sugerir_vinculo_ne_contrato: codContrato=24010263 com 2 NEs
        # de 2026 (2026NE00885 R$25.000 peças + 2026NE00886 R$100.000 serviços,
        # ambas emitidas em 28/07/2026) sem par local — este contrato nunca
        # tinha sido cadastrado. Era a última divergência acionável da PGJ na
        # conciliação com o TCE (diferença de exatamente R$125.000,00).
        #
        # HISTÓRICO DE VALOR (o contrato precisou de 2 apostilamentos para
        # corrigir um erro material de soma no instrumento original):
        #   - Contrato original (assinado 24/07/2024): texto da Cláusula
        #     Terceira dizia "R$223.042,39, sendo R$61.956,21 serviços e
        #     R$10.000,00 peças" — não fecha (61.956,21 + 10.000 = 71.956,21).
        #     O Anexo I do próprio contrato já trazia o total correto de
        #     R$259.042,39 (R$223.042,39 serviços + R$36.000,00 peças).
        #   - Apostilamento 01 (17/02/2025): corrigiu o total para R$259.042,39,
        #     mas manteve peças em R$10.000,00 — ainda não fechava.
        #   - Apostilamento 02 (10/06/2025): corrigiu peças para R$36.000,00.
        #     Só então 223.042,39 + 36.000,00 = 259.042,39 fecha.
        #   - Termo Aditivo 01 (11/12/2025): prorroga 18 meses a partir de
        #     24/01/2026 e reajusta pelo IPCA/IBGE — novo valor R$271.367,89
        #     (R$233.654,97 serviços + R$37.712,92 peças).
        #
        # valor_inicial = valor original já corrigido pelos apostilamentos
        # (que são meras correções de erro material, não alteram o objeto).
        # valor_atual = valor após o Termo Aditivo 01 (reajuste IPCA).
        "numero_contrato": "29/2024/PGJ",
        "numero_sei": "19.21.0010.0018316/2024-04",
        "tipo": "servico_continuo",
        "objeto": (
            "Contratação de empresa especializada na prestação de serviços de "
            "manutenção preventiva e corretiva COM FORNECIMENTO DE PEÇAS dos "
            "aparelhos de ar-condicionado tipo split, bebedouro, purificador de "
            "água, frigobar, geladeira, recarga de gás para split, geladeira, "
            "frigobar e bebedouro, bem como instalação, desinstalação e "
            "substituição de aparelhos de ar-condicionado (tipo split) de "
            "propriedade do MPPI, na sede da PGJ e demais órgãos, em Teresina e "
            "no interior do Estado (Lotes II, III e IV)."
        ),
        "contratado_razao_social": "EASWELL ENGENHARIA LTDA",
        "contratado_cnpj_cpf": "37.827.616/0001-40",
        "valor_inicial": Decimal("259042.39"),
        "valor_atual": Decimal("271367.89"),
        # Não há dado de execução/medição nos documentos fornecidos — o saldo
        # real depende das ordens de serviço já executadas. Registrado igual ao
        # valor_atual; ajustar quando houver a memória de execução.
        "saldo_disponivel": Decimal("271367.89"),
        # Deixado zerado de propósito: o importar_empenhos_siafe recalcula a
        # partir das NEs reais (2024NE00671, 2025NE01494/01495, 2026NE00885/00886).
        "valor_empenhado": Decimal("0.00"),
        "codigo_siafe": "24010263",
        "data_assinatura": date(2024, 7, 24),      # última assinatura eletrônica (contratada)
        "data_inicio_vigencia": date(2024, 7, 24),  # 18 meses da assinatura
        # Aditivo 01: mais 18 meses contados de 24/01/2026 -> 24/07/2027
        "data_fim_vigencia": date(2027, 7, 24),
        "unidade_orcamentaria": "pgj",
        "numero_arp_origem": "23/2023",  # ATA 23/2023, Pregão Eletrônico 28/2023, Lotes II, III e IV
    },
    {
        # Fonte: PDF SEI 19.21.0431.0018074/2025-26 (Contrato 17/2025/FMMP/PI),
        # fornecido pelo usuário em 2026-07-30. Achado via divergência no
        # conciliar_tcepi (FMMP 2025): codContrato=25014024, NE 2025NE00010,
        # R$1.198.997,67 — bate exato com o valor total do contrato.
        "numero_contrato": "17/2025/FMMP/PI",
        "numero_sei": "19.21.0431.0031890/2024-59",  # PGA citado no termo
        "tipo": "obra",
        "objeto": (
            "Contratação de empresa especializada para a execução dos serviços "
            "de implantação da sede que abrigará as Promotorias de Justiça de "
            "Barras-PI, na Rua 10 de Novembro, nº 299, Bairro Centro, Barras-PI "
            "(Concorrência Eletrônica nº 90002/2024, regime de empreitada por "
            "preço global)."
        ),
        "contratado_razao_social": "COINSTEL CONSTRUÇÕES E INSTALAÇÕES LTDA",
        "contratado_cnpj_cpf": "07.375.034/0001-00",
        "valor_inicial": Decimal("1198997.67"),
        "valor_atual": Decimal("1198997.67"),
        "saldo_disponivel": Decimal("1198997.67"),  # sem dado de medição/liquidação nos autos fornecidos
        "valor_empenhado": Decimal("0.00"),  # recalculado por importar_empenhos_siafe (NE 2025NE00010)
        "codigo_siafe": "25014024",
        "data_assinatura": date(2025, 3, 12),       # última assinatura eletrônica (contratada)
        "data_inicio_vigencia": date(2025, 3, 12),
        "data_fim_vigencia": date(2026, 9, 12),      # 18 meses da assinatura
        "unidade_orcamentaria": "fmmp",
        # Concorrência Eletrônica direta (execução de obra) — não decorre de ARP/SRP.
    },
    {
        # Fonte: PDF SEI 19.21.0431.0028803/2025-82 (Ata de Registro de Preços
        # nº 11/2024 + Contrato 12/2025/FMMP/PI), fornecido pelo usuário em
        # 2026-07-30. Achado via divergência no conciliar_tcepi (FMMP 2025):
        # codContrato=25013623, NEs 2025NE00009 (R$107.387,68) e 2025NE00076
        # (anulação parcial R$24.732,55) — líquido R$82.655,13, bate exato com
        # a divergência do TCE. Segundo contrato de cerca elétrica da RADNOR
        # com o MPPI — diferente do já cadastrado (pk=179, cercas de Buriti dos
        # Lopes e Campo Maior, codigo_siafe=25017188): este é para os imóveis
        # do MPPI na capital e interior (proteção geral), Ata 11/2024.
        "numero_contrato": "12/2025/FMMP/PI",
        "numero_sei": "19.21.0431.0000521/2025-15",  # PGA citado no termo
        "tipo": "obra",
        "objeto": (
            "Contratação de empresa especializada na aquisição e instalação de "
            "cerca elétrica destinada à proteção dos imóveis do Ministério "
            "Público do Estado do Piauí, localizados na capital e interior do "
            "estado (Pregão Eletrônico nº 90010/2024 — Ata de Registro de "
            "Preços nº 11/2024)."
        ),
        "contratado_razao_social": "RADNOR ENGENHARIA E TELECOMUNICAÇÃO LTDA – EPP",
        "contratado_cnpj_cpf": "01.252.610/0001-45",
        "valor_inicial": Decimal("107387.68"),
        "valor_atual": Decimal("107387.68"),
        "saldo_disponivel": Decimal("107387.68"),
        "valor_empenhado": Decimal("0.00"),  # recalculado por importar_empenhos_siafe (líquido de anulação = R$82.655,13)
        "codigo_siafe": "25013623",
        "data_assinatura": date(2025, 2, 12),
        "data_inicio_vigencia": date(2025, 2, 12),
        "data_fim_vigencia": date(2026, 2, 12),  # 12 meses, prorrogável por mais 1 ano
        "unidade_orcamentaria": "fmmp",
        "numero_arp_origem": "11/2024",  # Ata de Registro de Preços nº 11/2024 (PMPI)
    },
    {
        # Fonte: PDF SEI 1032399 (Contrato Nº 41/2025/FMMP/PI), fornecido pelo
        # usuário em 2026-07-30 — SUBSTITUI a hipótese anterior (baseada só na
        # Autorização de Empenho 1029968): existe sim um Termo de Contrato
        # formal, nº 41/2025/FMMP/PI, PGA 19.21.0431.0015069/2025-69. Achado
        # via divergência do TCE FMMP/2025 (codContrato=25015651, "MULTIPAR").
        # Objeto: manutenção predial CRH/GAECO/Casa da Cidadania/Sub-PJ
        # Administrativa, decorrente da Ata de Registro de Preços própria nº
        # 12/2025 (P.E. 90018/2024, Lote I — Teresina). Valor R$27.841,71 bate
        # exato com NE 2025NE00027 (13/05/25) e com a NE citada na cláusula
        # 14.1.5 do próprio contrato. NE 2025NE00063 (10/10/25) é anulação
        # parcial de R$8.549,81 ("não será necessária execução do restante do
        # objeto contratual" — Despacho SEI 1165944), líquido R$19.291,90.
        "numero_contrato": "41/2025/FMMP/PI",
        "numero_sei": "19.21.0431.0015069/2025-69",
        "tipo": "obra",
        "objeto": (
            "Contratação da empresa MULTPAR SERVIÇOS DE CONSTRUÇÃO LTDA "
            "para conservação e manutenção de edificações com aplicação de "
            "material — manutenção predial do CRH, GAECO, Casa da Cidadania "
            "e Sub-Procuradoria de Justiça Administrativa, decorrente da Ata "
            "de Registro de Preços própria nº 12/2025 (Pregão Eletrônico nº "
            "90018/2024, Lote I — Teresina)."
        ),
        "contratado_razao_social": "MULTPAR SERVIÇOS DE CONSTRUÇÃO LTDA",
        "contratado_cnpj_cpf": "22.561.863/0001-70",
        "valor_inicial": Decimal("27841.71"),
        "valor_atual": Decimal("27841.71"),
        "saldo_disponivel": Decimal("27841.71"),  # sem dado de medição além da anulação já contabilizada na NE
        "valor_empenhado": Decimal("0.00"),  # recalculado por importar_empenhos_siafe (NE00027 - anulação NE00063 = líquido R$19.291,90)
        "codigo_siafe": "25015651",
        "data_assinatura": date(2025, 5, 15),       # última assinatura eletrônica (contratada, Andreza Oliveira Pereira)
        "data_inicio_vigencia": date(2025, 5, 15),
        "data_fim_vigencia": date(2030, 5, 15),      # cláusula 2.1: 5 anos contados da assinatura
        "unidade_orcamentaria": "fmmp",
        "numero_arp_origem": "12/2025",  # Ata de Registro de Preços própria nº 12/2025 (P.E. 90018/2024)
    },
    {
        # Fonte: PDF SEI 1054268 (Contrato Nº 52/2025/FMMPPI), fornecido pelo
        # usuário em 2026-07-30 — mesmo fornecedor/ARP do contrato 41/2025
        # acima, mas 2ª aquisição (PGA 19.21.0431.0018606/2025-18) e NE
        # diferente. codigo_siafe confirmado via investigar_ne_faltante --cnpj
        # 22561863000170 --exercicio 2025 (2026-07-30): NE 2025NE00037
        # (R$25.988,25) tem codContrato=25016114, bate exato com o valor
        # total do contrato. A mesma NE 2025NE00062 (ANULACAO, R$13.279,03)
        # também tem codContrato=25016114 — anulação parcial, líquido
        # R$12.709,22.
        "numero_contrato": "52/2025/FMMPPI",
        "numero_sei": "19.21.0431.0018606/2025-18",
        "tipo": "obra",
        "objeto": (
            "Contratação da empresa MULTPAR SERVIÇOS DE CONSTRUÇÃO LTDA "
            "para conservação e manutenção de edificações com aplicação de "
            "material, para o Ministério Público do Estado do Piauí (2ª "
            "aquisição), decorrente da Ata de Registro de Preços própria nº "
            "12/2025 (Pregão Eletrônico nº 90018/2024, Lote I — Teresina)."
        ),
        "contratado_razao_social": "MULTPAR SERVIÇOS DE CONSTRUÇÃO LTDA",
        "contratado_cnpj_cpf": "22.561.863/0001-70",
        "valor_inicial": Decimal("25988.25"),
        "valor_atual": Decimal("25988.25"),
        "saldo_disponivel": Decimal("25988.25"),
        "valor_empenhado": Decimal("0.00"),  # recalculado por importar_empenhos_siafe (NE00037 - anulação NE00062 = líquido R$12.709,22)
        "codigo_siafe": "25016114",
        "data_assinatura": date(2025, 6, 12),       # assinatura eletrônica (MPPI); contratada assinou 12/06/2025 também
        "data_inicio_vigencia": date(2025, 6, 12),
        "data_fim_vigencia": date(2030, 6, 12),      # cláusula 2.1: 5 anos contados da assinatura
        "unidade_orcamentaria": "fmmp",
        "numero_arp_origem": "12/2025",  # Ata de Registro de Preços própria nº 12/2025 (P.E. 90018/2024)
    },
    {
        # Fonte: PDF SEI 19.21.0431.0001342/2025-61 (Contrato 70/2024/FMMPPI +
        # NE 2025NE00005 + Apostilamento + Nota Fiscal), fornecido pelo
        # usuário em 2026-07-30. Este é o "Contrato nº 70/2024/FMMPPI" citado
        # dentro da própria observação da NE — achado via divergência do TCE
        # FMMP/2025 (codContrato=24012761, "MULTIPAR"). Contrato original
        # (assinado 05/12/2024) via ATA DE REGISTRO DE PREÇOS Nº 21/2023
        # (Pregão Eletrônico 25/2023, Lote I), objeto SOB DEMANDA
        # (manutenção predial Sede Leste/GAECO/Sede Centro), valor
        # R$16.659,93 pago por NE 2024NE00057 (05/12/2024). Em 27/01/2025 foi
        # emitida NE 2025NE00005 (R$927,96) — "CONTRATO 70/2024 -
        # APOSTILAMENTO" (Nota Fiscal 2811), referente a nova Ordem de
        # Serviço executada em jan/2025 dentro da vigência do mesmo contrato
        # (12 meses da assinatura -> 05/12/2025). ATENÇÃO: como a NE original
        # é de 2024, é preciso rodar `importar_empenhos_siafe` para os DOIS
        # exercícios (2024 e 2025) para este contrato capturar as duas NEs.
        "numero_contrato": "70/2024/FMMPPI",
        "numero_sei": "19.21.0431.0043128/2024-49",  # PGA original do contrato
        "tipo": "obra",
        "objeto": (
            "Contratação de empresa especializada na prestação de serviços "
            "de conservação e manutenção de edificações, SOB DEMANDA, do "
            "Ministério Público do Estado do Piauí (Sede Leste, GAECO e Sede "
            "Centro), decorrente da Ata de Registro de Preços nº 21/2023 "
            "(Pregão Eletrônico nº 25/2023, Lote I)."
        ),
        "contratado_razao_social": "MULTPAR SERVIÇOS DE CONSTRUÇÃO LTDA – EPP",
        "contratado_cnpj_cpf": "22.561.863/0001-70",
        "valor_inicial": Decimal("16659.93"),
        "valor_atual": Decimal("17587.89"),  # 16.659,93 + apostilamento de 927,96 (NE 2025NE00005)
        "saldo_disponivel": Decimal("17587.89"),
        "valor_empenhado": Decimal("0.00"),  # recalculado por importar_empenhos_siafe (2024NE00057 + 2025NE00005 = R$17.587,89) — rodar para os exercícios 2024 E 2025
        "codigo_siafe": "24012761",
        "data_assinatura": date(2024, 12, 5),
        "data_inicio_vigencia": date(2024, 12, 5),
        "data_fim_vigencia": date(2025, 12, 5),  # cláusula 4.1: 12 meses da assinatura
        "unidade_orcamentaria": "fmmp",
        "numero_arp_origem": "21/2023",  # Ata de Registro de Preços nº 21/2023, Pregão Eletrônico 25/2023, Lote I
    },
    {
        # Fonte: PDFs SEI 0750071 (Contrato 14/2024/FMMP/PI), SEI 1037983
        # (Termo Aditivo 01) e NE 250102_2025NE00032_D, fornecidos pelo
        # usuário em 2026-07-30 — último grupo MULTIPAR pendente da
        # divergência TCE FMMP/2025 (codContrato=24008509). Contrato original
        # (P.E. 30/2023, sem ARP — contratação direta), assinado 22/05/2024,
        # objeto: execução/instalação/fornecimento de materiais para
        # Instalações de Prevenção e Combate a Incêndio e Pânico + Projeto de
        # SPDA nas sedes das Promotorias de Água Branca, Corrente, Luís
        # Correia, Luzilândia, Parnaíba e União, valor R$238.385,32 (NE
        # 2024NE00024). Termo Aditivo 01 (assinado 21/05/2025) = reajuste +
        # acréscimo quantitativo de 1,98%, valor R$12.481,48 — bate exato com
        # NE 2025NE00032 (21/05/25, "reajuste e acréscimo quantitativo da
        # minuta contratual nº 01 ao Contrato nº 14/2024/FMMP/PI"). ATENÇÃO:
        # (1) como a NE original é de 2024, rodar `importar_empenhos_siafe`
        # para os DOIS exercícios (2024 e 2025); (2) o Termo Aditivo 01 não
        # traz uma nova data de vigência explícita no texto extraído (só
        # menciona restituição dos dias de paralisação) — data_fim_vigencia
        # abaixo é a do contrato original (12 meses da assinatura), pode
        # estar desatualizada se o aditivo tiver prorrogado o prazo em outra
        # cláusula não capturada aqui.
        "numero_contrato": "14/2024/FMMP/PI",
        "numero_sei": "19.21.0431.0026337/2023-31",
        "tipo": "obra",
        "objeto": (
            "Contratação de empresa especializada em execução, instalação e "
            "fornecimento de materiais e mão de obra completa de Instalações "
            "de Prevenção e Combate a Incêndio e Pânico, Projeto de SPDA das "
            "sedes próprias das Promotorias de Justiça do Piauí localizadas "
            "em Água Branca, Corrente, Luís Correia, Luzilândia, Parnaíba e "
            "União."
        ),
        "contratado_razao_social": "MULTPAR SERVIÇOS DE CONSTRUÇÃO LTDA",
        "contratado_cnpj_cpf": "22.561.863/0001-70",
        "valor_inicial": Decimal("238385.32"),
        "valor_atual": Decimal("250866.80"),  # 238.385,32 + Termo Aditivo 01 (reajuste+acréscimo, R$12.481,48)
        "saldo_disponivel": Decimal("250866.80"),
        "valor_empenhado": Decimal("0.00"),  # recalculado por importar_empenhos_siafe (2024NE00024 + 2025NE00032) — rodar para os exercícios 2024 E 2025
        "codigo_siafe": "24008509",
        "data_assinatura": date(2024, 5, 22),
        "data_inicio_vigencia": date(2024, 5, 22),
        "data_fim_vigencia": date(2025, 5, 22),  # cláusula 4.1 do contrato original: 12 meses da assinatura (ver ressalva acima sobre o aditivo)
        "unidade_orcamentaria": "fmmp",
        # Contratação direta via Pregão Eletrônico 30/2023 — não decorre de ARP/SRP.
    },
    {
        # Fonte: PDF SEI 0935567 (Contrato Nº 1/2025/FMMP/PI) + NE
        # 250102_2025NE00001_D, fornecidos pelo usuário em 2026-07-30 —
        # resolve o ALTACON (codContrato=25012991, R$432.000,00, "reforma e
        # ampliação"), a última divergência do TCE FMMP/2025 desta rodada.
        # Concorrência Eletrônica nº 90001/2024 (contratação direta, sem
        # ARP), assinado 27/01/2025, objeto: reforma e ampliação da sede que
        # abriga as Promotorias de Justiça de Piripiri/PI (Rua Padre
        # Domingos, nº 505, Bairro Centro). Valor R$432.000,00 bate exato com
        # NE 2025NE00001 (20/01/25, autorizado pela AE SEI 0924890).
        "numero_contrato": "1/2025/FMMP/PI",
        "numero_sei": "19.21.0431.0011193/2024-61",
        "tipo": "obra",
        "objeto": (
            "Contratação de empresa especializada para a execução dos "
            "serviços de reforma e ampliação da Sede que abriga as "
            "Promotorias de Justiça de Piripiri/PI, localizada na Rua Padre "
            "Domingos, nº 505, Bairro Centro, Piripiri/PI (Concorrência "
            "Eletrônica nº 90001/2024, regime de empreitada por preço "
            "global)."
        ),
        "contratado_razao_social": "ALTACON ENGENHARIA E CONSTRUÇÃO LTDA",
        "contratado_cnpj_cpf": "22.829.583/0001-09",
        "valor_inicial": Decimal("432000.00"),
        "valor_atual": Decimal("432000.00"),
        "saldo_disponivel": Decimal("432000.00"),
        "valor_empenhado": Decimal("0.00"),  # recalculado por importar_empenhos_siafe (NE 2025NE00001)
        "codigo_siafe": "25012991",
        "data_assinatura": date(2025, 1, 27),        # última assinatura eletrônica (contratada)
        "data_inicio_vigencia": date(2025, 1, 27),
        "data_fim_vigencia": date(2026, 1, 27),      # cláusula 2.1: 12 meses da assinatura
        "unidade_orcamentaria": "fmmp",
        # Concorrência Eletrônica direta (execução de obra) — não decorre de ARP/SRP.
    },
    {
        # Fonte: payload bruto da API SIAFE (SiafeClient.nota_empenho_por_ug),
        # consultado em 2026-07-30 pelo usuário via shell — 6º e último grupo
        # MULTIPAR da divergência TCE FMMP/2025 (codContrato=24012839). Achado
        # depois de corrigir um bug em `investigar_ne_faltante` (o check de
        # "já importada" comparava só numero_empenho, sem CNPJ do credor —
        # dava falso positivo quando outra NE de OUTRO credor/UG tinha o
        # mesmo número; NE 2025NE00011 real da MULTIPAR nunca tinha sido
        # importada).
        # SEM Termo de Contrato localizado ainda — dados vêm só da própria NE:
        # observação cita "AUTORIZAÇÃO DE EMPENHO ASSCOMPRAS (SEI nº 0964150)",
        # ATA DE REGISTRO DE PREÇOS Nº 21/2023 (P.E. 25/2023, Lote 1-Teresina)
        # — mesma Ata do contrato 70/2024/FMMPPI já cadastrado acima, mas
        # objeto e codContrato diferentes (outro instrumento/OS na mesma Ata).
        # numOriginalContrato=null no payload SIAFE — reforça que não há
        # Termo de Contrato formal separado, só a AE direto contra a Ata.
        # Se aparecer um PDF de Termo de Contrato para este objeto, esta
        # entrada deve ser corrigida (mesmo padrão do que ocorreu com o
        # codContrato 25015651, que era "AE only" até o usuário achar o
        # Contrato 41/2025/FMMP/PI real).
        "numero_contrato": "AE 0964150/2025-FMMP",
        "numero_sei": "19.21.0431.0031329/2024-74",
        "tipo": "obra",
        "objeto": (
            "Contratação de empresa especializada na prestação de serviços "
            "de conservação e manutenção predial — 3ª etapa Casa da "
            "Cidadania (pinturas complementares, 32ª Promotoria de Justiça "
            "de Teresina, implantação do Centro de Apoio e da Sala "
            "Sensorial, e adequação da rede de esgoto), decorrente da Ata "
            "de Registro de Preços nº 21/2023 (Pregão Eletrônico nº "
            "25/2023, Lote I — Teresina), conforme Autorização de Empenho "
            "ASSCOMPRAS (SEI 0964150)."
        ),
        "contratado_razao_social": "MULTIPAR SERVIÇOS DE CONSTRUÇÃO LTDA-EPP",
        "contratado_cnpj_cpf": "22.561.863/0001-70",
        "valor_inicial": Decimal("6303.84"),
        "valor_atual": Decimal("6303.84"),
        "saldo_disponivel": Decimal("6303.84"),
        "valor_empenhado": Decimal("0.00"),  # recalculado por importar_empenhos_siafe (NE 2025NE00011)
        "codigo_siafe": "24012839",
        "data_assinatura": date(2025, 2, 21),        # CALCULADO: dataEmissao da NE (payload SIAFE) — não é data de assinatura de instrumento formal, pois não há Termo de Contrato localizado
        "data_inicio_vigencia": date(2025, 2, 21),
        "data_fim_vigencia": date(2026, 2, 21),      # CALCULADO: 1 ano a partir da emissão da NE, na ausência de vigência formal documentada
        "unidade_orcamentaria": "fmmp",
        "numero_arp_origem": "21/2023",  # Ata de Registro de Preços nº 21/2023, Pregão Eletrônico 25/2023, Lote I
    },
]


class Command(BaseCommand):
    help = "Cadastra contratos confirmados manualmente via documento fonte (idempotente, nunca sobrescreve existente)"

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args, **options):
        dry_run = options["dry_run"]

        orgao = next(
            (o for o in Orgao.objects.all() if _digitos(o.cnpj) == CNPJ_MPPI), None
        )
        if not orgao:
            todos = list(Orgao.objects.values_list("pk", "sigla", "cnpj"))
            self.stdout.write(self.style.ERROR(
                f"Órgão com CNPJ {CNPJ_MPPI} não encontrado (comparando dígitos) — não dá pra cadastrar nada. "
                f"Órgãos existentes no banco: {todos}"
            ))
            return

        criados = 0
        ja_existiam = 0

        for dados in CONTRATOS_MANUAIS:
            dados = dict(dados)
            numero_arp = dados.pop("numero_arp_origem", None)

            existente = Contrato.objects.filter(
                orgao=orgao, numero_contrato=dados["numero_contrato"]
            ).first()
            if existente:
                ja_existiam += 1
                self.stdout.write(
                    f"  [já existe, não mexido] pk={existente.pk} {dados['numero_contrato']!r} "
                    f"(codigo_siafe atual={existente.codigo_siafe!r})"
                )
                continue

            arp = None
            if numero_arp:
                arp = AtaRegistroPrecos.objects.filter(numero_arp__icontains=numero_arp).first()

            self.stdout.write(
                f"  {dados['numero_contrato']!r} — {dados['contratado_razao_social']} — "
                f"R$ {dados['valor_inicial']:,.2f} — arp_origem={arp.numero_arp if arp else '(não achada, ficará vazio)'}"
            )

            if not dry_run:
                Contrato.objects.create(orgao=orgao, arp_origem=arp, **dados)
            criados += 1

        modo = "[DRY-RUN — nada gravado] " if dry_run else ""
        self.stdout.write(self.style.SUCCESS(
            f"\n{modo}Criados: {criados} | Já existiam (mantidos intactos): {ja_existiam}"
        ))
        if criados and not dry_run:
            self.stdout.write(self.style.WARNING(
                "\nAgora rode `importar_empenhos_siafe --exercicio 2026` de novo — a NE que estava "
                "sem contrato local deve ser importada automaticamente."
            ))
