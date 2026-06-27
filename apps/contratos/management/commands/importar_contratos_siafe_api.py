"""
Management command: importar_contratos_siafe_api

Busca contratos diretamente da API SIAFE-PI usando os códigos automáticos
(codContrato) encontrados nas Notas de Empenho mas não cadastrados localmente.

Fluxo:
  1. Busca NEs das 3 UGs do MPPI
  2. Coleta os codContrato únicos com empenho
  3. Para cada código não cadastrado localmente, chama GET /contrato/{exercicio}/{codigo}
  4. Cria o Contrato local com os dados retornados pelo SIAFE

Uso:
  python manage.py importar_contratos_siafe_api
  python manage.py importar_contratos_siafe_api --exercicio-nes 2026
  python manage.py importar_contratos_siafe_api --dry-run
  python manage.py importar_contratos_siafe_api --debug   # inspeciona primeiro contrato
"""

import re
from datetime import date
from decimal import Decimal, InvalidOperation

from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.contratos.models import Contrato
from apps.core.models import Orgao
from apps.siafe.client import SiafeClient, SiafeAPIError

UGS_MPPI = ["250101", "250102", "250104"]

UGS_INFO = {
    "250101": {"sigla": "PGJ",     "nome": "PROCURADORIA GERAL DE JUSTICA DO MPPI"},
    "250102": {"sigla": "FUNDMPE", "nome": "FUNDO ESPECIAL DO MINISTERIO PUBLICO DO PIAUI"},
    "250104": {"sigla": "FPDC",    "nome": "FUNDO DE PROTECAO E DEFESA DO CONSUMIDOR"},
}

SITUACAO_PARA_STATUS = {
    # Formato XML (exportação)
    "Em Vigor":   "vigente",
    "Licitado":   "vigente",
    "Encerrado":  "encerrado",
    "Rescindido": "rescindido",
    "Suspenso":   "suspenso",
    # Formato API (enum SIAFE)
    "EM_VIGOR":   "vigente",
    "ASSINADO":   "vigente",
    "ENCERRADO":  "encerrado",
    "RESCINDIDO": "rescindido",
    "SUSPENSO":   "suspenso",
    "CANCELADO":  "rescindido",
}


def _parse_valor(v) -> Decimal:
    if v is None:
        return Decimal("0")
    if isinstance(v, (int, float)):
        return Decimal(str(v))
    limpo = re.sub(r"[R$\s]", "", str(v)).replace(".", "").replace(",", ".")
    try:
        return Decimal(limpo)
    except InvalidOperation:
        return Decimal("0")


def _exercicio_from_codigo(codigo: str) -> int:
    """'17000124' → 2017  |  '26100674' → 2026"""
    if len(codigo) >= 2 and codigo[:2].isdigit():
        return 2000 + int(codigo[:2])
    return date.today().year


def _get_or_create_orgao(cod_ug: str, nome_ug: str) -> Orgao:
    info = UGS_INFO.get(cod_ug, {})
    sigla = info.get("sigla", cod_ug)
    nome  = info.get("nome", nome_ug or cod_ug)

    orgao = Orgao.objects.filter(sigla=sigla).first()
    if orgao:
        return orgao

    orgao, _ = Orgao.objects.get_or_create(
        cnpj=f"UG-{cod_ug}"[:18],
        defaults={"nome": nome, "sigla": sigla},
    )
    return orgao


def _inferir_tipo(objeto: str, modalidade: str) -> str:
    obj = objeto.lower() if objeto else ""

    if any(k in obj for k in ["tic", "software", "sistema", "computador", "notebook",
                               "servidor", "link de internet", "all-flash", "storage",
                               "nobreak", "tablet", "imac", "firewall"]):
        return "solucao_ti"

    if any(k in obj for k in ["constru", "reforma", "manuten", "predial",
                               "topográf", "sondagem", "obra", "instala",
                               "demoli", "piso", "cerca"]):
        return "obra"

    if any(k in obj for k in ["postos", "mão de obra", "limpeza", "vigilância",
                               "agente de", "motorista", "energia elétrica",
                               "água tratada", "internet", "serviços continuados",
                               "dedicação exclusiva", "combate de vetores"]):
        return "servico_continuo"

    if any(k in obj for k in ["aquisição", "fornecimento", "compra", "material",
                               "equipamento", "veículo", "mobiliário", "toner"]):
        return "fornecimento"

    return "servico_nao_continuo"


def _strip_codigo_prefix(texto: str) -> str:
    """'250101 - PROCURADORIA GERAL DE JUSTICA' → 'PROCURADORIA GERAL DE JUSTICA'"""
    if " - " in texto:
        partes = texto.split(" - ", 1)
        if re.match(r"^[\d./\-]+$", partes[0].strip()):
            return partes[1].strip()
    return texto.strip()


def _parse_date(valor: str):
    """'2015-05-06' → date(2015, 5, 6)  |  None → None"""
    if not valor:
        return None
    try:
        parts = str(valor).split("-")
        return date(int(parts[0]), int(parts[1]), int(parts[2]))
    except Exception:
        return None


def _map_contrato_siafe(data: dict, codigo_siafe: str) -> dict:
    """
    Mapeia a resposta da API SIAFE (GET /contrato/{exercicio}/{codigo})
    para campos do model Contrato.

    Campos-chave da API:
      codigo, numeroOriginal, objeto, codigoContratante, nomeContratante,
      codigoContratado, nomeContratado, situacao, valorTotal, valor (parcela),
      dataCelebracao, dataInicioVigencia, dataFimVigencia, dataFimVigenciaTotal,
      codigoModalidadeLicitacao, nomeModalidadeLicitacao
    """
    def get(*keys):
        for k in keys:
            v = data.get(k)
            if v is not None and str(v).strip():
                return str(v).strip()
        return ""

    numero_original = get("numeroOriginal", "numOriginalContrato")
    numero_contrato = (numero_original or codigo_siafe)[:30]

    objeto           = get("objeto", "objetivo", "descricao")
    cod_contratante  = get("codigoContratante", "codigoUG")
    nome_contratante = _strip_codigo_prefix(get("nomeContratante", "nomeUG"))
    cod_contratado   = get("codigoContratado", "codigoCredor")[:18]
    nome_contratado  = _strip_codigo_prefix(get("nomeContratado", "nomeCredor"))
    situacao         = get("situacao", "status")

    # valorTotal = valor total do contrato (inclui aditivos); valor = parcela mensal
    valor = _parse_valor(data.get("valorTotal") or data.get("valor") or 0)

    # Datas: prefere dataFimVigenciaTotal (com aditivos) sobre dataFimVigencia
    data_assinatura      = _parse_date(get("dataCelebracao", "dataAssinatura"))
    data_inicio_vigencia = _parse_date(get("dataInicioVigencia"))
    data_fim_vigencia    = _parse_date(
        get("dataFimVigenciaTotal") or get("dataFimVigencia")
    )

    exercicio = (data_assinatura.year if data_assinatura
                 else _exercicio_from_codigo(codigo_siafe))

    # Fallback para datas ausentes
    if not data_assinatura:
        data_assinatura = date(exercicio, 1, 1)
    if not data_inicio_vigencia:
        data_inicio_vigencia = data_assinatura
    if not data_fim_vigencia:
        data_fim_vigencia = date(exercicio, 12, 31)

    modalidade = get("nomeModalidadeLicitacao", "codigoModalidadeLicitacao")

    return {
        "numero_contrato":     numero_contrato,
        "codigo_siafe":        codigo_siafe,
        "objeto":              objeto or f"Contrato SIAFE {codigo_siafe}",
        "cod_contratante":     cod_contratante,
        "nome_contratante":    nome_contratante,
        "cod_contratado":      cod_contratado,
        "nome_contratado":     nome_contratado[:255],
        "situacao":            situacao,
        "valor":               valor,
        "exercicio":           exercicio,
        "data_assinatura":     data_assinatura,
        "data_inicio_vigencia": data_inicio_vigencia,
        "data_fim_vigencia":   data_fim_vigencia,
        "tipo":                _inferir_tipo(objeto, modalidade),
        "status":              SITUACAO_PARA_STATUS.get(situacao, "vigente"),
    }


class Command(BaseCommand):
    help = "Importa contratos faltantes do SIAFE-PI via API, usando codContrato das NEs"

    def add_arguments(self, parser):
        parser.add_argument(
            "--exercicio-nes", type=int, default=date.today().year,
            help="Exercício das NEs para coletar codContratos (padrão: ano atual)",
        )
        parser.add_argument(
            "--dry-run", action="store_true",
            help="Lista o que seria importado sem salvar",
        )
        parser.add_argument(
            "--debug", action="store_true",
            help="Exibe a resposta bruta da API para o primeiro contrato",
        )

    def handle(self, *args, **options):
        exercicio_nes = options["exercicio_nes"]
        dry_run       = options["dry_run"]
        debug         = options["debug"]

        client = SiafeClient()

        # ----------------------------------------------------------------
        # 1. Coletar todos os codContratos únicos das NEs
        # ----------------------------------------------------------------
        self.stdout.write(f"Coletando NEs do exercício {exercicio_nes}...")
        codigos_com_empenho: dict[str, Decimal] = {}

        for ug in UGS_MPPI:
            try:
                nes = client.nota_empenho_por_ug(exercicio_nes, ug)
            except SiafeAPIError as exc:
                self.stderr.write(self.style.WARNING(f"  [ERRO] UG {ug}: {exc}"))
                continue

            for ne in nes:
                cod = (ne.get("codContrato") or "").strip()
                if not cod or cod in ("0", "00000000"):
                    continue
                valor    = _parse_valor(ne.get("valor"))
                tipo_alt = (ne.get("tipoAlteracaoNE") or "NENHUMA").upper()
                if tipo_alt == "ANULACAO":
                    codigos_com_empenho[cod] = codigos_com_empenho.get(cod, Decimal("0")) - valor
                else:
                    codigos_com_empenho[cod] = codigos_com_empenho.get(cod, Decimal("0")) + valor

        self.stdout.write(f"  {len(codigos_com_empenho)} contratos únicos com empenho nas NEs")

        # ----------------------------------------------------------------
        # 2. Identificar os não cadastrados localmente
        # ----------------------------------------------------------------
        faltantes = {
            cod: valor
            for cod, valor in codigos_com_empenho.items()
            if not Contrato.objects.filter(codigo_siafe=cod).exists()
        }
        self.stdout.write(f"  {len(faltantes)} contratos não cadastrados localmente\n")

        if not faltantes:
            self.stdout.write(self.style.SUCCESS("Nada a importar — todos já estão cadastrados."))
            return

        # ----------------------------------------------------------------
        # 3. Buscar cada contrato na API SIAFE e criar localmente
        # ----------------------------------------------------------------
        criados = erros = ignorados = 0
        agora = timezone.now()

        for i, (codigo, valor_empenhado) in enumerate(sorted(faltantes.items()), 1):
            exercicio_contrato = _exercicio_from_codigo(codigo)
            self.stdout.write(
                f"[{i:3d}/{len(faltantes)}] {codigo}  (ex. {exercicio_contrato})"
                f"  empenhado R$ {valor_empenhado:,.2f} ...",
                ending=" ",
            )

            try:
                data = client.contrato(exercicio_contrato, codigo)
            except SiafeAPIError as exc:
                self.stdout.write(self.style.WARNING(f"ERRO API: {exc}"))
                erros += 1
                continue

            if debug and i == 1:
                self.stdout.write("\n  --- DEBUG: campos da resposta ---")
                for k, v in (data.items() if isinstance(data, dict) else {}.items()):
                    self.stdout.write(f"    {k}: {repr(v)[:100]}")
                self.stdout.write("  ---\n")

            if not isinstance(data, dict) or not data:
                self.stdout.write(self.style.WARNING("resposta vazia"))
                ignorados += 1
                continue

            mapeado = _map_contrato_siafe(data, codigo)

            if dry_run:
                self.stdout.write(
                    self.style.WARNING(
                        f"[DRY] {mapeado['numero_contrato']:30s} | "
                        f"{mapeado['tipo']:22s} | R$ {mapeado['valor']:,.2f}"
                    )
                )
                criados += 1
                continue

            # Busca ou cria Orgao
            try:
                orgao = _get_or_create_orgao(mapeado["cod_contratante"], mapeado["nome_contratante"])
            except Exception as exc:
                self.stdout.write(self.style.WARNING(f"orgao ERR: {exc}"))
                ignorados += 1
                continue

            try:
                Contrato.objects.create(
                    numero_contrato          = mapeado["numero_contrato"],
                    codigo_siafe             = codigo,
                    objeto                   = mapeado["objeto"],
                    contratado_razao_social  = mapeado["nome_contratado"],
                    contratado_cnpj_cpf      = mapeado["cod_contratado"],
                    tipo                     = mapeado["tipo"],
                    status                   = mapeado["status"],
                    valor_inicial            = mapeado["valor"],
                    valor_atual              = mapeado["valor"],
                    saldo_disponivel         = mapeado["valor"],
                    valor_empenhado          = valor_empenhado,
                    ultima_atualizacao_siafe = agora,
                    data_assinatura          = mapeado["data_assinatura"],
                    data_inicio_vigencia     = mapeado["data_inicio_vigencia"],
                    data_fim_vigencia        = mapeado["data_fim_vigencia"],
                    orgao                    = orgao,
                    numero_sei               = "",
                )
                self.stdout.write(self.style.SUCCESS(
                    f"OK — {mapeado['numero_contrato']} / {mapeado['nome_contratado'][:40]}"
                ))
                criados += 1
            except Exception as exc:
                self.stdout.write(self.style.WARNING(f"ERR save: {exc}"))
                ignorados += 1

        self.stdout.write("\n" + "=" * 70)
        if dry_run:
            self.stdout.write(self.style.WARNING(
                f"DRY RUN — {criados} seriam criados, {erros} erros API, {ignorados} ignorados."
            ))
        else:
            self.stdout.write(self.style.SUCCESS(
                f"Concluído: {criados} criados, {erros} erros API, {ignorados} ignorados."
            ))
