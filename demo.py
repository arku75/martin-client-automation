"""Create a self-contained HTML article from synthetic examples, entirely offline."""
from pathlib import Path
import argparse
from examples.generate_demo import generate
import core
import app


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', default='demo-output/demo-article.html')
    args = parser.parse_args()
    docx, png = generate()
    article = core.heuristic_metadata(core.parse_docx(docx))
    article = core.match_pairs([article], [png])[0]
    article = core.heuristic_metadata(article)
    article.author = 'Synthetic demo'
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(app.article_html(article), encoding='utf-8')
    print(f'Offline example saved to {output.resolve()}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
