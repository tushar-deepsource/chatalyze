import json
from time import sleep

from celery.states import FAILURE, REVOKED, RETRY
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.http import HttpResponse, HttpResponseBadRequest, JsonResponse, HttpResponseForbidden
from django.shortcuts import redirect, get_object_or_404
from django.template import loader
from django.urls import reverse
from django_celery_results.models import TaskResult

from . import models, tasks
from .analysis_utils import get_chat_name_wa
from .const import TELEGRAM, WHATSAPP


def index(request):
    """Displays main page"""
    html_template = loader.get_template("home/index.html")
    return HttpResponse(html_template.render({}, request))


@login_required(login_url="/login/")
def analyze(request):
    """Stores received file and starts its analysis"""
    file = request.FILES["chatfile"]
    lang = request.POST.get("lang")
    if file and file.name.endswith((".txt", ".json")):
        if file.size > 1e8:
            return HttpResponseBadRequest("File is too big")
        if lang not in models.ChatAnalysis.AnalysisLanguage.values:
            return HttpResponseBadRequest("Choose chat language")
        chat_name = get_chat_name_wa(file.name) or "noname"
        analysis = models.ChatAnalysis.objects.create(
            author=request.user,
            chat_name=chat_name,
            chat_file=file,
            language=lang,
        )
        task = tasks.analyze_chat_file.delay(analysis_id=analysis.id)
        analysis.task_id = task.id
        analysis.save()
        sleep(1)
    else:
        return HttpResponseBadRequest("You've uploaded a wrong file")

    return redirect("dashboard:results")


@login_required(login_url="/login/")
def analysis_update(request, pk):
    """Stores the file and starts its analysis if it is compatible with specified chat_platform"""
    file = request.FILES.get("chatfile")
    if not file or not file.name.endswith((".txt", ".json")):
        return HttpResponseBadRequest("You've uploaded a wrong file")
    if file.size > 1e8:
        return HttpResponseBadRequest("File is too big")

    analysis = get_object_or_404(models.ChatAnalysis, pk=pk)
    if analysis.author != request.user:
        raise PermissionDenied()

    if not (analysis.chat_platform == TELEGRAM and file.name.endswith(".json")) and not (
        analysis.chat_platform == WHATSAPP and file.name.endswith(".txt")
    ):
        return HttpResponseBadRequest("The uploaded file doesn't match this chat's messenger")

    analysis.chat_file = file
    analysis.save()

    task = tasks.update_chat_analysis.delay(analysis_id=analysis.id)
    analysis.task_id = task.id
    analysis.status = analysis.AnalysisStatus.PROCESSING
    analysis.save()

    sleep(1)
    return redirect("dashboard:result", pk=pk)


@login_required(login_url="/login/")
def results(request):
    """Displays a list of analysis"""
    analysis = models.ChatAnalysis.objects.filter(author=request.user)
    context = {"results": analysis, "segment": "results"}
    html_template = loader.get_template("home/results.html")
    return HttpResponse(html_template.render(context, request))


@login_required(login_url="/login/")
def analysis_result(request, pk):
    """Displays chat analysis result"""
    analysis = get_object_or_404(models.ChatAnalysis, pk=pk)

    if analysis.author != request.user:
        raise PermissionDenied()

    chat_statistics = None
    if analysis.results:
        chat_statistics = get_chat_statistics(analysis.results)  # noqa

    context = {"result": analysis, "stats": chat_statistics}
    html_template = loader.get_template("home/result.html")

    return HttpResponse(html_template.render(context, request))


def is_task_failure(task_id):
    """Checks if analysis failed to finish"""
    task = TaskResult.objects.get_task(task_id)
    if task.status in (FAILURE, RETRY, REVOKED):
        return True
    return False


@login_required(login_url="/login/")
def discard_error(request, pk):
    """Removes the analysis' error status and text."""
    if request.method.lower() != "get":
        return HttpResponse("ok")

    analysis = get_object_or_404(models.ChatAnalysis, pk=pk)

    if analysis.author != request.user:
        raise PermissionDenied()

    if analysis.word_cloud_pic:
        if analysis.status != analysis.AnalysisStatus.READY or analysis.error_text:
            analysis.error_text = ""
            analysis.status = analysis.AnalysisStatus.READY
            analysis.save()
        return HttpResponse("ok")
    else:
        return HttpResponseBadRequest()


@login_required(login_url="/login/")
def check_status(request, pk):
    """Returns a JSON response containing updated analysis info"""
    if request.method.lower() != "get":
        return HttpResponse("ok")

    analysis = get_object_or_404(models.ChatAnalysis, pk=pk)

    if analysis.author != request.user:
        raise PermissionDenied()

    if is_task_failure(analysis.task_id):
        status_error = models.ChatAnalysis.AnalysisStatus.ERROR
        if analysis.status != status_error:
            error_text = "Server error. Try again later."
            models.ChatAnalysis.objects.filter(pk=analysis.pk).update(
                status=status_error,
                error_text=error_text,
            )
        analysis.refresh_from_db()

    data = {
        "chat_name": analysis.chat_name,
        "chat_platform": analysis.chat_platform,
        "messages_count": analysis.messages_count,
        "status": analysis.status,
        "updated": analysis.updated.strftime("%d.%m.%Y"),
    }

    return JsonResponse(data)


@login_required(login_url="/login/")
def delete_analysis(request, pk):
    """Deletes the analysis and redirects to the results list"""
    analysis = get_object_or_404(models.ChatAnalysis, pk=pk)
    if analysis.author == request.user:
        analysis.delete()
        return redirect("dashboard:results")
    else:
        return HttpResponseForbidden()


@login_required(login_url="/login/")
def rename_analysis(request, pk):
    """Changes the analysis chat name to the name received in request"""
    if request.method.lower() not in ("post", "get"):
        return HttpResponse("ok")
    analysis = get_object_or_404(models.ChatAnalysis, pk=pk)
    if not analysis.author == request.user:
        return HttpResponseForbidden()

    if request.method.lower() == "get":
        name = request.GET.get("name")
    else:
        name = json.loads(request.body).get("name")
    if name and 0 < len(name) < 50:
        analysis.chat_name = name
        analysis.save()
        data = {"success": True, "new_name": analysis.chat_name}
        return JsonResponse(data)
    else:
        return HttpResponseBadRequest()


def shared_result(request, pk):
    """Displays an analysis result by a shared link"""
    link = get_object_or_404(models.ShareLink, id=pk)
    analysis = link.analysis

    chat_statistics = None
    if analysis.results:
        chat_statistics = get_chat_statistics(analysis.results)  # noqa

    context = {"result": analysis, "stats": chat_statistics}
    html_template = loader.get_template("home/share.html")

    return HttpResponse(html_template.render(context, request))


@login_required(login_url="/login/")
def share_analysis(request, pk):
    """Creates a shared link for the analysis and returns it"""
    if request.method.lower() not in ("post", "get"):
        return HttpResponse("ok")

    analysis = get_object_or_404(models.ChatAnalysis, pk=pk)

    if not analysis.author == request.user:
        return HttpResponseForbidden()

    if request.method.lower() == "get":
        new_link = request.GET.get("new_link")
    else:
        new_link = json.loads(request.body).get("new_link")

    try:
        share_link = analysis.sharelink
    except models.ShareLink.DoesNotExist:
        models.ShareLink.objects.create(analysis=analysis)
        share_link = analysis.sharelink
    else:
        if new_link:
            share_link.delete()
            models.ShareLink.objects.create(analysis=analysis)
            share_link = analysis.sharelink

    link = reverse("dashboard:shared_result", args=[share_link.pk])

    return JsonResponse({"link": link})
