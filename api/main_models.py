from .exam_mode import subjects_for_mode

SUBJECTS = ["国語", "数学", "英語", "理科", "社会"]

def is_valid_subject(subject: str) -> bool:
    return subject in subjects_for_mode()
