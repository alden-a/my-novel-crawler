# -*- coding: utf-8 -*-
import asyncio
from urllib.parse import urljoin


import requests
from bs4 import BeautifulSoup

from novel_crawl.crawl_the_novel import AsyncNovelCrawler

URL = 'https://m.0ae247c57c.icu/book/64694/list.html'
HEADERS = {
    'user-agent': "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/139.0.7258.140 Safari/537.36"
}


def beautify() -> tuple[list[str], str]:
    """提取目录中的url"""
    repose = requests.get(URL, headers=HEADERS).text
    soup = BeautifulSoup(repose, 'html.parser')
    divs = soup.find('div', class_='book_last')
    title = soup.title.text if soup.title.text else '无标题'
    url_paths = []
    for a in divs.find_all('a'):
        if a.get('href').endswith('.html'):
            url_path = urljoin(URL, a.get('href'))
            url_paths.append(url_path)
    return url_paths, title


async def main(base_url, book_list_urls: list[str], novel_id: str) -> None:
    async with AsyncNovelCrawler(
            base_url=base_url,
            book_urls=book_list_urls,
            max_concurrency=20,
            batch_size=50,
            novel_id=novel_id
    ) as crawler:
        await crawler.crawl()


if __name__ == '__main__':
    new_book_list_urls, title = beautify()

    asyncio.run(main(URL, new_book_list_urls[:5], novel_id=title))
