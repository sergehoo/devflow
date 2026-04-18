from project import models as dm


def log_activity(
    *,
    workspace,
    activity_type,
    title,
    actor=None,
    project=None,
    task=None,
    sprint=None,
    description="",
    metadata=None,
):
    return dm.ActivityLog.objects.create(
        workspace=workspace,
        actor=actor,
        project=project,
        task=task,
        sprint=sprint,
        activity_type=activity_type,
        title=title,
        description=description or "",
        metadata=metadata or {},
    )