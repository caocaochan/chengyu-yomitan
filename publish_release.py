"""Publish a prepared release using gh without regressing the latest channel."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess


def numeric_revision(value):
    if not re.fullmatch(r"\d+(?:\.\d+){5}", value):
        raise ValueError(f"Expected six-component numeric revision: {value}")
    return tuple(map(int, value.split(".")))


def publish(folder, repository, gh="gh"):
    info = json.loads((folder / "build-info.json").read_text(encoding="utf-8"))
    revision = info["revision"]
    version = numeric_revision(revision)
    if repository != info["repository"] or not info["commit"]:
        raise ValueError("Release repository or commit is missing/mismatched")
    for line in (folder / "SHA256SUMS").read_text(encoding="utf-8").splitlines():
        expected, name = line.split("  ", 1)
        path = folder / name
        if path.parent.resolve() != folder.resolve():
            raise ValueError("Unsafe checksum filename")
        if hashlib.sha256(path.read_bytes()).hexdigest() != expected:
            raise ValueError(f"Release checksum mismatch: {name}")
    releases = json.loads(subprocess.check_output([gh, "release", "list", "--repo", repository,
                                                  "--limit", "100", "--json", "tagName,isPrerelease,isDraft"], text=True))
    prior = [numeric_revision(r["tagName"][len("build-"):]) for r in releases
             if not r["isPrerelease"] and not r["isDraft"] and re.fullmatch(r"build-\d+(?:\.\d+){5}", r["tagName"])]
    latest = not prior or version > max(prior)
    tag = "build-" + revision
    assets = [str(p) for p in sorted(folder.iterdir()) if p.is_file()]
    subprocess.run([gh, "release", "create", tag, *assets, "--repo", repository,
                    "--target", info["commit"], "--title", "Chengyu dictionaries " + revision,
                    "--notes-file", str(folder / "release-notes.md"), "--latest=" + str(latest).lower()], check=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--directory", type=Path, default=Path("outputs/release"))
    parser.add_argument("--repository", default="caocaochan/chengyu-yomitan")
    parser.add_argument("--gh", default="gh")
    args = parser.parse_args()
    publish(args.directory.resolve(), args.repository, args.gh)
