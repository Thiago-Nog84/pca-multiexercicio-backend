"""
Management command: revisar_duplicatas_contrato
====================================================
SOMENTE LEITURA. Mostra, lado a lado, os detalhes completos de cada grupo de
contratos duplicados (mesmo CNPJ + mesmo valor_inicial) achado pela
auditoria (auditar_consistencia_srp, checagem [duplicados]) — pra decidir
qual registro é o correto e qual é o lixo antes de mesclar/apagar.

Causa raiz mais comum (corrigida em importar_contratos_siafe_api.py em
2026-07-29): um contrato já cadastrado manualmente (via PNCP/planilha) sem
`codigo_siafe` preenchido não era encontrado pela checagem antiga
(`Contrato.objects.filter(codigo_siafe=cod)`), e o import criava um SEGUNDO
registro com numero_contrato = codigo_siafe (fallback). O daqui pra frente
já está blindado; este comando serve pra limpar o que já existe.

Não apaga nada — só lista. A decisão e o comando de exclusão ficam para
depois de você confirmar qual manter em cada par.

Uso:
  python manage.py revisar_duplicatas_contrato
"""

import re
from decimal import Decimal

from django.core.management.base import BaseCommand

from apps.contratos.models import Contrato
from apps.srp.models import ContratacaoDecorrente


def _digitos(valor) -> str:
    return re.sub(r"\D", "", str(valor or ""))


class Command(BaseCommand):
    help = "Lista, com detalhes completos, os grupos de contratos duplicados (somente leitura)"

    def handle(self, *args, **options):
        grupos = {}
        for c in Contrato.objects.all():
            cnpj = _digitos(c.contratado_cnpj_cpf)
            if not cnpj or not c.valor_inicial:
                continue
            grupos.setdefault((cnpj, c.valor_inicial), []).append(c)

        pares = {k: v for k, v in grupos.items() if len(v) >= 2}
        if not pares:
            self.stdout.write(self.style.SUCCESS("Nenhum grupo duplicado encontrado."))
            return

        self.stdout.write(f"{len(pares)} grupo(s) duplicado(s):\n")

        for i, ((cnpj, valor), lista) in enumerate(sorted(pares.items()), 1):
            self.stdout.write(self.style.MIGRATE_HEADING(
                f"\n[{i}] CNPJ {cnpj} · R$ {valor:,.2f} · {len(lista)} registros"
            ))
            for c in lista:
                # Sinaliza suspeita de ser o registro "lixo" criado pelo bug:
                # numero_contrato == codigo_siafe (fallback quando não havia
                # numeroOriginal na resposta do SIAFE).
                suspeito_fallback = bool(c.codigo_siafe) and c.numero_contrato == c.codigo_siafe
                n_cds = ContratacaoDecorrente.objects.filter(numero_pedido=c.numero_contrato).count()
                arp_origem = c.arp_origem.numero_arp if c.arp_origem_id else "—"
                self.stdout.write(
                    f"  pk={c.pk:6d} | numero_contrato={c.numero_contrato!r:30s} | "
                    f"codigo_siafe={c.codigo_siafe or '—':15s} | numero_sei={c.numero_sei or '—':25s}"
                )
                self.stdout.write(
                    f"           status={c.status:12s} | assinatura={c.data_assinatura} | "
                    f"arp_origem={arp_origem} | contratacoes_decorrentes={n_cds}"
                    + ("  ⚠ suspeito de ser o duplicata (numero_contrato = codigo_siafe)" if suspeito_fallback else "")
                )
                self.stdout.write(f"           objeto: {(c.objeto or '')[:100]}")

        self.stdout.write(self.style.WARNING(
            "\nNenhuma alteração foi feita — este comando é só leitura. "
            "Me diga, por grupo, qual registro manter (geralmente o que tem numero_sei "
            "preenchido e/ou arp_origem correto) que eu preparo a mesclagem."
        ))
