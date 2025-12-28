import re
import json

STOP = {"как","что","где","когда","почему","зачем","мне","нужно","подскажи","пожалуйста","это","в","на","и","или","а","ли","по","для"}

INTENTS = {
    "preparation": ["подготов", "натощ", "есть", "пить", "кофе"],
    "duration": ["срок", "сколько", "готов", "дней", "час"],
    "norms": ["норма", "референс", "значен", "повышен", "понижен"],
    "price": ["цена", "стоим", "руб", "сколько стоит"],
    "contacts": ["адрес", "телефон", "график", "работаете"],
    "document": ["документ", "приказ", "pdf"],
    "news": ["новост", "акци"],
}

TEST_KINDS = {"test", "tests", "lab_test", "analysis", "analyte"}


def normalize(q: str) -> str:
    q = (q or "").lower().replace("ё", "е")
    q = re.sub(r"[^\w\s\-]+", " ", q, flags=re.U)
    return " ".join(t for t in q.split() if t not in STOP)[:256]


def detect_intents(qn: str):
    found = []
    for k, words in INTENTS.items():
        if any(w in qn for w in words):
            found.append(k)
    return found or ["search"]


def cut(text: str, n: int) -> str:
    if not text:
        return ""
    text = str(text).strip()
    if len(text) <= n:
        return text
    return text[:n].rstrip() + "…"


def snippet(text: str, qn: str, max_len=220):
    """
    Делает сниппет вокруг первого найденного токена из запроса.
    Если токенов нет или text пустой — возвращает первые max_len символов.
    """
    if not text:
        return ""

    tokens = [t for t in qn.split() if len(t) > 2][:6]
    low = text.lower()

    positions = []
    for t in tokens:
        p = low.find(t)
        if p != -1:
            positions.append(p)

    pos = min(positions) if positions else 0

    start = max(0, pos - 70)
    end = min(len(text), pos + max_len)
    s = text[start:end].strip()

    prefix = "…" if start > 0 else ""
    suffix = "…" if end < len(text) else ""
    return prefix + s + suffix


def kind_norm(v) -> str:
    return (v or "").strip().lower()


def is_test_kind(kind: str) -> bool:
    k = kind_norm(kind)
    return k in TEST_KINDS or k.startswith("test")


def safe_meta(v):
    """
    meta может быть dict, JSON-строкой или None.
    """
    if not v:
        return {}
    if isinstance(v, dict):
        return v
    if isinstance(v, str):
        s = v.strip()
        if not s:
            return {}
        try:
            return json.loads(s)
        except Exception:
            return {}
    return {}


def extract_code_from_text(text: str) -> str:
    """
    Пытаемся выцепить код анализа из title/search_text.
    """
    if not text:
        return ""

    # "Код: FERR"
    m = re.search(r"\bкод[:\s]*([A-Za-z0-9][A-Za-z0-9\-\._]{1,20})\b", text, flags=re.I)
    if m:
        return m.group(1).upper()

    # "(FERR)"
    m = re.search(r"\(([A-Za-z0-9][A-Za-z0-9\-\._]{1,20})\)", text)
    if m:
        return m.group(1).upper()

    # короткий UPPER токен (например CRP, FERR, TSH, HbA1c, 25OHD)
    m = re.search(r"\b([A-Z][A-Z0-9]{1,9})\b", text)
    if m:
        return m.group(1).upper()

    return ""


def make_test_hint(r: dict, qn: str) -> str:
    """
    Короткий "смысл" для карточки (1 строка), без простыней.
    Приоритет:
      1) meta.hint
      2) кусок вокруг запроса из search_text
      3) первые 80 символов search_text
    """
    meta = safe_meta(r.get("meta"))
    if meta.get("hint"):
        return cut(str(meta["hint"]), 80)

    st = (r.get("search_text") or "").strip()
    if not st:
        return ""

    tokens = [t for t in qn.split() if len(t) > 2][:6]
    low = st.lower()
    pos = min([low.find(t) for t in tokens if low.find(t) != -1] or [0])

    start = max(0, pos - 30)
    end = min(len(st), start + 120)
    chunk = st[start:end].strip()
    chunk = re.sub(r"\s+", " ", chunk)

    return cut(chunk, 80)


def build_answer(query: str, rows: list):
    qn = normalize(query)
    intents = detect_intents(qn)

    chips = []
    if "preparation" in intents: chips.append("Подготовка")
    if "duration" in intents: chips.append("Срок выполнения")
    if "norms" in intents: chips.append("Нормы")
    if "price" in intents: chips.append("Стоимость")
    if "contacts" in intents: chips.append("Контакты")
    if not chips:
        chips = ["Панели", "Тесты", "Прайс", "Документы", "Новости"]

    results = []
    for r in rows:
        k = kind_norm(r.get("kind"))
        title = r.get("title") or ""
        st = r.get("search_text") or ""
        meta = safe_meta(r.get("meta"))

        # ✅ Анализы: отдаём структуру под красивую карточку
        if is_test_kind(k):
            code = meta.get("code") or extract_code_from_text(title) or extract_code_from_text(st)
            hint = make_test_hint(r, qn)

            results.append({
                "id": r["id"],
                "kind": "test",          # нормализуем для фронта
                "title": cut(title, 60), # красиво в заголовке карточки
                "url": r["url"],
                "snippet": "",           # ВАЖНО: никаких простыней
                "score": r["score"],
                "meta": {
                    "code": code,
                    "hint": hint,
                },
            })
            continue

        # Остальные: стандартно
        results.append({
            "id": r["id"],
            "kind": k,
            "title": title,
            "url": r["url"],
            "snippet": snippet(st, qn),
            "score": r["score"],
            "meta": meta,
        })

    return {
        "mode": "search_only",
        "query": query,
        "normalized": qn,
        "intents": intents,
        "answer": {
            "title": "Навигатор",
            "blocks": [
                {"type": "text", "text": "Я нашёл подходящие материалы на сайте:" if results else "Не нашёл точных совпадений."},
                {"type": "chips", "items": chips},
            ],
        },
        "results": results,
    }
