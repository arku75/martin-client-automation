"""Generate synthetic, deterministic DOCX and PNG fixtures using only stdlib."""
from pathlib import Path
from xml.sax.saxutils import escape
import struct
import zlib
import zipfile


def generate(destination=None):
    destination = Path(destination or Path(__file__).resolve().parent)
    destination.mkdir(parents=True, exist_ok=True)
    paragraphs = [
        ("", "Meta title: Lake Example: a fictional weekend guide"),
        ("", "Meta description: Explore a fictional lake itinerary in this synthetic demonstration of document parsing, photo pairing and local article preparation."),
        ("", "URL slug: demo-lake-trip"),
        ("", "Focus keyword: lake example"),
        ("Heading1", "Lake Example: a fictional weekend guide"),
        ("", "This document is invented for software demonstration. Lake Example is not a real destination, and the accompanying image is generated test data. It contains no client article, photograph or personal information."),
        ("Heading2", "A relaxed two-day itinerary"),
        ("", "Begin the first morning with a gentle walk around the imaginary shore. Stop at the fictional viewpoint to compare the sample photograph with its document name. This paragraph exists to exercise the article parser and should not be treated as travel advice. After lunch, review the heading structure, inspect the automatically prepared slug and confirm that the written meta description remains unchanged."),
        ("", "Use the second morning to explore the editor. Change a sentence, check the preview and export a standalone page. The example intentionally works without a publishing account, image hosting or a language model. Review every field before connecting your own compatible backend. The original program's travel taxonomy remains available, but a real editorial workflow requires human review of places, facts, rights and publication status."),
        ("Heading2", "Quick facts"),
        ("", "- Synthetic content created only for this public demonstration."),
        ("", "- Local preparation requires no website account or API key."),
        ("Heading2", "FAQ"),
        ("", "Is Lake Example a real destination?"),
        ("", "No. The destination, document and test image are fictional fixtures."),
        ("", "Does the offline demo publish an article?"),
        ("", "No. It creates a local HTML file and does not contact a backend."),
    ]
    body = []
    for style, text in paragraphs:
        props = f'<w:pPr><w:pStyle w:val="{style}"/></w:pPr>' if style else ""
        body.append(f'<w:p>{props}<w:r><w:t xml:space="preserve">{escape(text)}</w:t></w:r></w:p>')
    document = ('<?xml version="1.0" encoding="UTF-8"?>'
                '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
                '<w:body>' + ''.join(body) + '<w:sectPr/></w:body></w:document>')
    entries = {
        '[Content_Types].xml': '<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/></Types>',
        '_rels/.rels': '<?xml version="1.0"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/></Relationships>',
        'word/document.xml': document,
    }
    docx = destination / 'demo-lake-trip.docx'
    with zipfile.ZipFile(docx, 'w', zipfile.ZIP_DEFLATED) as archive:
        for name, value in entries.items():
            info = zipfile.ZipInfo(name, date_time=(2026, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, value.encode('utf-8'))
    def chunk(kind, data):
        return struct.pack('>I', len(data)) + kind + data + struct.pack('>I', zlib.crc32(kind + data))
    width, height = 320, 200
    rows = bytearray()
    for y in range(height):
        rows.append(0)
        for x in range(width):
            color = (172, 208, 219) if y < height // 2 else (41, 109, 114)
            if 60 < x < 260 and 70 < y < 140 and abs(x - 160) < (140 - y) * 2:
                color = (62, 102, 80)
            rows.extend(color)
    png = destination / 'demo-lake-trip.png'
    png.write_bytes(b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', width, height, 8, 2, 0, 0, 0)) + chunk(b'IDAT', zlib.compress(bytes(rows), 9)) + chunk(b'IEND', b''))
    return docx, png


if __name__ == '__main__':
    for path in generate():
        print(path)
