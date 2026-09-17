"""
Serviços de negócio (mutations/commands) para o módulo Planejamento.
Executa operações de escrita protegidas por transações atômicas com tipagem estrita (PEP 484).
"""
from typing import Any, Dict
from django.db import transaction
from django.core.exceptions import ValidationError
from .models import DocumentoOficializacaoDemanda, ETP, TermoReferencia


@transaction.atomic
def abrir_processo_dod(dod: DocumentoOficializacaoDemanda) -> DocumentoOficializacaoDemanda:
    """
    Avança o status do DOD de 'rascunho' para 'aberto', formalizando o processo.
    """
    if not dod.itens.exists():
        raise ValidationError("O DOD não possui itens do PCA vinculados.")
    dod.status = "aberto"
    dod.save(update_fields=["status"])
    return dod


@transaction.atomic
def cancelar_processo_dod(dod: DocumentoOficializacaoDemanda) -> DocumentoOficializacaoDemanda:
    """
    Cancela o processo do DOD e libera os itens para outros processos.
    """
    dod.status = "cancelado"
    dod.save(update_fields=["status"])
    return dod


@transaction.atomic
def avancar_status_etp(etp: ETP, novo_status: str) -> ETP:
    """Avança o ciclo de aprovação do ETP."""
    status_validos = [s[0] for s in ETP.STATUS]
    if novo_status not in status_validos:
        raise ValidationError(f"Status '{novo_status}' inválido para ETP.")
    etp.status = novo_status
    etp.save(update_fields=["status", "atualizado_em"])
    return etp


@transaction.atomic
def avancar_status_tr(tr: TermoReferencia, novo_status: str) -> TermoReferencia:
    """Avança o ciclo de aprovação do Termo de Referência."""
    status_validos = [s[0] for s in TermoReferencia.STATUS]
    if novo_status not in status_validos:
        raise ValidationError(f"Status '{novo_status}' inválido para TR.")
    tr.status = novo_status
    tr.save(update_fields=["status", "atualizado_em"])
    return tr
