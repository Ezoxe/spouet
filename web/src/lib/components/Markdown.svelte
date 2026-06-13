<script lang="ts">
    /**
     * Rendu Markdown leger et sur pour les reponses de l'assistant.
     *
     * - Echappe systematiquement le HTML entrant AVANT toute transformation
     *   (anti-XSS : le contenu vient du LLM).
     * - Gere : blocs de code (avec langage, copie, coloration), code inline,
     *   titres, gras/italique/barre, liens (schemas filtres), listes imbriquees,
     *   citations, tableaux, separateurs, sauts de ligne.
     * - Aucune dependance externe.
     */
    interface Props {
        content: string;
        class?: string;
        /** Pendant le streaming, le {@html} est re-rendu à chaque token : on coupe
         *  les animations d'apparition des blocs (code/tableaux) pour éviter le
         *  scintillement. Elles ne jouent qu'une fois, sur un message figé. */
        streaming?: boolean;
    }
    let { content, class: klass = '', streaming = false }: Props = $props();

    const html = $derived(parse(content ?? ''));

    function esc(s: string): string {
        return s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
    }

    // Langages ou « # » introduit un commentaire.
    const HASH_LANGS = new Set([
        'py', 'python', 'sh', 'bash', 'shell', 'zsh', 'yaml', 'yml', 'ruby', 'rb', 'r',
        'toml', 'ini', 'conf', 'dockerfile', 'docker', 'makefile', 'make', 'perl', 'pl',
        'elixir', 'ex', 'nim', 'julia', 'jl', 'php', 'powershell', 'ps1'
    ]);

    const KEYWORDS = [
        'const', 'let', 'var', 'function', 'func', 'fn', 'def', 'lambda', 'return', 'if',
        'elif', 'else', 'for', 'while', 'do', 'switch', 'case', 'match', 'break', 'continue',
        'class', 'struct', 'enum', 'trait', 'impl', 'interface', 'extends', 'implements',
        'new', 'delete', 'this', 'self', 'super', 'import', 'export', 'from', 'as', 'use',
        'mod', 'package', 'namespace', 'using', 'include', 'require', 'async', 'await',
        'yield', 'try', 'catch', 'except', 'finally', 'throw', 'raise', 'typeof',
        'instanceof', 'void', 'public', 'private', 'protected', 'static', 'final',
        'abstract', 'pub', 'mut', 'where', 'type', 'typename', 'template', 'auto', 'go',
        'defer', 'chan', 'range', 'select', 'with', 'pass', 'global', 'nonlocal', 'then',
        'begin', 'module', 'echo', 'print'
    ];

    function highlight(code: string, lang: string): string {
        let commentSrc = '\\/\\*[\\s\\S]*?\\*\\/|\\/\\/[^\\n]*';
        if (HASH_LANGS.has(lang)) commentSrc += '|#[^\\n]*';
        const re = new RegExp(
            '(' + commentSrc + ')' +
                '|("(?:\\\\.|[^"\\\\])*"|\'(?:\\\\.|[^\'\\\\])*\'|`(?:\\\\.|[^`\\\\])*`)' +
                '|(\\b0x[0-9a-fA-F]+\\b|\\b\\d+(?:\\.\\d+)?(?:e[+-]?\\d+)?\\b)' +
                '|(\\b(?:' + KEYWORDS.join('|') + ')\\b)' +
                '|(\\b(?:true|false|null|nil|undefined|None|True|False|NaN)\\b)' +
                '|([A-Za-z_$][\\w$]*(?=\\s*\\())',
            'g'
        );
        let out = '';
        let last = 0;
        let m: RegExpExecArray | null;
        while ((m = re.exec(code)) !== null) {
            if (m.index > last) out += esc(code.slice(last, m.index));
            let cls = '';
            if (m[1] !== undefined) cls = 'tok-comment';
            else if (m[2] !== undefined) cls = 'tok-string';
            else if (m[3] !== undefined) cls = 'tok-number';
            else if (m[4] !== undefined) cls = 'tok-keyword';
            else if (m[5] !== undefined) cls = 'tok-boolean';
            else if (m[6] !== undefined) cls = 'tok-function';
            out += cls ? '<span class="' + cls + '">' + esc(m[0]) + '</span>' : esc(m[0]);
            last = m.index + m[0].length;
            if (m[0].length === 0) re.lastIndex++;
        }
        out += esc(code.slice(last));
        return out;
    }

    const COPY_ICON =
        '<svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="9" y="9" width="13" height="13" rx="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/></svg>';
    const CHECK_ICON =
        '<svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.6" stroke-linecap="round" stroke-linejoin="round"><path d="M20 6 9 17l-5-5"/></svg>';

    function codeBlock(code: string, lang: string): string {
        const body = code.replace(/\n$/, '');
        const label = (lang || 'code').toLowerCase();
        const lines = body ? body.split('\n').length : 0;
        const count = lines > 1 ? '<span class="md-code-lines">' + lines + ' lignes</span>' : '';
        return (
            '<div class="md-code" data-lang="' + esc(label) + '">' +
            '<div class="md-code-head"><span class="md-code-id">' +
            '<span class="md-code-dot"></span>' +
            '<span class="md-code-lang">' + esc(label) + '</span>' + count +
            '</span><button class="md-code-copy" type="button" aria-label="Copier le code">' +
            '<span class="md-ico md-ico-copy">' + COPY_ICON + '</span>' +
            '<span class="md-ico md-ico-check">' + CHECK_ICON + '</span>' +
            '<span class="md-copy-label">Copier</span></button></div><pre><code>' +
            highlight(body, label) +
            '</code></pre></div>'
        );
    }

    function linkHtml(url: string, txt: string): string {
        const safe = /^(https?:|mailto:|\/|#|\.\/|\.\.\/)/i.test(url.trim());
        if (!safe) return txt; // txt deja echappe
        return '<a href="' + url + '" target="_blank" rel="noopener noreferrer">' + txt + '</a>';
    }

    // Sentinelles en zone a usage prive Unicode : n'apparaissent jamais dans du
    // texte normal -> pas de collision avec un nombre entoure d'espaces.
    const PH_OPEN = String.fromCharCode(0xe000);
    const PH_CLOSE = String.fromCharCode(0xe001);

    function renderInline(text: string): string {
        let s = esc(text);
        // Protege le code inline des autres transformations
        const codes: string[] = [];
        s = s.replace(/`([^`]+)`/g, (_m, c) => {
            codes.push('<code>' + c + '</code>');
            return PH_OPEN + (codes.length - 1) + PH_CLOSE;
        });
        // Images -> lien (les visuels passent par un autre canal)
        s = s.replace(/!\[([^\]]*)\]\(([^)]+)\)/g, (_m, alt, url) => linkHtml(url, alt || url));
        // Liens
        s = s.replace(/\[([^\]]+)\]\(([^)]+)\)/g, (_m, t, url) => linkHtml(url, t));
        // Gras
        s = s.replace(/\*\*([^*]+?)\*\*/g, '<strong>$1</strong>');
        s = s.replace(/__([^_]+?)__/g, '<strong>$1</strong>');
        // Italique
        s = s.replace(/(^|[^*])\*([^*\s][^*]*?)\*(?!\*)/g, '$1<em>$2</em>');
        s = s.replace(/(^|[^_\w])_([^_]+?)_(?!\w)/g, '$1<em>$2</em>');
        // Barre
        s = s.replace(/~~([^~]+?)~~/g, '<del>$1</del>');
        // Sauts de ligne intra-paragraphe
        s = s.replace(/\n/g, '<br>');
        // Restaure le code inline
        s = s.replace(new RegExp(PH_OPEN + '(\\d+)' + PH_CLOSE, 'g'), (_m, i) => codes[+i]);
        return s;
    }

    function splitRow(line: string): string[] {
        return line
            .trim()
            .replace(/^\|/, '')
            .replace(/\|$/, '')
            .split('|')
            .map((c) => c.trim());
    }

    function tableHtml(header: string[], rows: string[][]): string {
        const th = header.map((c) => '<th>' + renderInline(c) + '</th>').join('');
        const body = rows
            .map((r) => '<tr>' + r.map((c) => '<td>' + renderInline(c) + '</td>').join('') + '</tr>')
            .join('');
        return (
            '<div class="md-table-wrap"><table><thead><tr>' +
            th +
            '</tr></thead><tbody>' +
            body +
            '</tbody></table></div>'
        );
    }

    function listHtml(items: { depth: number; ordered: boolean; text: string }[]): string {
        let out = '';
        const open: string[] = [];
        let curDepth = -1;
        for (const it of items) {
            const d = Math.min(it.depth, curDepth + 1);
            while (open.length - 1 > d) out += '</li></' + open.pop() + '>';
            if (open.length - 1 === d) {
                out += '</li>';
            } else {
                const tag = it.ordered ? 'ol' : 'ul';
                out += '<' + tag + '>';
                open.push(tag);
            }
            out += '<li>' + renderInline(it.text);
            curDepth = d;
        }
        while (open.length) out += '</li></' + open.pop() + '>';
        return out;
    }

    function parse(src: string): string {
        if (!src) return '';
        const lines = src.replace(/\r\n?/g, '\n').split('\n');
        const out: string[] = [];
        let para: string[] = [];
        const flushPara = () => {
            if (para.length) {
                out.push('<p>' + renderInline(para.join('\n')) + '</p>');
                para = [];
            }
        };
        let i = 0;
        while (i < lines.length) {
            const line = lines[i];
            // Bloc de code
            const fence = line.match(/^\s*(```+|~~~+)\s*([\w+#-]*)\s*$/);
            if (fence) {
                flushPara();
                const lang = fence[2] || '';
                i++;
                const buf: string[] = [];
                while (i < lines.length && !/^\s*(```+|~~~+)\s*$/.test(lines[i])) {
                    buf.push(lines[i]);
                    i++;
                }
                i++; // saute la cloture eventuelle
                out.push(codeBlock(buf.join('\n'), lang));
                continue;
            }
            // Ligne vide
            if (/^\s*$/.test(line)) {
                flushPara();
                i++;
                continue;
            }
            // Titre
            const h = line.match(/^(#{1,6})\s+(.*)$/);
            if (h) {
                flushPara();
                const lvl = h[1].length;
                out.push('<h' + lvl + '>' + renderInline(h[2].trim()) + '</h' + lvl + '>');
                i++;
                continue;
            }
            // Separateur
            if (/^\s*([-*_])(\s*\1){2,}\s*$/.test(line)) {
                flushPara();
                out.push('<hr>');
                i++;
                continue;
            }
            // Citation
            if (/^\s*>/.test(line)) {
                flushPara();
                const buf: string[] = [];
                while (i < lines.length && /^\s*>/.test(lines[i])) {
                    buf.push(lines[i].replace(/^\s*>\s?/, ''));
                    i++;
                }
                out.push('<blockquote>' + renderInline(buf.join('\n')) + '</blockquote>');
                continue;
            }
            // Tableau
            if (
                line.includes('|') &&
                i + 1 < lines.length &&
                lines[i + 1].includes('-') &&
                /^\s*\|?[\s:|-]*-[\s:|-]*\|?\s*$/.test(lines[i + 1])
            ) {
                flushPara();
                const header = splitRow(line);
                i += 2;
                const rows: string[][] = [];
                while (i < lines.length && lines[i].includes('|') && !/^\s*$/.test(lines[i])) {
                    rows.push(splitRow(lines[i]));
                    i++;
                }
                out.push(tableHtml(header, rows));
                continue;
            }
            // Liste
            if (/^(\s*)([-*+]|\d+\.)\s+/.test(line)) {
                flushPara();
                const items: { depth: number; ordered: boolean; text: string }[] = [];
                while (i < lines.length && /^(\s*)([-*+]|\d+\.)\s+/.test(lines[i])) {
                    const m = lines[i].match(/^(\s*)([-*+]|\d+\.)\s+(.*)$/)!;
                    items.push({
                        depth: Math.floor(m[1].replace(/\t/g, '  ').length / 2),
                        ordered: /\d/.test(m[2]),
                        text: m[3]
                    });
                    i++;
                }
                out.push(listHtml(items));
                continue;
            }
            // Paragraphe
            para.push(line);
            i++;
        }
        flushPara();
        return out.join('\n');
    }

    function onClick(e: MouseEvent) {
        const target = e.target as HTMLElement;
        const btn = target.closest('.md-code-copy');
        if (!btn) return;
        const code = btn.closest('.md-code')?.querySelector('pre code');
        if (!code) return;
        navigator.clipboard
            .writeText(code.textContent ?? '')
            .then(() => {
                btn.classList.add('copied');
                const label = btn.querySelector('.md-copy-label');
                const prev = label?.textContent ?? 'Copier';
                if (label) label.textContent = 'Copié';
                setTimeout(() => {
                    btn.classList.remove('copied');
                    if (label) label.textContent = prev;
                }, 1500);
            })
            .catch(() => {});
    }
</script>

<!-- svelte-ignore a11y_click_events_have_key_events, a11y_no_static_element_interactions -->
<div class="md {klass}" class:md-streaming={streaming} onclick={onClick}>
    {@html html}
</div>
