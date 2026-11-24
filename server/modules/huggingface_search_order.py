"""Hub ranking and local alphabetical ordering of the bounded candidate set."""
from server.app_deps import HTTPException


def hub_search_order(order):
    choices = {"downloads": "downloads", "likes": "likes", "name": "downloads", "default": None}
    if order not in choices:
        raise HTTPException(422, "検索の並び順が不正です。")
    return choices[order]


def order_search_results(models, order):
    if order == "name":
        return sorted(models, key=lambda model: (model["displayName"].casefold(), model["repoId"].casefold()))
    return models
