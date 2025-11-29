# Bao RSS Reader

Ứng dụng đọc tin tức RSS sử dụng Tkinter cho giao diện và asyncio + aiohttp cho các tác vụ mạng bất đồng bộ. Hỗ trợ nhập URL RSS tùy ý hoặc chọn nhanh các danh mục của báo Thanh Niên, hiển thị danh sách bài viết và nội dung chi tiết với văn bản, hình ảnh được tải về.

## Yêu cầu
- Python 3.10+ kèm Tkinter (thường đi kèm trong bản cài đặt Python, với Linux có thể cần cài `python3-tk`).
- Thư viện pip:
  - `aiohttp`
  - `beautifulsoup4`
  - `pillow`

Cài đặt nhanh thông qua tệp `requirements.txt`:

```bash
pip install -r requirements.txt
```

## Cách chạy
1. Đảm bảo đã cài đặt các yêu cầu ở trên và có kết nối Internet.
2. Chạy ứng dụng:

   ```bash
   python news_reader.py
   ```

3. Nhập URL RSS hoặc chọn danh mục báo Thanh Niên, nhấn **Tải dữ liệu** để lấy danh sách bài viết. Nhấp vào từng bài để tải nội dung chi tiết (thao tác mạng diễn ra bất đồng bộ, không làm treo giao diện).
