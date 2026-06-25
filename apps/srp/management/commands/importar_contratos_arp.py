"""
Management command: importar_contratos_arp
==========================================
Importa contratos decorrentes de ARPs do MPPI.

Fontes consultadas em ordem (--fonte auto):
  1. dadosabertos.compras.gov.br — /modulo-contrato/1_consultarContrato
     Filtra por UASG e período; vincula via numeroAtaRegistroPreco.
  2. PNCP REST API — /orgaos/{cnpj}/compras/{ano}/{compraSeq}/atas/{ataSeq}/contratos
     Usado como fallback se dadosabertos não retornar dados.

Modos:
    python manage.py importar_contratos_arp --uasg 926092
    python manage.py importar_contratos_arp --uasg 926092 --ano-inicio 2024 --atualizar
    python manage.py importar_contratos_arp --uasg 926092 --debug
    python manage.py importar_contratos_arp --uasg 926092 --fonte pncp
    python manage.py importar_contratos_arp --uasg 926092 --fonte dadosabertos
"""
import json
import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

import requests
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.srp.models import AtaRegistroPrecos, ContratoARP, ItemContratoARP

PNCP_API = "https://pncp.gov.br/api/pncp/v1"
BASE_DB = "https://dadosabertos.compras.gov.br"
TIMEOUT = 30
TAMANHO_PAGINA = 500

RE_LINK_ARP = re.compile(r"pncp\.gov\.br/app/atas/(\d+)/(\d+)/(\d+)/(\d+)")
RE_NUMERO_ARP = re.compile(r"^(\d+)/(\d{4})$")


def _normalizar_numero_arp(numero: str) -> str:
    """
    Normaliza o número de ARP para formato canônico zero-padded: "001/2026".

    Aceita: "1/2026", "01/2026", "001/2026", "1/26" (sem normalizar se não casar).
    Garante que o vínculo contrato → ARP não falhe por diferença de formatação
    entre o que a API retorna no endpoint de contratos e o que foi gravado no banco
    pelo importar_arp_compras_gov (que lê o número diretamente do endpoint de ARPs).
    """
    m = RE_NUMERO_ARP.match((numero or "").strip())
    if m:
        return f"{int(m.group(1)):03d}/{m.group(2)}"
    return (numero or "").strip()


class Command(BaseCommand):
    help = "Importa contratos decorrentes de ARPs via dadosabertos ou PNCP"

    def add_arguments(self, parser):
        parser.add_argument("--uasg", required=True,
                            help="Código UASG do órgão gerenciador (MPPI = 926092)")
        parser.add_argument("--ano-inicio", type=int, default=2024,
                            help="Filtra ARPs com vigência a partir deste ano (padrão: 2024)")
        parser.add_argument("--atualizar", action="store_true", default=False,
                            help="Atualiza registros já existentes")
        parser.add_argument("--dry-run", action="store_true", default=False,
                            help="Simula sem gravar")
        parser.add_argument("--debug", action="store_true", default=False,
                            help="Exibe JSON bruto das respostas da API")
        parser.add_argument("--fonte", choices=["auto", "dadosabertos", "pncp"],
                            default="auto",
                            help="Fonte: auto (dadosabertos → pncp), dadosabertos, pncp")

    # ------------------------------------------------------------------
    # handle
    # ------------------------------------------------------------------

    def handle(self, *args, **options):
        uasg = options["uasg"].strip()
        ano_inicio = options["ano_inicio"]
        atualizar = options["atualizar"]
        dry_run = options["dry_run"]
        debug = options["debug"]
        fonte = options["fonte"]
        ano_fim = date.today().year

        if dry_run:
            self.stdout.write(self.style.WARNING("MODO DRY-RUN — nenhuma alteração será gravada.\n"))

        # Indexado pelo número normalizado para sobreviver a variações de formatação
        # entre o endpoint de ARPs e o endpoint de contratos (ex: "1/2026" vs "001/2026")
        arps_db = {_normalizar_numero_arp(a.numero_arp): a for a in AtaRegistroPrecos.objects.all()}
        arps_com_link = list(
            AtaRegistroPrecos.objects.filter(
                link_ata_pncp__regex=r"pncp\.gov\.br",
                data_inicio_vigencia__year__gte=ano_inicio,
            ).order_by("data_inicio_vigencia")
        )
        self.stdout.write(
            f"ARPs com link PNCP: {len(arps_com_link)} | Total banco: {len(arps_db)}"
        )

        resumo = {
            "contratos_criados": 0, "contratos_atualizados": 0,
            "contratos_ignorados": 0, "itens_criados": 0, "itens_atualizados": 0,
        }

        # ----------------------------------------------------------------
        # Tenta dadosabertos primeiro
        # ----------------------------------------------------------------
        if fonte in ("auto", "dadosabertos"):
            self.stdout.write(self.style.SUCCESS("\n→ Tentando dadosabertos.compras.gov.br..."))
            contratos_raw = self._buscar_contratos_dadosabertos(uasg, ano_inicio, ano_fim, debug)
            self.stdout.write(f"  Total: {len(contratos_raw)} contrato(s)")

            if contratos_raw:
                itens_por_contrato = self._buscar_itens_dadosabertos(uasg, ano_inicio, ano_fim, debug)
                self._processar_contratos(contratos_raw, itens_por_contrato, arps_db, uasg,
                                          atualizar, dry_run, resumo)
                self._imprimir_resumo(resumo, dry_run)
                return

            if fonte == "dadosabertos":
                self.stdout.write(self.style.WARNING(
                    "Nenhum contrato retornado pelo dadosabertos. "
                    "Tente --fonte pncp ou verifique o UASG."
                ))
                return

        # ----------------------------------------------------------------
        # Fallback: PNCP por ARP
        # ----------------------------------------------------------------
        self.stdout.write(self.style.SUCCESS("\n→ Tentando PNCP REST API (por ARP)..."))

        for arp in arps_com_link:
            m = RE_LINK_ARP.search(arp.link_ata_pncp)
            if not m:
                continue
            cnpj, ano_arp, compra_seq, ata_seq = m.groups()

            self.stdout.write(f"\n{'='*60}")
            self.stdout.write(
                f"ARP {arp.numero_arp} | compra {compra_seq}/ata {ata_seq} ({ano_arp})"
            )
            self.stdout.write(f"{'='*60}")

            contratos_api = self._buscar_contratos_pncp(cnpj, ano_arp, compra_seq, ata_seq, debug)
            self.stdout.write(f"  {len(contratos_api)} contrato(s).")

            itens_arp_db = {i.numero_item: i for i in arp.itens.all()}

            for dados_contrato in contratos_api:
                numero_contrato = (
                    dados_contrato.get("numeroContratoEmpenho")
                    or dados_contrato.get("numero") or ""
                )
                sequencial = (
                    dados_contrato.get("sequencialContrato")
                    or dados_contrato.get("sequencial")
                )
                unidade = dados_contrato.get("unidadeOrgao") or {}
                uasg_contratante = str(
                    unidade.get("codigoUnidade")
                    or dados_contrato.get("codigoUnidadeGerenciadora")
                    or uasg
                )

                self.stdout.write(
                    f"\n  → Contrato {numero_contrato or '?'} | UASG {uasg_contratante}"
                )
                if debug:
                    self.stdout.write(
                        f"  [DEBUG] {json.dumps(dados_contrato, ensure_ascii=False)[:600]}"
                    )

                itens_raw = []
                if sequencial:
                    itens_raw = self._buscar_itens_pncp(
                        cnpj, ano_arp, compra_seq, ata_seq, sequencial, debug
                    )
                self.stdout.write(f"    Itens: {len(itens_raw)}")

                if dry_run:
                    resumo["contratos_criados"] += 1
                    resumo["itens_criados"] += len(itens_raw)
                    continue

                with transaction.atomic():
                    contrato_obj, criado, ignorado = self._importar_contrato(
                        dados_contrato, arp, uasg, numero_contrato, uasg_contratante, atualizar
                    )
                    if ignorado:
                        resumo["contratos_ignorados"] += 1
                        self.stdout.write("    Ignorado (use --atualizar)")
                        continue
                    if criado:
                        resumo["contratos_criados"] += 1
                        self.stdout.write(self.style.SUCCESS("    CRIADO"))
                    else:
                        resumo["contratos_atualizados"] += 1
                        self.stdout.write(self.style.WARNING("    ATUALIZADO"))

                    for item_raw in itens_raw:
                        r = self._importar_item(item_raw, contrato_obj, itens_arp_db, atualizar)
                        resumo[f"itens_{r}s"] = resumo.get(f"itens_{r}s", 0) + 1

        self._imprimir_resumo(resumo, dry_run)

    # ------------------------------------------------------------------
    # dadosabertos
    # ------------------------------------------------------------------

    def _consultar_dadosabertos(self, endpoint, params_base, debug=False):
        """Consulta paginada genérica para dadosabertos."""
        resultados = []
        pagina = 1
        while True:
            params = {**params_base, "pagina": pagina, "tamanhoPagina": TAMANHO_PAGINA}
            url = f"{BASE_DB}{endpoint}"
            try:
                resp = requests.get(url, params=params, timeout=TIMEOUT)
                if debug:
                    self.stdout.write(
                        f"\n  [DEBUG] GET {url} pagina={pagina} → HTTP {resp.status_code}"
                    )
                    try:
                        self.stdout.write(
                            json.dumps(resp.json(), indent=2, ensure_ascii=False)[:3000]
                        )
                    except Exception:
                        self.stdout.write(resp.text[:500])
                if resp.status_code != 200:
                    self.stdout.write(
                        self.style.WARNING(f"  dadosabertos {endpoint}: HTTP {resp.status_code}")
                    )
                    return resultados
                payload = resp.json()
            except requests.RequestException as exc:
                self.stdout.write(self.style.ERROR(f"  Erro dadosabertos: {exc}"))
                return resultados

            if isinstance(payload, list):
                resultados.extend(payload)
                break
            if isinstance(payload, dict):
                dados = (
                    payload.get("resultado")
                    or payload.get("data")
                    or payload.get("itens")
                    or payload.get("content")
                    or []
                )
                resultados.extend(dados)
                if (not dados
                        or payload.get("paginasRestantes", 0) == 0
                        or len(dados) < TAMANHO_PAGINA):
                    break
                pagina += 1
            else:
                break
        return resultados

    def _buscar_contratos_dadosabertos(self, uasg, ano_inicio, ano_fim, debug=False):
        params = {
            "codigoUnidadeGerenciadora": uasg,
            "dataAssinaturaMin": f"{ano_inicio}-01-01",
            "dataAssinaturaMax": f"{ano_fim}-12-31",
        }
        for ep in [
            "/modulo-contrato/1_consultarContrato",
            "/modulo-arp/3_consultarContratosARP",
            "/modulo-arp/3_consultarContratoARP",
        ]:
            self.stdout.write(f"  Tentando: {ep}")
            dados = self._consultar_dadosabertos(ep, params, debug)
            if dados:
                self.stdout.write(
                    self.style.SUCCESS(f"  Endpoint: {ep} ({len(dados)} registros)")
                )
                return dados
        return []

    def _buscar_itens_dadosabertos(self, uasg, ano_inicio, ano_fim, debug=False):
        """Retorna dict: '{numeroContrato}|{uasg}' → [itens]."""
        params = {
            "codigoUnidadeGerenciadora": uasg,
            "dataAssinaturaMin": f"{ano_inicio}-01-01",
            "dataAssinaturaMax": f"{ano_fim}-12-31",
        }
        for ep in [
            "/modulo-contrato/2_consultarItemContrato",
            "/modulo-arp/4_consultarItensContratosARP",
            "/modulo-arp/4_consultarItemContratosARP",
        ]:
            dados = self._consultar_dadosabertos(ep, params, debug)
            if dados:
                self.stdout.write(
                    self.style.SUCCESS(f"  Itens via: {ep} ({len(dados)} itens)")
                )
                por_contrato = {}
                for it in dados:
                    chave = (
                        str(it.get("numeroContrato") or it.get("numero") or "")
                        + "|"
                        + str(it.get("codigoUnidadeGerenciadora") or uasg)
                    )
                    por_contrato.setdefault(chave, []).append(it)
                return por_contrato
        return {}

    def _processar_contratos(self, contratos_raw, itens_por_contrato, arps_db, uasg,
                              atualizar, dry_run, resumo):
        for dados_contrato in contratos_raw:
            numero_arp_api = (
                dados_contrato.get("numeroAtaRegistroPreco")
                or dados_contrato.get("numeroAta")
                or dados_contrato.get("codigoAta")
                or ""
            )
            numero_contrato = (
                dados_contrato.get("numeroContrato")
                or dados_contrato.get("numero")
                or dados_contrato.get("numeroAjuste")
                or ""
            )
            uasg_contratante = str(
                dados_contrato.get("codigoUnidadeGerenciadora") or uasg
            )

            if not numero_arp_api:
                resumo["contratos_ignorados"] += 1
                continue

            arp_obj = arps_db.get(_normalizar_numero_arp(numero_arp_api))
            if not arp_obj:
                self.stdout.write(self.style.WARNING(
                    f"  ARP {numero_arp_api} (normalizado: {_normalizar_numero_arp(numero_arp_api)}) "
                    f"não encontrada no banco."
                ))
                resumo["contratos_ignorados"] += 1
                continue

            self.stdout.write(
                f"\n  → Contrato {numero_contrato or '?'} | ARP {numero_arp_api} | UASG {uasg_contratante}"
            )

            chave = f"{numero_contrato}|{uasg_contratante}"
            itens_raw = itens_por_contrato.get(chave, [])
            self.stdout.write(f"    Itens: {len(itens_raw)}")

            if dry_run:
                resumo["contratos_criados"] += 1
                resumo["itens_criados"] += len(itens_raw)
                continue

            itens_arp_db = {i.numero_item: i for i in arp_obj.itens.all()}

            with transaction.atomic():
                contrato_obj, criado, ignorado = self._importar_contrato(
                    dados_contrato, arp_obj, uasg, numero_contrato, uasg_contratante, atualizar
                )
                if ignorado:
                    resumo["contratos_ignorados"] += 1
                    self.stdout.write("    Ignorado (use --atualizar)")
                    continue
                if criado:
                    resumo["contratos_criados"] += 1
                    self.stdout.write(self.style.SUCCESS("    CRIADO"))
                else:
                    resumo["contratos_atualizados"] += 1
                    self.stdout.write(self.style.WARNING("    ATUALIZADO"))

                for item_raw in itens_raw:
                    r = self._importar_item(item_raw, contrato_obj, itens_arp_db, atualizar)
                    resumo[f"itens_{r}s"] = resumo.get(f"itens_{r}s", 0) + 1

    # ------------------------------------------------------------------
    # PNCP REST API
    # ------------------------------------------------------------------

    def _buscar_contratos_pncp(self, cnpj, ano, compra_seq, ata_seq, debug=False):
        candidatos = [
            f"{PNCP_API}/orgaos/{cnpj}/compras/{ano}/{compra_seq}/atas/{ata_seq}/contratos",
            f"{PNCP_API}/orgaos/{cnpj}/compras/{ano}/{compra_seq}/contratos",
        ]
        for url in candidatos:
            try:
                resp = requests.get(url, timeout=TIMEOUT)
                if debug:
                    self.stdout.write(f"\n  [DEBUG] GET {url} → HTTP {resp.status_code}")
                    try:
                        self.stdout.write(
                            json.dumps(resp.json(), indent=2, ensure_ascii=False)[:3000]
                        )
                    except Exception:
                        self.stdout.write(resp.text[:500])
                if resp.status_code == 200:
                    payload = resp.json()
                    if isinstance(payload, list):
                        return payload
                    if isinstance(payload, dict):
                        return (
                            payload.get("data")
                            or payload.get("resultado")
                            or payload.get("content")
                            or payload.get("itens")
                            or []
                        )
                elif debug:
                    self.stdout.write(f"  HTTP {resp.status_code} — próximo.")
            except requests.RequestException as exc:
                if debug:
                    self.stdout.write(f"  Erro: {exc}")
        return []

    def _buscar_itens_pncp(self, cnpj, ano, compra_seq, ata_seq, contrato_seq, debug=False):
        candidatos = [
            f"{PNCP_API}/orgaos/{cnpj}/compras/{ano}/{compra_seq}/atas/{ata_seq}/contratos/{contrato_seq}/itens",
            f"{PNCP_API}/orgaos/{cnpj}/compras/{ano}/{compra_seq}/contratos/{contrato_seq}/itens",
        ]
        for url in candidatos:
            try:
                resp = requests.get(url, timeout=TIMEOUT)
                if debug:
                    self.stdout.write(f"\n    [DEBUG] Itens: GET {url} → HTTP {resp.status_code}")
                    try:
                        self.stdout.write(
                            json.dumps(resp.json(), indent=2, ensure_ascii=False)[:2000]
                        )
                    except Exception:
                        self.stdout.write(resp.text[:300])
                if resp.status_code == 200:
                    payload = resp.json()
                    if isinstance(payload, list):
                        return payload
                    if isinstance(payload, dict):
                        return (
                            payload.get("data")
                            or payload.get("resultado")
                            or payload.get("itens")
                            or []
                        )
            except requests.RequestException as exc:
                if debug:
                    self.stdout.write(f"    [DEBUG] Erro itens: {exc}")
        return []

    # ------------------------------------------------------------------
    # Persistência
    # ------------------------------------------------------------------

    def _importar_contrato(self, dados, arp_obj, uasg_gerenciador, numero_contrato,
                            uasg_contratante, atualizar):
        """Retorna (contrato_obj, criado, ignorado)."""
        fornecedor = dados.get("fornecedor") or {}
        contratado_cnpj = str(
            fornecedor.get("cnpjCpf") or fornecedor.get("ni")
            or dados.get("niFornecedor") or ""
        )[:20]
        contratado_nome = str(
            fornecedor.get("razaoSocial") or fornecedor.get("nome")
            or dados.get("nomeFornecedor") or dados.get("nomeRazaoSocialFornecedor") or ""
        )[:255]
        unidade = dados.get("unidadeOrgao") or {}
        nome_uasg = str(
            unidade.get("nomeUnidade") or unidade.get("nome")
            or dados.get("nomeUnidadeGerenciadora") or ""
        )[:255]
        data_assinatura = self._parse_data(
            dados.get("dataAssinatura") or dados.get("dataPublicacao")
        )
        data_inicio = self._parse_data(
            dados.get("vigenciaInicio") or dados.get("dataInicioVigencia")
            or dados.get("dataInicio")
        )
        data_fim = self._parse_data(
            dados.get("vigenciaFim") or dados.get("dataFimVigencia")
            or dados.get("dataFim") or dados.get("dataVencimento")
        )
        valor_total = self._parse_decimal(
            dados.get("valorInicial") or dados.get("valorGlobal")
            or dados.get("valorTotal") or dados.get("valor")
        )
        numero_pncp = str(
            dados.get("numeroControlePncpContrato") or dados.get("numeroPncp") or ""
        )[:100]
        is_carona = str(uasg_contratante) != str(uasg_gerenciador)

        defaults = {
            "contratado_cnpj": contratado_cnpj,
            "contratado_nome": contratado_nome,
            "uasg_contratante": str(uasg_contratante)[:10],
            "nome_uasg_contratante": nome_uasg,
            "data_assinatura": data_assinatura,
            "data_inicio_vigencia": data_inicio,
            "data_fim_vigencia": data_fim,
            "valor_total": valor_total,
            "numero_pncp": numero_pncp,
            "is_carona": is_carona,
        }

        numero_banco = str(numero_contrato or f"SEM-NUMERO-ARP{arp_obj.pk}")

        contrato, criado = ContratoARP.objects.get_or_create(
            arp=arp_obj,
            numero_contrato=numero_banco,
            uasg_contratante=str(uasg_contratante)[:10],
            defaults=defaults,
        )
        if not criado and not atualizar:
            return contrato, False, True
        if not criado and atualizar:
            for campo, valor in defaults.items():
                setattr(contrato, campo, valor)
            contrato.save()
            return contrato, False, False
        return contrato, True, False

    def _importar_item(self, item_raw, contrato_obj, itens_arp_db, atualizar):
        try:
            numero_item = int(
                item_raw.get("numeroItem") or item_raw.get("numero")
                or item_raw.get("item") or 0
            )
        except (TypeError, ValueError):
            return "ignorado"
        if not numero_item:
            return "ignorado"

        descricao = str(
            item_raw.get("descricao") or item_raw.get("descricaoItem")
            or item_raw.get("nomePdm") or ""
        )
        unidade = str(
            item_raw.get("unidadeFornecimento") or item_raw.get("siglaUnidade")
            or item_raw.get("unidade") or ""
        )
        qtd = self._parse_decimal(
            item_raw.get("quantidadeContratada") or item_raw.get("quantidade")
        )
        vl_unit = self._parse_decimal(
            item_raw.get("valorUnitario") or item_raw.get("valorUnitarioContratado")
        )
        vl_total = self._parse_decimal(item_raw.get("valorTotal") or item_raw.get("valor"))
        if vl_total == Decimal("0") and qtd and vl_unit:
            vl_total = qtd * vl_unit

        item_arp = itens_arp_db.get(numero_item)

        defaults = {
            "item_arp": item_arp,
            "descricao": descricao,
            "unidade": unidade,
            "quantidade_contratada": qtd,
            "valor_unitario": vl_unit,
            "valor_total": vl_total,
        }

        obj, criado = ItemContratoARP.objects.get_or_create(
            contrato=contrato_obj,
            numero_item=numero_item,
            defaults=defaults,
        )
        if not criado and atualizar:
            for campo, valor in defaults.items():
                setattr(obj, campo, valor)
            obj.save()
            return "atualizado"
        return "criado" if criado else "ignorado"

    # ------------------------------------------------------------------
    # Utilitários
    # ------------------------------------------------------------------

    def _imprimir_resumo(self, resumo, dry_run):
        self.stdout.write(f"\n{'='*60}")
        self.stdout.write(self.style.SUCCESS(
            f"{'DRY-RUN — ' if dry_run else ''}Importação concluída:\n"
            f"  Contratos criados:     {resumo['contratos_criados']}\n"
            f"  Contratos atualizados: {resumo['contratos_atualizados']}\n"
            f"  Contratos ignorados:   {resumo.get('contratos_ignorados', 0)}\n"
            f"  Itens criados:         {resumo['itens_criados']}\n"
            f"  Itens atualizados:     {resumo.get('itens_atualizados', 0)}"
        ))

    def _parse_data(self, valor):
        if not valor:
            return None
        s = str(valor).strip()
        for fmt in ["%Y-%m-%d", "%d/%m/%Y"]:
            try:
                return datetime.strptime(s[:10], fmt).date()
            except ValueError:
                continue
        try:
            return datetime.strptime(s[:19], "%Y-%m-%dT%H:%M:%S").date()
        except ValueError:
            pass
        return None

    def _parse_decimal(self, valor):
        if valor is None:
            return Decimal("0")
        try:
            return Decimal(str(valor).replace(",", ".").strip())
        except InvalidOperation:
            return Decimal("0")
