import html
import re
from urllib.parse import urlsplit

from django import template
from django.utils.safestring import mark_safe

register = template.Library()


@register.filter
def announcement_markdown(value):
    """Render a tiny safe Markdown subset used by announcement messages."""
    source = str(value or '')
    rendered_lines = []
    list_items = []

    def inline(text):
        safe_text = html.escape(text, quote=True)

        def link(match):
            label, url = match.group(1), match.group(2)
            scheme = urlsplit(url).scheme.lower()
            if scheme not in {'http', 'https'}:
                return match.group(0)
            return '<a href="{}" target="_blank" rel="noopener noreferrer">{}</a>'.format(
                html.escape(url, quote=True), label,
            )

        safe_text = re.sub(r'\[([^\]]+)\]\((https?://[^\s)]+)\)', link, safe_text)
        return re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', safe_text)

    def flush_list():
        if list_items:
            rendered_lines.append('<ul class="mb-2">' + ''.join(f'<li>{item}</li>' for item in list_items) + '</ul>')
            list_items.clear()

    for line in source.splitlines():
        stripped = line.strip()
        if stripped.startswith('• ') or stripped.startswith('- '):
            list_items.append(inline(stripped[2:]))
            continue
        flush_list()
        rendered_lines.append(inline(line))
    flush_list()
    return mark_safe('<br>'.join(rendered_lines))
