import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import fastjsonschema

from build_dictionary import ROOT, dictionary_index, flatten
from publish_release import numeric_revision, publish
from xinhua import REDIRECT_REPAIRS, expand_references, is_article, parse_article


def fixture(key, reading, body):
    return f'<div><cypy>{reading}</cypy><cyhw>{key}</cyhw><cypg>42</cypg><hr>{body}</div>'


class XinhuaTests(unittest.TestCase):
    def test_navigation_is_not_an_article(self):
        self.assertFalse(is_article('<cyhw>目录</cyhw><hr><div>导航</div>'))
        self.assertFalse(is_article('<div w="一"><a>一丝不苟</a></div>'))
        self.assertTrue(is_article(fixture("甲乙", "jiǎ yǐ", "<js>释义</js>")))

    def test_notes_quotes_preserved_and_page_numbers_dropped(self):
        raw = fixture("甲乙", "jiǎ yǐ", '<js>释义<hh></hh>第二行。</js><jl>甲引文</jl><zhushu>注疏</zhushu><zyi>注意<lai>来源</lai></zyi>')
        article = parse_article("甲乙", raw, 1, {"甲乙"})
        self.assertEqual(article["examples"], 2)
        text = flatten(article["glossary"][0]["content"])
        self.assertNotIn("42", text)
        self.assertIn("释义第二行。例证甲引文注疏注意来源", text)

    def test_reference_expansion_keeps_own_header_and_reading(self):
        stub = parse_article("一丁不识", fixture("一丁不识", "yī dīng bù shí", '<cj>见“不识一丁”。</cj>'), 1, {"一丁不识", "不识一丁"})
        target = parse_article("不识一丁", fixture("不识一丁", "bù shí yī dīng", '<js>不识字。</js><jl>原引文。</jl>'), 2, {"一丁不识", "不识一丁"})
        result = expand_references([stub, target], {"一丁不识": {0}, "不识一丁": {1}})
        self.assertEqual(result["expanded_whole_entry_references"], 1)
        self.assertEqual(stub["reading"], "yī dīng bù shí")
        text = flatten(stub["glossary"][0]["content"])
        self.assertIn("不识字。", text)
        self.assertIn("原引文。", text)
        badges = stub["glossary"][0]["content"]["content"][0]
        self.assertNotIn("不识一丁", flatten(badges))

    def test_missing_reference_remains_visible(self):
        article = parse_article("甲乙", fixture("甲乙", "jiǎ yǐ", '<cj>见“丙丁”。</cj>'), 1, {"甲乙"})
        result = expand_references([article], {"甲乙": {0}})
        self.assertEqual(len(result["unresolved_whole_entry_references"]), 1)
        self.assertIn("丙丁", flatten(article["glossary"][0]["content"]))
        self.assertEqual(article["links"], set())

    def test_redirect_target_repairs_are_explicit(self):
        self.assertEqual(REDIRECT_REPAIRS["含哺而煕"], "含哺而熙")
        self.assertEqual(REDIRECT_REPAIRS["喑㺄叱咤"], "喑噁叱咤")
        self.assertEqual(REDIRECT_REPAIRS["梗泛萍飘"], "梗泛萍漂")

    def test_malformed_homograph_link_is_repaired_without_changing_text(self):
        raw = fixture("甲乙", "jiǎ yǐ", '<cj><a href="entry://难(nán)兄难(nán)弟">难(nán)兄难(nán)弟</a></cj>')
        article = parse_article("甲乙", raw, 1, {"甲乙", "难兄难弟"})
        self.assertEqual(article["links"], {"难兄难弟"})
        self.assertIn("难(nán)兄难(nán)弟", flatten(article["glossary"][0]["content"]))


class UpdateTests(unittest.TestCase):
    def test_distinct_stable_channels_validate_against_official_schema(self):
        validate = fastjsonschema.compile(json.loads((ROOT / "schemas/dictionary-index-schema.json").read_text(encoding="utf-8")))
        a = dictionary_index("hycyyl", "2026.11.08.2.1.1")
        b = dictionary_index("xhcycd", "2026.11.08.2.1.1")
        for index in [a, b]:
            validate(index)
            self.assertTrue(index["isUpdatable"])
            self.assertIn("/releases/latest/download/", index["indexUrl"])
        self.assertNotEqual(a["title"], b["title"])
        self.assertNotEqual(a["indexUrl"], b["indexUrl"])
        self.assertNotEqual(a["downloadUrl"], b["downloadUrl"])

    def test_numeric_revision_crosses_digit_boundaries(self):
        self.assertGreater(numeric_revision("2026.11.08.2.10.1"), numeric_revision("2026.11.08.2.9.9"))
        with self.assertRaises(ValueError):
            dictionary_index("hycyyl", "2026.11.08.1")

    def test_old_workflow_rerun_does_not_regress_latest(self):
        test_root = ROOT / ".test-tmp"
        test_root.mkdir(exist_ok=True)
        self.assertEqual(test_root.resolve().parent, ROOT)
        with tempfile.TemporaryDirectory(dir=test_root) as directory:
            folder = Path(directory)
            self.assertTrue(folder.resolve().is_relative_to(ROOT))
            info = {"revision": "2026.11.08.2.9.2", "repository": "caocaochan/chengyu-yomitan", "commit": "abc123"}
            content = json.dumps(info).encode()
            (folder / "build-info.json").write_bytes(content)
            (folder / "release-notes.md").write_text("Release notes", encoding="utf-8")
            digest = hashlib.sha256(content).hexdigest()
            (folder / "SHA256SUMS").write_text(f"{digest}  build-info.json\n", encoding="utf-8")
            existing = json.dumps([{"tagName": "build-2026.11.08.2.10.1", "isPrerelease": False, "isDraft": False}])
            with patch("publish_release.subprocess.check_output", return_value=existing), patch("publish_release.subprocess.run") as run:
                publish(folder, info["repository"], "user-gh")
                self.assertIn("--latest=false", run.call_args.args[0])
                self.assertEqual(run.call_args.args[0][0], "user-gh")
            (folder / "build-info.json").write_text(json.dumps({**info, "commit": "tampered"}), encoding="utf-8")
            with self.assertRaises(ValueError):
                publish(folder, info["repository"], "user-gh")


if __name__ == "__main__":
    unittest.main()
