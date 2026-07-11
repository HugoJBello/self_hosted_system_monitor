def _round_mb(value):
    return round(max(float(value or 0), 0), 2)


def build_memory_breakdown(*, used_mb=0, available_mb=0, cached_mb=0, buffers_mb=0, slab_mb=0):
    used_mb = _round_mb(used_mb)
    available_mb = _round_mb(available_mb)
    cached_mb = _round_mb(cached_mb)
    buffers_mb = _round_mb(buffers_mb)
    slab_mb = _round_mb(slab_mb)
    return {
        "used_mb": used_mb,
        "available_mb": available_mb,
        "cached_mb": cached_mb,
        "buffers_mb": buffers_mb,
        "slab_mb": slab_mb,
        "reclaimable_mb": _round_mb(cached_mb + buffers_mb),
    }


def build_snapshot_memory_breakdown(snapshot):
    if not snapshot:
        return build_memory_breakdown()
    return build_memory_breakdown(
        used_mb=getattr(snapshot, "memory_used_mb", 0),
        available_mb=getattr(snapshot, "memory_available_mb", 0),
        cached_mb=getattr(snapshot, "memory_cached_mb", 0),
        buffers_mb=getattr(snapshot, "memory_buffers_mb", 0),
        slab_mb=getattr(snapshot, "memory_slab_mb", 0),
    )
