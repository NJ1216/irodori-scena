"""Portable identities of optional downloads; never import application startup code."""
import ast
import re


def static_value(node, values):
    if isinstance(node, ast.Constant):
        return node.value
    if isinstance(node, ast.Name):
        return values[node.id]
    if isinstance(node, (ast.Tuple, ast.List)):
        items = [static_value(item, values) for item in node.elts]
        return tuple(items) if isinstance(node, ast.Tuple) else items
    if isinstance(node, ast.JoinedStr):
        return "".join(str(static_value(item.value, values)) if isinstance(item, ast.FormattedValue) else item.value for item in node.values)
    if isinstance(node, ast.BinOp) and isinstance(node.op, (ast.Add, ast.Mult)):
        left, right = static_value(node.left, values), static_value(node.right, values)
        return left + right if isinstance(node.op, ast.Add) else left * right
    raise ValueError("Not a supported static catalogue expression")


def catalog_literal(tree, field):
    for node in ast.walk(tree):
        if not isinstance(node, ast.Dict):
            continue
        for key, value in zip(node.keys, node.values):
            if isinstance(key, ast.Constant) and key.value == field:
                return ast.literal_eval(value.orelse if isinstance(value, ast.IfExp) else value)
    raise ValueError(f"Missing static catalogue field: {field}")


def runtime_entries(root):
    values = {}
    tree = ast.parse((root / "server/modules/tts_catalog.py").read_text())
    for node in tree.body:
        if isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name):
            try:
                values[node.targets[0].id] = static_value(node.value, values)
            except (KeyError, ValueError, TypeError):
                pass
    identities = [(values["ENGINE_REPO"], values["ENGINE_COMMIT"], "github")]
    identities.extend((spec[0], spec[2], "huggingface") for spec in values["MODEL_SPECS"])
    large_tree = ast.parse((root / "server/modules/tts_large_assets.py").read_text())
    large = {node.targets[0].id: ast.literal_eval(node.value) for node in large_tree.body if isinstance(node, ast.Assign)}
    identities.append((large["LARGE_QUANTIZED_REPO"], large["LARGE_QUANTIZED_REVISION"], "huggingface"))
    identities.extend([(catalog_literal(tree, "codecRepo"), values["CODEC_REVISION"], "huggingface"), (catalog_literal(tree, "tokenizerRepo"), catalog_literal(tree, "tokenizerRevision"), "huggingface")])
    for name, version, provider in identities:
        host = "github.com" if provider == "github" else "huggingface.co"
        yield {"id": f"download:{name}@{version}", "ecosystem": provider, "name": name, "version": version, "source": f"https://{host}/{name}/tree/{version}", "license": "SEE MODEL OR ENGINE TERMS", "scope": "runtime-download", "status": "needs-review"}, []
    for line in (root / "tools/omlx-runtime-requirements.txt").read_text().splitlines():
        if "==" in line and not line.startswith("#"):
            name, version = line.split("==", 1)
            yield {"id": f"download:pypi:{name}@{version}", "ecosystem": "pypi", "name": name, "version": version, "source": f"https://pypi.org/project/{name}/{version}/", "license": "UNKNOWN", "scope": "runtime-download"}, []
        match = re.fullmatch(r"(.+) @ git\+https://github.com/(.+)\.git@([a-f0-9]{40})", line)
        if match:
            name, repo, version = match.groups()
            yield {"id": f"download:{name}@{version}", "ecosystem": "github", "name": name, "version": version, "source": f"https://github.com/{repo}/tree/{version}", "license": "SEE ENGINE TERMS", "scope": "runtime-download", "status": "needs-review"}, []
