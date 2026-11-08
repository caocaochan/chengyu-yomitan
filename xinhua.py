"""Parse the text entries in the Xinhua source; page scans are not supplied."""
from copy import deepcopy
import re
from urllib.parse import quote, unquote

from bs4 import BeautifulSoup, NavigableString, Tag

from build_dictionary import clean_reading, flatten, nfc, node, script_forms


# Each broken MDX redirect is contradicted by the same key's own text entry.
# These are target repairs only; dictionary prose is left untouched.
REDIRECT_REPAIRS = {
    "含哺而煕": "含哺而熙",
    "喑㺄叱咤": "喑噁叱咤",
    "梗泛萍飘": "梗泛萍漂",
}
LINK_REPAIRS = {"难(nán)兄难(nán)弟": "难兄难弟"}


def is_article(raw):
    return bool(re.search(r'<(?:cyhw\b|span\b[^>]*class="hw")', raw)
                and re.search(r'<(?:cypy\b|span\b[^>]*class="py")', raw))


def parse_article(key, raw, sequence, source_keys):
    soup = BeautifulSoup(raw, "html.parser")
    headword = soup.select_one("cyhw,.hw")
    divider = soup.find("hr")
    if headword is None or divider is None or headword.get_text() != key:
        raise ValueError(f"Unrecognized Xinhua article: {key}")
    pronunciation = soup.select_one("cypy,.py")
    original_reading = nfc(pronunciation.get_text()) if pronunciation else ""
    simplified, traditional = script_forms(key)
    reading = clean_reading(original_reading, simplified)
    badges = [node("span", traditional, "traditional-term")]
    if traditional != simplified:
        badges.append(node("span", simplified, "simplified-term"))
    result = [node("span", [node("span", badges, "terms-parent")], "first-row-parent")]
    page = soup.select_one("cypg,.ref")
    metadata = []
    if page:
        digits = re.search(r"\d+", page.get_text())
        if digits:
            metadata.append(node("span", f"第{int(digits[0])}页", "note"))
    if original_reading and (not reading or "（" in original_reading):
        metadata.append(node("div", original_reading, "phonology"))
    if metadata:
        result.append(node("div", metadata, "header"))
    links = set()

    def convert(element):
        if isinstance(element, NavigableString):
            return str(element)
        if not isinstance(element, Tag):
            raise ValueError(f"Unexpected Xinhua content: {key}")
        content = [convert(c) for c in element.children]
        tag = element.name
        if tag == "a":
            href = element.get("href", "")
            if not href.startswith("entry://"):
                raise ValueError(f"Unexpected Xinhua link: {href}")
            target = unquote(href[len("entry://"):])
            target = LINK_REPAIRS.get(target, target)
            links.add(target)
            return node("a", content, href="?query=" + quote(target, safe=""))
        if tag in {"hh", "br"}:
            return {"tag": "br"}
        if tag == "sub":
            return node("span", content, style={"verticalAlign": "sub", "fontSize": "0.8em"})
        if tag == "span":
            if element.get("class") != ["py2"]:
                raise ValueError(f"Unexpected body span: {element}")
            return node("span", content, "reading-note")
        kinds = {"js": "sense", "hy": "sense", "yz": "sense", "jl": "example",
                 "zhushu": "example", "zyi": "note", "lai": "book", "zhu": "note",
                 "jiaoji": "note", "cj": "see", "cypy2": "reading-note", "div": "sense"}
        if tag not in kinds:
            raise ValueError(f"Unexpected Xinhua body tag: {tag}: {key}")
        if tag in {"jl", "zhushu"} and content and isinstance(content[0], str):
            colon = content[0].find("：")
            if colon >= 0:
                first = content[0]
                content = [node("span", first[:colon + 1], "book"), first[colon + 1:], *content[1:]]
        # Some see-references are plain quoted text. Add links only when the
        # source contains a matching term, preserving every displayed character.
        if tag == "cj" and not element.find("a"):
            text = element.get_text()
            content = []
            start = 0
            for match in re.finditer(r"[“「]([^”」]+)[”」]", text):
                target = match[1]
                if target not in source_keys:
                    continue
                content.append(text[start:match.start(1)])
                content.append(node("a", target, href="?query=" + quote(target, safe="")))
                links.add(target)
                start = match.end(1)
            content.append(text[start:])
        return node("span" if tag in {"cypy2", "zhu"} else "div", content, kinds[tag])

    original = list(divider.next_siblings)
    pending = []

    def flush():
        if pending:
            result.append(node("details", [node("summary", "例证"), *pending], "examples", open=False))
            pending.clear()

    for child in original:
        if isinstance(child, NavigableString):
            # Literal text and whitespace are retained for the audit below.
            flush()
            result.append(node("span", str(child), "layout"))
        elif isinstance(child, Tag) and child.name in {"jl", "zhushu"}:
            pending.append(convert(child))
        else:
            flush()
            result.append(convert(child))
    flush()

    def body_text(value):
        if isinstance(value, str): return value
        if isinstance(value, list): return "".join(map(body_text, value))
        if value.get("tag") == "summary": return ""
        return body_text(value.get("content", ""))

    source_text = "".join(str(c) if isinstance(c, NavigableString) else c.get_text() for c in original)
    converted_text = "".join(body_text(c) for c in result[1:] if c.get("data", {}).get("content") != "header")
    if source_text != converted_text:
        raise ValueError(f"Xinhua article text changed: {key}")
    main = [c for c in original if isinstance(c, Tag)]
    target = None
    if len(main) == 1 and main[0].name == "cj":
        match = re.fullmatch(r'(?:参)?见[“「"]([^”」"]+)[”」"]。?', source_text.strip())
        if match:
            target = match[1]
    return {"key": key, "sequence": sequence, "base": simplified, "reading": reading,
            "source_reading": original_reading,
            "glossary": [{"type": "structured-content", "content": node("div", result, "hydcd-entry", lang="zh-Hans")}],
            "links": links, "examples": len(soup.select("jl,zhushu")),
            "source_characters": len(source_text), "reference_target": target}


def expand_references(articles, reachable):
    """Expand whole-entry see-references while keeping their own readings."""
    snapshots = [deepcopy(a["glossary"][0]["content"]["content"]) for a in articles]
    cache = {}
    unresolved = []

    def resolve(identifier, trail=()):
        if identifier in cache:
            return cache[identifier]
        if identifier in trail:
            raise ValueError("cyclic whole-entry reference")
        article = articles[identifier]
        body = [deepcopy(n) for n in snapshots[identifier]
                if n.get("data", {}).get("content") not in {"first-row-parent", "header"}]
        target = article["reference_target"]
        if target:
            ids = sorted(i for i in reachable.get(target, set()) if i >= 0)
            if not ids:
                raise ValueError("missing whole-entry reference target")
            for other in ids:
                body.append(node("div", deepcopy(resolve(other, trail + (identifier,))), "reference-definition"))
        cache[identifier] = body
        return body

    expanded = 0
    for identifier, article in enumerate(articles):
        if not article["reference_target"]:
            continue
        try:
            body = resolve(identifier)
        except ValueError as error:
            unresolved.append({"term": article["key"], "target": article["reference_target"], "reason": str(error)})
            continue
        header = [n for n in snapshots[identifier] if n.get("data", {}).get("content") in {"first-row-parent", "header"}]
        article["glossary"][0]["content"]["content"] = [*header, *body]
        expanded += 1
    return {"expanded_whole_entry_references": expanded, "unresolved_whole_entry_references": unresolved}
