# -*- coding: utf-8 -*-
import asyncio

import logging
import os
import re

from typing import Optional
from urllib.parse import urljoin

import aiohttp
import requests
from bs4 import BeautifulSoup

URL = 'https://m.0ae247c57c.icu/book/64694/list.html'
HEADERS = {
    'user-agent': "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/139.0.7258.140 Safari/537.36"
}


def beautify():
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


def novel_write_file(title: str, content: str, novel_id) -> None:
    """写入文件"""
    base_dir = 'D:\\'
    novel_dir = os.path.join(base_dir, novel_id)
    if not os.path.exists(novel_dir):
        os.makedirs(novel_dir)
    with open(os.path.join(novel_dir, f'{title}.txt'), 'a', encoding='utf-8') as f:
        f.write(content)


class AsyncNovelCrawler:
    """异步爬取类"""

    def __init__(
            self,
            base_url: str,
            book_urls: list[str],
            novel_id: str,
            headers=None,
            max_concurrency: int = 10,
            timeout: float = 6.1,
            batch_size: int = 20
    ):
        self.base_url = base_url
        self.book_urls = book_urls
        self.novel_id = novel_id
        self.session = None
        self.headers = headers or HEADERS
        self.timeout = timeout
        self.max_concurrency = max_concurrency
        self.semaphore = asyncio.Semaphore(max_concurrency)
        self.batch_size = batch_size
        self.chain = set()
        self.logger = logging.getLogger(self.__class__.__name__)
        if not self.logger.handlers:
            handler = logging.StreamHandler()
            formatter = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
            handler.setFormatter(formatter)
            self.logger.addHandler(handler)
            self.logger.setLevel(logging.DEBUG)

    async def __aenter__(self):
        timeout = aiohttp.ClientTimeout(total=self.timeout)
        self.session = aiohttp.ClientSession(
            headers=self.headers,
            timeout=timeout,
        )
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.session.close()

    async def fetch_page(self, url: str, retries: int = 3) -> str:
        """异步获取页面内容"""
        for attempt in range(retries):
            try:
                await asyncio.sleep(0.2)
                async with self.session.get(url) as response:
                    if response.status == 200:
                        return await response.text()
                    else:
                        self.logger.warning(f"HTTP {response.status} 为 {url}, 尝试 {attempt + 1}/{retries}")

            except (aiohttp.ClientError, asyncio.TimeoutError) as e:
                self.logger.warning(f"获取错误 {url}, 尝试 {attempt + 1}/{retries}: {e}")
            if attempt < retries - 1:
                await asyncio.sleep(1 * (attempt + 1))
        self.logger.error(f"Failed to fetch {url} after {retries} attempts")
        return ""

    def extract_and_save(self, html: str):
        """提取标题，内容..."""
        try:
            soup = BeautifulSoup(html, 'html.parser')
            title = soup.title.text if soup.title.text else '无标题'

            self.logger.info(f"{title} 爬取成功")
            content_element = soup.find('div', id='chaptercontent')
            if content_element:
                content = content_element.get_text(separator='\n', strip=True)
                # self.logger.info(f"成功提取 {title}")
                novel_write_file(title, content, novel_id=self.novel_id)
            else:
                self.logger.warning('未找到')

        except Exception as e:
            self.logger.error(f'Error: {e}')

    def find_chapter_link(self, html: str) -> Optional[str]:
        """解析器， 查找下一章的url"""
        try:
            soup = BeautifulSoup(html, 'html.parser')
            next_chapter_url = soup.select_one('#pb_next')
            if next_chapter_url and next_chapter_url.get('href'):
                next_url = next_chapter_url.get('href')
                return urljoin(self.base_url, next_url)
        except Exception as e:
            self.logger.error(f'Error: {e}')
            return None

    async def worker(self, star_url: str) -> None:
        """
        处理一个主章节及其所有子章节
        以下的正则只能匹配笔趣阁中小说连接
        """
        try:
            current_url = star_url

            # 用正则提取来判断是否有子章节如：1.html 和 子章节1_2 来进行比较
            pattern = r'(\d+)(?:_(\d+))?\.html$'
            match = re.search(pattern, current_url)
            if not match:
                self.logger.info(f'pattern error---> 错误！！！请确认 {current_url} 是否正确url？')
            main_chapter_id = match.group(1)

            while current_url and current_url not in self.chain:
                self.chain.add(current_url)
                html = await self.fetch_page(current_url)
                if not html:
                    break

                # 提取并保存当前页内容
                await asyncio.to_thread(self.extract_and_save, html)
                try:
                    # 获取子章节url
                    next_url = self.find_chapter_link(html)
                    if not next_url:
                        break

                    # 检查是否还在同一主章节内（如 6_1.html → 6_2.html，但 6_9.html → 7.html 就停止）
                    match_next = re.search(pattern, next_url)
                    if not match_next:
                        break

                    if main_chapter_id == match_next.group(1):
                        # 如果是直接爬取下一章
                        current_url = next_url
                    else:
                        break
                except AttributeError:
                    self.logger.info('爬取成功！！！')
                    break

        except Exception as e:
            self.logger.error(f'Error: {e}')

    async def crawl(self):
        """并发执行所有主章节抓取"""

        # 用于限制并发量
        async def bounded_worker(star_url):
            async with self.semaphore:
                await self.worker(star_url)

        tasks = [bounded_worker(url) for url in self.book_urls]
        future = await asyncio.gather(*tasks)
        for fut in future:
            if isinstance(fut, Exception):
                self.logger.error(fut)


async def main(base_url, book_list_urls: list[str], novel_id: str) -> None:
    async with AsyncNovelCrawler(
            base_url=base_url,
            book_urls=book_list_urls,
            max_concurrency=20,
            batch_size=50,
            novel_id=novel_id
    ) as crawler:
        await crawler.crawl()

# if __name__ == '__main__':
#     new_book_list_urls, title = beautify()
#
#     asyncio.run(main(URL, new_book_list_urls[:20], novel_id=title))
