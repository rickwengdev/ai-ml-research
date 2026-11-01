#!/usr/bin/env node
/**
 * A research write-up in Markdown → a standalone HTML page next to it (same name, .html), the form papers and notes
 * are kept in. Rendered the way the research UI renders Markdown (apps/research-web/src/domain/research-markdown.js):
 * GitHub tables, headings with the same ids, raw HTML shown as text. Links to other write-ups that exist as .html
 * point there; figures keep their relative paths, so the page also reads on its own from a checkout.
 *
 *   node research/lib/md2html.mjs research/notes/math.md [...]
 */
import { existsSync, readFileSync, writeFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const REPO = path.resolve(HERE, '..', '..');
const require = createRequire(path.join(REPO, 'apps', 'research-web', 'package.json'));
const { Marked } = await import(pathToFileURL(require.resolve('marked')).href);

const ESCAPES = { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' };
const escape = (text) => String(text ?? '').replace(/[&<>"']/g, (char) => ESCAPES[char]);
const EXTERNAL = /^(https?:|mailto:)/i;

const STYLE = `
:root { color-scheme: light dark; --bg: #fbfaf8; --text: #1f1e1c; --text-2: #55524c; --text-3: #85817a; --border: #e4e0d8; --code: #f1eee8; --accent: #b4532a; }
@media (prefers-color-scheme: dark) { :root { --bg: #1b1a18; --text: #ece9e3; --text-2: #b9b4aa; --text-3: #8a857c; --border: #36332e; --code: #26241f; --accent: #e08a5f; } }
* { box-sizing: border-box; }
body { margin: 0; background: var(--bg); color: var(--text); font: 16px/1.75 -apple-system, BlinkMacSystemFont, "Segoe UI", "Noto Sans TC", "PingFang TC", "Microsoft JhengHei", sans-serif; }
article { max-width: 780px; margin: 0 auto; padding: 48px 16px 96px; }
h1, h2, h3, h4 { line-height: 1.35; font-weight: 650; }
h1 { font-size: 1.9rem; margin: 0 0 1.2rem; }
h2 { font-size: 1.4rem; margin: 2.6rem 0 0.9rem; padding-bottom: 0.3rem; border-bottom: 1px solid var(--border); }
h3 { font-size: 1.15rem; margin: 2rem 0 0.7rem; }
h4 { font-size: 1rem; margin: 1.6rem 0 0.5rem; }
p, ul, ol, table, pre, blockquote { margin: 0 0 1rem; }
a { color: var(--accent); }
code { font: 0.86em/1.5 ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; background: var(--code); padding: 0.1em 0.35em; border-radius: 4px; }
pre { background: var(--code); padding: 12px 14px; border-radius: 8px; overflow-x: auto; }
pre code { background: none; padding: 0; }
blockquote { margin-left: 0; padding: 0.2rem 0 0.2rem 1rem; border-left: 3px solid var(--border); color: var(--text-2); }
table { border-collapse: collapse; display: block; overflow-x: auto; font-size: 0.9rem; }
th, td { border: 1px solid var(--border); padding: 6px 10px; text-align: left; vertical-align: top; }
th { background: var(--code); font-weight: 600; }
img { max-width: 100%; height: auto; border-radius: 6px; }
hr { border: 0; border-top: 1px solid var(--border); margin: 2rem 0; }
`;

function convert(file) {
  const source = path.resolve(file);
  const dir = path.dirname(source);
  const text = readFileSync(source, 'utf8');
  const slugs = new Map();
  const slug = (title) => {
    const root = title.toLowerCase().replace(/<[^>]+>/g, '').replace(/[^\p{L}\p{N}]+/gu, '-').replace(/^-|-$/g, '') || 'section';
    const count = slugs.get(root) ?? 0;
    slugs.set(root, count + 1);
    return count ? `${root}-${count}` : root;
  };
  // A link to another write-up goes to its .html when that is the form it is in (or is being converted to).
  const target = (href) => {
    const [plain, hash = ''] = href.split('#');
    if (!plain.endsWith('.md')) return href;
    const html = plain.replace(/\.md$/, '.html');
    return existsSync(path.resolve(dir, html)) || CONVERTING.has(path.resolve(dir, plain)) ? html + (hash ? `#${hash}` : '') : href;
  };
  let title = path.basename(source, '.md');
  const markdown = new Marked({
    gfm: true,
    renderer: {
      html({ text: raw }) {
        return escape(raw);
      },
      heading({ tokens, depth }) {
        const inner = this.parser.parseInline(tokens);
        if (depth === 1 && title === path.basename(source, '.md')) title = inner.replace(/<[^>]+>/g, '');
        return `<h${depth} id="${slug(inner)}">${inner}</h${depth}>\n`;
      },
      link({ href, title: hint, tokens }) {
        const label = this.parser.parseInline(tokens);
        const extra = EXTERNAL.test(href ?? '') ? ' target="_blank" rel="noopener noreferrer"' : '';
        return `<a href="${escape(target(href ?? ''))}"${hint ? ` title="${escape(hint)}"` : ''}${extra}>${label}</a>`;
      },
    },
  });
  const body = markdown.parse(text);
  const page = `<!doctype html>
<html lang="zh-Hant">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>${escape(title.replace(/&amp;/g, '&').replace(/&#39;/g, "'").replace(/&quot;/g, '"'))}</title>
<style>${STYLE}</style>
</head>
<body>
<article>
${body}</article>
</body>
</html>
`;
  const out = source.replace(/\.md$/, '.html');
  writeFileSync(out, page);
  return out;
}

const files = process.argv.slice(2);
if (!files.length) {
  console.error('usage: node research/lib/md2html.mjs <write-up.md> [...]');
  process.exit(2);
}
const CONVERTING = new Set(files.map((file) => path.resolve(file)));
for (const file of files) console.log(path.relative(REPO, convert(file)));
