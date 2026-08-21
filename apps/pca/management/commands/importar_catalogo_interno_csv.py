"""
Importa o Catalogo Interno para ItemCatalogo a partir do NOVO formato de
export em CSV (substitui a planilha .xlsx que "importar_catalogo_interno"
le — ver aquele comando para o formato antigo).

Fonte: export CSV do catalogo interno, ex.:
    catalogo_interno-export-AAAA-MM-DD_HH-MM-SS.csv
Colunas (separadas por ';'): id;nome;descricao;tipo;codigo;grupo;ativo;
    exercicio;ordem_exibicao;created_at;updated_at;created_by;updated_by;
    valor_estimado

Regras:
- Chave de idempotencia: (descricao_padrao=NOME, codigo_catmat_catser=CODIGO,
  descricao_detalhada=DESCRICAO). Diferente do importador da planilha antiga
  (que usava so NOME+CODIGO): neste export o mesmo par nome/codigo se repete
  para itens genuinamente distintos — ex. "Locacao de imovel" com o mesmo
  codigo PDM aparece uma vez por imovel, cada um com uma descricao (endereco)
  diferente. Usar so nome+codigo colapsaria esses itens em um so.
  Re-execucoes do mesmo CSV atualizam em vez de duplicar; duplicatas exatas
  (mesmo nome+codigo+descricao) sao puladas.
- codigo_catalogo gerado sequencialmente: CONT-FORN-NNN (Material) /
  CONT-SERV-NNN (Servico), continuando a numeracao ja existente no banco
  (mesma convencao do importador da planilha antiga).
- GRUPO normalizado (variacoes de caixa/acento sao unificadas pela primeira
  ocorrencia no arquivo).
- ATIVO: "true"/"false" (string) conforme a coluna do CSV.
- Categoria inferida de TIPO + GRUPO (heuristica conservadora — revisar
  depois, mesma logica do importador da planilha antiga, com dois grupos
  adicionais que so existem neste export):
    grupo contendo "permanente"                          -> material_permanente
    grupo contendo "software"                             -> software
    Servico + grupo contendo "curso"/"capacitacao"/
      "qualificacao"/"eventos, cursos e capacitacao"       -> treinamento
    Material + grupo tipicamente permanente (lista fixa)  -> material_permanente
    Material (demais)                                     -> material
    Servico (demais)                                      -> servico

Uso:
    python manage.py importar_catalogo_interno_csv --arquivo caminho\\catalogo_interno-export-....csv --dry-run
    python manage.py importar_catalogo_interno_csv --arquivo caminho\\catalogo_interno-export-....csv
"""

import csv
import re
import unicodedata
from decimal import Decimal, InvalidOperation

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.pca.models import ItemCatalogo

GRUPOS_PERMANENTES = [
    "mobiliario",
    "eletroeletronico",
    "eletrodomestico",
    "informatica - equipamentos",
    "informatica - infraestrutura",
    "veiculos",
    "seguranca eletronica",
]

GRUPOS_TREINAMENTO = [
    "eventos, cursos e capacitacao",
    "curso",
    "capacitacao",
    "qualificacao",
]

CAMPOS_ESPERADOS = {"id", "nome", "descricao", "tipo", "codigo", "grupo", "ativo", "valor_estimado"}


def _sem_acento(texto):
    return unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode("ascii")


def _parse_decimal(valor):
    valor = (valor or "").strip()
    if not valor:
        return None
    try:
        return Decimal(valor)
    except InvalidOperation:
        return None


class Command(BaseCommand):
    help = "Importa o export CSV (novo formato) do Catalogo Interno para ItemCatalogo."

    def add_arguments(self, parser):
        parser.add_argument("--arquivo", required=True, help="Caminho do .csv (separado por ';').")
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Mostra o que seria feito (criados/atualizados/duplicatas) sem gravar no banco.",
        )

    # ------------------------------------------------------------------
    def _categoria(self, tipo, grupo):
        g = _sem_acento(grupo or "").lower()
        if "permanente" in g:
            return "material_permanente"
        if "software" in g:
            return "software"
        if tipo == "servico":
            if any(chave in g for chave in GRUPOS_TREINAMENTO):
                return "treinamento"
            return "servico"
        for perm in GRUPOS_PERMANENTES:
            if perm in g:
                return "material_permanente"
        return "material"

    # ------------------------------------------------------------------
    def handle(self, *args, **opts):
        caminho = opts["arquivo"]
        dry_run = opts["dry_run"]

        try:
            arquivo = open(caminho, encoding="utf-8-sig", newline="")
        except OSError as exc:
            raise CommandError(f"Nao consegui abrir o arquivo: {exc}")

        with arquivo:
            reader = csv.DictReader(arquivo, delimiter=";")
            faltando = CAMPOS_ESPERADOS - set(reader.fieldnames or [])
            if faltando:
                raise CommandError(
                    f"O CSV nao tem as colunas esperadas: {', '.join(sorted(faltando))}"
                )

            # Continuar numeracao de codigos ja existente por prefixo
            usados = {}
            for cod in ItemCatalogo.objects.values_list("codigo_catalogo", flat=True):
                m = re.match(r"^(CONT-[A-Z]+)-(\d+)$", cod)
                if m:
                    pref, num = m.group(1), int(m.group(2))
                    usados[pref] = max(usados.get(pref, 0), num)

            def proximo_codigo(prefixo):
                n = usados.get(prefixo, 0) + 1
                usados[prefixo] = n
                return f"{prefixo}-{n:03d}"

            grupos_canonicos = {}  # casefold sem acento -> forma canonica (1a ocorrencia)
            vistos = set()         # (nome, codigo, descricao) ja processados nesta execucao
            criados = atualizados = pulados_dup = avisos = 0
            por_categoria = {}

            with transaction.atomic():
                for i, linha in enumerate(reader, start=2):  # linha 1 e o cabecalho
                    nome = (linha.get("nome") or "").strip()
                    if not nome:
                        continue
                    descricao = (linha.get("descricao") or "").strip()
                    tipo_raw = (linha.get("tipo") or "").strip().lower()
                    codigo = (linha.get("codigo") or "").strip()
                    grupo_raw = (linha.get("grupo") or "").strip()
                    ativo = (linha.get("ativo") or "").strip().lower() != "false"
                    valor = _parse_decimal(linha.get("valor_estimado"))

                    # descricao_padrao tem limite de 300 caracteres no modelo.
                    # Algumas linhas na origem vieram com nome/descricao trocados
                    # (o texto longo da especificacao caiu na coluna "nome").
                    if len(nome) > 300:
                        avisos += 1
                        if descricao and len(descricao) <= 300:
                            self.stderr.write(
                                f"  linha {i}: nome com {len(nome)} caracteres — parece trocado "
                                f"com a descricao na origem; invertendo os dois campos"
                            )
                            nome, descricao = descricao, nome
                        else:
                            self.stderr.write(
                                f"  linha {i}: nome com {len(nome)} caracteres — truncado para 300"
                            )
                            nome = nome[:300]

                    if tipo_raw.startswith("material"):
                        tipo = "material"
                    elif tipo_raw.startswith("servi"):
                        tipo = "servico"
                    else:
                        avisos += 1
                        self.stderr.write(f"  linha {i}: tipo vazio/desconhecido ({tipo_raw!r}) — assumindo material")
                        tipo = "material"

                    if not codigo:
                        avisos += 1
                        self.stderr.write(f"  linha {i}: sem codigo PDM/CATSER ({nome[:50]})")

                    # Grupo canonico (unifica variacoes de caixa/acento)
                    chave_g = _sem_acento(grupo_raw).casefold()
                    if chave_g and chave_g not in grupos_canonicos:
                        grupos_canonicos[chave_g] = grupo_raw
                    grupo = grupos_canonicos.get(chave_g, "")

                    chave = (nome, codigo, descricao)
                    if chave in vistos:
                        pulados_dup += 1
                        continue
                    vistos.add(chave)

                    categoria = self._categoria(tipo, grupo)
                    por_categoria[categoria] = por_categoria.get(categoria, 0) + 1

                    defaults = {
                        "descricao_detalhada": descricao,
                        "categoria": categoria,
                        "grupo": grupo,
                        "valor_referencia": valor,
                        "ativo": ativo,
                    }
                    obj = ItemCatalogo.objects.filter(
                        descricao_padrao=nome,
                        codigo_catmat_catser=codigo,
                        descricao_detalhada=descricao,
                    ).first()
                    if obj:
                        for campo, v in defaults.items():
                            setattr(obj, campo, v)
                        obj.save(update_fields=list(defaults))
                        atualizados += 1
                    else:
                        prefixo = "CONT-FORN" if tipo == "material" else "CONT-SERV"
                        ItemCatalogo.objects.create(
                            codigo_catalogo=proximo_codigo(prefixo),
                            descricao_padrao=nome,
                            codigo_catmat_catser=codigo,
                            **defaults,
                        )
                        criados += 1

                if dry_run:
                    transaction.set_rollback(True)

        modo = "[DRY-RUN — nada gravado] " if dry_run else ""
        self.stdout.write(self.style.SUCCESS(
            f"{modo}Criados: {criados} | Atualizados: {atualizados} | "
            f"Duplicatas puladas: {pulados_dup} | Avisos: {avisos}"
        ))
        self.stdout.write("Distribuicao por categoria (heuristica — revisar):")
        for cat, qtd in sorted(por_categoria.items(), key=lambda x: -x[1]):
            self.stdout.write(f"  {cat}: {qtd}")
