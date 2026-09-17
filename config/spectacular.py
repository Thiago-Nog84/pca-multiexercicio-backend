"""
Configurações e hooks customizados para o drf-spectacular (Swagger / OpenAPI).
"""


def split_tags_by_app(result, generator, request, public):
    """
    Hook de pós-processamento do OpenAPI.
    Agrupa os endpoints no Swagger UI de acordo com as aplicações de domínio,
    em vez de agrupá-los todos genericamente sob o prefixo 'v1'.
    """
    tag_map = {
        "pca": "PCA",
        "planejamento": "Planejamento",
        "licitacao": "Licitação",
        "srp": "SRP",
        "contratos": "Contratos",
        "siafe": "SIAFE",
        "core": "Core",
    }

    for path, path_item in result.get("paths", {}).items():
        for method, operation in path_item.items():
            if not isinstance(operation, dict):
                continue
            if path.startswith("/api/v1/"):
                parts = path.split("/")
                if len(parts) > 3:
                    app_key = parts[3].lower()
                    tag_name = tag_map.get(app_key, app_key.capitalize())
                    operation["tags"] = [tag_name]
            elif "/auth/" in path:
                operation["tags"] = ["Autenticação"]
            elif "/schema/" in path:
                operation["tags"] = ["Documentação"]

    return result
