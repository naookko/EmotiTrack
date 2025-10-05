import math
import random

from fastapi import FastAPI
from pydantic import BaseModel
from pymongo import MongoClient
from datetime import datetime

#Database connection
client = MongoClient("mongodb://localhost:27017/")
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
    phone_number: str
    consent_accepted: bool
    code: str
    courses: list[str] = []


class ResponseIn(BaseModel):
    student_id: str
    questionnaire_id: str
    answer: list[dict]


class ScoresIn(BaseModel):
    student_id: str
    questionnaire_id: str
    stress_score: int
    anxiety_score: int
    depression_score: int


class AnalyticsIn(BaseModel):
    student_id: str
    method: str
    cluster_label: str
    notes: str = ""


class LogIn(BaseModel):
    student_id: str
    log_type: str
    message: str


#K-Means implementations
def run_kmeans(k: int = 2, max_iterations: int = 10):
    all_scores = list(scores.find({}))
    if not all_scores:
        return []

    data = {
        s["student_id"]: [
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
                "student_id": sid,
                "method": "K-Means",
                "cluster_label": f"cluster_{cluster_id}",
                "run_date": datetime.utcnow(),
                "notes": f"Scores: {vector}"
            })

    return clusters


#Endpoints
@app.post("/students")
def register_student(data: StudentIn):
    student = {
        "_id": data.code, #change the id for the one of whatsapp
        "phone_number": data.phone_number,
        "consent_accepted": data.consent_accepted,
        "code": data.code,
        "created_at": datetime.utcnow(),
        "courses": data.courses,
    }
    students.insert_one(student)
    return {"message": "Student registered successfully", "student_code": data.code}


@app.post("/responses")
def save_response(data: ResponseIn):
    # Generate a sequential questionnaire_id using MongoDB's count
    questionnaire_id = str(responses.count_documents({}) + 1)
    response_id = f"resp_{datetime.utcnow().date()}_{data.student_id}"
    response = {
        "_id": response_id,
        "student_id": data.student_id,
        "questionnaire_id": questionnaire_id,
        "response_date": datetime.utcnow(),
        "answer": data.answer,
        "created_at": datetime.utcnow(),
    }
    responses.insert_one(response)

    return response

@app.patch("/responses")
def update_response(data: ResponseIn):
    update_field = f"answer.{data.question_key}"
    result = responses.update_one(
        {
            "questionnaire_id": data.questionnaire_id,
        },
        {
            "$set": {
                update_field: data.answer,
                "updated_at": datetime.utcnow(),
            }
        },
    )

    if result.matched_count == 0:
        return {
            "message": "Response not found",
            "analytics_updated": False,
            "modified": False,
        }

