import unittest
from lingaris import split_long, split_text, transform_xhtml

class DummyTranslator:
    source, target = "en", "es"
    def translate(self, value):
        return "ES: " + value

class LingarisTests(unittest.TestCase):
    def test_sentence_pairs(self):
        self.assertEqual(split_text("A lovely day. Another nice morning."),
                         ["A lovely day.", "Another nice morning."])

    def test_long_sentence(self):
        self.assertEqual(len(split_long(
            "One two three four five six seven eight, nine ten eleven twelve thirteen fourteen fifteen.")), 2)

    def test_preserve_images_and_headings(self):
        data = (b'<?xml version="1.0" encoding="utf-8"?>'
                b'<html xmlns="http://www.w3.org/1999/xhtml"><head><title>A book</title></head>'
                b'<body><h1>Chapter One</h1><p id="first">The desert was very quiet today.</p>'
                b'<p><img src="illustration.jpg"/></p></body></html>')
        result = transform_xhtml(data, DummyTranslator()).decode("utf-8")
        self.assertIn("ES: The desert was very quiet today.", result)
        self.assertIn("lingaris-original", result)
        self.assertIn('id="first"', result)
        self.assertIn('src="illustration.jpg"', result)
        self.assertIn("Chapter One", result)

if __name__ == "__main__":
    unittest.main()
