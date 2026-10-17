#!/usr/bin/env python3
"""Convert a DRM-free EPUB to a bilingual, sentence-paired EPUB."""
import argparse
import posixpath
import re
import sqlite3
import time
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

from bs4 import BeautifulSoup
from deep_translator import GoogleTranslator

STYLE = """
.lingaris-pair { display: block; margin-bottom: .65em; }
.lingaris-translation { display: block; }
.lingaris-original { display: block; font-size: .88em; color: #777; }
"""


def split_long(sentence):
    sentence = sentence.strip()
    if len(sentence.split()) <= 12:
        return [sentence] if sentence else []
    positions = sorted((m.end() for m in re.finditer(r'[,;]', sentence)), reverse=True)
    for pos in positions:
        before, after = sentence[:pos].strip(), sentence[pos:].strip()
        if len(before.split()) >= 3 and len(after.split()) >= 3:
            return split_long(before) + split_long(after)
    return [sentence]


def split_text(text):
    text = re.sub(r'\s+', ' ', text).strip()
    if not text:
        return []
    # Retain punctuation and avoid splitting after common English abbreviations.
    pieces = re.split(r'(?<=[.!?])\s+(?=[\\"“‘A-Z0-9])', text)
    pieces = [p for s in pieces for p in split_long(s)]
    result, pending = [], []
    for piece in pieces:
        pending.append(piece)
        if len(' '.join(pending).split()) >= 3:
            result.append(' '.join(pending))
            pending = []
    if pending:
        if result:
            result[-1] += ' ' + ' '.join(pending)
        else:
            result.append(' '.join(pending))
    return result


def prepare_argos(source, target, install=False):
    """Load a locally installed Argos model; optionally download it once."""
    try:
        import argostranslate.package as package
        import argostranslate.translate as translate
    except ImportError as exc:
        raise RuntimeError("Argos is not installed. Run: pip install argostranslate") from exc

    def find_model():
        packages = package.get_installed_packages()
        return any(p.from_code == source and p.to_code == target for p in packages)

    if not find_model():
        if not install:
            raise RuntimeError(
                f"No Argos model for {source}->{target}. "
                f"Run with --engine argos --install-argos-model --test-translation 'Hello world.'"
            )
        print(f"Downloading Argos {source}->{target} model (one-time setup)...", flush=True)
        package.update_package_index()
        available = next((p for p in package.get_available_packages()
                          if p.from_code == source and p.to_code == target), None)
        if available is None:
            raise RuntimeError(f"No direct Argos package available for {source}->{target}")
        package.install_from_path(available.download())
    return translate.get_translation_from_codes(source, target)


class Translator:
    def __init__(self, source, target, cache, retries=3, delay=1, interval=1.5, cooldown=30, engine='google', install_argos_model=False):
        self.source, self.target = source, target
        self.engine = engine
        self.cache_source = f'{engine}:{source}'
        self.client = (GoogleTranslator(source=source, target=target) if engine == 'google'
                       else prepare_argos(source, target, install_argos_model))
        self.db = sqlite3.connect(cache)
        self.db.execute('CREATE TABLE IF NOT EXISTS translations (source TEXT, target TEXT, original TEXT, translated TEXT, PRIMARY KEY(source,target,original))')
        self.retries, self.delay = retries, delay
        self.interval, self.cooldown = interval, cooldown
        self.last_request = None
        self.new, self.hits, self.failed = 0, 0, 0

    def translate(self, text):
        row = self.db.execute('SELECT translated FROM translations WHERE source=? AND target=? AND original=?', (self.cache_source, self.target, text)).fetchone()
        if row:
            self.hits += 1
            print(f'[{self.new} new / {self.hits} cached] {self.source.upper()}: {text}', flush=True)
            print(f'  {self.target.upper()} (cached): {row[0]}\\n', flush=True)
            return row[0]
        print(f'[{self.new} new / {self.hits} cached] {self.source.upper()}: {text}', flush=True)
        rate_limited = False
        for attempt in range(self.retries):
            if self.last_request is not None:
                wait = self.interval - (time.monotonic() - self.last_request)
                if wait > 0:
                    time.sleep(wait)
            self.last_request = time.monotonic()
            try:
                result = self.client.translate(text)
                if not result:
                    raise ValueError('Empty translation')
                with self.db:
                    self.db.execute('INSERT OR REPLACE INTO translations VALUES (?,?,?,?)', (self.cache_source, self.target, text, result))
                self.new += 1
                print(f'  {self.target.upper()}: {result}\\n', flush=True)
                return result
            except Exception as e:
                print(f'Translation attempt {attempt+1}/{self.retries} failed: {e}', flush=True)
                limited = any(word in str(e).lower() for word in ('too many requests', '429', 'rate limit'))
                rate_limited = rate_limited or limited
                if attempt + 1 < self.retries:
                    wait = self.cooldown * (2 ** attempt) if limited else self.delay
                    print(f'Waiting {wait:g}s before retry', flush=True)
                    time.sleep(wait)
        if rate_limited:
            raise RuntimeError('Translation service is still rate-limiting requests after retries. Stop now; successful translations are cached. Try again later.')
        self.failed += 1
        print(f'  FAILED: untranslated unit (total failures: {self.failed})\\n', flush=True)
        return None

    def close(self):
        self.db.close()


def transform_xhtml(raw, translator, original_first=False):
    soup = BeautifulSoup(raw, 'xml')
    body = soup.find('body')
    if body is None:
        return raw
    altered = False
    for node in list(body.find_all(['p', 'li'])):
        # Do not break figures, hyperlinks or nested block layouts.
        if node.find(['img', 'svg', 'math', 'a', 'table', 'pre', 'code', 'audio', 'video']):
            continue
        if node.name == 'li' and node.find(['p', 'li', 'div', 'ul', 'ol']):
            continue
        if node.find_parent(['nav', 'script', 'style']):
            continue
        units = split_text(node.get_text(' ', strip=True))
        if not units:
            continue
        translations = [translator.translate(unit) for unit in units]
        if any(x is None for x in translations):
            continue
        block = soup.new_tag('div')
        block['class'] = 'lingaris-block'
        if node.get('id') and node.name == 'p':
            block['id'] = node['id']
        for unit, translated in zip(units, translations):
            pair = soup.new_tag('div')
            pair['class'] = 'lingaris-pair'
            contents = [('original', unit, translator.source), ('translation', translated, translator.target)]
            if not original_first:
                contents.reverse()
            for cls, value, language in contents:
                span = soup.new_tag('span')
                span['class'] = 'lingaris-' + cls
                span['lang'] = language
                span.string = value
                pair.append(span)
            block.append(pair)
        if node.name == 'li':
            node.clear()
            node.append(block)
        else:
            node.replace_with(block)
        altered = True
    if not altered:
        return raw
    head = soup.find('head')
    if head:
        style = soup.new_tag('style', type='text/css')
        style.string = STYLE
        head.append(style)
    return str(soup).encode('utf-8')


def chapter_paths(archive):
    container = ET.fromstring(archive.read('META-INF/container.xml'))
    rootfile = next(el.attrib['full-path'] for el in container.iter() if el.tag.endswith('rootfile'))
    package = ET.fromstring(archive.read(rootfile))
    items = {el.get('id'): el for el in package.iter() if el.tag.endswith('item') and el.get('id')}
    spine = next(el for el in package.iter() if el.tag.endswith('spine'))
    names = set(archive.namelist())
    result = set()
    for ref in spine:
        if not ref.tag.endswith('itemref'):
            continue
        item = items.get(ref.get('idref'))
        if item is None or item.get('media-type') != 'application/xhtml+xml' or 'nav' in item.get('properties', '').split():
            continue
        href = item.get('href', '').split('#')[0]
        path = posixpath.normpath(posixpath.join(posixpath.dirname(rootfile), href))
        if path in names:
            result.add(path)
    return result


def convert(source, output, translator, original_first=False):
    if source.resolve() == output.resolve():
        raise ValueError('Input and output must differ')
    partial = output.with_name(output.name + '.partial')
    try:
        with zipfile.ZipFile(source) as src, zipfile.ZipFile(partial, 'w') as dst:
            chapters = chapter_paths(src)
            print(f'Found {len(chapters)} chapter documents')
            for item in src.infolist():
                raw = src.read(item.filename)
                if item.filename in chapters:
                    print('Processing', item.filename, flush=True)
                    raw = transform_xhtml(raw, translator, original_first)
                dst.writestr(item, raw)
        partial.replace(output)
    finally:
        partial.unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser(description='Translate an EPUB to bilingual reading units')
    parser.add_argument('epub', type=Path, nargs='?', help='EPUB to convert')
    parser.add_argument('--engine', choices=['google', 'argos'], default='google')
    parser.add_argument('--install-argos-model', action='store_true', help='Download the selected Argos language model once')
    parser.add_argument('--test-translation', metavar='TEXT', help='Translate only this text and exit')
    parser.add_argument('-o', '--output', type=Path)
    parser.add_argument('--source', default='en')
    parser.add_argument('--target', default='es')
    parser.add_argument('--original-first', action='store_true')
    parser.add_argument('--cache', type=Path, default=Path('.lingaris-cache.sqlite3'))
    parser.add_argument('--retries', type=int, default=3)
    parser.add_argument('--retry-delay', type=float, default=1)
    parser.add_argument('--request-interval', type=float, default=1.5, help='Minimum seconds between translation requests (default: 1.5)')
    parser.add_argument('--rate-limit-cooldown', type=float, default=30, help='Initial pause after rate limiting; doubles per retry (default: 30)')
    args = parser.parse_args()
    if args.test_translation is None and (args.epub is None or not args.epub.is_file()):
        parser.error('Input EPUB not found')
    if args.source == args.target:
        parser.error('Source and target must differ')
    if args.retries < 1 or args.retry_delay < 0 or args.request_interval < 0 or args.rate_limit_cooldown < 0:
        parser.error('Retries must be >= 1 and retry delay must be >= 0')
    output = (args.output or args.epub.with_name(f'{args.epub.stem}_{args.source}_{args.target}.epub')) if args.epub else None
    translator = Translator(args.source, args.target, args.cache, args.retries, args.retry_delay,
                            args.request_interval, args.rate_limit_cooldown,
                            args.engine, args.install_argos_model)
    try:
        try:
            if args.test_translation is not None:
                result = translator.translate(args.test_translation)
                if result is None:
                    parser.exit(1, 'Test translation failed.\\n')
                return
            convert(args.epub, output, translator, args.original_first)
        except RuntimeError as exc:
            parser.exit(1, f'\\nStopped: {exc}\\nTranslations saved: {translator.new} new, {translator.hits} cached.\\n')
        print(f'Created {output}: {translator.new} new, {translator.hits} cached, {translator.failed} failed')
    finally:
        translator.close()


if __name__ == '__main__':
    main()
