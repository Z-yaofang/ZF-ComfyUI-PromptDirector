"""Local, tensor-free previews for the segment desk and interview."""

from aiohttp import web

from ..h3_focus.interview import InterviewError
from ..media_evidence.contract import ProjectError
from ..media_evidence.runtime import get_store
from .interview import compile_segment_interview
from .plan import SegmentPlanError, build_segment_plan, canonical_task_project


def prepare_plan(value):
    store = get_store()
    project = canonical_task_project(value["media_project"], store)
    settings = dict(value["settings"])
    if settings.get("source_snapshot") is not None and settings.get("refresh_sources") is not True:
        settings["source_snapshot"] = canonical_task_project(settings["source_snapshot"], store)
    return build_segment_plan(project, settings)


def register_long_video_routes(routes):
    async def respond(request, interview=False):
        try:
            value = await request.json()
            plan = prepare_plan(value)
            result = compile_segment_interview(plan, value["state"], align=value.get("align") is True) if interview else {"plan": plan}
            return web.json_response(result)
        except (ProjectError, SegmentPlanError, InterviewError) as error:
            issues = error.errors if isinstance(error, ProjectError) else error.issues
            return web.json_response({"errors": issues}, status=400)
        except (KeyError, TypeError, ValueError) as error:
            return web.json_response({"error": str(error)}, status=400)

    @routes.post("/zf-prompt-director/long-video/plan")
    async def plan(request):
        return await respond(request)

    @routes.post("/zf-prompt-director/long-video/interview")
    async def interview(request):
        return await respond(request, interview=True)
