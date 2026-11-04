from __future__ import annotations

from contextvars import ContextVar

EXAM_MODES = {"high_school", "university"}
exam_mode_context: ContextVar[str] = ContextVar("exam_mode", default="high_school")

HIGH_SCHOOL_SUBJECTS = ["国語", "数学", "英語", "理科", "社会"]
UNIVERSITY_SUBJECTS = [
    "国語", "英語", "英語リーディング", "英語リスニング",
    "数学IA", "数学IIBC", "数学III",
    "物理", "化学", "生物", "地学",
    "地理総合・地理探究", "歴史総合・日本史探究",
    "歴史総合・世界史探究", "公共・政治経済", "情報I",
    "小論文", "面接",
]

def get_exam_mode() -> str:
    return exam_mode_context.get()

def subjects_for_mode(mode: str | None = None) -> list[str]:
    selected = mode or get_exam_mode()
    return UNIVERSITY_SUBJECTS if selected == "university" else HIGH_SCHOOL_SUBJECTS

def is_valid_subject(subject: str) -> bool:
    return subject in subjects_for_mode()