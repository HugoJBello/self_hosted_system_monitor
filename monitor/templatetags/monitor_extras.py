from django import template


register = template.Library()


@register.filter
def get_item(mapping, key):
    if isinstance(mapping, dict):
        return mapping.get(key)
    return None


@register.filter
def get_attr(obj, attr_name):
    return getattr(obj, attr_name, None)
