"""
Tkinter + asyncio RSS reader for Thanh Nien.
"""
import asyncio
import html
import threading
import webbrowser
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
    categories: List[str]


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
        self.root.geometry("1220x780")
        self.root.configure(bg="#f6f8fb")

        self._init_styles()

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
        self.current_article_link: Optional[str] = None
        self.current_categories: List[str] = []

        self._build_layout()
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)
        self.load_feed()

    def _init_styles(self) -> None:
        """Configure ttk styles for a modern, readable appearance."""
        style = ttk.Style()
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass

        base_bg = "#f6f8fb"
        accent = "#1a73e8"
        style.configure("TFrame", background=base_bg)
        style.configure("TLabel", background=base_bg, font=("Arial", 10))
        style.configure("Heading.TLabel", background=base_bg, font=("Arial", 16, "bold"))
        style.configure("Subheading.TLabel", background=base_bg, font=("Arial", 11, "bold"))
        style.configure("Accent.TButton", font=("Arial", 10, "bold"), foreground="white", background=accent)
        style.map("Accent.TButton", background=[("active", "#125abc")])
        style.configure(
            "Sidebar.Treeview",
            font=("Arial", 11),
            rowheight=32,
            background="white",
            fieldbackground="white",
        )
        style.configure("Sidebar.Treeview.Heading", font=("Arial", 10, "bold"))

    def _build_layout(self) -> None:
        top_frame = ttk.Frame(self.root, padding=(16, 14))
        top_frame.pack(fill=tk.X)

        ttk.Label(top_frame, text="Thanh Niên RSS Reader", style="Heading.TLabel").pack(
            side=tk.LEFT, padx=(0, 20)
        )

        ttk.Label(top_frame, text="Chọn chuyên mục:", style="Subheading.TLabel").pack(
            side=tk.LEFT, padx=(0, 8)
        )
        self.feed_choice = tk.StringVar(value=list(self.default_feeds.keys())[0])
        feed_combo = ttk.Combobox(
            top_frame,
            textvariable=self.feed_choice,
            values=list(self.default_feeds.keys()),
            width=24,
            state="readonly",
        )
        feed_combo.pack(side=tk.LEFT, padx=(0, 12))
        feed_combo.bind("<<ComboboxSelected>>", self.on_feed_selected)

        self.load_button = ttk.Button(
            top_frame, text="Làm mới", style="Accent.TButton", command=self.load_feed
        )
        self.load_button.pack(side=tk.LEFT)

        main_frame = ttk.Frame(self.root, padding=14)
        main_frame.pack(fill=tk.BOTH, expand=True)

        # Left list of article titles
        left_frame = ttk.Frame(main_frame)
        left_frame.pack(side=tk.LEFT, fill=tk.Y)
        ttk.Label(left_frame, text="Danh sách bài viết", style="Subheading.TLabel").pack(
            anchor=tk.W
        )
        tree_container = ttk.Frame(left_frame)
        tree_container.pack(fill=tk.BOTH, expand=True, pady=(6, 0))
        columns = ("title", "category")
        self.article_tree = ttk.Treeview(
            tree_container,
            columns=columns,
            show="headings",
            selectmode="browse",
            style="Sidebar.Treeview",
            height=28,
        )
        self.article_tree.heading("title", text="Tiêu đề")
        self.article_tree.heading("category", text="Danh mục")
        self.article_tree.column("title", width=420, anchor=tk.W)
        self.article_tree.column("category", width=160, anchor=tk.CENTER)
        self.article_tree.bind("<<TreeviewSelect>>", self.on_article_selected)
        self.article_tree.tag_configure("oddrow", background="#f2f4f7")
        tree_scroll = ttk.Scrollbar(tree_container, orient=tk.VERTICAL, command=self.article_tree.yview)
        self.article_tree.configure(yscrollcommand=tree_scroll.set)
        self.article_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        tree_scroll.pack(side=tk.RIGHT, fill=tk.Y)

        # Right content view
        right_frame = ttk.Frame(main_frame)
        right_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(15, 0))
        ttk.Label(right_frame, text="Nội dung bài viết", style="Subheading.TLabel").pack(
            anchor=tk.W
        )

        meta_frame = ttk.Frame(right_frame)
        meta_frame.pack(fill=tk.X, pady=(6, 0))
        self.category_var = tk.StringVar(value="Danh mục: -")
        ttk.Label(meta_frame, textvariable=self.category_var, style="TLabel").pack(side=tk.LEFT)
        self.link_button = ttk.Button(meta_frame, text="Mở bài gốc", command=self.open_current_article, state=tk.DISABLED)
        self.link_button.pack(side=tk.RIGHT)

        content_container = ttk.Frame(right_frame)
        content_container.pack(fill=tk.BOTH, expand=True, pady=(5, 0))
        self.content_text = tk.Text(
            content_container,
            wrap=tk.WORD,
            font=("Arial", 12),
            spacing3=8,
            padx=10,
            pady=10,
            relief=tk.FLAT,
            bg="white",
        )
        self.content_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        content_scroll = ttk.Scrollbar(content_container, orient=tk.VERTICAL, command=self.content_text.yview)
        content_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self.content_text.config(yscrollcommand=content_scroll.set)

    def on_feed_selected(self, event: tk.Event) -> None:
        self.load_feed()

    def load_feed(self) -> None:
        url = self.default_feeds.get(self.feed_choice.get())
        if not url:
            messagebox.showwarning("Thiếu RSS", "Vui lòng chọn chuyên mục hợp lệ")
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
            title = html.unescape(item_el.findtext("title", default="(Không tiêu đề)"))
            link = item_el.findtext("link", default="")
            categories = [html.unescape(cat.text.strip()) for cat in item_el.findall("category") if cat.text]
            if link:
                items.append(Article(title=title, link=link, categories=categories))
        return items

    def populate_list(self, articles: List[Article]) -> None:
        self.articles = articles
        for item in self.article_tree.get_children():
            self.article_tree.delete(item)
        for idx, art in enumerate(articles):
            category_label = ", ".join(art.categories) if art.categories else "-"
            tags = ("oddrow",) if idx % 2 else ()
            self.article_tree.insert(
                "", tk.END, iid=str(idx), values=(art.title, category_label), tags=tags
            )
        self.content_text.delete("1.0", tk.END)
        self.image_refs.clear()
        self.category_var.set("Danh mục: -")
        self.current_article_link = None
        self.current_categories = []
        self.link_button.config(state=tk.DISABLED)
        if not articles:
            self.content_text.insert(tk.END, "Không tìm thấy bài viết nào.")

    def on_article_selected(self, event: tk.Event) -> None:
        selection = self.article_tree.selection()
        if not selection:
            return
        index = int(selection[0])
        article = self.articles[index]
        self.current_article_link = article.link
        self.current_categories = article.categories
        self.category_var.set(
            f"Danh mục: {', '.join(article.categories) if article.categories else 'Không rõ danh mục'}"
        )
        self.link_button.config(state=tk.NORMAL if article.link else tk.DISABLED)
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
                page_html = await resp.text()

            soup = BeautifulSoup(page_html, "html.parser")
            paragraphs = [
                html.unescape(p.get_text(strip=True)) for p in soup.find_all("p") if p.get_text(strip=True)
            ]

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
        self.content_text.tag_config("title", font=("Arial", 15, "bold"))

        category_label = ", ".join(self.current_categories) if self.current_categories else "Không rõ danh mục"
        self.content_text.insert(tk.END, f"Danh mục: {category_label}\n", ("meta",))
        self.content_text.insert(tk.END, f"Liên kết gốc: {self.current_article_link}\n\n", ("link",))
        self.content_text.tag_config("meta", font=("Arial", 10, "italic"))
        self.content_text.tag_config("link", foreground="#1a73e8", underline=1)
        self.content_text.tag_bind("link", "<Button-1>", lambda _event: self.open_current_article())

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

    def open_current_article(self) -> None:
        if self.current_article_link:
            webbrowser.open(self.current_article_link)

    def on_close(self) -> None:
        self.async_thread.shutdown()
        self.root.destroy()


def main() -> None:
    root = tk.Tk()
    app = NewsReaderApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
