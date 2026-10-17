# Lingaris

Turn an EPUB into a bilingual language-learning EPUB: translated text first, original text underneath, one reading unit at a time.

**Defaults:** English original → Spanish translation. Other language pairs are configurable.

## Features

- EPUB input and EPUB output, retaining embedded pictures, chapter files, stylesheets, and navigation
- Configurable source and translation languages and their display order
- Short reading units based on sentence boundaries and (for long sentences) commas/semicolons
- Google Translate via `deep-translator`, with retries and a pause between requests
- SQLite cache to resume after an interrupted conversion without retranslating successful segments
- Original text printed smaller and grey via EPUB CSS
- No DRM removal; use EPUB files you have permission to process

## Installation

Requires Python 3.10+.

```bash
git clone https://github.com/f-r-e-d-eth/Lingaris.git
cd Lingaris
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Usage

```bash
python lingaris.py "My Book.epub"
```

Produces `My Book_en_es.epub` next to the source EPUB.

Specify a different language pair:

```bash
python lingaris.py "Mon Livre.epub" --source fr --target de
```

Change language order to show the original first:

```bash
python lingaris.py book.epub --original-first
```

See `python lingaris.py --help` for settings.

## Limitations (initial release)

- Processes paragraph/list text in XHTML chapters. Headings and navigation labels stay in the original language.
- Images, EPUB resource files and navigation are copied unchanged. Paragraphs that contain images, links, or complex embedded block elements are left untouched to avoid damaging them.
- Original inline emphasis within translated text paragraphs is simplified when rebuilding bilingual sentence pairs. We can improve this after testing a sample EPUB.
- Google's unofficial web translation interface is not guaranteed to remain available and may throttle large books.
- Translation quality and sentence alignment need review, especially for dialogue and abbreviations.
- The translation cache is stored locally in `.lingaris-cache.sqlite3`; don't commit it or copyrighted books.

## Development

```bash
pip install -r requirements.txt
python -m unittest discover -s tests -v
```

MIT licensed. Lingaris is intended for personal language learning; follow the license and local rules applying to each source book.
