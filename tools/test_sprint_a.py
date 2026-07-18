from src.utils.parser import PDFParser
import os

pdf_path = r'Obsidian_Vault\02_Knowledge\2309.15217v2.pdf'
if not os.path.exists(pdf_path):
    print('[SKIP] File chua co trong 02_Knowledge, kiem tra lai duong dan')
else:
    parser = PDFParser()
    chunks = parser.parse(pdf_path)
    print(f'[OK] Tong so chunks: {len(chunks)}  (truoc Sprint A: 8 chunks)')
    for i, c in enumerate(chunks[:5]):
        section = c.get('metadata', {}).get('section_title', 'N/A')
        print(f'  Chunk {i+1}: page={c["page"]}, section="{section}", len={len(c["text"])} chars')
        print(f'    Preview: {c["text"][:100].strip()}')
        print()
