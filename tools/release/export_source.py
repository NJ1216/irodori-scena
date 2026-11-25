"""Export reviewed files only; never copy the development Git database."""
import argparse
import fnmatch
import hashlib
import json
import os
import shutil
import subprocess
from pathlib import Path

from privacy import audit_file, public_bytes, safe_name

ROOT = Path(__file__).resolve().parents[2]
# Owner-local list of names, hosts and folders that must never be published; shared with the global github-push skill, never committed.
DEFAULT_PRIVATE_TERMS = Path.home() / ".config" / "github-push" / "private-terms.txt"


def classification_findings(tracked, published, excluded):
    """Every tracked file must be published or explicitly excluded, never both."""
    for entry in excluded:
        if not entry.get("pattern") or not entry.get("reason"):
            raise ValueError("Each exclusion needs a pattern and a reason")
    findings = []
    for name in tracked:
        hidden = any(fnmatch.fnmatchcase(name, entry["pattern"]) for entry in excluded)
        if name in published and hidden:
            findings.append({"file": name, "kind": "published-and-excluded"})
        elif name not in published and not hidden:
            findings.append({"file": name, "kind": "unclassified"})
    return findings


def tracked_files(root):
    """Tracked paths of a development checkout; None for an exported snapshot without Git."""
    result = subprocess.run(["git", "-C", str(root), "ls-files", "-z"], capture_output=True)
    if result.returncode != 0 or not (root / ".git").exists():
        return None
    return [name for name in result.stdout.decode("utf-8").split("\0") if name]


def audit(root, manifest, private_terms=()):
    findings = []
    for name in manifest["files"]:
        if not (root / name).is_file():
            findings.append({"file": name, "kind": "missing"})
            continue
        findings.extend(audit_file(root, name, manifest.get("exceptions"), private_terms))
    return findings


def publication_terms(args, manifest):
    """Private terms to audit with; a public export also requires them and committed published files."""
    terms_file = args.private_terms or (DEFAULT_PRIVATE_TERMS if args.public_base else None)
    if args.public_base and not (terms_file and terms_file.is_file()):
        raise SystemExit("Public publication needs the owner's private terms file; pass --private-terms")
    if args.public_base and tracked_files(ROOT) is not None:
        dirty = subprocess.run(["git", "-C", str(ROOT), "status", "--porcelain", "--", *manifest["files"]], check=True, capture_output=True, text=True).stdout
        if dirty.strip():
            raise SystemExit("Published files have uncommitted changes; commit them before a public export")
    return terms_file.read_text().splitlines() if terms_file else []


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("destination", nargs="?", type=Path)
    parser.add_argument("--draft", action="store_true", help="Allow incomplete public metadata; never commit")
    parser.add_argument("--private-terms", type=Path, help="Local-only newline-separated names or secrets; never copied")
    parser.add_argument("--public-base", help="Public repository URL; append one snapshot commit to its main instead of a new history")
    args = parser.parse_args()
    manifest = json.loads((ROOT / "release-files.json").read_text())
    private_terms = publication_terms(args, manifest)
    findings = audit(ROOT, manifest, private_terms)
    tracked = tracked_files(ROOT)
    if tracked is not None:
        # The development checkout lists its unpublished files; a published snapshot has none.
        exclusions = ROOT / "release-private.json"
        excluded = json.loads(exclusions.read_text())["excluded"] if exclusions.exists() else []
        findings.extend(classification_findings(tracked, set(manifest["files"]), excluded))
    print(json.dumps({"files": len(manifest["files"]), "findings": findings}, indent=2))
    if findings:
        raise SystemExit(1)
    if not args.destination:
        return
    destination = args.destination.resolve()
    if destination.exists() or destination == ROOT or ROOT in destination.parents:
        raise SystemExit("Destination must be a new directory outside the development repository")
    report = destination.parent / f"{destination.name}.sha256.json"
    if report.exists():
        raise SystemExit("Hash report already exists; choose a new destination")
    if not args.draft:
        subprocess.run(["node", "tools/release/check.mjs", "--publication"], cwd=ROOT, check=True)
    if args.public_base:
        base_sha = prepare_public_base(destination, args.public_base)
        (destination.parent / f"{destination.name}.public-base.json").write_text(json.dumps({"repository": args.public_base, "main": base_sha}, indent=2) + "\n")
    else:
        destination.mkdir(parents=True)
    hashes = {}
    for name in manifest["files"]:
        if not safe_name(name):
            raise SystemExit("Unsafe manifest")
        target = destination / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(public_bytes(ROOT, name))
        target.chmod((ROOT / name).stat().st_mode & 0o777)
        hashes[name] = hashlib.sha256(target.read_bytes()).hexdigest()
    # Stored beside the export: the public source itself contains no local provenance.
    report.write_text(json.dumps(hashes, indent=2) + "\n")
    if audit(destination, manifest, private_terms):
        raise SystemExit("Export changed during copy; re-audit required")
    if not args.draft:
        metadata = json.loads((ROOT / "release-metadata.json").read_text())
        if args.public_base:
            commit_snapshot(destination, metadata)
        else:
            init_public_repository(destination, metadata)


def isolated_git_env():
    """Git environment that ignores the developer's identity, hooks and global configuration."""
    git_env = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
    git_env.update({"GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1"})
    return git_env


def commit_public(destination, metadata, message):
    commands = [["config", "user.name", metadata["author"]], ["config", "user.email", metadata["commitEmail"]], ["config", "commit.gpgSign", "false"], ["config", "core.hooksPath", "/dev/null"], ["add", "--all"], ["commit", "-m", message]]
    for command in commands:
        subprocess.run(["git", "-C", str(destination), *command], check=True, env=isolated_git_env())


def init_public_repository(destination, metadata):
    subprocess.run(["git", "-c", "init.templateDir=", "init", "-b", "main", str(destination)], check=True, env=isolated_git_env())
    commit_public(destination, metadata, f"Initial source release v{metadata['version']}")


def prepare_public_base(destination, url):
    """Clone the public main and empty its working tree; returns the base commit the snapshot extends."""
    subprocess.run(["git", "-c", "init.templateDir=", "clone", "--quiet", "--single-branch", "--branch", "main", "--no-tags", url, str(destination)], check=True, env=isolated_git_env())
    for entry in destination.iterdir():
        if entry.name == ".git":
            continue
        if entry.is_dir() and not entry.is_symlink():
            shutil.rmtree(entry)
        else:
            entry.unlink()
    return subprocess.run(["git", "-C", str(destination), "rev-parse", "HEAD"], check=True, capture_output=True, text=True, env=isolated_git_env()).stdout.strip()


def commit_snapshot(destination, metadata):
    """Record exactly the exported tree as one new commit on top of the public main."""
    commit_public(destination, metadata, f"Source snapshot v{metadata['version']}")


if __name__ == "__main__":
    main()
