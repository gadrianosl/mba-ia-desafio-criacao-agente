import unittest

from aurora.regulations import search_regulations


class RegulationTests(unittest.TestCase):
    def test_pool_sunday_returns_hours_without_other_chapters(self):
        result = search_regulations('Até que horas a piscina funciona aos domingos?')
        self.assertEqual(result['capitulo'], 'Capítulo IV: Piscina')
        self.assertTrue(any('20h' in article and 'Art. 22.' in article for article in result['trechos']))
        self.assertLessEqual(len(result['trechos']), 2)
        self.assertNotIn('Capítulo VI', str(result))

    def test_distinct_subject_and_unknown_question(self):
        result = search_regulations('Quais são as regras para animais de estimação?')
        self.assertEqual(result['capitulo'], 'Capítulo VIII: Animais de estimação')
        self.assertNotIn('Art. 22.', str(result))
        self.assertEqual(search_regulations('criptomoedas interestelares')['status'], 'esclarecer')
        self.assertEqual(search_regulations('')['trechos'], [])
