def tx(el, path, default=""):
    n = el.find(path)
    return (n.text or "").strip() if n is not None and n.text is not None else default

def attr(el, name, default=""):
    v = el.get(name)
    return (v or "").strip() if v is not None else default
