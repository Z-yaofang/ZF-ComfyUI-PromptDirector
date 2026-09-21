"""Local, tensor-free plan preview for the Animate segment desk."""

from aiohttp import web

from ..media_evidence.contract import ProjectError
from ..media_evidence.runtime import get_store
from .plan import AnimatePlanError, build_plan


def prepare_plan(media_project, settings, fps=None):
    return build_plan(get_store().canonical(media_project), settings, fps=fps)


def register_animate_routes(routes):
    @routes.post("/zf-prompt-director/animate-video/plan")
    async def plan(request):
        try:
            value = await request.json()
            return web.json_response({"plan": prepare_plan(value["media_project"], value["settings"], fps=value.get("fps"))})
        except (AnimatePlanError, ProjectError) as error:
            return web.json_response({"errors": error.errors if isinstance(error, ProjectError) else error.issues}, status=400)
        except (KeyError, TypeError, ValueError) as error:
            return web.json_response({"error": str(error)}, status=400)
