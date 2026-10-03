#!/usr/bin/env python3
"""Download the room photos from the camp's WordPress room pages.

    python3 fetch_photos.py OUT_DIR

Writes OUT_DIR/<page-slug>/NN.jpg in page order. WordPress lists most photos
twice (the original and a "-scaled" 2560 px copy): the scaled copy is kept.
mod_security on the host refuses requests without a browser User-Agent.
"""
import json
import os
import re
import sys
import time
import urllib.request

UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/128 Safari/537.36'
SITE = 'https://www.laktentedcamp.com/room/%s/'
IMG = re.compile(r'(https://www\.laktentedcamp\.com/wp-content/uploads/[^"\'\s)]+\.(?:jpe?g|png|webp))', re.I)


def get(url):
    req = urllib.request.Request(url, headers={'User-Agent': UA})
    with urllib.request.urlopen(req, timeout=60) as resp:
        return resp.read()


def photo_urls(page_html):
    chosen = {}
    for url in IMG.findall(page_html):
        url = re.sub(r'-\d+x\d+(?=\.\w+$)', '', url)          # thumbnails -> full
        if 'cropped-lak' in url or 'logo' in url.lower():
            continue
        key = re.sub(r'-scaled(?=\.\w+$)', '', url)
        if key not in chosen or '-scaled' in url:
            chosen[key] = url
    return list(chosen.values())


def main(out):
    content = json.load(open(os.path.join(os.path.dirname(__file__), 'room_content.json')))
    pages = [p for k, v in content.items() if not k.startswith('_') for p in v['pages']]
    for page in pages:
        folder = os.path.join(out, page)
        os.makedirs(folder, exist_ok=True)
        urls = photo_urls(get(SITE % page).decode('utf-8', 'ignore'))
        for i, url in enumerate(urls, 1):
            path = os.path.join(folder, '%02d%s' % (i, os.path.splitext(url)[1].lower()))
            if not os.path.exists(path):
                open(path, 'wb').write(get(url))
                time.sleep(0.5)
        print(page, len(urls), 'photos')


if __name__ == '__main__':
    main(sys.argv[1])
