from pathlib import Path

from app.adapters.jianying import DraftPackage, EditPlan, build_draft


class DraftService:
    def __init__(self, artifact_root: Path, *, target: str = "6+"):
        self.artifact_root = artifact_root.resolve()
        self.target = target

    def generate(self, task_id: str, plan: EditPlan) -> DraftPackage:
        task_dir = (self.artifact_root / task_id / "drafts").resolve()
        if self.artifact_root not in task_dir.parents:
            raise ValueError("Draft output path escapes the configured artifact root")
        return build_draft(plan, task_dir, target=self.target)
