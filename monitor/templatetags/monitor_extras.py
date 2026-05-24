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


def _platform_key(value):
    return (value or "").strip().lower()


@register.filter
def platform_icon_class(platform_label):
    value = _platform_key(platform_label)
    mapping = [
        ("ubuntu", "bi bi-circle-fill"),
        ("debian", "bi bi-square-fill"),
        ("fedora", "bi bi-hexagon-fill"),
        ("arch", "bi bi-triangle-fill"),
        ("manjaro", "bi bi-triangle-fill"),
        ("linux mint", "bi bi-circle-fill"),
        ("pop!_os", "bi bi-stars"),
        ("centos", "bi bi-octagon-fill"),
        ("red hat", "bi bi-octagon-fill"),
        ("rocky", "bi bi-pentagon-fill"),
        ("alma", "bi bi-pentagon-fill"),
        ("opensuse", "bi bi-diamond-fill"),
        ("suse", "bi bi-diamond-fill"),
        ("raspbian", "bi bi-flower1"),
        ("mac", "bi bi-apple"),
        ("darwin", "bi bi-apple"),
        ("windows", "bi bi-windows"),
        ("linux", "bi bi-pc-display-horizontal"),
    ]
    for needle, icon_name in mapping:
        if needle in value:
            return icon_name
    return "bi bi-cpu"


@register.filter
def platform_tone_class(platform_label):
    value = _platform_key(platform_label)
    mapping = [
        ("ubuntu", "os-tone-ubuntu"),
        ("debian", "os-tone-debian"),
        ("fedora", "os-tone-fedora"),
        ("arch", "os-tone-arch"),
        ("manjaro", "os-tone-manjaro"),
        ("linux mint", "os-tone-mint"),
        ("pop!_os", "os-tone-pop"),
        ("centos", "os-tone-centos"),
        ("red hat", "os-tone-redhat"),
        ("rocky", "os-tone-rocky"),
        ("alma", "os-tone-alma"),
        ("opensuse", "os-tone-suse"),
        ("suse", "os-tone-suse"),
        ("raspbian", "os-tone-raspberry"),
        ("mac", "os-tone-macos"),
        ("darwin", "os-tone-macos"),
        ("windows", "os-tone-windows"),
        ("linux", "os-tone-linux"),
    ]
    for needle, tone_name in mapping:
        if needle in value:
            return tone_name
    return "os-tone-generic"


@register.filter
def human_uptime(total_seconds):
    try:
        seconds = max(int(total_seconds or 0), 0)
    except (TypeError, ValueError):
        return "-"
    days, remainder = divmod(seconds, 86400)
    hours, remainder = divmod(remainder, 3600)
    minutes, secs = divmod(remainder, 60)
    parts = []
    if days:
        parts.append(f"{days}d")
    if hours:
        parts.append(f"{hours}h")
    if minutes:
        parts.append(f"{minutes}m")
    if secs and not parts:
        parts.append(f"{secs}s")
    if not parts:
        parts.append("0s")
    return " ".join(parts)
