from pydantic import BaseModel


class QCIssueStatusUpdate(BaseModel):
    status: str  # resolved / ignored
