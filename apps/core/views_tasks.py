from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import permissions, status
from celery.result import AsyncResult


class CeleryTaskStatusView(APIView):
    """
    Endpoint para consulta do status e resultado de tarefas assíncronas do Celery.
    GET /api/v1/core/tasks/{task_id}/
    """
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, task_id):
        res = AsyncResult(task_id)
        data = {
            "task_id": task_id,
            "status": res.state,
            "ready": res.ready(),
            "successful": res.successful() if res.ready() else None,
        }

        if res.ready():
            if res.successful():
                data["result"] = res.result
            else:
                data["error"] = str(res.result)
        else:
            if isinstance(res.info, dict):
                data["progress"] = res.info

        return Response(data, status=status.HTTP_200_OK)
