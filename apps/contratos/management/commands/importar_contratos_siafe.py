"""
Management command: importar_contratos_siafe

Importa contratos do MPPI a partir de arquivo exportado do SIAFE-PI.
Suporta dois formatos (auto-detectado pela extensão):
  - XML  (.xml) — recomendado; campos explícitos, sem ambiguidade
  - TXT  (.txt) — legado; colunas separadas por 2+ espaços

Uso:
  python manage.py importar_contratos_siafe --arquivo caminho/exportacao.xml
  python manage.py importar_contratos_siafe --arquivo exportacao.xml --dry-run
  python manage.py importar_contratos_siafe --arquivo exportacao.xml --apenas-ug 250101

Colunas do XML:
  numero_automatico | numero_da_licitacao | numero_original | natureza | objeto
  | cod_contratante | nome_contratante | cod_contratado | modalidade_de_licitacao
  | nome_do_contratado | situacao | valor_do_contrato | qtd_aditivos
  | qtd_reajustes | qtd_anexos
"""

import re
import xml.etree.ElementTree as ET
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from apps.contratos.models import Contrato
from apps.core.models import Orgao

# UGs MPPI no SIAFE
UGS_MPPI = {
    "250101": {"sigla": "PGJ",     "nome": "PROCURADORIA GERAL DE JUSTICA DO MPPI"},
    "250102": {"sigla": "FUNDMPE", "nome": "FUNDO ESPECIAL DO MINISTERIO PUBLICO DO PIAUI"},
    "250104": {"sigla": "FPDC",    "nome": "FUNDO DE PROTECAO E DEFESA DO CONSUMIDOR"},
}

SITUACAO_PARA_STATUS = {
    "Em Vigor":   "vigente",
    "Licitado":   "vigente",
    "Encerrado":  "encerrado",
    "Rescindido": "rescindido",
    "Suspenso":   "suspenso",
}

MODALIDADE_PARA_TIPO = {
    "04": "obra",
    "01": "obra",
}


# ---------------------------------------------------------------------------
# Utilitários
# ---------------------------------------------------------------------------

def _parse_valor(valor_str: str) -> Decimal:
    """'R$ 1.490.701,03' → Decimal('1490701.03')"""
    if not valor_str:
        return Decimal("0")
    limpo = re.sub(r"[R$\s]", "", valor_str).replace(".", "").replace(",", ".")
    try:
        return Decimal(limpo)
    except InvalidOperation:
        return Decimal("0")


def _inferir_tipo(objeto: str, modalidade_codigo: str) -> str:
    obj = objeto.lower()

    ti = ["tic", "software", "sistema", "computador", "notebook", "servidor",
          "link de internet", "tecnologia da informa", "all-flash", "hd externo",
          "storage", "nobreak", "tablet", "imac", "firewall", "monitoramento veicular",
          "equipamentos de ti", "equipamentos e itens de ti"]
    if any(k in obj for k in ti):
        return "solucao_ti"

    obra = ["constru", "demoli", "muro", "edifica", "reforma", "manuten",
            "predial", "topográf", "sondagem", "obra", "instala",
            "cercas", "piso", "anel viário"]
    if any(k in obj for k in obra):
        return "obra"

    continuo = ["postos", "mão de obra", "m de obra", "limpeza", "vigilância",
                "agente de", "motorista", "recepcionista", "telefonista",
                "energia elétrica", "água tratada", "internet", "serviços continuados",
                "serviço continuado", "dedicação exclusiva",
                "serviços de controle", "buffet", "chaveiro",
                "combate de vetores", "audiovisual"]
    if any(k in obj for k in continuo):
        return "servico_continuo"

    bens = ["aquisição", "fornecimento", "compra", "material", "equipamento",
            "veículo", "mobiliário", "toner", "gás", "água mineral", "aliment",
            "gêneros", "camiseta", "medalha", "brinde", "colete", "beca",
            "fragmentadora", "bebedouro", "purificador", "poltrona", "armário",
            "gaveteiro", "cadeira", "mesa de madeira", "planta ornamental"]
    if any(k in obj for k in bens):
        return "fornecimento"

    return MODALIDADE_PARA_TIPO.get(modalidade_codigo, "servico_nao_continuo")


def _extrair_exercicio(numero_automatico: str) -> int:
    """'26100674' → 2026  |  '25019030' → 2025"""
    if len(numero_automatico) >= 2 and numero_automatico[:2].isdigit():
        return 2000 + int(numero_automatico[:2])
    return date.today().year


def _limpar_nome_contratado(nome_raw: str) -> str:
    """'56953630000135 - Prospera Comércio Ltda' → 'Prospera Comércio Ltda'"""
    if " - " in nome_raw:
        partes = nome_raw.split(" - ", 1)
        # Primeiro segmento é CNPJ/CPF (só dígitos, pontos, barras, hífens)
        candidato = re.sub(r"[\d.\/\-]", "", partes[0]).strip()
        if not candidato:
            return partes[1].strip()
    return nome_raw.strip()


def _get_orgao(cod_contratante: str, nome_contratante: str) -> Orgao:
    """Retorna (ou cria) o Orgao correspondente à UG do SIAFE."""
    ug = UGS_MPPI.get(cod_contratante)
    if ug:
        sigla = ug["sigla"]
        nome  = ug["nome"]
    else:
        sigla = cod_contratante
        nome  = nome_contratante or cod_contratante

    # Tenta buscar por sigla; cria com CNPJ-placeholder se não existir
    orgao = Orgao.objects.filter(sigla=sigla).first()
    if orgao:
        return orgao

    # Cria como órgão-placeholder vinculado ao código SIAFE
    # O CNPJ real pode ser atualizado depois via admin
    cnpj_placeholder = f"UG-{cod_contratante}"[:18]
    orgao, _ = Orgao.objects.get_or_create(
        cnpj=cnpj_placeholder,
        defaults={"nome": nome, "sigla": sigla},
    )
    return orgao


# ---------------------------------------------------------------------------
# Parsers
# ---------------------------------------------------------------------------

def _xml_text(element, tag: str) -> str:
    el = element.find(tag)
    return (el.text or "").strip() if el is not None else ""


def parse_arquivo_siafe_xml(caminho: Path) -> list:
    """
    Lê o XML exportado do SIAFE e retorna lista de dicts.
    Cada <row> contém campos explícitos — sem risco de deslocamento de colunas.
    O SIAFE às vezes gera '&' não escapado (ex: 'V&M') — corrigido antes do parse.
    """
    content = caminho.read_text(encoding="utf-8", errors="replace")
    # Escapa '&' soltos que não são parte de entidade XML válida
    content = re.sub(r"&(?!amp;|lt;|gt;|quot;|apos;|#\d+;|#x[\da-fA-F]+;)", "&amp;", content)
    root = ET.fromstring(content)
    contratos = []

    for row in root.findall("row"):
        numero_automatico   = _xml_text(row, "numero_automatico")
        numero_original     = _xml_text(row, "numero_original")
        objeto              = _xml_text(row, "objeto")
        cod_contratante     = _xml_text(row, "cod_contratante")
        nome_contratante    = _xml_text(row, "nome_contratante")
        cod_contratado      = _xml_text(row, "cod_contratado")[:18]  # max_length=18
        modalidade_str      = _xml_text(row, "modalidade_de_licitacao")
        nome_do_contratado  = _xml_text(row, "nome_do_contratado")
        situacao            = _xml_text(row, "situacao")
        valor_str           = _xml_text(row, "valor_do_contrato")

        modalidade_codigo = modalidade_str.split("-")[0].strip() if "-" in modalidade_str else ""
        nome_limpo = _limpar_nome_contratado(nome_do_contratado)
        exercicio  = _extrair_exercicio(numero_automatico)

        contratos.append({
            "numero_automatico": numero_automatico,
            "numero_original":   numero_original,
            "objeto":            objeto,
            "cod_contratante":   cod_contratante,
            "nome_contratante":  nome_contratante,
            "cod_contratado":    cod_contratado,
            "modalidade_codigo": modalidade_codigo,
            "nome_contratado":   nome_limpo,
            "situacao":          situacao,
            "valor":             _parse_valor(valor_str),
            "exercicio":         exercicio,
            "tipo":              _inferir_tipo(objeto, modalidade_codigo),
            "status":            SITUACAO_PARA_STATUS.get(situacao, "vigente"),
        })

    return contratos


def parse_arquivo_siafe_txt(caminho: Path) -> list:
    """
    Lê o TXT exportado do SIAFE (Latin-1, campos separados por 2+ espaços).
    Mantido para compatibilidade — prefira o XML.
    """
    contratos = []

    with open(caminho, encoding="latin-1", errors="replace") as f:
        linhas = f.readlines()

    inicio = None
    for i, linha in enumerate(linhas):
        if "mero Autom" in linha:
            inicio = i + 1
            break

    if inicio is None:
        return contratos

    NATUREZAS = {"Despesa", "Receita", "Despesa/Receita"}

    for linha in linhas[inicio:]:
        partes = [p.strip() for p in re.split(r"  +", linha.rstrip())]
        if not partes or not partes[0]:
            continue
        if not re.match(r"^\d{7,9}$", partes[0]):
            continue

        while len(partes) < 15:
            partes.append("")

        numero_automatico = partes[0]

        if partes[2] in NATUREZAS:
            numero_original = ""
            objeto          = partes[3]
            cod_contratante = partes[4]
            nome_contratante = partes[5]
            cod_contratado  = partes[6][:18]
            modalidade_str  = partes[7]
            nome_contratado = partes[8]
            situacao        = partes[9]
            valor_str       = partes[10]
        else:
            numero_original = partes[2]
            objeto          = partes[4]
            cod_contratante = partes[5]
            nome_contratante = partes[6]
            cod_contratado  = partes[7][:18]
            modalidade_str  = partes[8]
            nome_contratado = partes[9]
            situacao        = partes[10]
            valor_str       = partes[11]

        modalidade_codigo = modalidade_str.split("-")[0].strip() if "-" in modalidade_str else ""
        nome_limpo = _limpar_nome_contratado(nome_contratado)
        exercicio  = _extrair_exercicio(numero_automatico)

        contratos.append({
            "numero_automatico": numero_automatico,
            "numero_original":   numero_original,
            "objeto":            objeto,
            "cod_contratante":   cod_contratante,
            "nome_contratante":  nome_contratante,
            "cod_contratado":    cod_contratado,
            "modalidade_codigo": modalidade_codigo,
            "nome_contratado":   nome_limpo,
            "situacao":          situacao,
            "valor":             _parse_valor(valor_str),
            "exercicio":         exercicio,
            "tipo":              _inferir_tipo(objeto, modalidade_codigo),
            "status":            SITUACAO_PARA_STATUS.get(situacao, "vigente"),
        })

    return contratos


# ---------------------------------------------------------------------------
# Command
# ---------------------------------------------------------------------------

class Command(BaseCommand):
    help = "Importa contratos SIAFE-PI de arquivo exportado (XML ou TXT) para o banco local"

    def add_arguments(self, parser):
        parser.add_argument(
            "--arquivo", type=str, required=True,
            help="Caminho para o arquivo exportado do SIAFE-PI (.xml ou .txt)",
        )
        parser.add_argument(
            "--dry-run", action="store_true",
            help="Exibe os contratos sem salvar",
        )
        parser.add_argument(
            "--apenas-ug", type=str, default=None,
            help="Filtrar apenas uma UG (ex: 250101)",
        )

    def handle(self, *args, **options):
        arquivo  = Path(options["arquivo"])
        dry_run  = options["dry_run"]
        apenas_ug = options["apenas_ug"]

        if not arquivo.exists():
            raise CommandError(f"Arquivo não encontrado: {arquivo}")

        ext = arquivo.suffix.lower()
        self.stdout.write(f"Lendo ({ext}): {arquivo}")

        if ext == ".xml":
            contratos = parse_arquivo_siafe_xml(arquivo)
        else:
            contratos = parse_arquivo_siafe_txt(arquivo)

        self.stdout.write(f"Total encontrado: {len(contratos)}")

        if apenas_ug:
            contratos = [c for c in contratos if c["cod_contratante"] == apenas_ug]
            self.stdout.write(f"Filtrado para UG {apenas_ug}: {len(contratos)}")

        criados = atualizados = ignorados = 0

        for c in contratos:
            numero = (c["numero_original"] or c["numero_automatico"])[:30]
            if not numero:
                ignorados += 1
                continue

            ug_sigla = UGS_MPPI.get(c["cod_contratante"], {}).get("sigla", c["cod_contratante"])

            if dry_run:
                self.stdout.write(
                    f"  [{c['status'][:3].upper()}] {numero:30s} | {ug_sigla:8s} "
                    f"| {c['tipo']:22s} | R$ {c['valor']:>14,.2f} | {c['nome_contratado'][:35]}"
                )
                criados += 1
                continue

            # Busca ou cria o Orgao correspondente à UG
            try:
                orgao = _get_orgao(c["cod_contratante"], c["nome_contratante"])
            except Exception as exc:
                self.stderr.write(self.style.WARNING(f"  [ERR-ORG] {numero}: {exc}"))
                ignorados += 1
                continue

            existente = Contrato.objects.filter(numero_contrato=numero).first()

            if existente:
                existente.valor_atual   = c["valor"]
                existente.status        = c["status"]
                existente.objeto        = c["objeto"] or existente.objeto
                existente.codigo_siafe  = c["numero_automatico"]
                existente.save(update_fields=["valor_atual", "status", "objeto", "codigo_siafe"])
                atualizados += 1
                self.stdout.write(f"  [ATU] {numero}")
            else:
                try:
                    Contrato.objects.create(
                        numero_contrato          = numero,
                        objeto                   = c["objeto"],
                        contratado_razao_social  = c["nome_contratado"][:255],
                        contratado_cnpj_cpf      = c["cod_contratado"],
                        tipo                     = c["tipo"],
                        status                   = c["status"],
                        valor_inicial            = c["valor"],
                        valor_atual              = c["valor"],
                        saldo_disponivel         = c["valor"],
                        data_assinatura          = date(c["exercicio"], 1, 1),
                        data_inicio_vigencia     = date(c["exercicio"], 1, 1),
                        data_fim_vigencia        = date(c["exercicio"], 12, 31),
                        orgao                    = orgao,
                        numero_sei               = "",
                        codigo_siafe             = c["numero_automatico"],
                    )
                    criados += 1
                    self.stdout.write(self.style.SUCCESS(
                        f"  [NEW] {numero:30s} — {c['nome_contratado'][:40]}"
                    ))
                except Exception as exc:
                    self.stderr.write(self.style.WARNING(f"  [ERR] {numero}: {exc}"))
                    ignorados += 1

        self.stdout.write("\n" + "=" * 60)
        if dry_run:
            self.stdout.write(self.style.WARNING(
                f"DRY RUN — {criados} contratos seriam importados. Nada salvo."
            ))
        else:
            self.stdout.write(self.style.SUCCESS(
                f"Concluído: {criados} criados, {atualizados} atualizados, {ignorados} ignorados."
            ))
