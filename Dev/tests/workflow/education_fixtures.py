"""Protocol fixtures only; these sentences do not establish model or clinical quality."""

TEXT = {
    "tests": "Discuss whether further evaluation is needed for this simulated case.",
    "treatment": "Review the treatment plan and relevant precautions with the patient.",
    "disposition": "Explain the appropriate next clinical contact for this simulated case.",
    "follow_up": "Discuss follow-up and symptoms that require reassessment.",
    "education": "Explain the selected diagnosis and the management plan to the patient.",
}
KOREAN = {
    "tests": "추가 검사 계획을 안내드릴게요.",
    "treatment": "치료 계획을 함께 확인해요.",
    "disposition": "진료 후 계획을 안내드릴게요.",
    "follow_up": "다시 진료받을 때를 안내드릴게요.",
    "education": "주의할 점을 함께 확인해요.",
}


def education_response(payload):
    task = payload.get("task")
    if task == "education":
        phase = payload.get("repair_phase", payload.get("phase"))
        if phase in {"read", "combine"}:
            return {"notes": []}
        return {"P": {field: [{"text": text, "basis": "model_knowledge", "references": [],
                               "priority": "safety" if field in {"follow_up", "disposition"} else "routine"}]
                      for field, text in TEXT.items()}}
    if task == "education_doctor":
        return {"items": [{"id": row["id"], "utterances": [KOREAN[row["id"].split(":")[1]]]}
                          for row in payload["sentences"]]}
    return None
