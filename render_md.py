#!/usr/bin/env python3
"""Minimal stdlib Markdown -> styled HTML -> PDF (via headless Chrome).
Usage: python3 render_md.py INPUT.md OUTPUT.pdf ["Doc Title"]
Handles the subset used by the LIVE playbook: #/##/### headings, **bold**,
*italic*, `code`, pipe tables, - bullet lists, 1. ordered lists, --- rules,
and paragraphs. No external deps."""
import html as _html
import os
import re
import subprocess
import sys
import tempfile

CSS = """
@page{size:letter;margin:0.6in}
*{box-sizing:border-box}
body{font-family:-apple-system,'Helvetica Neue',Arial,sans-serif;color:#15202b;
line-height:1.5;margin:0 auto;max-width:820px;padding:18px;font-size:14.5px}
h1{font-size:25px;margin:0 0 6px}
h2{font-size:18px;margin:24px 0 6px;color:#0a7c3c;border-bottom:2px solid #e6e6e6;padding-bottom:4px}
h3{font-size:14.5px;margin:15px 0 4px}
p{margin:7px 0}ul,ol{margin:7px 0;padding-left:22px}li{margin:4px 0}
b,strong{color:#000}em{font-style:italic}
code{background:#f0f0f0;padding:1px 5px;border-radius:3px;font-size:12.5px;
font-family:ui-monospace,Menlo,monospace}
table{width:100%;border-collapse:collapse;margin:9px 0;font-size:12.5px}
th,td{border:1px solid #ccc;padding:6px 8px;text-align:left;vertical-align:top}
th{background:#f4f4f4;font-size:11px;text-transform:uppercase;letter-spacing:.02em}
hr{border:none;border-top:1px solid #ddd;margin:16px 0}
"""


def inline(t):
    t = _html.escape(t)
    t = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", t)
    t = re.sub(r"(?<!\w)\*(?!\s)(.+?)(?<!\s)\*(?!\w)", r"<em>\1</em>", t)
    t = re.sub(r"`(.+?)`", r"<code>\1</code>", t)
    return t


def render(md):
    lines = md.split("\n")
    out, i = [], 0
    while i < len(lines):
        ln = lines[i]
        s = ln.strip()
        if not s:
            i += 1
            continue
        if re.fullmatch(r"-{3,}", s):
            out.append("<hr>")
            i += 1
            continue
        m = re.match(r"(#{1,6})\s+(.*)", s)
        if m:
            lvl = len(m.group(1))
            out.append(f"<h{lvl}>{inline(m.group(2))}</h{lvl}>")
            i += 1
            continue
        # table: a line with | and the next line is the |---| separator
        if s.startswith("|") and i + 1 < len(lines) and \
                re.match(r"\s*\|?[\s:|-]+\|", lines[i + 1]) and "-" in lines[i + 1]:
            head = [c.strip() for c in s.strip("|").split("|")]
            out.append("<table><tr>" +
                       "".join(f"<th>{inline(c)}</th>" for c in head) + "</tr>")
            i += 2
            while i < len(lines) and lines[i].strip().startswith("|"):
                cells = [c.strip() for c in lines[i].strip().strip("|").split("|")]
                out.append("<tr>" +
                           "".join(f"<td>{inline(c)}</td>" for c in cells) + "</tr>")
                i += 1
            out.append("</table>")
            continue
        if re.match(r"[-*]\s+", s):
            out.append("<ul>")
            while i < len(lines) and re.match(r"\s*[-*]\s+", lines[i]):
                out.append("<li>" +
                           inline(re.sub(r"^\s*[-*]\s+", "", lines[i])) + "</li>")
                i += 1
            out.append("</ul>")
            continue
        if re.match(r"\d+\.\s+", s):
            out.append("<ol>")
            while i < len(lines) and re.match(r"\s*\d+\.\s+", lines[i]):
                out.append("<li>" +
                           inline(re.sub(r"^\s*\d+\.\s+", "", lines[i])) + "</li>")
                i += 1
            out.append("</ol>")
            continue
        out.append("<p>" + inline(s) + "</p>")
        i += 1
    return "\n".join(out)


def main():
    if len(sys.argv) < 3:
        sys.exit("usage: render_md.py INPUT.md OUTPUT.pdf [title]")
    src, pdf = sys.argv[1], sys.argv[2]
    title = sys.argv[3] if len(sys.argv) > 3 else os.path.basename(src)
    body = render(open(src).read())
    doc = (f"<!DOCTYPE html><html><head><meta charset='utf-8'>"
           f"<title>{_html.escape(title)}</title><style>{CSS}</style></head>"
           f"<body>{body}</body></html>")
    with tempfile.NamedTemporaryFile("w", suffix=".html", delete=False) as f:
        f.write(doc)
        htmlp = f.name
    chrome = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
    subprocess.run([chrome, "--headless=new", "--disable-gpu",
                    "--no-pdf-header-footer", f"--print-to-pdf={pdf}",
                    "file://" + htmlp], check=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    os.unlink(htmlp)
    print(f"wrote {pdf} ({os.path.getsize(pdf)} bytes)")


if __name__ == "__main__":
    main()
