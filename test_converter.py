import unittest

from build_dictionary import (clean_reading, equivalent_spelling, flatten,
                              lookup_forms, parse_article, resolve_source_keys,
                              script_forms)


class ConversionTests(unittest.TestCase):
    def test_reciprocal_redirects_keep_both_articles(self):
        self.assertEqual(resolve_source_keys({"甲": [0], "乙": [1]}, {"甲": ["乙"], "乙": ["甲"]}),
                         {"甲": {0, 1}, "乙": {0, 1}})

    def test_multi_target_and_transitive_redirects(self):
        result = resolve_source_keys({"甲": [0], "乙": [1, 2]}, {"丙": ["甲", "乙"], "丁": ["丙"]})
        self.assertEqual(result["丁"], {0, 1, 2})

    def test_missing_target_fails(self):
        with self.assertRaises(ValueError):
            resolve_source_keys({}, {"甲": ["乙"]})

    def test_annotation_uses_attested_traditional_character(self):
        self.assertEqual(script_forms("一触即发（發）"), ("一触即发", "一觸即發"))
        self.assertEqual(script_forms("一发（髮）之见"), ("一发之见", "一髮之見"))

    def test_multi_character_annotation(self):
        self.assertEqual(script_forms("历历（歷歷）在目"), ("历历在目", "歷歷在目"))

    def test_optional_and_reading_annotation(self):
        self.assertEqual(script_forms("一言以蔽（之）")[0], "一言以蔽")
        self.assertEqual(script_forms("恶（è）衣恶食")[0], "恶衣恶食")

    def test_punctuation_aliases(self):
        self.assertIn("一不做二不休", lookup_forms("一不做，二不休"))

    def test_primary_reading_keeps_syllable_boundaries(self):
        self.assertEqual(clean_reading("bù kě shēng（今读 shèng）shǔ", "不可胜数"), "bù kě shēng shǔ")
        self.assertEqual(clean_reading("yī yán yǐ bì（zhī）", "一言以蔽"), "yī yán yǐ bì")

    def test_incomplete_pinyin_is_not_guessed(self):
        self.assertEqual(clean_reading("（- qǔ jīn zé）", "丰取矜择"), "")
        self.assertEqual(clean_reading("yī yán", "一言以蔽"), "")

    def test_redirect_reading_requires_equivalent_spelling(self):
        self.assertTrue(equivalent_spelling("一觸即發", "一触即发"))
        self.assertFalse(equivalent_spelling("不识一丁", "目不识丁"))

    def test_quotations_and_interleaved_comments_stay_in_order(self):
        raw = '<h1 class="entry-headword">甲乙</h1><span class="pinyin">jiǎ yǐ</span><section class="entry-body"><p><span class="example"><span class="example-source">书：</span><span class="example-text">引文。</span></span><span class="definition">按语。<a href="entry://丙丁">参见</a></span><span class="example"><span class="example-source">史：</span><span class="example-text">后引文。</span></span></p></section>'
        result = parse_article("甲乙", raw, 1)
        content = result["glossary"][0]["content"]["content"]
        self.assertEqual([x["tag"] for x in content], ["span", "details", "div", "details"])
        self.assertEqual(result["links"], {"丙丁"})
        self.assertEqual(result["examples"], 2)
        self.assertIn("书：引文。", flatten(content))
        self.assertEqual(content[2]["content"][0]["content"][1]["href"], "?query=%E4%B8%99%E4%B8%81")


if __name__ == "__main__":
    unittest.main()
