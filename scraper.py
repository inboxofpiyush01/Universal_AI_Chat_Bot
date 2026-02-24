# crawler/scraper.py
import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse
import time
import logging
import html as html_module
import unicodedata
import re
from typing import List, Dict, Optional
from config.settings import settings

logger = logging.getLogger(__name__)


class WebScraper:
    """
    Generic web scraper. Extracts individual products as separate documents
    so each product gets its own vector embedding — no hallucination.
    """

    def __init__(self, base_url: str, max_pages: int = None):
        self.base_url = base_url.rstrip("/")
        self.domain = urlparse(base_url).netloc
        self.max_pages = max_pages or settings.MAX_PAGES_PER_SITE
        self.visited_urls = set()
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (compatible; ChatBotSaaSBot/1.0)"
        })

    def crawl(self) -> List[Dict]:
        logger.info(f"Starting crawl for: {self.base_url}")
        pages_data = []
        urls_to_visit = [self.base_url]

        while urls_to_visit and len(self.visited_urls) < self.max_pages:
            url = urls_to_visit.pop(0)
            if url in self.visited_urls:
                continue

            page_data = self._scrape_page(url)
            if page_data:
                pages_data.append(page_data)
                self.visited_urls.add(url)
                new_links = self._extract_links(page_data.get("raw_html", ""), url)
                for link in new_links:
                    if link not in self.visited_urls:
                        urls_to_visit.append(link)

            time.sleep(settings.CRAWL_DELAY_SECONDS)

        logger.info(f"Crawled {len(pages_data)} pages from {self.base_url}")
        return pages_data

    def _scrape_page(self, url: str) -> Optional[Dict]:
        try:
            response = self.session.get(url, timeout=10)
            if response.status_code != 200:
                return None

            response.encoding = "utf-8"
            soup = BeautifulSoup(response.text, "lxml")

            title = self._extract_title(soup)
            page_type = self._detect_page_type(url, soup)

            # ── Extract individual products (each becomes its own chroma doc) ──
            products = self._extract_products(soup, url)

            # ── Extract general page text (for non-product pages) ─────────────
            for tag in soup(["script", "style", "nav", "footer", "head"]):
                tag.decompose()
            content = self._extract_content(soup, products)

            if not content.strip() and not products:
                return None

            return {
                "url": url,
                "title": title,
                "content": content,
                "page_type": page_type,
                "products": products,       # ← individual product dicts
                "structured": {"images": self._extract_images(soup)},
                "raw_html": response.text,
            }

        except Exception as e:
            logger.warning(f"Failed to scrape {url}: {e}")
            return None

    def _extract_products(self, soup: BeautifulSoup, page_url: str) -> List[Dict]:
        """
        Extract each product as an individual structured dict.
        Tries multiple class-name patterns to work across different websites.
        """
        products = []

        # Find all product containers
        containers = (
            soup.find_all(class_=re.compile(r"product[-_]?(card|item|tile|box)", re.I)) or
            soup.find_all(attrs={"data-product-id": True}) or
            soup.find_all(attrs={"data-sku": True})
        )

        if not containers:
            # Fallback: find all product-name elements and walk up to parent
            name_els = soup.find_all(class_=re.compile(r"product[-_]?name|item[-_]?name", re.I))
            containers = [el.find_parent() for el in name_els if el.find_parent()]

        seen = set()
        for card in containers:
            # ── Name ──────────────────────────────────────────────────────────
            name_el = (
                card.find(class_=re.compile(r"product[-_]?name|item[-_]?name", re.I)) or
                card.find(["h2", "h3", "h4"])
            )
            if not name_el:
                continue
            name = self._clean_text(name_el.get_text(strip=True))
            if not name or name in seen:
                continue
            seen.add(name)

            # ── Brand ─────────────────────────────────────────────────────────
            brand_el = card.find(class_=re.compile(r"product[-_]?brand|brand[-_]?name", re.I))
            brand = self._clean_text(brand_el.get_text(strip=True)) if brand_el else ""

            # ── Price — remove strikethrough old price, keep current ──────────
            price_el = card.find(class_=re.compile(r"product[-_]?price|current[-_]?price|price", re.I))
            price = ""
            if price_el:
                # Remove struck-through old price
                for old in price_el.find_all(["s", "del", "span"], class_=re.compile(r"old|original|mrp|strike", re.I)):
                    old.decompose()
                raw_price = price_el.get_text(strip=True)
                # Extract the LAST price in the string (current price after sale)
                price_matches = re.findall(r'(?:Rs\.?\s*|₹\s*)[\d,]+', raw_price)
                if price_matches:
                    price = self._clean_text(price_matches[-1])
                else:
                    price = self._clean_text(raw_price.strip())

            # ── Description ───────────────────────────────────────────────────
            desc_el = card.find(class_=re.compile(r"product[-_]?desc|description|product[-_]?info", re.I))
            desc = self._clean_text(desc_el.get_text(strip=True)) if desc_el else ""

            # ── Rating ────────────────────────────────────────────────────────
            rating_el = card.find(class_=re.compile(r"rating|review|stars", re.I))
            rating = self._clean_text(rating_el.get_text(strip=True)) if rating_el else ""

            # ── Image — real product photo ────────────────────────────────────
            image = ""
            img_container = card.find(class_=re.compile(r"product[-_]?img|product[-_]?image|thumb", re.I))
            img_el = (img_container.find("img") if img_container else None) or card.find("img")
            if img_el:
                src = img_el.get("src") or img_el.get("data-src") or ""
                if src and not any(x in src.lower() for x in ["logo", "icon", ".svg", ".ico", "sprite", "placeholder"]):
                    # Resolve relative URLs
                    if src.startswith("http"):
                        image = src
                    else:
                        image = urljoin(page_url, src)

            # ── Product page URL ──────────────────────────────────────────────
            link_el = card.find("a", href=True)
            prod_url = urljoin(page_url, link_el["href"]) if link_el else page_url

            if name:
                products.append({
                    "name": name,
                    "brand": brand,
                    "price": price,
                    "description": desc,
                    "rating": rating,
                    "image": image,
                    "url": prod_url,
                    "page_url": page_url,
                })

        logger.info(f"  Extracted {len(products)} products from {page_url}")
        return products

    def _extract_content(self, soup: BeautifulSoup, products: List[Dict]) -> str:
        """Build content string. Products are formatted precisely — no ambiguity for LLM."""
        parts = []

        # Products first — exact data, no hallucination possible
        for p in products:
            lines = [f"Product: {p['name']}"]
            if p["brand"]:    lines.append(f"Brand: {p['brand']}")
            if p["price"]:    lines.append(f"Price: {p['price']}")
            if p["description"]: lines.append(f"Description: {p['description']}")
            if p["rating"]:   lines.append(f"Rating: {p['rating']}")
            if p["image"]:    lines.append(f"Image: {p['image']}")
            if p["url"]:      lines.append(f"URL: {p['url']}")
            parts.append("\n".join(lines))

        # Non-product text (about, FAQ, policies)
        for tag in soup.find_all(["h1", "h2", "h3"]):
            text = self._clean_text(tag.get_text(strip=True))
            if text and len(text) > 3:
                parts.append(f"[{text}]")

        for p_tag in soup.find_all("p"):
            text = self._clean_text(p_tag.get_text(strip=True))
            if len(text) > 30:
                parts.append(text)

        for li in soup.find_all("li"):
            text = self._clean_text(li.get_text(strip=True))
            if len(text) > 10:
                parts.append(f"- {text}")

        return "\n\n".join(parts)

    def _extract_title(self, soup: BeautifulSoup) -> str:
        if soup.title and soup.title.string:
            return self._clean_text(soup.title.string)
        h1 = soup.find("h1")
        return self._clean_text(h1.get_text(strip=True)) if h1 else ""

    def _detect_page_type(self, url: str, soup: BeautifulSoup) -> str:
        u = url.lower()
        if any(k in u for k in ["product", "item", "catalogue"]): return "product"
        if any(k in u for k in ["faq", "help", "support"]):       return "faq"
        if any(k in u for k in ["about", "story", "team"]):        return "about"
        if any(k in u for k in ["contact", "store", "location"]):  return "contact"
        if any(k in u for k in ["price", "plan", "cost"]):         return "pricing"
        if any(k in u for k in ["women", "men", "accessories", "sale", "collection"]): return "category"
        if u == self.base_url.lower() or u == self.base_url.lower() + "/": return "homepage"
        return "general"

    def _extract_images(self, soup: BeautifulSoup) -> List[Dict]:
        images = []
        for img in soup.find_all("img", src=True)[:5]:
            src = img.get("src", "")
            if src and not any(x in src.lower() for x in ["logo", "icon", ".svg", ".ico"]):
                images.append({"src": src, "alt": img.get("alt", "")})
        return images

    def _clean_text(self, text: str) -> str:
        """Clean text — fix encoding, convert ₹ to Rs., strip garbage."""
        if not text:
            return ""
        text = html_module.unescape(text)
        text = unicodedata.normalize("NFKC", text)
        # Convert rupee symbol to Rs. at source — prevents all downstream mojibake
        text = text.replace("\u20b9", "Rs.")
        text = text.replace("₹", "Rs.")
        # Fix common garbled sequences
        text = re.sub(r'\u00e2[\u0080-\u00bf\u201a\u2020\u0082]?\u00b9', 'Rs.', text)
        text = text.replace("\u00d7", "x").replace("×", "x")
        text = text.replace("\u2019", "'").replace("\u2018", "'")
        text = text.replace("\u201c", '"').replace("\u201d", '"')
        text = text.replace("\u2013", "-").replace("\u2014", "-")
        text = text.replace("\u2026", "...").replace("\u00a0", " ")
        # Clean whitespace
        text = re.sub(r'\s+', ' ', text).strip()
        return text

    def _extract_links(self, html: str, current_url: str) -> List[str]:
        soup = BeautifulSoup(html, "lxml")
        links = []
        for a in soup.find_all("a", href=True):
            full_url = urljoin(current_url, a["href"])
            parsed = urlparse(full_url)
            if parsed.netloc == self.domain:
                clean_url = f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
                if not any(clean_url.endswith(ext) for ext in [".pdf", ".jpg", ".png", ".zip", ".csv"]):
                    links.append(clean_url)
        return list(set(links))
