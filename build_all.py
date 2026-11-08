"""Build, audit, and prepare both dictionaries for a single GitHub release."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess

from audit_archive import audit
from build_dictionary import DEFAULT_REPOSITORY, DICTIONARIES, ROOT, build, dictionary_index, sha256


def verify_sources():
    manifest = json.loads((ROOT / "source-manifest.json").read_text(encoding="utf-8"))
    for config in DICTIONARIES.values():
        path = ROOT / config["input"]
        if sha256(path) != manifest[path.name]["sha256"] or path.stat().st_size != manifest[path.name]["bytes"]:
            raise ValueError(f"Source checksum mismatch: {path.name}")


def prepare_release(revision, repository, output_root=ROOT / "outputs"):
    release_dir = output_root / "release"
    release_dir.mkdir(parents=True, exist_ok=True)
    expected_files = set()
    summaries = []
    for dictionary, config in DICTIONARIES.items():
        folder = output_root / dictionary
        archive_path = folder / config["asset"]
        import zipfile
        with zipfile.ZipFile(archive_path) as archive:
            index_bytes = archive.read("index.json")
            index = json.loads(index_bytes)
            if index != dictionary_index(dictionary, revision, repository):
                raise ValueError(f"Incorrect update metadata: {dictionary}")
            if index_bytes != (folder / f"index-{dictionary}.json").read_bytes():
                raise ValueError(f"Published index differs from embedded index: {dictionary}")
            uncompressed = sum(info.file_size for info in archive.infolist())
        report = json.loads((folder / "conversion-report.json").read_text(encoding="utf-8"))
        if report["output_sha256"] != sha256(archive_path):
            raise ValueError(f"Package changed after validation: {dictionary}")
        copies = {config["asset"]: archive_path,
                  f"index-{dictionary}.json": folder / f"index-{dictionary}.json",
                  f"{dictionary}-conversion-report.json": folder / "conversion-report.json",
                  f"{dictionary}-archive-audit.json": folder / "archive-audit.json",
                  f"{dictionary}-preview.html": folder / "preview.html"}
        for name, path in copies.items():
            shutil.copyfile(path, release_dir / name)
            expected_files.add(name)
        summaries.append({"dictionary": dictionary, "title": config["title"],
                          "articles": report["articles"], "term_rows": report["term_rows"],
                          "zip_bytes": archive_path.stat().st_size, "uncompressed_bytes": uncompressed,
                          "source_sha256": report["source_sha256"]})
    commit = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True, capture_output=True)
    info = {"revision": revision, "repository": repository,
            "commit": commit.stdout.strip() if commit.returncode == 0 else None,
            "dictionaries": summaries}
    (release_dir / "build-info.json").write_text(json.dumps(info, ensure_ascii=False, indent=2), encoding="utf-8")
    expected_files.add("build-info.json")
    notes = [f"Both dictionaries, revision **{revision}**.", "",
             "| Dictionary | Articles | Lookup rows | ZIP | Uncompressed |",
             "| --- | ---: | ---: | ---: | ---: |"]
    for item in summaries:
        notes.append(f'| {item["title"]} | {item["articles"]:,} | {item["term_rows"]:,} | {item["zip_bytes"]/1e6:.2f} MB | {item["uncompressed_bytes"]/1e6:.2f} MB |')
    notes += ["", "Import the dictionary ZIPs directly into Yomitan. Both include separate stable update indexes and download URLs. Future successful main-branch builds publish both channels together with a higher numeric revision.",
              "", "If you installed the first local 汉语成语源流大辞典 build without update metadata, replace it manually once with this release. Subsequent releases can be found through Yomitan's dictionary update check.",
              "", "Both use the HYDCD stylesheet. All available article text and quotations are retained. Xinhua's unavailable scan pages and reverse-character navigation indexes are omitted; printed page numbers remain visible. Whole-entry see-references expand inline while keeping the referring entry's own reading.",
              "", "Validation: official Yomitan v3 schemas, exact source text checks, ZIP CRC checks, and archive-wide glossary/link audits. Reports, previews, build information, and SHA-256 checksums are attached.",
              "", f'Source commit: `{info["commit"] or "local build"}`.']
    (release_dir / "release-notes.md").write_text("\n".join(notes) + "\n", encoding="utf-8")
    expected_files.add("release-notes.md")
    checksums = "".join(f"{sha256(release_dir / name)}  {name}\n" for name in sorted(expected_files))
    (release_dir / "SHA256SUMS").write_text(checksums, encoding="utf-8")
    expected_files.add("SHA256SUMS")
    unexpected = {p.name for p in release_dir.iterdir()} - expected_files
    if unexpected:
        raise ValueError(f"Stale files in release directory: {unexpected}")
    print(json.dumps(info, ensure_ascii=False, indent=2), flush=True)
    return release_dir


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--revision", default="2026.11.08.2.0.1")
    parser.add_argument("--repository", default=DEFAULT_REPOSITORY)
    parser.add_argument("--prepare-only", action="store_true")
    args = parser.parse_args()
    if not args.prepare_only:
        verify_sources()
        for dictionary, config in DICTIONARIES.items():
            path = ROOT / "outputs" / dictionary / config["asset"]
            build(ROOT / config["input"], path, args.revision, dictionary, args.repository)
            audit(path)
    prepare_release(args.revision, args.repository)
