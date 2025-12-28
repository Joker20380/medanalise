import json
from django.http import JsonResponse
from django.views.decorators.http import require_POST

from .retrieval import search_mysql_fulltext
from .orchestrator import normalize, build_answer
from .models import AssistantEvent

@require_POST
def ask(request):
    payload = json.loads(request.body.decode("utf-8"))
    query = (payload.get("q") or "")[:512]
    limit = int(payload.get("limit", 8))

    if not request.session.session_key:
        request.session.save()

    qn = normalize(query)
    rows = search_mysql_fulltext(qn, limit=limit)

    data = build_answer(query, rows)

    AssistantEvent.objects.create(
        session_key=request.session.session_key,
        user=request.user if request.user.is_authenticated else None,
        query=query,
        normalized=qn,
        intents=data["intents"],
        results=[r["id"] for r in data["results"]],
    )

    return JsonResponse(data)
