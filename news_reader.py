"""
Tkinter + asyncio RSS reader for Thanh Nien.
"""
import asyncio
import threading
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from io import BytesIO
from typing import Any, Coroutine, List, Optional, TypeVar

T = TypeVar("T")

import aiohttp
from bs4 import BeautifulSoup
from PIL import Image, ImageTk
import tkinter as tk
from tkinter import ttk, messagebox


@dataclass
class Article:
    title: str
    link: str


class AsyncioThread(threading.Thread):
    """Run an asyncio event loop in a background thread.

    Tkinter must run on the main thread, so network tasks live in the loop below.
    The ``submit`` helper schedules coroutines without blocking the UI.
    """

    def __init__(self) -> None:
        super().__init__(daemon=True)
        self.loop = asyncio.new_event_loop()

    def run(self) -> None:
        asyncio.set_event_loop(self.loop)
        self.loop.run_forever()

    def submit(self, coro: Coroutine[Any, Any, T]) -> asyncio.Future[T]:
        return asyncio.run_coroutine_threadsafe(coro, self.loop)

    def shutdown(self) -> None:
        self.loop.call_soon_threadsafe(self.loop.stop)


class NewsReaderApp:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("Thanh Nien RSS Reader")
        self.root.geometry("1100x700")

        self.async_thread = AsyncioThread()
        self.async_thread.start()

        self.default_feeds = {
            "Tin mới": "https://thanhnien.vn/rss/home.rss",
            "Thời sự": "https://thanhnien.vn/rss/thoi-su.rss",
            "Thế giới": "https://thanhnien.vn/rss/the-gioi.rss",
            "Kinh doanh": "https://thanhnien.vn/rss/kinh-doanh.rss",
            "Văn hóa": "https://thanhnien.vn/rss/van-hoa.rss",
        }

        self.articles: List[Article] = []
        self.image_refs: List[ImageTk.PhotoImage] = []

        self._build_layout()
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

    def _build_layout(self) -> None:
        top_frame = ttk.Frame(self.root, padding=10)
        top_frame.pack(fill=tk.X)

        ttk.Label(top_frame, text="RSS URL:").pack(side=tk.LEFT)
        self.url_var = tk.StringVar(value="https://thanhnien.vn/rss/home.rss")
        ttk.Entry(top_frame, textvariable=self.url_var, width=60).pack(side=tk.LEFT, padx=5)

        ttk.Label(top_frame, text="Hoặc chọn nhanh:").pack(side=tk.LEFT, padx=5)
        self.feed_choice = tk.StringVar()
        feed_combo = ttk.Combobox(
            top_frame,
            textvariable=self.feed_choice,
            values=list(self.default_feeds.keys()),
            width=20,
            state="readonly",
        )
        feed_combo.pack(side=tk.LEFT)
        feed_combo.bind("<<ComboboxSelected>>", self.on_feed_selected)

        self.load_button = ttk.Button(top_frame, text="Tải dữ liệu", command=self.load_feed)
        self.load_button.pack(side=tk.LEFT, padx=10)

        main_frame = ttk.Frame(self.root, padding=10)
        main_frame.pack(fill=tk.BOTH, expand=True)

        # Left list of article titles
        left_frame = ttk.Frame(main_frame)
        left_frame.pack(side=tk.LEFT, fill=tk.Y)
        ttk.Label(left_frame, text="Danh sách bài viết", font=("Arial", 12, "bold")).pack(anchor=tk.W)
        self.listbox = tk.Listbox(left_frame, width=45, height=30)
        self.listbox.pack(side=tk.LEFT, fill=tk.Y, expand=False, pady=(5, 0))
        self.listbox.bind("<<ListboxSelect>>", self.on_article_selected)
        list_scroll = ttk.Scrollbar(left_frame, orient=tk.VERTICAL, command=self.listbox.yview)
        list_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self.listbox.config(yscrollcommand=list_scroll.set)

        # Right content view
        right_frame = ttk.Frame(main_frame)
        right_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(15, 0))
        ttk.Label(right_frame, text="Nội dung bài viết", font=("Arial", 12, "bold")).pack(anchor=tk.W)

        content_container = ttk.Frame(right_frame)
        content_container.pack(fill=tk.BOTH, expand=True, pady=(5, 0))
        self.content_text = tk.Text(content_container, wrap=tk.WORD)
        self.content_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        content_scroll = ttk.Scrollbar(content_container, orient=tk.VERTICAL, command=self.content_text.yview)
        content_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self.content_text.config(yscrollcommand=content_scroll.set)

    def on_feed_selected(self, event: tk.Event) -> None:
        choice = self.feed_choice.get()
        url = self.default_feeds.get(choice)
        if url:
            self.url_var.set(url)

    def load_feed(self) -> None:
        url = self.url_var.get().strip()
        if not url:
            messagebox.showwarning("Thiếu URL", "Vui lòng nhập đường dẫn RSS hợp lệ")
            return
        self.load_button.config(state=tk.DISABLED)
        future = self.async_thread.submit(self.fetch_rss(url))
        future.add_done_callback(self._handle_feed_result)

    def _handle_feed_result(self, fut: asyncio.Future) -> None:
        try:
            articles = fut.result()
        except Exception as exc:  # noqa: BLE001
            self.root.after(0, lambda: messagebox.showerror("Lỗi tải RSS", str(exc)))
            self.root.after(0, lambda: self.load_button.config(state=tk.NORMAL))
            return
        self.root.after(0, lambda: self.populate_list(articles))
        self.root.after(0, lambda: self.load_button.config(state=tk.NORMAL))

    async def fetch_rss(self, url: str) -> List[Article]:
        """Download and parse the RSS feed asynchronously."""
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=20) as resp:
                resp.raise_for_status()
                content = await resp.text()

        root = ET.fromstring(content)
        items = []
        for item_el in root.findall(".//item"):
            title = item_el.findtext("title", default="(Không tiêu đề)")
            link = item_el.findtext("link", default="")
            if link:
                items.append(Article(title=title, link=link))
        return items

    def populate_list(self, articles: List[Article]) -> None:
        self.articles = articles
        self.listbox.delete(0, tk.END)
        for art in articles:
            self.listbox.insert(tk.END, art.title)
        self.content_text.delete("1.0", tk.END)
        self.image_refs.clear()
        if not articles:
            self.content_text.insert(tk.END, "Không tìm thấy bài viết nào.")

    def on_article_selected(self, event: tk.Event) -> None:
        if not self.listbox.curselection():
            return
        index = self.listbox.curselection()[0]
        article = self.articles[index]
        self.content_text.delete("1.0", tk.END)
        self.content_text.insert(tk.END, "Đang tải nội dung bài viết...")

        future = self.async_thread.submit(self.fetch_article(article.link))
        future.add_done_callback(lambda fut: self._handle_article_result(fut, article.title))

    def _handle_article_result(self, fut: asyncio.Future, title: str) -> None:
        try:
            paragraphs, images = fut.result()
        except Exception as exc:  # noqa: BLE001
            self.root.after(0, lambda: messagebox.showerror("Lỗi tải bài viết", str(exc)))
            return
        self.root.after(0, lambda: self.display_article(title, paragraphs, images))

    async def fetch_article(self, url: str) -> tuple[list[str], list[Image.Image]]:
        """Fetch article HTML and download embedded images asynchronously."""
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=20) as resp:
                resp.raise_for_status()
                html = await resp.text()

            soup = BeautifulSoup(html, "html.parser")
            paragraphs = [p.get_text(strip=True) for p in soup.find_all("p") if p.get_text(strip=True)]

            images: list[Image.Image] = []
            for img_el in soup.find_all("img"):
                src = img_el.get("src")
                if not src:
                    continue
                try:
                    async with session.get(src, timeout=20) as img_resp:
                        img_resp.raise_for_status()
                        data = await img_resp.read()
                    image = Image.open(BytesIO(data)).convert("RGB")
                    images.append(image)
                except Exception:
                    # Skip images that fail to download or parse
                    continue

        return paragraphs, images

    def display_article(self, title: str, paragraphs: List[str], images: List[Image.Image]) -> None:
        self.content_text.delete("1.0", tk.END)
        self.image_refs.clear()
        self.content_text.insert(tk.END, f"{title}\n\n", ("title",))
        self.content_text.tag_config("title", font=("Arial", 14, "bold"))

        img_iter = iter(images)
        for idx, para in enumerate(paragraphs):
            self.content_text.insert(tk.END, para + "\n\n")
            try:
                image = next(img_iter)
            except StopIteration:
                continue
            photo = self._prepare_image_for_display(image)
            if photo:
                self.content_text.image_create(tk.END, image=photo)
                self.content_text.insert(tk.END, "\n\n")
                self.image_refs.append(photo)

        # Append any leftover images if there were more images than paragraphs.
        for image in img_iter:
            photo = self._prepare_image_for_display(image)
            if photo:
                self.content_text.image_create(tk.END, image=photo)
                self.content_text.insert(tk.END, "\n\n")
                self.image_refs.append(photo)

    def _prepare_image_for_display(self, image: Image.Image) -> Optional[ImageTk.PhotoImage]:
        max_width = 700
        if image.width > max_width:
            ratio = max_width / image.width
            new_size = (int(image.width * ratio), int(image.height * ratio))
            image = image.resize(new_size, Image.LANCZOS)
        return ImageTk.PhotoImage(image)

    def on_close(self) -> None:
        self.async_thread.shutdown()
        self.root.destroy()


def main() -> None:
    root = tk.Tk()
    app = NewsReaderApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
