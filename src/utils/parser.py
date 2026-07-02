"""
parser.py - Tầng Bóc tách Tài liệu Học thuật (Document Parsing Layer)
======================================================================
Hỗ trợ:
  - PDFParser  : Sử dụng PyMuPDF (fitz) bóc văn bản -> Markdown theo cấp đoạn văn.
  - PPTXParser : Trích xuất text từ shapes, sau đó gửi lên Gemini Flash để làm sạch
                 và cấu trúc hóa nội dung học thuật. Gài time.sleep(4) giữa mỗi slide
                 để chống Rate Limit Google (15 req/phút).
  - chunk_by_paragraph() : Chiến lược cắt chunk theo ranh giới ngữ nghĩa của đoạn văn.

Thiết kế:
  - Mỗi parser trả về list[dict] chuẩn, sẵn sàng đẩy vào QdrantManager.upsert_chunks().
  - Chunk size và overlap có thể điều chỉnh qua hằng số cấu hình.
  - Xử lý lỗi chi tiết: ghi log cảnh báo và bỏ qua slide lỗi thay vì crash.

Ghi chú PPTXParser:
  Hiện tại sử dụng chế độ Text+Gemini (trích xuất text từ shapes -> đẩy lên Gemini
  để làm sạch và tóm tắt học thuật). Chế độ Vision Image thật sự (render slide
  thành PNG bằng win32com) là nâng cấp tương lai — cần Microsoft Office cài sẵn.
"""

import os
import time
import logging
import re
from pathlib import Path
from typing import List, Dict, Any, Optional

import fitz  # PyMuPDF
import google.genai as genai
from google.genai import types as genai_types
from dotenv import load_dotenv

# python-pptx chỉ dùng để xuất slide thành ảnh
try:
    from pptx import Presentation
    from pptx.util import Inches
    import io
    from PIL import Image
    PPTX_AVAILABLE = True
except ImportError:
    PPTX_AVAILABLE = False

# ─── Cấu hình Logging ──────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] [%(levelname)s] [%(name)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("Parser")

# ─── Tải biến môi trường ───────────────────────────────────────────────────────
load_dotenv()
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")

# ─── Hằng số cấu hình Chunking ────────────────────────────────────────────────
MIN_CHUNK_CHARS = 150     # Bỏ qua đoạn văn quá ngắn (tiêu đề, số trang...)
MAX_CHUNK_CHARS = 2000    # Giới hạn kích thước tối đa một chunk
PPTX_SLEEP_SECONDS = 4   # Ngủ giữa mỗi slide để tránh Rate Limit Google (15 req/phút)


# ══════════════════════════════════════════════════════════════════════════════
#  HELPER: Chunking theo ranh giới đoạn văn
# ══════════════════════════════════════════════════════════════════════════════
def chunk_by_paragraph(
    text: str,
    source: str,
    page: int = 0,
    metadata: Optional[Dict] = None,
) -> List[Dict[str, Any]]:
    """
    Cắt văn bản dài thành các chunk nhỏ theo ranh giới đoạn văn (paragraph level).
    Chiến lược này bảo toàn ngữ nghĩa của câu tốt hơn so với cắt theo số ký tự cố định.

    Args:
        text    : Văn bản đầu vào (Markdown hoặc plain text).
        source  : Tên file nguồn (để lưu vào metadata Qdrant).
        page    : Số trang (cho PDF).
        metadata: Thông tin bổ sung tuỳ chỉnh.

    Returns:
        Danh sách dict chunk chuẩn để đưa vào Qdrant.
    """
    # Tách theo dòng trống (paragraph break) hoặc heading Markdown
    paragraphs = re.split(r"\n{2,}|(?=^#+\s)", text, flags=re.MULTILINE)
    chunks = []
    buffer = ""

    for para in paragraphs:
        para = para.strip()
        if not para:
            continue

        # Nếu buffer + đoạn hiện tại vẫn nằm trong giới hạn, tiếp tục ghép
        if len(buffer) + len(para) < MAX_CHUNK_CHARS:
            buffer = (buffer + "\n\n" + para).strip() if buffer else para
        else:
            # Đẩy buffer hiện tại vào kết quả nếu đủ dài
            if len(buffer) >= MIN_CHUNK_CHARS:
                chunks.append({
                    "text": buffer,
                    "source": source,
                    "page": page,
                    "metadata": metadata or {},
                })
            buffer = para

    # Đẩy phần còn lại của buffer
    if buffer and len(buffer) >= MIN_CHUNK_CHARS:
        chunks.append({
            "text": buffer,
            "source": source,
            "page": page,
            "metadata": metadata or {},
        })

    logger.info(f"[Parser] Chunking '{source}' trang {page}: {len(chunks)} chunks")
    return chunks


# ══════════════════════════════════════════════════════════════════════════════
#  PDFParser - Bóc tách PDF bằng PyMuPDF
# ══════════════════════════════════════════════════════════════════════════════
class PDFParser:
    """
    Bóc tách tài liệu PDF thành các chunk văn bản chuẩn.
    - Sử dụng PyMuPDF (fitz) đọc từng trang.
    - Lọc các dòng rác (số trang, tiêu đề lặp, dòng quá ngắn).
    - Kết xuất Markdown đơn giản (heading, paragraph) trước khi chunk.
    """

    def parse(self, pdf_path: str) -> List[Dict[str, Any]]:
        """
        Bóc tách toàn bộ file PDF.

        Args:
            pdf_path: Đường dẫn tuyệt đối đến file PDF.

        Returns:
            Danh sách chunk chuẩn, sẵn sàng đưa vào Qdrant.
        """
        file_name = Path(pdf_path).name
        logger.info(f"[PDFParser] Bắt đầu bóc tách: {file_name}")

        all_chunks = []
        try:
            doc = fitz.open(pdf_path)
            for page_num, page in enumerate(doc, start=1):
                # Lấy toàn bộ text của trang, giữ nguyên layout dọc
                raw_text = page.get_text("text")
                if not raw_text or len(raw_text.strip()) < 50:
                    continue

                # Làm sạch: loại bỏ dòng quá ngắn (< 20 ký tự) như số trang, header lặp
                cleaned_lines = [
                    line for line in raw_text.split("\n")
                    if len(line.strip()) > 20
                ]
                cleaned_text = "\n".join(cleaned_lines)

                # Chunk theo đoạn văn
                page_chunks = chunk_by_paragraph(
                    text=cleaned_text,
                    source=file_name,
                    page=page_num,
                    metadata={"file_type": "pdf", "total_pages": len(doc)},
                )
                all_chunks.extend(page_chunks)

            doc.close()

        except Exception as e:
            logger.error(f"[PDFParser] Lỗi khi bóc tách '{file_name}': {e}")

        logger.info(f"[PDFParser] Hoàn thành: {file_name} -> {len(all_chunks)} chunks.")
        return all_chunks

    def save_markdown(self, pdf_path: str, output_dir: str) -> str:
        """
        Bóc tách PDF và lưu kết quả ra file Markdown trong thư mục 02_Knowledge/.

        Args:
            pdf_path  : Đường dẫn file PDF nguồn.
            output_dir: Thư mục đích (Obsidian_Vault/02_Knowledge/).

        Returns:
            Đường dẫn file Markdown đã lưu.
        """
        file_stem = Path(pdf_path).stem
        os.makedirs(output_dir, exist_ok=True)
        output_path = os.path.join(output_dir, f"{file_stem}.md")

        chunks = self.parse(pdf_path)
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(f"# {file_stem}\n\n")
            for chunk in chunks:
                f.write(f"<!-- Page {chunk['page']} -->\n")
                f.write(chunk["text"] + "\n\n---\n\n")

        logger.info(f"[PDFParser] Đã lưu Markdown: {output_path}")
        return output_path


# ══════════════════════════════════════════════════════════════════════════════
#  PPTXParser - Bóc tách Slide PPTX bằng Gemini Vision API
# ══════════════════════════════════════════════════════════════════════════════
class PPTXParser:
    """
    Bóc tách file Slide PowerPoint theo 2 chế độ:

    Chế độ hiện tại - Text+Gemini (mặc định):
      1. Trích xuất text thô từ từng shape trong slide bằng python-pptx.
      2. Gửi text lên Gemini Flash để làm sạch cấu trúc, nhận diện thuật ngữ học thuật.
      3. Gài time.sleep(4) giữa mỗi slide để chống Rate Limit (15 req/phút Google Free).

    Chế độ tương lai - Vision Image (nâng cấp sau):
      Render slide thành PNG qua win32com (yêu cầu Microsoft Office cài sẵn).
      Gửi ảnh thật lên Gemini Vision API để đọc biểu đồ, hình minh họa.
      Sử dụng USE_VISION_MODE = True khi có Microsoft Office.

    Yêu cầu: GEMINI_API_KEY trong file .env.
    """

    # Cờ cho phép chuyển sang chế độ Vision thật sự (nâng cấp tương lai)
    USE_VISION_MODE = False

    GEMINI_PROMPT_TEXT = """Bạn là trợ lý học thuật. Dưới đây là nội dung text thô trích xuất từ một slide thuyết trình.
Nhiệm vụ: Làm sạch, cấu trúc hóa và giữ lại toàn bộ nội dung học thuật quan trọng.
Trả về văn bản thuần túy (plain text), không dùng JSON, không thêm bình luận."""

    def __init__(self):
        self._client = None
        if not GEMINI_API_KEY or "điền" in GEMINI_API_KEY.lower():
            logger.warning(
                "[PPTXParser] Thiếu GEMINI_API_KEY. Sẽ chỉ dùng text thô từ shapes."
            )
        else:
            self._client = genai.Client(api_key=GEMINI_API_KEY)

    # ── Hook cho chế độ Vision Image tương lai ─────────────────────────────────
    # Để bật chế độ Vision:
    #   1. Đặt USE_VISION_MODE = True
    #   2. Thêm method _render_slide_to_png(slide) dùng win32com.client
    #   3. Gửi kết quả PNG dạng bytes lên Gemini với mime_type="image/png"

    def parse(self, pptx_path: str) -> List[Dict[str, Any]]:
        """
        Bóc tách toàn bộ file PPTX.

        Args:
            pptx_path: Đường dẫn tuyệt đối đến file PPTX.

        Returns:
            Danh sách chunk chuẩn, sẵn sàng đưa vào Qdrant.
        """
        if not PPTX_AVAILABLE:
            logger.error("[PPTXParser] Thiếu thư viện python-pptx hoặc Pillow.")
            return []

        file_name = Path(pptx_path).name
        logger.info(f"[PPTXParser] Bắt đầu bóc tách: {file_name}")

        prs = Presentation(pptx_path)
        all_chunks = []
        total_slides = len(prs.slides)

        for slide_idx, slide in enumerate(prs.slides, start=1):
            logger.info(f"[PPTXParser] Đang xử lý slide {slide_idx}/{total_slides}...")

            # Bước 1: Luôn trích xuất text thô từ shapes (nhanh, không cần API)
            raw_texts = [
                shape.text.strip()
                for shape in slide.shapes
                if hasattr(shape, "text") and shape.text.strip()
            ]
            raw_slide_text = "\n".join(raw_texts)

            if not raw_slide_text.strip():
                logger.info(f"[PPTXParser] Slide {slide_idx} rỗng, bỏ qua.")
                # Vẫn ngủ để giữ kịoảng cách giữa các API call
                if self._client and slide_idx < total_slides:
                    time.sleep(PPTX_SLEEP_SECONDS)
                continue

            slide_text = raw_slide_text

            # Bước 2: Nếu có Gemini client, gửi text lên để làm sạch cấu trúc học thuật
            # (Thực sự gọi API - không bỏ qua)
            if self._client:
                try:
                    prompt = (
                        self.GEMINI_PROMPT_TEXT +
                        f"\n\nNỘI DUNG SLIDE {slide_idx}:\n{raw_slide_text}"
                    )
                    response = self._client.models.generate_content(
                        model="gemini-1.5-flash",
                        contents=prompt,
                        config=genai_types.GenerateContentConfig(
                            temperature=0.1,
                            max_output_tokens=1024,
                        ),
                    )
                    slide_text = response.text.strip()
                    logger.info(
                        f"[PPTXParser] Gemini đã làm sạch slide {slide_idx}: "
                        f"{len(raw_slide_text)} -> {len(slide_text)} ky tu"
                    )
                except Exception as e:
                    logger.warning(
                        f"[PPTXParser] Gemini lỗi slide {slide_idx}: {e}. "
                        f"Giữ lại text thô."
                    )
                    slide_text = raw_slide_text  # Fallback về text thô nếu Gemini lỗi

            # Chunk nội dung slide vừa trích xuất
            if slide_text and len(slide_text.strip()) >= 30:
                slide_chunks = chunk_by_paragraph(
                    text=slide_text,
                    source=file_name,
                    page=slide_idx,
                    metadata={"file_type": "pptx", "total_slides": total_slides},
                )
                all_chunks.extend(slide_chunks)

            # *** CHỐT CHẶN AN TOÀN: Ngủ 4 giây giữa mỗi slide ***
            # Tránh vượt quá giới hạn 15 requests/phút của Google AI Free Tier
            if self._model and slide_idx < total_slides:
                logger.info(f"[PPTXParser] Đang chờ {PPTX_SLEEP_SECONDS}s (chống Rate Limit)...")
                time.sleep(PPTX_SLEEP_SECONDS)

        logger.info(f"[PPTXParser] Hoàn thành: {file_name} -> {len(all_chunks)} chunks.")
        return all_chunks

    def save_markdown(self, pptx_path: str, output_dir: str) -> str:
        """
        Bóc tách PPTX và lưu kết quả ra file Markdown trong thư mục 02_Knowledge/.
        """
        file_stem = Path(pptx_path).stem
        os.makedirs(output_dir, exist_ok=True)
        output_path = os.path.join(output_dir, f"{file_stem}.md")

        chunks = self.parse(pptx_path)
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(f"# {file_stem}\n\n")
            for chunk in chunks:
                f.write(f"<!-- Slide {chunk['page']} -->\n")
                f.write(chunk["text"] + "\n\n---\n\n")

        logger.info(f"[PPTXParser] Đã lưu Markdown: {output_path}")
        return output_path


# ─── Factory function tiện lợi ────────────────────────────────────────────────
def parse_document(file_path: str) -> List[Dict[str, Any]]:
    """
    Auto-detect loại tài liệu và gọi parser tương ứng.
    Trả về danh sách chunk chuẩn.

    Args:
        file_path: Đường dẫn đến file PDF hoặc PPTX.

    Returns:
        Danh sách chunk hoặc list rỗng nếu định dạng không hỗ trợ.
    """
    ext = Path(file_path).suffix.lower()
    if ext == ".pdf":
        return PDFParser().parse(file_path)
    elif ext in (".pptx", ".ppt"):
        return PPTXParser().parse(file_path)
    else:
        logger.warning(f"[Parser] Định dạng không hỗ trợ: '{ext}'. Bỏ qua file.")
        return []


# ─── Test nhanh khi chạy trực tiếp ───────────────────────────────────────────
if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("Cách dùng: python parser.py <đường_dẫn_file.pdf|.pptx>")
        sys.exit(1)

    test_path = sys.argv[1]
    print(f"\n--- Test Parser: {test_path} ---")
    chunks = parse_document(test_path)
    print(f"\nKết quả: {len(chunks)} chunks")
    for i, c in enumerate(chunks[:3]):
        print(f"\n[Chunk {i+1}] Source: {c['source']} | Page: {c['page']}")
        print(f"  Text: {c['text'][:150]}...")
