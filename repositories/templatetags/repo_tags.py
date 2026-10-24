from django import template

register = template.Library()


@register.filter
def get_item(value, key):
    if isinstance(value, dict):
        return value.get(key, '')
    return ''


@register.filter
def split(value, separator=','):
    """Split a string into a list, e.g. {{ 'a,b,c'|split:',' }}."""
    if isinstance(value, (list, tuple)):
        return list(value)
    if not isinstance(value, str):
        return []
    return [part for part in value.split(separator)] if separator else list(value)
