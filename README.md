# Chengyu → Yomitan

Two Chinese idiom dictionaries using the same structured-content stylesheet as
[caocaochan/hydcd-yomitan](https://github.com/caocaochan/hydcd-yomitan).

| Dictionary | Download | Update index |
| --- | --- | --- |
| 汉语成语源流大辞典 | [Yomitan ZIP](https://github.com/caocaochan/chengyu-yomitan/releases/latest/download/hycyyl-yomitan.zip) | [index-hycyyl.json](https://github.com/caocaochan/chengyu-yomitan/releases/latest/download/index-hycyyl.json) |
| 新华成语大词典 | [Yomitan ZIP](https://github.com/caocaochan/chengyu-yomitan/releases/latest/download/xhcycd-yomitan.zip) | [index-xhcycd.json](https://github.com/caocaochan/chengyu-yomitan/releases/latest/download/index-xhcycd.json) |

Import either ZIP directly using Yomitan's dictionary settings. Both dictionaries
can be installed together. [Latest release](https://github.com/caocaochan/chengyu-yomitan/releases/latest)
includes counts, sizes, checksums, conversion reports, archive audits, and previews.

## Updates and automatic releases

Each ZIP embeds `isUpdatable: true`, its own `indexUrl`, and its own `downloadUrl`.
The index and download URLs use GitHub's stable `/releases/latest/download/`
paths. The release attaches the exact index bytes embedded in each ZIP. Titles
and asset names remain constant, and the two dictionaries have separate channels.
Use Yomitan's dictionary update check to find later published versions.

**If you imported the first local 汉语成语源流大辞典 ZIP before this repository
existed, replace it manually once with the release ZIP. That earlier ZIP lacks
update metadata; it cannot discover this channel by itself.**

Every branch push runs tests, builds both dictionaries, validates the official
Yomitan schemas, and audits the complete archives. Successful `main` builds also
publish a GitHub release containing both ZIPs and both indexes. The workflow can
also be run manually from Actions. Branch builds upload artifacts but do not
publish releases.

CI uses six-component numeric revisions:
`2026.11.08.2.<workflow run number>.<attempt>`. This matches Yomitan's numeric
revision comparison, including transitions such as run 9 to run 10. Older reruns
cannot replace a newer release as `latest`. The release job verifies prepared
asset checksums and publishes only after both dictionaries pass validation.

The two original source archives are tracked in this repository, with sizes and
SHA-256 hashes in `source-manifest.json`. A source change requires updating that
manifest too; builds reject mismatches. No personal token is needed in CI: builds
have `contents: read`, and only the release job has `contents: write`.

## Presentation and conversion

`styles.css` is byte-for-byte identical to the HYDCD stylesheet at
[commit 476782f](https://github.com/caocaochan/hydcd-yomitan/blob/476782fa656c4c90a9ff5a54f7db74fc33e93d95/work/hydcd-yomitan/hydcd_yomitan/data/styles.css).
It uses pink traditional and blue simplified badges, muted citations, indented
quotations, and collapsible `例证` sections. Source punctuation remains intact.

Both converters preserve homographs, all available article text, quotations,
notes, and their order. Each article body is compared with its source text before
packaging or reference expansion. All packaged links use Yomitan internal queries.
Aliases are placed next to their articles to improve ZIP compression.

Simplified/traditional and punctuationless lookup forms are added. Traditional
forms use OpenCC `s2t`, honoring explicit source annotations where available.
Automatic conversion can be ambiguous; definition text is never converted.
Only complete, source-attested primary pinyin becomes lookup readings. Missing or
uncertain pinyin remains visible in source notes where available. A differently
worded redirect does not inherit the destination's pronunciation.

### 汉语成语源流大辞典

Preserves all 12,270 article records and all 46,837 source redirect records,
including multiple destinations, reciprocal redirects, and the original short
partial-word aliases. Headword annotations remain visible in notes, while ordinary
unannotated lookup forms are added. All 87,305 quotations are retained.

### 新华成语大词典

Preserves all 26,558 text entries, including reference entries and homographs.
Whole-entry `见“…”` references show the destination's definition inline while
keeping the referring entry's own headword and pinyin. The original reference
text also remains visible. Duplicate MDX redirects that repeat a reference entry's
destination are merged with that entry.

Reverse-character indexes, the table of contents, image-page navigation, and
aliases pointing only to those indexes are omitted. The supplied archive contains
no scanned dictionary pages or font files, so no missing scans or fonts are linked.
Original printed page numbers remain visible as plain text. The source cover JPG
is retained inside the original archive.

Three broken MDX target spellings are repaired using the same key's own text entry:
`含哺而煕 → 含哺而熙`, `喑㺄叱咤 → 喑噁叱咤`, and
`梗泛萍飘 → 梗泛萍漂`. One malformed `难(nán)兄难(nán)弟` link targets
`难兄难弟`, which retains both pronunciation-specific entries. These changes
repair destinations without altering source prose. Missing plain-text references
remain visible and are listed in the conversion report if expansion is impossible.

## Build locally on Windows / PowerShell

Assumes Python 3.12+ and pip, with the source archives present at the repository root.
The build is offline after dependency installation.

```powershell
python -m venv .venv --without-pip
python -m pip --python .venv install -r requirements.txt
.\.venv\Scripts\python -m unittest -v
.\.venv\Scripts\python build_all.py --revision '2026.11.08.2.0.1'
```

Individual builds and archive audits:

```powershell
.\.venv\Scripts\python build_dictionary.py --dictionary hycyyl
.\.venv\Scripts\python audit_archive.py outputs/hycyyl/hycyyl-yomitan.zip
.\.venv\Scripts\python build_dictionary.py --dictionary xhcycd
.\.venv\Scripts\python audit_archive.py outputs/xhcycd/xhcycd-yomitan.zip
```

Prepared release assets are in `outputs/release/`. Each dictionary also has its own
conversion report, archive audit, and `preview.html` in `outputs/<dictionary>/`.
Open the preview in a browser; append `?expanded` to open every example.
The preview shows the converted content and CSS, not a live Yomitan session.

To intentionally replace a source archive, update the matching byte count and
SHA-256 in `source-manifest.json`, then commit both changes. A `main` push publishes
the next successful build automatically.

## Verification and provenance

Official Yomitan v3 schemas are pinned to
[commit ee81f8d](https://github.com/yomidevs/yomitan/tree/ee81f8dcf13e985bb4d7961009fb49a764b4d924/ext/data/schemas).
The build checks every row's metadata and every nested glossary against the
unmodified schemas. Recursive validation results are cached for shared glossary
objects. A separate archive audit reads every serialized row back and verifies
that all aliases contain exactly the validated article glossary, all article
sequences exist, and all packaged link destinations resolve. ZIP CRC checks and
source-text comparisons are also mandatory.

Reports identify source and output SHA-256 hashes, counts, unresolved source
readings/references, applied repairs, and reference commits. Release build
information identifies the exact source commit. Tests cover homographs,
reciprocal and multi-target redirects, text preservation, reference expansion,
pronunciation ownership, updater indexes, numeric revisions, and prevention of
latest-channel regression.

Dictionary content comes from the supplied archives; converting it does not grant
additional redistribution rights. Presentation attribution is preserved in each
package. No live Yomitan import is implied by schema validation or preview inspection.
