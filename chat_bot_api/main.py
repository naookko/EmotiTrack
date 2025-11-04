import math
import os
import random

from datetime import datetime
from fastapi import FastAPI, Body, Query, HTTPException
from pydantic import BaseModel, Field
from pymongo import MongoClient

#Database connection
client = MongoClient(os.getenv("MONGO_URI", "mongodb://localhost:27017/"))
db = client["chat_bot"]

students = db["students"]
responses = db["responses"]
scores = db["scores"]
analytics = db["analytics"]
logs = db["system_logs"]

#Start API
app = FastAPI(title="Chat Bot API")


#Models
class StudentIn(BaseModel):
    wha_id: str = Field(..., min_length=1)
    consent_accepted: bool = False
    age: int | None = None
    semester: str | None = None
    career: str | None = None

class ResponseIn(BaseModel):
    wha_id: str
    questionnaire_id: str
    answer: dict


class ScoresIn(BaseModel):
    wha_id: str
    questionnaire_id: str
    stress_score: int
    anxiety_score: int
    depression_score: int


class AnalyticsIn(BaseModel):
    wha_id: str
    method: str
    cluster_label: str
    notes: str = ""


class LogIn(BaseModel):
    wha_id: str
    log_type: str
    message: str


class ResponsePatch(BaseModel):
    wha_id: str
    questionnaire_id: str
    updates: dict


class Dass21Calculator:
    DEPRESSION_ITEMS = [3, 5, 10, 13, 16, 17, 21]
    ANXIETY_ITEMS = [2, 4, 7, 9, 15, 19, 20]
    STRESS_ITEMS = [1, 6, 8, 11, 12, 14, 18]
    QUESTION_PREFIX = "dass_q"

    @classmethod
    def _question_key(cls, index: int) -> str:
        return f"{cls.QUESTION_PREFIX}{index:02d}"

    @staticmethod
    def _extract_score(answer_entry) -> int | None:
        value = answer_entry
        if isinstance(answer_entry, dict):
            value = answer_entry.get("value")
        if value is None:
            return None
        if isinstance(value, str):
            text = value.strip()
            if text.startswith("scale_"):
                text = text.split("_", 1)[-1]
            try:
                value = int(text)
            except ValueError:
                return None
        try:
            score = int(value)
        except (TypeError, ValueError):
            return None
        if 0 <= score <= 3:
            return score
        return None

    @classmethod
    def calculate(cls, answers: dict) -> dict:
        if not isinstance(answers, dict):
            raise ValueError("Answers must be a dictionary")

        subscale_map = {
            "stress": cls.STRESS_ITEMS,
            "anxiety": cls.ANXIETY_ITEMS,
            "depression": cls.DEPRESSION_ITEMS,
        }
        scores_result: dict[str, int] = {}
        missing: list[str] = []

        for label, indices in subscale_map.items():
            subtotal = 0
            for idx in indices:
                key = cls._question_key(idx)
                entry = answers.get(key)
                score = cls._extract_score(entry)
                if score is None:
                    missing.append(key)
                    continue
                subtotal += score
            scores_result[f"{label}_score"] = subtotal

        if missing:
            missing_sorted = ", ".join(sorted(set(missing)))
            raise ValueError(f"Missing or invalid answers for: {missing_sorted}")

        total_score = sum(scores_result.values())
        scores_result["total_score"] = total_score
        return scores_result


#K-Means implementations
def run_kmeans(k: int = 2, max_iterations: int = 10):
    all_scores = list(scores.find({}))
    if not all_scores:
        return []

    data = {
        s["wha_id"]: [
            s.get("stress_score", 0),
            s.get("anxiety_score", 0),
            s.get("depression_score", 0)
        ]
        for s in all_scores
    }

    centroids = random.sample(list(data.values()), min(k, len(data)))
    for _ in range(max_iterations):
        clusters = {i: [] for i in range(k)}

        for sid, vector in data.items():
            distances = [
                math.sqrt(sum((a - b) ** 2 for a, b in zip(vector, c)))
                for c in centroids
            ]
            cluster_idx = distances.index(min(distances))
            clusters[cluster_idx].append((sid, vector))

        new_centroids = []
        for idx, items in clusters.items():
            if items:
                mean = [sum(vec[i] for _, vec in items) / len(items) for i in range(len(items[0]))]
                new_centroids.append(mean)
            else:
                new_centroids.append(centroids[idx])

        if new_centroids == centroids:
            break
        centroids = new_centroids

    analytics.delete_many({})
    for cluster_id, members in clusters.items():
        for sid, vector in members:
            analytics.insert_one({
                "wha_id": sid,
                "method": "K-Means",
                "cluster_label": f"cluster_{cluster_id}",
                "run_date": datetime.utcnow(),
                "notes": f"Scores: {vector}"
            })

    return clusters


#Endpoints
@app.post("/students")
def register_student(data: StudentIn):
    # Generate a sequential questionnaire_id
    questionnaire_id = str(responses.count_documents({}) + 1)
    student = {
        "wha_id": data.wha_id,
        "consent_accepted": data.consent_accepted,
        "age": data.age,
        "semester": data.semester,
        "career": data.career,
        "created_at": datetime.utcnow(),
    }
    students.insert_one(student)
    # Create initial chat response with null values
    response = {
        "wha_id": data.wha_id,
        "questionnaire_id": questionnaire_id,
        "answer": {},  # Empty dictionary for answers
        "response_date": datetime.utcnow(),
        "created_at": datetime.utcnow(),
    }
    responses.insert_one(response)
    return {"message": "Student registered successfully", "wha_id": data.wha_id}

@app.patch("/students")
def update_student(data: StudentIn):
    # Remove wha_id from the fields to update to prevent editing
    update_fields = {
        "consent_accepted": data.consent_accepted,
        "age": data.age,
        "semester": data.semester,
        "career": data.career,
        "updated_at": datetime.utcnow(),
    }
    result = students.update_one(
        {"wha_id": data.wha_id},
        {"$set": update_fields},
    )
    if result.matched_count == 0:
        return {"message": "Student not found", "modified": False}
    return {"message": "Student updated successfully", "modified": True, "wha_id": data.wha_id}

@app.get("/students/{wha_id}")
def get_student(wha_id: str):
    student = students.find_one({"wha_id": wha_id}, {"_id": 0})
    if not student:
        return {"message": "Student not found"}
    return student
@app.get("/responses")
def get_all_responses(
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100)
):
    total = responses.count_documents({})
    skip = (page - 1) * limit
    items = list(
        responses.find({}, {"_id": 0}).skip(skip).limit(limit)
    )
    return {
        "page": page,
        "limit": limit,
        "total": total,
        "responses": items,
    }

@app.post("/responses/{wha_id}")
def create_questionnaire(wha_id: str):
    questionnaire_id = _generate_questionnaire_id()
    now = datetime.utcnow()
    document = {
        "wha_id": wha_id,
        "questionnaire_id": questionnaire_id,
        "answer": {},
        "response_date": now,
        "created_at": now,
    }
    responses.insert_one(document)
    return {
        "message": "Questionnaire created",
        "questionnaire_id": questionnaire_id,
        "wha_id": wha_id,
        "answer": document["answer"],
        "response_date": document["response_date"],
        "created_at": document["created_at"],
    }

# All responses for a student
@app.get("/responses/{wha_id}")
def get_responses(wha_id: str):
    user_responses = list(responses.find({"wha_id": wha_id}, {"_id": 0}))
    if not user_responses:
        return {"message": "No responses found for this student"}
    return {"responses": user_responses}

# Specific questionnaire response
@app.get("/responses/{wha_id}/{questionnaire_id}")
def get_responses(wha_id: str, questionnaire_id: str):
    user_response = responses.find_one({"wha_id": wha_id, "questionnaire_id": questionnaire_id}, {"_id": 0})
    if not user_response:
        return {"message": "No response found for this student and questionnaire"}
    return {"response": user_response}

@app.patch("/responses/{wha_id}/{questionnaire_id}")
def update_response(wha_id: str, questionnaire_id: str, updates: dict = Body(...)):
    response = responses.find_one({"wha_id": wha_id, "questionnaire_id": questionnaire_id})
    if not response:
        return {"message": "Response not found", "modified": False}
    answer = response.get("answer", {})
    answer.update(updates)
    responses.update_one(
        {"wha_id": wha_id, "questionnaire_id": questionnaire_id},
        {"$set": {"answer": answer, "updated_at": datetime.utcnow()}}
    )
    return {"message": "Response updated", "modified": True, "answer": answer}


@app.post("/calculation/{questionnaire_id}")
def calculate_questionnaire(questionnaire_id: str):
    document = responses.find_one({"questionnaire_id": questionnaire_id})
    if not document:
        raise HTTPException(status_code=404, detail="Questionnaire not found")
    answers = document.get("answer") or {}
    if not answers:
        raise HTTPException(status_code=400, detail="Questionnaire has no answers")
    try:
        score_values = Dass21Calculator.calculate(answers)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    responses.update_one({"_id": document["_id"]}, {"$set": score_values})
    return {
        "questionnaire_id": questionnaire_id,
        "wha_id": document.get("wha_id"),
        **score_values,
    }


@app.post("/calculation-massive")
def calculate_all_questionnaires():
    processed = 0
    skipped = 0
    errors: list[dict[str, str]] = []
    cursor = responses.find({}, {"questionnaire_id": 1, "wha_id": 1, "answer": 1})
    for document in cursor:
        questionnaire_id = document.get("questionnaire_id")
        answers = document.get("answer") or {}
        if not answers:
            skipped += 1
            if len(errors) < 50:
                errors.append({
                    "questionnaire_id": str(questionnaire_id),
                    "wha_id": str(document.get("wha_id")),
                    "error": "missing answers",
                })
            continue
        try:
            score_values = Dass21Calculator.calculate(answers)
        except ValueError as exc:
            skipped += 1
            if len(errors) < 50:
                errors.append({
                    "questionnaire_id": str(questionnaire_id),
                    "wha_id": str(document.get("wha_id")),
                    "error": str(exc),
                })
            continue
        responses.update_one({"_id": document["_id"]}, {"$set": score_values})
        processed += 1
    return {
        "processed": processed,
        "skipped": skipped,
        "errors": errors,
    }


@app.get("/scores/{questionnaire_id}")
def get_scores(questionnaire_id: str):
    document = responses.find_one({"questionnaire_id": questionnaire_id})
    if not document:
        raise HTTPException(status_code=404, detail="Questionnaire not found")

    score_fields = ["stress_score", "anxiety_score", "depression_score", "total_score"]
    scores_present = {field: document.get(field) for field in score_fields}
    if any(value is None for value in scores_present.values()):
        answers = document.get("answer") or {}
        if not answers:
            raise HTTPException(status_code=400, detail="Questionnaire lacks answers to calculate scores")
        try:
            recalculated = Dass21Calculator.calculate(answers)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        responses.update_one({"_id": document["_id"]}, {"$set": recalculated})
        scores_present.update(recalculated)

    return {
        "questionnaire_id": questionnaire_id,
        "wha_id": document.get("wha_id"),
        **scores_present,
    }

# After defining students collection
students.create_index("wha_id", unique=True)


