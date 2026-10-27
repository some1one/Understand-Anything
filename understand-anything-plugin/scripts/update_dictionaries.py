#!/usr/bin/env python3
"""Download dictionary data only; publish a verified generation atomically.

Never imports upstream Python or executes upstream build/install scripts.
Used for missing local components during installation and explicit plugin maintenance.
Packaging, graph updates and searches never invoke this downloader.
"""
from __future__ import annotations
import argparse
from concurrent.futures import ThreadPoolExecutor
import gzip
import hashlib
import io
import json
import math
import os
from pathlib import Path
import re
import ssl
import sys
import tempfile
import time
import urllib.error
import urllib.request
import zipfile

NAMES = ('cpp csharp css dart docker golang html java kotlin lua node php '
         'powershell python ruby rust scala shell software-terms sql swift '
         'terraform typescript').split()
TOKEN = re.compile(r'[\w]+(?:[./:\\-][\w]+)*(?:\+\+|#)?')
MAX_DOWNLOAD = 64 * 1024 * 1024


def sha(data):
    return hashlib.sha256(data).hexdigest()


def fetch(url):
    if not url.startswith('https://'):
        raise ValueError('Dictionary downloads require HTTPS')
    try:
        timeout = float(os.environ.get('UA_DICTIONARY_DOWNLOAD_TIMEOUT', '45'))
        attempts = int(os.environ.get('UA_DICTIONARY_DOWNLOAD_ATTEMPTS', '3'))
    except ValueError as error:
        raise ValueError('UA_DICTIONARY_DOWNLOAD_TIMEOUT must be a positive number and '
                         'UA_DICTIONARY_DOWNLOAD_ATTEMPTS an integer from 1 to 5') from error
    if not math.isfinite(timeout) or not 0 < timeout <= 300 or not 1 <= attempts <= 5:
        raise ValueError('UA_DICTIONARY_DOWNLOAD_TIMEOUT must be between 0 and 300 seconds '
                         '(exclusive of 0); UA_DICTIONARY_DOWNLOAD_ATTEMPTS must be from 1 to 5')
    request = urllib.request.Request(url, headers={'User-Agent': 'Understand-Anything-dictionary-updater'})
    for attempt in range(1, attempts + 1):
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                if not response.url.startswith('https://'):
                    raise ValueError('Insecure dictionary redirect')
                data = response.read(MAX_DOWNLOAD + 1)
            if len(data) > MAX_DOWNLOAD:
                raise ValueError('Dictionary download exceeds size limit')
            return data
        except (urllib.error.URLError, TimeoutError, ConnectionError, ssl.SSLError) as error:
            reason = getattr(error, 'reason', error)
            retry = not (isinstance(error, ssl.SSLCertVerificationError)
                         or isinstance(reason, ssl.SSLCertVerificationError))
            if isinstance(error, urllib.error.HTTPError):
                retry = error.code in (408, 429) or 500 <= error.code < 600
                error.close()
            if not retry or attempt == attempts:
                raise OSError(f'Dictionary download failed for {url} after {attempt} attempt(s) '
                              f'(socket timeout {timeout:g}s): {error}') from error
            print(f'Retrying dictionary download {url} (attempt {attempt + 1}/{attempts}): {error}',
                  file=sys.stderr)
            time.sleep(min(0.5 * 2 ** (attempt - 1), 4))


def json_bytes(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':')) + '\n').encode()


def compile_cspell(sources):
    dictionaries = {}
    for name in NAMES:
        words, forbidden = set(), set()
        prefix = f'dictionaries/{name}/'
        for path, data in sorted(sources.items()):
            if not path.startswith(prefix) or not path.endswith('.txt'):
                continue
            for line in data.decode('utf-8').splitlines():
                line = line.strip()
                if not line or line.startswith('#'):
                    continue
                if line.startswith('!'):
                    forbidden.add(line[1:].casefold())
                elif TOKEN.fullmatch(line):
                    words.add(line)
        dictionaries[name] = sorted(w for w in words if w.casefold() not in forbidden)
        if not dictionaries[name]:
            raise ValueError(f'Empty CSpell dictionary: {name}')
    return dictionaries


def compile_lemmas(lookup, overrides):
    result = {}
    for line in gzip.decompress(lookup).decode('utf-8').splitlines():
        word, category, forms = line.strip().split(',')
        pos = 'AUX' if category.upper() == 'MODAL' else category.upper()
        result.setdefault(word, {})[pos] = forms.split('/')
    for line in overrides.decode('utf-8').splitlines():
        line = line.strip()
        if line and not line.startswith('#'):
            word, pos, lemma = line.split(',')
            result.setdefault(word, {})[pos] = [lemma]
    if not result:
        raise ValueError('Empty LemmInflect dictionary')
    return result


def download_cspell():
    repository = 'https://api.github.com/repos/streetsidesoftware/cspell-dicts'
    revision = json.loads(fetch(repository + '/commits/main'))['sha']
    if not re.fullmatch('[0-9a-f]{40}', revision):
        raise ValueError('Invalid CSpell revision')
    tree = json.loads(fetch(repository + f'/git/trees/{revision}?recursive=1'))
    if tree.get('truncated'):
        raise ValueError('Incomplete CSpell file inventory')
    paths = []
    for entry in tree['tree']:
        path = entry['path']
        parts = path.split('/')
        if entry['type'] != 'blob' or len(parts) < 3 or parts[0] != 'dictionaries' or parts[1] not in NAMES:
            continue
        folder = 'src' if parts[1] in {'java', 'sql', 'swift'} else 'dict'
        if parts[2:] == ['LICENSE'] or (parts[2] == folder and path.endswith('.txt')):
            paths.append(path)
    def get(path):
        return path, fetch(f'https://raw.githubusercontent.com/streetsidesoftware/cspell-dicts/{revision}/{path}')
    with ThreadPoolExecutor(max_workers=8) as pool:
        sources = dict(pool.map(get, sorted(paths)))
    words = compile_cspell(sources)
    licenses = {f'cspell-{name}.LICENSE': sources[f'dictionaries/{name}/LICENSE'] for name in NAMES}
    return words, licenses, {'revision': revision, 'sourceSha256': {p: sha(v) for p, v in sources.items()}}


def download_lemminflect():
    metadata = json.loads(fetch('https://pypi.org/pypi/lemminflect/json'))
    wheels = [f for f in metadata['urls'] if f['filename'].endswith('-py3-none-any.whl') and not f.get('yanked')]
    if len(wheels) != 1:
        raise ValueError('Expected one platform-independent LemmInflect wheel')
    wheel = wheels[0]
    data = fetch(wheel['url'])
    if sha(data) != wheel['digests']['sha256']:
        raise ValueError('LemmInflect wheel checksum mismatch')
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        if sum(item.file_size for item in archive.infolist()) > MAX_DOWNLOAD:
            raise ValueError('LemmInflect archive exceeds size limit')
        lookup = archive.read('lemminflect/resources/lemma_lu.csv.gz')
        overrides = archive.read('lemminflect/resources/lemma_overrides.csv')
        license_path = next(p for p in archive.namelist() if p.endswith('/LICENSE') and '.dist-info/' in p)
        license_data = archive.read(license_path)
    return compile_lemmas(lookup, overrides), license_data, {'version': metadata['info']['version'],
        'wheelSha256': sha(data), 'lookupSha256': sha(lookup), 'overridesSha256': sha(overrides)}


def validate(output):
    pointer = json.loads((output / 'current.json').read_bytes())
    generation = pointer['generation']
    if not re.fullmatch('[0-9a-f]{64}', generation):
        raise ValueError('Invalid dictionary generation')
    directory = output / generation
    manifest_bytes = (directory / 'manifest.json').read_bytes()
    if sha(manifest_bytes) != generation:
        raise ValueError('Dictionary manifest checksum mismatch')
    manifest = json.loads(manifest_bytes)
    if manifest.get('version') != 1:
        raise ValueError('Unsupported dictionary schema')
    for name, digest in manifest['files'].items():
        if Path(name).name != name or sha((directory / name).read_bytes()) != digest:
            raise ValueError(f'Dictionary checksum mismatch: {name}')
    for name in ('cspell.json.gz', 'lemmas.json.gz'):
        json.loads(gzip.decompress((directory / name).read_bytes()))
    return pointer


def publish(output, words, lemmas, licenses, provenance):
    files = {'cspell.json.gz': gzip.compress(json_bytes(words), mtime=0),
             'lemmas.json.gz': gzip.compress(json_bytes(lemmas), mtime=0), **licenses}
    manifest = {'version': 1, 'sources': provenance, 'files': {name: sha(data) for name, data in files.items()}}
    manifest_bytes = json_bytes(manifest)
    generation = sha(manifest_bytes)
    output.mkdir(parents=True, exist_ok=True)
    # Readers use immutable generations. Failed downloads never alter current.json.
    with tempfile.TemporaryDirectory(prefix='.update-', dir=output) as temporary:
        staging = Path(temporary)
        for name, data in files.items():
            (staging / name).write_bytes(data)
        (staging / 'manifest.json').write_bytes(manifest_bytes)
        destination = output / generation
        if not destination.exists():
            try:
                staging.rename(destination)
            except OSError:
                if not destination.is_dir():
                    raise
        # Validate existing generations as well; never publish a corrupt snapshot.
        if (destination / 'manifest.json').read_bytes() != manifest_bytes:
            raise ValueError('Existing dictionary generation is corrupt')
        for name, digest in manifest['files'].items():
            if sha((destination / name).read_bytes()) != digest:
                raise ValueError(f'Existing dictionary file is corrupt: {name}')
        pointer = json_bytes({'version': 1, 'generation': generation})
        if not (output / 'current.json').exists() or (output / 'current.json').read_bytes() != pointer:
            with tempfile.NamedTemporaryFile(dir=output, prefix='.current-', delete=False) as handle:
                handle.write(pointer)
                temporary_pointer = Path(handle.name)
            temporary_pointer.replace(output / 'current.json')
    return validate(output)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    cache = Path(os.environ.get('XDG_CACHE_HOME', Path.home() / '.cache')) / 'understand-anything/dictionaries'
    parser.add_argument('--output', type=Path, default=Path(os.environ.get('UA_DICTIONARY_DIR', cache)))
    parser.add_argument('--offline', action='store_true', help='Validate existing data without downloads')
    args = parser.parse_args(argv)
    try:
        if args.offline:
            pointer = validate(args.output)
        else:
            words, licenses, cspell = download_cspell()
            lemmas, license_data, lemminflect = download_lemminflect()
            licenses['lemminflect.LICENSE'] = license_data
            pointer = publish(args.output, words, lemmas, licenses, {'cspell': cspell, 'lemminflect': lemminflect})
        print(json.dumps({'directory': str(args.output.resolve()), **pointer}))
        return 0
    except (OSError, ValueError, KeyError, StopIteration, zipfile.BadZipFile) as error:
        print(f'Dictionary update failed; previous generation retained: {error}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
