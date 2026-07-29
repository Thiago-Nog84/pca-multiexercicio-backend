"""
Management command: inferir_fonte_contratos_via_tcepi
====================================================
Preenche `Contrato.unidade_orcamentaria` para contratos sem sufixo
reconhecível no número (os que `inferir_fonte_contratos` não consegue
resolver por regex) cruzando o CNPJ do contratado contra a lista de
credores do TCE-PI (Portal da Cidadania) em cada órgão do MPPI (pgj/fmmp/
fepdc).

Método (mesmo raciocínio que resolveu o caso EPSG em 2026-07-29 via
`conciliar_tcepi`): se o CNPJ do contrato aparece na lista de credores de
UM SÓ órgão do TCE nos exercícios testados, é praticamente certo que esse é
o órgão certo — fornecedor de um contrato SRP do MPPI dificilmente presta
serviço simultâneo para os 3 fundos com o mesmo CNPJ sem já ter outro
contrato próprio classificado. Se aparecer em MAIS DE UM órgão, ou em
NENHUM, fica sem decisão automática (listado para revisão manual) — nunca
adivinha.

Nunca sobrescreve `unidade_orcamentaria` já preenchido.

Exercícios testados por contrato: ano de `data_assinatura` até o ano atual
(cobre contratos plurianuais cuja execução continua depois da assinatura).

Uso:
  python manage.py inferir_fonte_contratos_via_tcepi --dry-run
  python manage.py inferir_fonte_contratos_via_tcepi
"""

import re
from datetime import date

from django.core.management.base import BaseCommand

from apps.contratos.models import Contrato
from apps.tcepi.client import CODIGOS_UG_MPPI, TcePiAPIError, TcePiClient


def _digitos(valor) -> str:
    return re.sub(r"\D", "", str(valor or ""))


class Command(BaseCommand):
    help = "Preenche unidade_orcamentaria cruzando CNPJ do contrato contra credores do TCE-PI (somente preenche vazios)"

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true")
        parser.add_argument("--saida", type=str, default=None)

    def handle(self, *args, **options):
        arquivo_saida = None
        if options.get("saida"):
            arquivo_saida = open(options["saida"], "w", encoding="utf-8")
            escrever_original = self.stdout.write

            def escrever_e_gravar(msg="", *a, **kw):
                escrever_original(msg, *a, **kw)
                arquivo_saida.write(str(msg) + "\n")

            self.stdout.write = escrever_e_gravar

        dry_run = options["dry_run"]
        client = TcePiClient()
        ano_atual = date.today().year

        candidatos = Contrato.objects.filter(unidade_orcamentaria="").exclude(contratado_cnpj_cpf="")
        self.stdout.write(f"{candidatos.count()} contrato(s) sem unidade_orcamentaria e com CNPJ/CPF preenchido.\n")

        # Cache (orgao_key, ano) -> {cnpj_digitos: credor_dict}, buscado sob demanda.
        cache_credores = {}

        def mapa_credores(orgao_key: str, ano: int) -> dict:
            chave = (orgao_key, ano)
            if chave not in cache_credores:
                codigo_ug = CODIGOS_UG_MPPI[orgao_key]
                try:
                    lista = client.credores_orgao_lista_completa(codigo_ug, ano)
                except TcePiAPIError as exc:
                    self.stdout.write(self.style.WARNING(f"  [erro TCE] {orgao_key}/{ano}: {exc}"))
                    lista = []
                cache_credores[chave] = {
                    _digitos(c.get("documento")): c for c in lista if _digitos(c.get("documento"))
                }
            return cache_credores[chave]

        resolvidos = 0
        ambiguos = []
        nao_encontrados = []

        for contrato in candidatos:
            cnpj = _digitos(contrato.contratado_cnpj_cpf)
            if not cnpj:
                continue

            ano_inicio = contrato.data_assinatura.year if contrato.data_assinatura else ano_atual
            anos = range(min(ano_inicio, ano_atual), ano_atual + 1)

            orgaos_encontrados = set()
            evidencia = {}
            for orgao_key in CODIGOS_UG_MPPI:
                for ano in anos:
                    m = mapa_credores(orgao_key, ano)
                    if cnpj in m:
                        orgaos_encontrados.add(orgao_key)
                        evidencia[orgao_key] = (ano, m[cnpj])
                        break  # já achou nesse órgão, não precisa testar outros anos

            if len(orgaos_encontrados) == 1:
                orgao_key = next(iter(orgaos_encontrados))
                ano, credor = evidencia[orgao_key]
                self.stdout.write(
                    f"  pk={contrato.pk} {contrato.numero_contrato!r} ({contrato.contratado_razao_social[:40]}): "
                    f"-> {orgao_key!r} (achado no TCE {ano}, credor {credor.get('nome')})"
                )
                if not dry_run:
                    contrato.unidade_orcamentaria = orgao_key
                    contrato.save(update_fields=["unidade_orcamentaria"])
                resolvidos += 1
            elif len(orgaos_encontrados) > 1:
                ambiguos.append((contrato, orgaos_encontrados))
                self.stdout.write(self.style.WARNING(
                    f"  pk={contrato.pk} {contrato.numero_contrato!r}: AMBIGUO — achado em {orgaos_encontrados}, não decide sozinho."
                ))
            else:
                nao_encontrados.append(contrato)

        modo = "[DRY-RUN — nada gravado] " if dry_run else ""
        self.stdout.write(self.style.SUCCESS(
            f"\n{modo}Resolvidos: {resolvidos} | Ambíguos (mais de 1 órgão): {len(ambiguos)} | "
            f"Não encontrados em nenhum órgão do TCE: {len(nao_encontrados)}"
        ))

        if nao_encontrados:
            self.stdout.write("\nNão encontrados no TCE (CNPJ não aparece como credor em nenhum dos 3 órgãos/anos testados):")
            for c in nao_encontrados[:40]:
                self.stdout.write(f"  pk={c.pk} {c.numero_contrato!r} — CNPJ {c.contratado_cnpj_cpf} — {c.contratado_razao_social[:50]}")
            if len(nao_encontrados) > 40:
                self.stdout.write(f"  ... e mais {len(nao_encontrados) - 40}")

        if arquivo_saida:
            arquivo_saida.close()
