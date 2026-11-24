"""Exact GGUF variants shared by search, size filters, and download selection."""
from server.modules.huggingface_gguf import gguf_compatibility, variants_from_info, quantization_label


def catalog_from_info(info):
    return variants_from_info("", info)["variants"]


def apply_catalog(model, catalog):
    model["ggufVariants"] = catalog
    model["inferredTags"] = [tag for tag in model["inferredTags"] if tag["kind"] != "quantization"]
    labels = sorted({variant["quantization"] for variant in catalog if quantization_label(variant["quantization"])})
    model["inferredTags"].extend({"kind": "quantization", "value": label} for label in labels)


def enrich_search_model(model, info):
    from server.modules.huggingface_metadata import cached_gguf_catalog
    model["compatibility"], model["warning"] = gguf_compatibility(info)
    model["inferredTags"].append({"kind": "compatibility", "value": "GGUF"})
    catalog = cached_gguf_catalog(model["repoId"], model["revision"])
    if catalog is None and getattr(info, "siblings", None) is not None:
        catalog = catalog_from_info(info)
    if catalog is not None:
        apply_catalog(model, catalog)
    else:
        model["inferredTags"] = [tag for tag in model["inferredTags"] if tag["kind"] != "quantization"]
