"""
Management command: sincronizar_instrumentos_pncp
==================================================
Busca automaticamente, no PNCP, os INSTRUMENTOS contratuais (PDF do contrato
assinado) e os TERMOS (aditivos e apostilamentos) de cada contrato local, e
grava:
  - `Contrato.link_contrato`  ← URL do PDF do instrumento (documento "Contrato");
  - `Contrato.numero_pncp`    ← quando resolvido via dadosabertos (estava vazio);
  - registros `Aditivo` / `Apostilamento` ← a partir de /contratos/.../termos.

Como resolve o ID PNCP de cada contrato (cnpj-tipo-seq/ano):
  1. Usa `Contrato.numero_pncp` se já estiver preenchido.
  2. Senão, consulta o dadosabertos Módulo Contratos (campo
     `numeroControlePncpContrato`), casando por número de contrato normalizado
     + CNPJ do fornecedor — só aceita quando ambos batem (nunca adivinha).
     Cobre contratos com vigência inicial em 2026+ (limite da base).

Endpoints PNCP confirmados ao vivo (2026-07-30):
  - GET /orgaos/{cnpj}/contratos/{ano}/{seq}/arquivos → lista de documentos
    (cada um com `url` e `tipoDocumentoNome`: "Contrato", "Termo Aditivo"…).
  - GET /orgaos/{cnpj}/contratos/{ano}/{seq}/termos → aditivos/apostilamentos
    estruturados (HTTP 204 quando não há nenhum). Campo `tipoTermoContratoNome`
    distingue "Termo Aditivo" de "Termo de Apostilamento".

Limitação honesta: contratos que o MPPI NÃO publica no PNCP (só existem no SEI,
ex.: 05/2026/PGJ da NTSEC, cuja numeração interna não corresponde à SIASG) não
têm instrumento em fonte pública — o comando os lista como "sem PNCP" para
tratamento manual (upload do PDF).

⚠️ Os modelos Aditivo/Apostilamento têm `save()` que ATUALIZA o contrato
(valor_atual/saldo/vigência). Por isso a criação é idempotente (get_or_create
por número) — rodar o comando de novo não aplica o mesmo termo duas vezes.

Uso:
    python manage.py sincronizar_instrumentos_pncp --dry-run
    python manage.py sincronizar_instrumentos_pncp --numero 00039/2026
    python manage.py sincronizar_instrumentos_pncp
"""

import re
from datetime import datetime
from decimal import Decimal, InvalidOperation

import requests
from django.core.management.base import BaseCommand
from django.db import transaction

from apps.contratos.models import Aditivo, Apostilamento, Contrato

PNCP_API = "https://pncp.gov.br/api/pncp/v1"
DADOS_URL = "https://dadosabertos.compras.gov.br/modulo-contratos/1_consultarContratos"
CODIGO_ORGAO = 94252          # MPPI (SIASG) — ver dadosabertos_contratos.py
UASG = 926092
TIMEOUT = 25


def _parse_pncp(numero):
    """cnpj-tipo-seq/ano → (cnpj, ano, seq) ou None."""
    m = re.match(r"(\d{14})-(\d+)-(\d+)/(\d{4})", (numero or "").strip())
    if not m:
        return None
    return m.group(1), m.group(4), int(m.group(3))


def _norm(numero):
    """Núcleo NN/AAAA sem zeros à esquerda (00036/2026 == 36/2026)."""
    if not numero:
        return ""
    m = re.search(r"(\d+)\s*[/\-]\s*(\d{4})", numero)
    if not m:
        return re.sub(r"\D", "", numero)
    return f"{int(m.group(1))}/{m.group(2)}"


def _dec(v):
    if v is None:
        return None
    try:
        return Decimal(str(v))
    except (InvalidOperation, TypeError):
        return None


def _data(v):
    if not v:
        return None
    try:
        return datetime.strptime(str(v)[:10], "%Y-%m-%d").date()
    except ValueError:
        return None


class Command(BaseCommand):
    help = "Busca no PNCP o PDF do instrumento e os aditivos/apostilamentos de cada contrato."

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true", help="Simula sem gravar.")
        parser.add_argument("--numero", type=str, help="Só o contrato com este número (ex: 00039/2026).")
        parser.add_argument("--limit", type=int, help="Processa no máximo N contratos.")

    def handle(self, *args, **options):
        dry = options["dry_run"]
        if dry:
            self.stdout.write(self.style.WARNING("*** DRY-RUN — nada será gravado ***\n"))

        qs = Contrato.objects.all().order_by("numero_contrato")
        if options["numero"]:
            qs = qs.filter(numero_contrato=options["numero"])
        if options["limit"]:
            qs = qs[: options["limit"]]

        self._cache_dados = {}   # ano -> lista de contratos do dadosabertos
        resumo = {
            "processados": 0, "sem_pncp": 0, "pncp_resolvido_dados": 0,
            "instrumentos": 0, "aditivos": 0, "apostilamentos": 0, "erros": 0,
        }
        sem_pncp = []

        with transaction.atomic():
            for contrato in qs:
                resumo["processados"] += 1
                try:
                    self._processar(contrato, dry, resumo, sem_pncp)
                except Exception as exc:  # noqa: BLE001 — não deixa 1 contrato derrubar o lote
                    resumo["erros"] += 1
                    self.stdout.write(self.style.ERROR(
                        f"  [ERRO] {contrato.numero_contrato}: {exc}"
                    ))

            if dry:
                transaction.set_rollback(True)

        # ── Resumo ──
        self.stdout.write("\n" + "=" * 60)
        self.stdout.write(self.style.SUCCESS(
            f"{'DRY-RUN — ' if dry else ''}Concluído: {resumo['processados']} contrato(s).\n"
            f"  PDFs de instrumento gravados: {resumo['instrumentos']}\n"
            f"  Aditivos criados:             {resumo['aditivos']}\n"
            f"  Apostilamentos criados:       {resumo['apostilamentos']}\n"
            f"  PNCP resolvido via dadosabertos: {resumo['pncp_resolvido_dados']}\n"
            f"  Sem PNCP (tratar manual):     {resumo['sem_pncp']}\n"
            f"  Erros:                        {resumo['erros']}"
        ))
        if sem_pncp:
            self.stdout.write("\n  Contratos sem instrumento em fonte pública (só SEI?):")
            for n in sem_pncp:
                self.stdout.write(f"    - {n}")

    # ------------------------------------------------------------------
    def _processar(self, contrato, dry, resumo, sem_pncp):
        pncp = self._resolver_pncp(contrato, dry, resumo)
        if not pncp:
            resumo["sem_pncp"] += 1
            sem_pncp.append(contrato.numero_contrato)
            return
        cnpj, ano, seq = pncp

        # 1) Instrumento (PDF do documento "Contrato")
        arquivos = self._get_json(f"/orgaos/{cnpj}/contratos/{ano}/{seq}/arquivos") or []
        doc = next(
            (a for a in arquivos if (a.get("tipoDocumentoNome") or "").strip().lower() == "contrato"),
            None,
        ) or (arquivos[0] if arquivos else None)
        if doc and doc.get("url") and not (contrato.link_contrato or "").strip():
            self.stdout.write(f"  [INSTRUMENTO] {contrato.numero_contrato} ← {doc.get('titulo') or 'Contrato'}")
            if not dry:
                contrato.link_contrato = doc["url"]
                contrato.save(update_fields=["link_contrato"])
            resumo["instrumentos"] += 1

        # 2) Termos (aditivos / apostilamentos)
        termos = self._get_json(f"/orgaos/{cnpj}/contratos/{ano}/{seq}/termos") or []
        for t in termos:
            self._processar_termo(contrato, t, dry, resumo)

    # ------------------------------------------------------------------
    def _processar_termo(self, contrato, t, dry, resumo):
        tipo_nome = (t.get("tipoTermoContratoNome") or "").lower()
        seq = t.get("sequencialTermoContrato") or 0
        num_pncp_termo = t.get("numeroTermoContrato") or ""
        data_ass = _data(t.get("dataAssinatura")) or _data(t.get("dataPublicacaoPncp"))
        objeto = (t.get("objetoTermoContrato") or t.get("informativoObservacao") or "").strip()
        vig_fim = _data(t.get("dataVigenciaFim"))
        valor_acr = _dec(t.get("valorAcrescido")) or Decimal("0")
        valor_global = _dec(t.get("valorGlobal"))

        if "apostilamento" in tipo_nome:
            if Apostilamento.objects.filter(contrato=contrato, numero_apostilamento=seq).exists():
                return
            tipo = "reajuste" if t.get("qualificacaoReajuste") else "correcao_erro"
            self.stdout.write(
                f"  [APOSTILAMENTO {seq}] {contrato.numero_contrato}: {objeto[:50]}"
            )
            resumo["apostilamentos"] += 1
            if not dry:
                Apostilamento.objects.create(
                    contrato=contrato,
                    numero_apostilamento=seq,
                    tipo=tipo,
                    data_apostilamento=data_ass or contrato.data_assinatura,
                    valor_anterior=contrato.valor_atual or Decimal("0"),
                    valor_novo=(valor_global if valor_global is not None else (contrato.valor_atual or Decimal("0"))),
                    descricao=objeto or "Apostilamento importado do PNCP",
                )
        else:
            # trata como Termo Aditivo
            if Aditivo.objects.filter(contrato=contrato, numero_aditivo=seq).exists():
                return
            muda_prazo = bool(t.get("qualificacaoVigencia")) or (t.get("prazoAditadoDias") or 0) > 0
            muda_valor = bool(t.get("qualificacaoAcrescimoSupressao")) or valor_acr != 0
            if muda_prazo and muda_valor:
                tipo = "prazo_valor"
            elif muda_prazo:
                tipo = "prazo"
            elif muda_valor:
                tipo = "supressao" if valor_acr < 0 else "valor"
            else:
                tipo = "objeto"
            base = contrato.valor_inicial or Decimal("0")
            pct = (valor_acr / base * 100).quantize(Decimal("0.01")) if base else Decimal("0")
            self.stdout.write(
                f"  [ADITIVO {seq}] {contrato.numero_contrato} ({tipo}): "
                f"acréscimo R${valor_acr} nova_vig={vig_fim} — {objeto[:40]}"
            )
            resumo["aditivos"] += 1
            if not dry:
                Aditivo.objects.create(
                    contrato=contrato,
                    numero_aditivo=seq,
                    tipo=tipo,
                    data_assinatura=data_ass or contrato.data_assinatura,
                    nova_data_fim_vigencia=vig_fim if muda_prazo else None,
                    valor_acrescimo=valor_acr,
                    percentual_acrescimo=pct,
                    numero_pncp=num_pncp_termo,
                    objeto_aditivo=objeto or "Termo aditivo importado do PNCP",
                )

    # ------------------------------------------------------------------
    def _resolver_pncp(self, contrato, dry, resumo):
        p = _parse_pncp(contrato.numero_pncp)
        if p:
            return p
        # tenta via dadosabertos Módulo Contratos
        ano_ref = (contrato.data_assinatura or contrato.data_inicio_vigencia).year \
            if (contrato.data_assinatura or getattr(contrato, "data_inicio_vigencia", None)) else None
        if not ano_ref:
            return None
        candidatos = self._dados_ano(ano_ref)
        alvo = _norm(contrato.numero_contrato)
        cnpj_local = re.sub(r"\D", "", contrato.contratado_cnpj_cpf or "")
        for c in candidatos:
            if c.get("contratoExcluido"):
                continue
            if _norm(c.get("numeroContrato")) != alvo:
                continue
            cnpj_api = re.sub(r"\D", "", str(c.get("niFornecedor") or ""))
            if cnpj_local and cnpj_api and cnpj_local != cnpj_api:
                continue
            p = _parse_pncp(c.get("numeroControlePncpContrato"))
            if p:
                resumo["pncp_resolvido_dados"] += 1
                if not dry and not (contrato.numero_pncp or "").strip():
                    contrato.numero_pncp = c["numeroControlePncpContrato"]
                    contrato.save(update_fields=["numero_pncp"])
                return p
        return None

    def _dados_ano(self, ano):
        if ano in self._cache_dados:
            return self._cache_dados[ano]
        params = {
            "codigoOrgao": CODIGO_ORGAO, "codigoUnidadeGestora": UASG,
            "dataVigenciaInicialMin": f"{ano}-01-01", "dataVigenciaInicialMax": f"{ano}-12-31",
            "pagina": 1, "tamanhoPagina": 200,
        }
        resultado = []
        try:
            r = requests.get(DADOS_URL, params=params, timeout=TIMEOUT)
            if r.status_code == 200:
                resultado = r.json().get("resultado", [])
        except (requests.RequestException, ValueError):
            resultado = []
        self._cache_dados[ano] = resultado
        return resultado

    def _get_json(self, path):
        """GET no PNCP; retorna lista/dict ou None (inclui 204 → None)."""
        try:
            r = requests.get(f"{PNCP_API}{path}", timeout=TIMEOUT,
                             headers={"User-Agent": "Mozilla/5.0", "Accept": "application/json"})
        except requests.RequestException:
            return None
        if r.status_code == 204 or not r.content:
            return None
        if r.status_code != 200:
            return None
        try:
            return r.json()
        except ValueError:
            return None
