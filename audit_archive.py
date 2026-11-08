"""Audit the finished archive, especially shared glossaries after serialization."""
import hashlib
import json
from pathlib import Path
import sys
from urllib.parse import parse_qs, urlsplit
import zipfile


def audit(path):
    rows = 0
    expressions = set()
    glossaries = {}
    targets = set()
    links = 0

    def visit(value):
        nonlocal links
        if isinstance(value, list):
            for item in value:
                visit(item)
        elif isinstance(value, dict):
            if value.get("tag") == "a":
                query = parse_qs(urlsplit(value["href"]).query)
                if set(query) != {"query"} or len(query["query"]) != 1:
                    raise ValueError("Malformed cross-reference")
                targets.add(query["query"][0])
                links += 1
            if "content" in value:
                visit(value["content"])

    with zipfile.ZipFile(path) as archive:
        names = archive.namelist()
        if len(names) != len(set(names)):
            raise ValueError("Duplicate archive members")
        banks = sorted((name for name in names if name.startswith("term_bank_")),
                       key=lambda name: int(name.removeprefix("term_bank_").removesuffix(".json")))
        if banks != [f"term_bank_{i}.json" for i in range(1, len(banks) + 1)]:
            raise ValueError("Noncontiguous bank numbering")
        for name in banks:
            for row in json.loads(archive.read(name)):
                if len(row) != 8 or not row[0] or len(row[5]) != 1:
                    raise ValueError("Malformed term row")
                glossary = row[5]
                digest = hashlib.sha256(json.dumps(glossary, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()
                sequence = row[6]
                if sequence in glossaries:
                    if glossaries[sequence] != digest:
                        raise ValueError(f"An alias changed its validated glossary: {row[0]}")
                else:
                    glossaries[sequence] = digest
                    visit(glossary)
                rows += 1
                expressions.add(row[0])
    if targets - expressions:
        raise ValueError(f"Unresolved packaged links: {targets - expressions}")
    if set(glossaries) != set(range(1, len(glossaries) + 1)):
        raise ValueError("Missing article sequences")
    report = {"term_rows": rows, "lookup_expressions": len(expressions),
              "unique_article_glossaries": len(glossaries), "source_cross_references": links,
              "distinct_cross_reference_targets": len(targets),
              "all_alias_glossaries_identical_to_validated_article": True,
              "all_packaged_cross_references_resolve": True}
    conversion_path = path.parent / "conversion-report.json"
    if conversion_path.exists():
        conversion = json.loads(conversion_path.read_text(encoding="utf-8"))
        for key in ["term_rows", "lookup_expressions", "distinct_cross_reference_targets"]:
            if report[key] != conversion[key]:
                raise ValueError(f"Build/audit count mismatch: {key}")
        if report["unique_article_glossaries"] != conversion["articles"]:
            raise ValueError("Missing packaged articles")
    (path.parent / "archive-audit.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    audit(Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parent / "outputs/hycyyl-yomitan.zip")
