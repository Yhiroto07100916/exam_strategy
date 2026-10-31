from __future__ import annotations

import math

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field, ConfigDict, field_validator, model_validator

from .target_allocator import allocate_subject_targets
from .main_models import SUBJECTS


router = APIRouter(prefix="/api/targets", tags=["targets"])


class AllocationSubject(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    subject: str
    current_score: float = Field(ge=0, allow_inf_nan=False)
    max_score: float = Field(gt=0, allow_inf_nan=False)
    weight: float = Field(default=1, gt=0, le=10, allow_inf_nan=False)

    @field_validator("subject")
    @classmethod
    def validate_subject(cls, value: str) -> str:
        if value not in SUBJECTS:
            raise ValueError("科目は国語・数学・英語・理科・社会から選択してください")
        return value

    @model_validator(mode="after")
    def validate_score(self):
        if self.current_score > self.max_score:
            raise ValueError("現在点は満点以下にしてください")
        return self


class TargetAllocationRequest(BaseModel):
    subjects: list[AllocationSubject] = Field(min_length=2, max_length=5)
    target_total: float = Field(ge=0, allow_inf_nan=False)

    @model_validator(mode="after")
    def validate_subjects(self):
        names = [item.subject for item in self.subjects]
        if len(names) != len(set(names)):
            raise ValueError("科目を重複して指定できません")
        if self.target_total > sum(item.max_score for item in self.subjects):
            raise ValueError("総合目標点は全科目の満点合計以下にしてください")
        return self


@router.post("/allocate")
def allocate_targets(request: TargetAllocationRequest):
    try:
        return allocate_subject_targets(
            [item.model_dump() for item in request.subjects],
            request.target_total,
        )
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error))
