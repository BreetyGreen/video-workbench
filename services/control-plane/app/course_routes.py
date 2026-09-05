from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from sqlmodel import Session, select

from app.models import Course, CourseAsset, CourseSchedule, CourseScheduleRun, DeliveryDevice, EditingRecipe
from app.schemas.course_schedules import CourseScheduleCreate, CourseScheduleToggle


def course_router(service, session_dependency, templates, *, worker_enabled: bool):
    router = APIRouter()

    @router.get("/courses", response_class=HTMLResponse)
    def page(request: Request):
        return templates.TemplateResponse(request=request, name="courses.html", context={})

    @router.get("/api/course-schedules/catalog")
    def catalog(session: Session = Depends(session_dependency)):
        courses = []
        for course in session.exec(select(Course).order_by(Course.created_at.desc()).limit(100)).all():
            assets = session.exec(select(CourseAsset).where(CourseAsset.course_id == course.id)).all()
            recipe = session.exec(select(EditingRecipe).where(EditingRecipe.course_id == course.id)
                                  .order_by(EditingRecipe.version.desc())).first()
            courses.append({"id": course.id, "title": course.title, "status": course.status,
                            "recipe_id": recipe.id if recipe else None,
                            "assets": [{"id": a.id, "name": a.original_name, "role": a.role,
                                        "rights_status": a.rights_status, "mime_type": a.mime_type} for a in assets]})
        return {"courses": courses, "devices": [{"id": d.id, "name": d.name, "last_seen_at": d.last_seen_at}
                for d in session.exec(select(DeliveryDevice).where(DeliveryDevice.active == True)).all()],
                "worker_enabled": worker_enabled}

    @router.get("/api/course-schedules")
    def plans(session: Session = Depends(session_dependency)):
        return [service.plan_read(p) for p in session.exec(select(CourseSchedule)
                .order_by(CourseSchedule.created_at.desc()).limit(200)).all()]

    @router.post("/api/course-schedules", status_code=201)
    def create(body: CourseScheduleCreate, session: Session = Depends(session_dependency)):
        try:
            return service.plan_read(service.create(session, body))
        except ValueError as error:
            raise HTTPException(400, str(error)) from error

    @router.patch("/api/course-schedules/{plan_id}")
    def toggle(plan_id: str, body: CourseScheduleToggle, session: Session = Depends(session_dependency)):
        plan = session.get(CourseSchedule, plan_id)
        if plan is None:
            raise HTTPException(404, "course_schedule_not_found")
        plan.enabled = body.enabled
        session.add(plan)
        session.commit()
        return service.plan_read(plan)

    @router.post("/api/course-schedules/{plan_id}/run", status_code=202)
    def run_now(plan_id: str, session: Session = Depends(session_dependency)):
        plan = session.get(CourseSchedule, plan_id)
        if plan is None:
            raise HTTPException(404, "course_schedule_not_found")
        run, _ = service.enqueue(session, plan)
        return service.run_read(session, run)

    @router.get("/api/course-schedules/{plan_id}/runs")
    def runs(plan_id: str, session: Session = Depends(session_dependency)):
        return [service.run_read(session, r) for r in session.exec(select(CourseScheduleRun)
                .where(CourseScheduleRun.schedule_id == plan_id)
                .order_by(CourseScheduleRun.created_at.desc()).limit(30)).all()]

    return router
