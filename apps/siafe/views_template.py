"""Views Django Templates — Módulo SIAFE."""

import logging
import re
from decimal import Decimal, InvalidOperation

from django.contrib.auth.decorators import login_required
from django.shortcuts import render
from django.utils.decorators import method_decorator
from django.views import View

from .client import SiafeClient, SiafeAPIError

logger = logging.getLogger(__name__)

# Mapeamento UG → nome legível
UG_NOMES = {
    "250101": "PGJ — Procuradoria-Geral de Justiça",
    "250102": "FUNDMPE — Fundo de Modernização do MPPI",
    "250104": "FPDC — Fundo de Proteção dos Direitos da Criança",
}


def _parse_valor(valor_raw) -> Decimal:
    """Converte string ou número SIAFE para Decimal."""
    if valor_raw is None:
        return Decimal("0")
    if isinstance(valor_raw, (int, float)):
        return Decimal(str(valor_raw))
    limpo = re.sub(r"[R$\s]", "", str(valor_raw)).replace(".", "").replace(",", ".")
    try:
        return Decimal(limpo)
    except InvalidOperation:
        return Decimal("0")


def _enrich_nes(nes: list) -> list:
    """Adiciona campo valor_decimal e ordena por data de emissão (desc)."""
    for ne in nes:
        ne["valor_decimal"] = _parse_valor(ne.get("valor"))
    return sorted(nes, key=lambda n: n.get("dataEmissao") or "", reverse=True)


@method_decorator(login_required, name="dispatch")
class NotasEmpenhoUGView(View):
    """
    GET /siafe/nota-empenho/<exercicio>/<codigo_ug>/
    Exibe as Notas de Empenho de uma UG em página HTML.
    """
    template_name = "siafe/notas_empenho.html"

    def get(self, request, exercicio, codigo_ug):
        ug_nome = UG_NOMES.get(str(codigo_ug), f"UG {codigo_ug}")
        nes = []
        erro = None
        total_empenhado = Decimal("0")
        total_anulado = Decimal("0")

        try:
            nes_raw = SiafeClient().nota_empenho_por_ug(exercicio, str(codigo_ug))
            nes = _enrich_nes(nes_raw)
            for ne in nes:
                tipo = (ne.get("tipoAlteracaoNE") or "").upper()
                if tipo == "ANULACAO":
                    total_anulado += ne["valor_decimal"]
                else:
                    total_empenhado += ne["valor_decimal"]
        except SiafeAPIError as exc:
            logger.warning("SIAFE template error [%s]: %s", exc.status_code, exc.detail)
            erro = f"Falha ao consultar o SIAFE-PI (HTTP {exc.status_code}): {exc.detail}"
        except Exception as exc:
            logger.exception("Erro inesperado ao consultar SIAFE para template")
            erro = f"Erro interno: {exc}"

        total_liquido = total_empenhado - total_anulado

        context = {
            "exercicio": exercicio,
            "codigo_ug": codigo_ug,
            "ug_nome": ug_nome,
            "nes": nes,
            "total_empenhado": total_empenhado,
            "total_anulado": total_anulado,
            "total_liquido": total_liquido,
            "erro": erro,
        }
        return render(request, self.template_name, context)
