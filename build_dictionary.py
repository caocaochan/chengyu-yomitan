"""Assumes Python 3.12+ on Windows; install requirements.txt before running."""
from __future__ import annotations

import argparse
from collections import defaultdict, deque
from functools import lru_cache
import hashlib
import html
import json
from pathlib import Path
import re
import unicodedata
from urllib.parse import quote, unquote
import zipfile

from bs4 import BeautifulSoup, NavigableString, Tag
import fastjsonschema
from mdict_utils.base.readmdict import MDX, MDD
from opencc import OpenCC

ROOT = Path(__file__).resolve().parent
TITLE = "汉语成语源流大辞典"
DEFAULT_REPOSITORY = "caocaochan/chengyu-yomitan"
DICTIONARIES = {
    "hycyyl": {"title": TITLE, "input": "汉语成语源流大辞典.zip", "asset": "hycyyl-yomitan.zip"},
    "xhcycd": {"title": "新华成语大词典", "input": "新华成语大词典.zip", "asset": "xhcycd-yomitan.zip"},
}
S2T = OpenCC("s2t")
T2S = OpenCC("t2s")
REFERENCE_COMMIT = "476782fa656c4c90a9ff5a54f7db74fc33e93d95"
YOMITAN_COMMIT = "ee81f8dcf13e985bb4d7961009fb49a764b4d924"


def nfc(text):
    return unicodedata.normalize("NFC", text.replace("\x00", "")).strip()


def node(tag, content, kind=None, **attrs):
    result = {"tag": tag, "content": content}
    if kind:
        result["data"] = {"content": kind}
    result.update(attrs)
    return result


@lru_cache(maxsize=None)
def script_forms(term):
    """Honor explicit source traditional annotations before OpenCC conversion."""
    base = re.sub(r"（[^（）]*）", "", term)
    traditional = ""
    remaining = term
    while match := re.search(r"（([^（）]*)）", remaining):
        traditional += remaining[:match.start()]
        choices = match[1].split("、")
        for alternative in choices:
            # 髪 is a source spelling variant of 髮 unsupported by t2s.
            equivalent = lambda s: T2S.convert(s.replace("髪", "髮").replace("锺", "鍾"))
            lengths = [n for n in range(1, len(traditional) + 1)
                       if equivalent(traditional[-n:]) == equivalent(alternative)]
            if lengths:
                traditional = traditional[:-max(lengths)] + alternative
                break
        remaining = remaining[match.end():]
    traditional += remaining
    return T2S.convert(base), S2T.convert(traditional)


def lookup_forms(term):
    forms = [term, *script_forms(term)]
    # The source itself has unpunctuated aliases; also support punctuationless
    # traditional spellings without changing the displayed original text.
    forms += [re.sub(r"[，,、；;。！？!?\s]", "", value) for value in forms]
    return list(dict.fromkeys(value for value in forms if value))


def han_count(text):
    return sum("\u3400" <= c <= "\u9fff" or "\U00020000" <= c <= "\U000323af" for c in text)


def clean_reading(original, base):
    """Extract only a complete, source-attested primary pronunciation."""
    text = nfc(original).translate(str.maketrans({"ɡ": "g", "ɑ": "a"}))
    if text.startswith("（") and text.endswith("）"):
        text = text[1:-1]
    text = re.sub(r"（[^（）]*）", " ", text)
    text = re.sub(r"[·．]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    decomposed = unicodedata.normalize("NFD", text)
    if not text or not re.fullmatch(r"[a-zA-Z\u0300-\u036f ,，、'’]+", decomposed):
        return ""
    syllables = re.findall(r"[^ ,，、'’]+", text)
    if len(syllables) != han_count(base):
        return ""
    return text


def equivalent_spelling(a, b):
    strip = lambda s: re.sub(r"[，,、；;。！？!?\s]", "", T2S.convert(s))
    return strip(a) == strip(b)


def resolve_source_keys(direct, redirects):
    """Propagate reachable articles through the complete redirect graph.

    Some source keys have both articles and redirects, including reciprocal
    redirects. A fixed point preserves all articles without treating those
    useful cycles as broken references.
    """
    reachable = {key: set(ids) for key, ids in direct.items()}
    predecessors = defaultdict(set)
    for key, targets in redirects.items():
        reachable.setdefault(key, set())
        for target in targets:
            reachable.setdefault(target, set())
            predecessors[target].add(key)
    pending = deque(key for key, ids in reachable.items() if ids)
    while pending:
        target = pending.popleft()
        for key in predecessors[target]:
            extra = reachable[target] - reachable[key]
            if extra:
                reachable[key].update(extra)
                pending.append(key)
    unresolved = [key for key, ids in reachable.items() if not ids]
    if unresolved:
        raise ValueError(f"Unresolved source keys: {unresolved[:20]}")
    return reachable


def inline(element, links):
    if isinstance(element, NavigableString):
        return str(element)
    if not isinstance(element, Tag):
        raise ValueError(f"Unsupported HTML object: {type(element)}")
    content = [inline(c, links) for c in element.children]
    if element.name == "a":
        href = element.get("href", "")
        if not href.startswith("entry://"):
            raise ValueError(f"Unexpected source link: {href}")
        target = unquote(href[len("entry://"):])
        links.add(target)
        return node("a", content, href="?query=" + quote(target, safe=""))
    classes = element.get("class", [])
    if element.name != "span":
        raise ValueError(f"Unexpected source body tag: {element.name}")
    kinds = {"definition": "definition", "example": "example",
             "example-source": "book", "example-text": "example-text"}
    if len(classes) != 1 or classes[0] not in kinds:
        raise ValueError(f"Unexpected source class: {classes}")
    return node("div" if classes[0] == "example" else "span", content, kinds[classes[0]])


def flatten(value):
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return "".join(map(flatten, value))
    return flatten(value.get("content", ""))


def parse_article(key, raw, sequence):
    soup = BeautifulSoup(raw, "html.parser")
    title = soup.select_one(".entry-headword")
    body = soup.select_one(".entry-body")
    if title is None or body is None or title.get_text() != key:
        raise ValueError(f"Unrecognized article: {key}")
    pronunciation = soup.select_one(".pinyin")
    original_reading = nfc(pronunciation.get_text()) if pronunciation else ""
    simplified, traditional = script_forms(key)
    reading = clean_reading(original_reading, simplified)
    badges = [node("span", traditional, "traditional-term")]
    if simplified != traditional:
        badges.append(node("span", simplified, "simplified-term"))
    result = [node("span", [node("span", badges, "terms-parent")], "first-row-parent")]
    if "（" in key or (original_reading and (not reading or "（" in original_reading or "．" in original_reading)):
        metadata = []
        if "（" in key:
            metadata.append(node("div", "原词头：" + key, "note"))
        if original_reading:
            metadata.append(node("div", original_reading, "phonology"))
        result.append(node("div", metadata, "header"))
    links = set()
    # Keep all text in source order. Consecutive citations share a disclosure;
    # definitions and comments between quotations remain in their exact place.
    pending = []

    def flush():
        if pending:
            result.append(node("details", [node("summary", "例证"), *pending], "examples", open=False))
            pending.clear()

    for paragraph in body.children:
        if isinstance(paragraph, NavigableString) and not paragraph.strip():
            continue
        if not isinstance(paragraph, Tag) or paragraph.name != "p":
            raise ValueError(f"Unexpected article block: {key}: {paragraph}")
        definition = []
        for child in paragraph.children:
            is_example = isinstance(child, Tag) and "example" in child.get("class", [])
            if is_example:
                if definition:
                    flush()
                    result.append(node("div", definition, "sense"))
                    definition = []
                pending.append(inline(child, links))
            else:
                flush()
                definition.append(inline(child, links))
        if definition:
            result.append(node("div", definition, "sense"))
    flush()
    structured = node("div", result, "hydcd-entry", lang="zh-Hans")
    # Audit actual content preservation, not merely record counts.
    source_text = body.get_text()
    # Disclosure labels are generated UI, not source content.
    def body_text(x):
        if isinstance(x, str): return x
        if isinstance(x, list): return "".join(map(body_text, x))
        if x.get("tag") == "summary": return ""
        return body_text(x.get("content", ""))
    generated_text = "".join(body_text(x) for x in result[1:] if x.get("data", {}).get("content") != "header")
    if source_text != generated_text:
        raise ValueError(f"Body text was changed during conversion: {key}")
    return {"key": key, "sequence": sequence, "base": simplified, "reading": reading,
            "source_reading": original_reading, "glossary": [{"type": "structured-content", "content": structured}],
            "links": links, "examples": len(body.select(".example")),
            "source_characters": len(source_text)}


def json_bytes(value):
    return json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_member(archive, name, content):
    info = zipfile.ZipInfo(name, date_time=(2026, 11, 8, 0, 0, 0))
    info.compress_type = zipfile.ZIP_DEFLATED
    archive.writestr(info, content, compresslevel=9)


def dictionary_index(dictionary, revision, repository=DEFAULT_REPOSITORY):
    if not re.fullmatch(r"[\w.-]+/[\w.-]+", repository):
        raise ValueError("Expected repository as owner/name")
    if not re.fullmatch(r"\d+(?:\.\d+){5}", revision):
        raise ValueError("Release revisions must have six numeric components")
    config = DICTIONARIES[dictionary]
    base = f"https://github.com/{repository}"
    return {"title": config["title"], "format": 3, "revision": revision, "sequenced": True,
            "sourceLanguage": "zh", "targetLanguage": "zh", "url": base,
            "isUpdatable": True,
            "indexUrl": f"{base}/releases/latest/download/index-{dictionary}.json",
            "downloadUrl": f"{base}/releases/latest/download/{config['asset']}",
            "description": config["title"] + "；保留源文、引文、异体及交叉参照。例证可展开。简繁检索含 OpenCC 自动转换形式。",
            "attribution": "Dictionary content from the user-supplied MDX archive. Presentation adapted from caocaochan/hydcd-yomitan, commit " + REFERENCE_COMMIT + "."}


def render_preview(articles, css, output, title=TITLE):
    def render(value):
        if isinstance(value, str): return html.escape(value)
        if isinstance(value, list): return "".join(map(render, value))
        attrs = "".join(f' data-sc-{html.escape(k)}="{html.escape(v, quote=True)}"' for k, v in value.get("data", {}).items())
        for attr in ["href", "lang", "title"]:
            if attr in value: attrs += f' {attr}="{html.escape(value[attr], quote=True)}"'
        if value.get("open"): attrs += " open"
        return f'<{value["tag"]}{attrs}>{render(value.get("content", ""))}</{value["tag"]}>'
    selected = ["一不做，二不休", "一触即发（發）", "不可胜数", "东道主", "画蛇添足", "一日之长"]
    panels = []
    for theme in ["dark", "light"]:
        cards = []
        for key in selected:
            entry = next((a for a in articles if a["key"] == key), None)
            if entry is None:
                continue
            cards.append('<article class="card">' + render(entry["glossary"][0]["content"]) + '</article>')
        panels.append(f'<section class="{theme}"><h2>{theme.title()}</h2>{"".join(cards)}</section>')
    output.write_text('<!doctype html><html lang="zh-Hans"><meta charset="utf-8"><title>' + html.escape(title) + ' · Yomitan preview</title><style>'
        + css + '\nbody{margin:0;font:16px/1.55 "Microsoft YaHei",sans-serif;background:#777}main{display:grid;grid-template-columns:1fr 1fr;gap:1px}section{padding:20px;min-width:0}.dark{color:#ddd;background:#202124}.light{color:#222;background:#fff}.card{padding:16px;margin:18px 0;border:1px solid #8886;border-radius:8px}h2{font:600 18px sans-serif}a{color:#6b99e3}details[open]>summary{margin-bottom:.5em}@media(max-width:700px){main{grid-template-columns:1fr}}</style><main>'
        + "".join(panels) + '</main><script>if(location.search.includes("expanded"))document.querySelectorAll("details").forEach(x=>x.open=true)</script></html>', encoding="utf-8")


def build(input_archive, output, revision, dictionary="hycyyl", repository=DEFAULT_REPOSITORY):
    from xinhua import LINK_REPAIRS, REDIRECT_REPAIRS, expand_references, is_article, parse_article as parse_xinhua
    config = DICTIONARIES[dictionary]
    output.parent.mkdir(parents=True, exist_ok=True)
    source_dir = ROOT / "source" / dictionary
    source_dir.mkdir(parents=True, exist_ok=True)
    mdx_paths = []
    mdd_paths = []
    with zipfile.ZipFile(input_archive) as archive:
        for name in archive.namelist():
            # Only extract flat, expected source files.
            if Path(name).name != name or Path(name).suffix.lower() not in {".mdx", ".mdd", ".css", ".jpg"}:
                raise ValueError(f"Unexpected source archive member: {name}")
            (source_dir / name).write_bytes(archive.read(name))
            if name.endswith(".mdx"): mdx_paths.append(source_dir / name)
            if name.endswith(".mdd"): mdd_paths.append(source_dir / name)
    mdx_path, = mdx_paths
    raw_records = [(nfc(k.decode("utf-8")), v.decode("utf-8").replace("\x00", "").rstrip())
                   for k, v in MDX(str(mdx_path), "", False, None).items()]
    articles = []
    direct = defaultdict(list)
    redirects = defaultdict(list)
    source_keys = {key for key, _ in raw_records}
    navigation_keys = set()
    repairs = []
    for key, raw in raw_records:
        if raw.startswith("@@@LINK="):
            target = nfc(raw[len("@@@LINK="):])
            if dictionary == "xhcycd" and target in REDIRECT_REPAIRS:
                repairs.append({"term": key, "source_target": target, "repaired_target": REDIRECT_REPAIRS[target]})
                target = REDIRECT_REPAIRS[target]
            redirects[key].append(target)
        elif dictionary == "xhcycd" and not is_article(raw):
            navigation_keys.add(key)
        else:
            article = (parse_xinhua(key, raw, len(articles) + 1, source_keys) if dictionary == "xhcycd"
                       else parse_article(key, raw, len(articles) + 1))
            articles.append(article)
            direct[key].append(len(articles) - 1)
            if len(articles) % 2000 == 0:
                print(f'Parsed {len(articles):,} articles', flush=True)

    source_redirect_count = sum(map(len, redirects.values()))
    redundant_redirects = 0
    if dictionary == "xhcycd":
        for key, ids in direct.items():
            # A number of text stubs occur again as redundant MDX redirects.
            # Keep the text entry's own headword and pronunciation, and expand
            # its definition instead of producing a second target-headed row.
            refs = {articles[i]["reference_target"] for i in ids}
            kept = [target for target in redirects.get(key, []) if target not in refs]
            redundant_redirects += len(redirects.get(key, [])) - len(kept)
            if key in redirects:
                redirects[key] = kept
    seeds = dict(direct)
    seeds.update({key: [-1] for key in navigation_keys})
    reachable = resolve_source_keys(seeds, redirects)
    extra_report = expand_references(articles, reachable) if dictionary == "xhcycd" else {}
    if dictionary == "xhcycd":
        extra_report["source_cross_reference_repairs"] = LINK_REPAIRS
    mapping = defaultdict(set)
    skipped_keys = 0
    for key in dict.fromkeys(k for k, _ in raw_records):
        ids = {i for i in reachable[key] if i >= 0}
        if not ids:
            skipped_keys += 1
            continue
        for form in lookup_forms(key):
            mapping[form].update(ids)
    source_link_targets = set().union(*(a["links"] for a in articles))
    missing_targets = source_link_targets - mapping.keys()
    if missing_targets:
        raise ValueError(f"Broken cross-references: {sorted(missing_targets)}")
    resources = []
    for mdd in mdd_paths:
        for key, value in MDD(str(mdd), None).items():
            name = key.decode("utf-8").replace("\\", "/").lstrip("/")
            if not name.endswith(".css"):
                raise ValueError(f"Unexpected media resource requires conversion: {name}")
            resources.append({"name": name, "bytes": len(value), "policy": "Replaced by HYDCD presentation stylesheet"})
    css = (ROOT / "styles.css").read_text(encoding="utf-8")
    index = dictionary_index(dictionary, revision, repository)
    validate_index = fastjsonschema.compile(json.loads((ROOT / "schemas/dictionary-index-schema.json").read_text(encoding="utf-8")))
    validate_bank = fastjsonschema.compile(json.loads((ROOT / "schemas/dictionary-term-bank-v3-schema.json").read_text(encoding="utf-8")))
    validate_index(index)
    validated_glossaries = set()

    def validate_rows(rows):
        # Alias rows share the exact same in-memory glossary object. Validate
        # that subtree once against the unmodified official schema, then check
        # every alias's remaining fields against that same schema. No content
        # is omitted from validation; immutable subtree results are cached.
        metadata_rows = []
        for row in rows:
            identity = id(row[5])
            if identity not in validated_glossaries:
                validate_bank([row])
                validated_glossaries.add(identity)
            else:
                metadata_rows.append([*row[:5], [], *row[6:]])
        if metadata_rows:
            validate_bank(metadata_rows)

    row_count = 0
    blank_readings = 0
    bank_count = 0
    with zipfile.ZipFile(output, "w") as archive:
        write_member(archive, "index.json", json_bytes(index))
        write_member(archive, "styles.css", css.encode("utf-8"))
        bank = []
        # Put aliases next to their article so ZIP compression can reuse the
        # repeated definition rather than storing it in distant banks.
        forms_by_article = defaultdict(list)
        for form, ids in mapping.items():
            for identifier in sorted(ids):
                forms_by_article[identifier].append(form)
        for identifier in sorted(forms_by_article):
            for form in forms_by_article[identifier]:
                article = articles[identifier]
                reading = article["reading"] if equivalent_spelling(form, article["base"]) else ""
                bank.append([form, reading, "", "", 0, article["glossary"], article["sequence"], ""])
                row_count += 1
                blank_readings += not bool(reading)
                if len(bank) == 500:
                    validate_rows(bank)
                    bank_count += 1
                    write_member(archive, f"term_bank_{bank_count}.json", json_bytes(bank))
                    bank.clear()
                    if bank_count % 40 == 0: print(f'Validated and packaged {row_count:,} rows', flush=True)
        if bank:
            validate_rows(bank)
            bank_count += 1
            write_member(archive, f"term_bank_{bank_count}.json", json_bytes(bank))
    with zipfile.ZipFile(output) as archive:
        damaged = archive.testzip()
        if damaged: raise ValueError(f"ZIP CRC failed: {damaged}")
    (output.parent / f"index-{dictionary}.json").write_bytes(json_bytes(index))
    report = {"title": config["title"], "dictionary": dictionary, "revision": revision, "source_archive": input_archive.name,
        "source_sha256": sha256(input_archive), "output_sha256": sha256(output),
        "source_records": len(raw_records), "source_unique_keys": len(set(k for k, _ in raw_records)),
        "source_resources": resources,
        "articles": len(articles), "source_redirect_records": source_redirect_count,
        "omitted_navigation_keys_and_aliases": skipped_keys,
        "redundant_stub_redirects_merged": redundant_redirects,
        "source_redirect_repairs": repairs,
        "lookup_expressions": len(mapping), "term_rows": row_count, "term_banks": bank_count,
        "rows_without_reading": blank_readings, "examples": sum(a["examples"] for a in articles),
        "article_body_characters_preserved": sum(a["source_characters"] for a in articles),
        "distinct_cross_reference_targets": len(source_link_targets),
        "unresolved_cross_references": 0, "unresolved_redirects": 0,
        "articles_without_source_pinyin": sum(not a["source_reading"] for a in articles),
        "unresolved_primary_readings": [{"term": a["key"], "source": a["source_reading"]} for a in articles if a["source_reading"] and not a["reading"]],
        "schema_validation": "Official Yomitan v3 schema used unchanged: full recursive validation cached once per shared glossary object; every row's other fields validated. Index validated; ZIP CRC checked.",
        "unique_glossaries_schema_validated": len(validated_glossaries),
        "yomitan_schema_commit": YOMITAN_COMMIT, "hydcd_style_commit": REFERENCE_COMMIT,
        "style_sha256": sha256(ROOT / "styles.css"), "bytes": output.stat().st_size,
        "conversion_policy": "All source keys and redirects retained, including short redirects. Simplified/traditional and punctuationless aliases generated. OpenCC conversion is automatic and may be ambiguous. No pinyin invented for differently worded redirects. Source pronunciation notes retained. Every article body is checked for exact text preservation."}
    report.update(extra_report)
    if dictionary == "xhcycd":
        report["conversion_policy"] = "All text articles and their term aliases retained; navigation pages, reverse-character indexes, and aliases pointing only to navigation are omitted. Original page numbers omitted because scans are absent. Exact article body text checked before expanding whole-entry references. Three broken redirect targets repaired from the same key's own text entry. Simplified/traditional and punctuationless aliases generated; unknown readings left blank."
    (output.parent / "conversion-report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    render_preview(articles, css, output.parent / "preview.html", config["title"])
    print(json.dumps({k: report[k] for k in ["articles", "source_redirect_records", "term_rows", "lookup_expressions", "bytes", "output_sha256"]}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Convert the source MDX ZIP to a styled Yomitan dictionary.")
    parser.add_argument("--dictionary", choices=DICTIONARIES, default="hycyyl")
    parser.add_argument("--input", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--repository", default=DEFAULT_REPOSITORY)
    parser.add_argument("--revision", default="2026.11.08.2.0.1")
    args = parser.parse_args()
    config = DICTIONARIES[args.dictionary]
    build((args.input or ROOT / config["input"]).resolve(),
          (args.output or ROOT / "outputs" / args.dictionary / config["asset"]).resolve(),
          args.revision, args.dictionary, args.repository)
