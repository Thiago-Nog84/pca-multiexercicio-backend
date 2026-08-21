"""
Corrige os codigos PDM/CATSER dos itens do catalogo interno apontados como
"NAO ENCONTRADO" por `validar_codigos_catalogo` (execucao de 2026-08-21:
13 codigos invalidos, de 1217 itens totais).

Cada codigo novo foi pesquisado manualmente no portal oficial de busca por
texto livre (https://catalogo.compras.gov.br/cnbs-web/busca) em 2026-08-21 —
a API dadosabertos.compras.gov.br usada por catalogo_gov.py NAO tem busca por
descricao livre, so por codigo ou navegacao de grupo/classe, entao essa etapa
nao da para automatizar.

Descobertas relevantes:
- Os codigos 11248, 8715 e 2276 estavam cada um duplicado em dois itens
  distintos e sem relacao (ex.: 8715 usado tanto em "Geradores" quanto em
  "Manutencao Preventiva e Corretiva de Motores-Geradores") -- fortes
  indicios de erro de copia-e-cola na origem, nao de itens genuinamente
  sem catalogacao.
- O codigo 14805 (usado em "GPU (Placa de Video)") EXISTE na base oficial,
  mas corresponde a outro item ("Placa de captura de video"). O correto
  (PDM 235, "Placa controladora video") esta na mesma classe (7060).
- Tres itens (GPU, Geradores, Rastreador veicular) vieram categorizados como
  "servico" no catalogo interno mas sao materiais -- isso faz o validador
  (`validar_codigos_catalogo`) restringir a busca oficial a CATSER e nunca
  achar o PDM correto. A categoria desses tres foi corrigida junto para
  "material_permanente".
- Nao foi encontrado candidato adequado para CONT-SERV-288 "Telefonia Movel
  e Dados" (codigo antigo 1412): o catalogo oficial nao tem um item unico
  de pacote voz+dados, trata cada tipo de chamada separadamente. Fica de
  fora desta correcao ate pesquisa mais aprofundada.

Uso:
    python manage.py corrigir_codigos_catalogo_gov --dry-run
    python manage.py corrigir_codigos_catalogo_gov
"""

from django.core.management.base import BaseCommand
from django.db import transaction

from apps.pca.models import ItemCatalogo

# codigo_catalogo (chave unica e estavel) -> correcao.
# Chave por codigo_catalogo (nao por codigo_catmat_catser antigo) porque
# varios dos codigos antigos estavam duplicados entre itens diferentes --
# corrigir pelo codigo antigo aplicaria o mesmo codigo novo aos dois.
CORRECOES = {
    "CONT-FORN-517": {
        "codigo": "8435",
        "nota": "PDM 'Notebook' (classe 7010) — código antigo 640476 não existe na base oficial",
    },
    "CONT-FORN-531": {
        "codigo": "8435",
        "nota": "PDM 'Notebook' — mesmo PDM genérico; código antigo 158642 não existe (catálogo oficial não distingue 'corporativo')",
    },
    "CONT-SERV-269": {
        "codigo": "235",
        "categoria": "material_permanente",
        "nota": "PDM 'Placa controladora vídeo' (classe 7060) — código antigo 14805 existe mas é outro item (Placa de captura de vídeo)",
    },
    "CONT-SERV-224": {
        "codigo": "30127",
        "nota": "CATSER 'Seguro automotivo' (grupo 713) — código antigo 2276 era placeholder duplicado (mesmo código de CONT-SERV-250)",
    },
    "CONT-SERV-296": {
        "codigo": "2356",
        "nota": "CATSER 'Manutenção de grupos diesel gerador de emergência' (grupo 871) — código antigo 8715 era placeholder duplicado (mesmo código de CONT-SERV-185)",
    },
    "CONT-SERV-312": {
        "codigo": "19747",
        "nota": "CATSER 'Instalação/manutenção — energia solar fotovoltaica' (grupo 871) — código antigo 6783 não existe",
    },
    "CONT-SERV-185": {
        "codigo": "8113",
        "categoria": "material_permanente",
        "nota": "PDM 'Grupo diesel gerador' (material, classe 6115) — código antigo 8715 era placeholder duplicado",
    },
    "CONT-SERV-250": {
        "codigo": "14537",
        "categoria": "material_permanente",
        "nota": "PDM 'Rastreador' (material, classe 5811) — código antigo 2276 era placeholder duplicado; não há serviço equivalente de monitoramento no catálogo oficial",
    },
    "CONT-SERV-136": {
        "codigo": "26050",
        "nota": "CATSER 'Infraestrutura como serviço — IaaS' (grupo 131) — código antigo 11248 era placeholder duplicado (mesmo código de CONT-SERV-143)",
    },
    "CONT-SERV-282": {
        "codigo": "26050",
        "nota": "CATSER 'Infraestrutura como serviço — IaaS' (grupo 131) — código antigo 1311 não existe",
    },
    "CONT-SERV-143": {
        "codigo": "27502",
        "nota": "CATSER 'Cessão temporária de direitos sobre programas de computador / locação de software' (grupo 182) — código antigo 11248 era placeholder duplicado (mesmo código de CONT-SERV-136); escolhido em vez de SaaS (26077) por refletir melhor uma assinatura anual sem cessão permanente",
    },
    "CONT-SERV-268": {
        "codigo": "21172",
        "nota": "CATSER 'Treinamento qualificação profissional' (grupo 929) — código antigo 253729 não existe; item genérico demais para um código único exato",
    },
}


class Command(BaseCommand):
    help = "Corrige os códigos PDM/CATSER dos 13 itens NÃO ENCONTRADO da validação de 2026-08-21."

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true",
                            help="Mostra o que seria alterado sem gravar.")

    def handle(self, *args, **opts):
        dry_run = opts["dry_run"]
        corrigidos = 0
        nao_encontrados = 0

        with transaction.atomic():
            for codigo_catalogo, correcao in CORRECOES.items():
                obj = ItemCatalogo.objects.filter(codigo_catalogo=codigo_catalogo).first()
                if not obj:
                    nao_encontrados += 1
                    self.stderr.write(f"  [não encontrado no banco] {codigo_catalogo}")
                    continue

                codigo_antigo = obj.codigo_catmat_catser
                categoria_antiga = obj.categoria
                obj.codigo_catmat_catser = correcao["codigo"]
                update_fields = ["codigo_catmat_catser"]
                if "categoria" in correcao:
                    obj.categoria = correcao["categoria"]
                    update_fields.append("categoria")

                linha = (
                    f"  {codigo_catalogo} — {obj.descricao_padrao[:50]}\n"
                    f"      código: '{codigo_antigo}' -> '{correcao['codigo']}'"
                )
                if "categoria" in correcao:
                    linha += f"\n      categoria: '{categoria_antiga}' -> '{correcao['categoria']}'"
                linha += f"\n      {correcao['nota']}"
                self.stdout.write(linha)

                if not dry_run:
                    obj.save(update_fields=update_fields)
                corrigidos += 1

            if dry_run:
                transaction.set_rollback(True)

        modo = "[DRY-RUN — nada gravado] " if dry_run else ""
        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS(
            f"{modo}Corrigidos: {corrigidos} | Não encontrados no banco: {nao_encontrados}"
        ))
        self.stdout.write(
            "Fora desta correção (sem candidato encontrado): CONT-SERV-288 "
            "'Telefonia Móvel e Dados' (código 1412) — precisa de pesquisa manual."
        )
