from django.db import connection

def search_mysql_fulltext(qn: str, limit: int = 8, kinds=None):
    kinds = kinds or []
    kind_sql = ""
    params = [qn, qn]

    if kinds:
        kind_sql = " AND kind IN (" + ",".join(["%s"] * len(kinds)) + ") "
        params.extend(kinds)

    sql = f"""
    SELECT kind, object_id, title, url, search_text, boost, extra,
           (MATCH(search_text) AGAINST (%s IN NATURAL LANGUAGE MODE)) AS score
    FROM assistant_searchindex
    WHERE MATCH(search_text) AGAINST (%s IN NATURAL LANGUAGE MODE)
    {kind_sql}
    ORDER BY (score * boost) DESC
    LIMIT %s;
    """
    params.append(int(limit))

    rows = []
    with connection.cursor() as cur:
        cur.execute(sql, params)
        for kind, obj_id, title, url, text, boost, extra, score in cur.fetchall():
            rows.append({
                "id": f"{kind}:{obj_id}",
                "kind": kind,
                "object_id": obj_id,
                "title": title,
                "url": url,
                "search_text": text or "",
                "meta": extra or {},
                "score": float(score or 0.0) * float(boost or 1.0),
            })
    return rows
