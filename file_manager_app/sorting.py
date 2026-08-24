SORT_FIELDS = {
    "name": "Name",
    "kind": "Type",
    "size": "Size",
    "modified": "Modified",
    "owner": "Owner",
    "permissions": "Permissions",
}
SORT_DIRECTIONS = {
    "asc": "Ascending",
    "desc": "Descending",
}


def normalize_sort(field, direction):
    normalized_field = field if field in SORT_FIELDS else "name"
    normalized_direction = direction if direction in SORT_DIRECTIONS else "asc"
    return normalized_field, normalized_direction


def _sort_value(entry, field):
    if field == "size":
        return entry.get("size_bytes") if entry.get("size_bytes") is not None else -1
    if field == "modified":
        return entry.get("modified_at") or ""
    if field == "kind":
        return entry.get("kind") or ("folder" if entry.get("is_dir") else "file")
    return str(entry.get({"name": "name", "owner": "owner", "permissions": "permissions"}[field]) or "").lower()


def sort_entries(entries, field="name", direction="asc"):
    field, direction = normalize_sort(field, direction)
    sorted_entries = sorted(entries, key=lambda entry: _sort_value(entry, field), reverse=direction == "desc")
    # Keep folders grouped before files, matching the file manager's default browsing model.
    return sorted(sorted_entries, key=lambda entry: 1 if not entry.get("is_dir") else 0)
