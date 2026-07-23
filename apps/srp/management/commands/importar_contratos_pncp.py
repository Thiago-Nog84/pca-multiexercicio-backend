"""
Importa/completa dados de contratos a partir da API do PNCP, casando pelo
número do contrato/empenho com os registros locais (Contrato e ContratoARP).

Contexto (2026-07-23): o botão "Ver Instrumento" da tela da ARP não tinha
como abrir o contrato assinado de verdade — só a ata de origem ou o site do
MPPI (busca manual), porque os registros locais quase nunca têm `numero_pncp`
preenchido (só foi possível descobrir manualmente pra 1 contrato até agora).
Testado ao vivo (rede real): o PNCP tem um endpoint que lista TODOS os
contratos de uma ata:

    GET https://pncp.gov.br/api/pncp/v1/orgaos/{cnpj}/compras/{ano}/{compra}/atas/{ata}/contratos

Cada item traz `numeroContratoEmpenho` (bate com `Contrato.numero_contrato`/
`ContratoARP.numero_contrato`, com normalização) e `numeroControle` (o valor
certo pra `numero_pncp` — formato "cnpj-modalidade-sequencial/ano"). Depois de
gravado, `_resolver_instrumento_contrato` (apps/srp/views.py) já sabe montar o
link do PDF real do contrato assinado a partir desse campo — não precisa de
mais nada além de rodar este comando.

Este comando percorre as ARPs com `numero_controle_pncp_ata` preenchido,
busca a lista de contratos de cada uma, casa por número (normalizado) contra
os registros locais, e grava:
  - numero_pncp (sempre que vazio)
  - vigência (só quando vazia local)
  - valor (só quando o campo local estiver zerado — NUNCA sobrescreve valor
    já preenchido, dado financeiro é sensível)

Regra de segurança: NUNCA sobrescreve dado já preenchido — só completa o que
está faltando (mesmo padrão de `reconciliar_contratada_arp`). Contratos do
PNCP sem correspondência local, e ARPs sem resposta da API, são listados no
final pra revisão manual — nada é criado silenciosamente.

Uso:
    python manage.py importar_contratos_pncp [--arp <pk>] [--dry-run] [--debug]
"""

import json
import re
import time
import urllib.error
import urllib.request
from datetime import datetime

from django.core.management.base import BaseCommand
from django.db import transaction

from apps.contratos.models import Contrato
from apps.srp.models import AtaRegistroPrecos, ContratoARP


def _normalizar_numero(numero):
    """
    Extrai o primeiro grupo numérico "significativo" de um número de
    contrato pra comparação tolerante a formatos diferentes (ex:
    "29/2026/PGJ" -> "29", "00035" -> "35", "00035/2026" -> "35").
    """
    if not numero:
        return ""
    m = re.match(r"^0*(\d+)", str(numero).strip())
    return m.group(1) if m else str(numero).strip().lower()


def _parse_data(valor):
    """Converte 'YYYY-MM-DD' (ou com hora) vindo do PNCP em date, ou None."""
    if not valor:
        return None
    try:
        return datetime.strptime(valor[:10], "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return None


class Command(BaseCommand):
    help = "Importa numero_pncp/vigência/valor dos contratos a partir da API do PNCP (lista de contratos por ata)."

    def add_arguments(self, parser):
        parser.add_argument("--arp", type=int, help="Restringe a uma ARP específica (pk)")
        parser.add_argument("--dry-run", action="store_true")
        parser.add_argument("--debug", action="store_true")

    def handle(self, *args, **opts):
        qs = AtaRegistroPrecos.objects.exclude(numero_controle_pncp_ata="")
        if opts.get("arp"):
            qs = qs.filter(pk=opts["arp"])

        total_arps = qs.count()
        self.stdout.write(f"Processando {total_arps} ARP(s) com numero_controle_pncp_ata preenchido...\n")

        atualizados = 0
        nao_casados = []
        arps_com_erro = []

        with transaction.atomic():
            for arp in qs:
                contratos_pncp = self._buscar_contratos_pncp(arp, opts["debug"])
                if contratos_pncp is None:
                    arps_com_erro.append(arp.numero_arp)
                    continue
                if not contratos_pncp:
                    continue

                locais = list(Contrato.objects.filter(arp_origem=arp)) + list(
                    ContratoARP.objects.filter(arp=arp)
                )
                locais_por_norm = {}
                for loc in locais:
                    locais_por_norm.setdefault(_normalizar_numero(loc.numero_contrato), []).append(loc)

                for cp in contratos_pncp:
                    norm = _normalizar_numero(cp.get("numeroContratoEmpenho"))
                    candidatos = locais_por_norm.get(norm, [])
                    if not candidatos:
                        nao_casados.append(
                            f"ARP {arp.numero_arp}: contrato PNCP "
                            f"{cp.get('numeroContratoEmpenho')!r} (seq {cp.get('sequencialContrato')}) "
                            f"sem correspondência local"
                        )
                        continue
                    for loc in candidatos:
                        mudancas = self._atualizar_registro(loc, cp)
                        if mudancas:
                            atualizados += 1
                            self.stdout.write(
                                f"  ARP {arp.numero_arp} — {loc.numero_contrato}: {mudancas}"
                            )
                            if not opts["dry_run"]:
                                loc.save()

            if opts["dry_run"]:
                transaction.set_rollback(True)

        modo = "[DRY-RUN — nada gravado] " if opts["dry_run"] else ""
        self.stdout.write(self.style.SUCCESS(f"\n{modo}{atualizados} registro(s) atualizado(s)."))
        if nao_casados:
            self.stdout.write(self.style.WARNING(f"\n{len(nao_casados)} contrato(s) do PNCP sem correspondência local:"))
            for n in nao_casados[:40]:
                self.stdout.write(f"  - {n}")
        if arps_com_erro:
            self.stdout.write(self.style.ERROR(f"\nFalha ao consultar PNCP para: {', '.join(arps_com_erro)}"))

    def _buscar_contratos_pncp(self, arp, debug):
        """
        Retorna a lista de contratos da ata (via API do PNCP), [] se a ata
        não tiver contratos, ou None se não deu pra consultar (erro/formato).
        """
        valor = (arp.numero_controle_pncp_ata or "").strip()
        try:
            cnpj, _modalidade, compra_ano, ata_seq = valor.split("-")
            compra_seq, ano = compra_ano.split("/")
        except (ValueError, AttributeError):
            if debug:
                self.stdout.write(f"  [debug] ARP {arp.numero_arp}: numero_controle_pncp_ata em formato inesperado: {valor!r}")
            return None

        url = (
            f"https://pncp.gov.br/api/pncp/v1/orgaos/{cnpj}/compras/"
            f"{int(ano)}/{int(compra_seq)}/atas/{int(ata_seq)}/contratos"
        )
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0", "Accept": "application/json"})
            with urllib.request.urlopen(req, timeout=20) as resp:
                data = json.loads(resp.read())
            if debug:
                self.stdout.write(f"  [debug] {url} -> {data.get('totalRegistros')} contrato(s)")
            time.sleep(0.3)  # gentileza com a API pública
            return data.get("data", [])
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                return []
            self.stdout.write(self.style.WARNING(f"  Erro HTTP {exc.code} em {url}"))
            return None
        except Exception as exc:
            self.stdout.write(self.style.WARNING(f"  Erro em {url}: {exc}"))
            return None

    def _atualizar_registro(self, loc, cp):
        """
        Preenche campos VAZIOS do registro local com dados do PNCP. Nunca
        sobrescreve dado já preenchido. Retorna string descrevendo o que
        mudou, ou None se nada mudou.
        """
        mudancas = []

        if not (loc.numero_pncp or "").strip() and cp.get("numeroControle"):
            loc.numero_pncp = cp["numeroControle"]
            mudancas.append(f"numero_pncp={cp['numeroControle']}")

        if not loc.data_inicio_vigencia:
            d = _parse_data(cp.get("dataVigenciaInicio"))
            if d:
                loc.data_inicio_vigencia = d
                mudancas.append(f"data_inicio_vigencia={d}")

        if not loc.data_fim_vigencia:
            d = _parse_data(cp.get("dataVigenciaFim"))
            if d:
                loc.data_fim_vigencia = d
                mudancas.append(f"data_fim_vigencia={d}")

        valor_pncp = cp.get("valorGlobal")
        if valor_pncp:
            if isinstance(loc, Contrato):
                if not loc.valor_atual:
                    loc.valor_atual = valor_pncp
                    mudancas.append(f"valor_atual={valor_pncp}")
                if not loc.valor_inicial:
                    loc.valor_inicial = valor_pncp
                    mudancas.append(f"valor_inicial={valor_pncp}")
            else:
                if not loc.valor_total:
                    loc.valor_total = valor_pncp
                    mudancas.append(f"valor_total={valor_pncp}")

        if not mudancas:
            return None
        return ", ".join(mudancas)
