import math
import random

from fastapi import FastAPI, Body
from pydantic import BaseModel, Field
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
    wha_id: str = Field(..., min_length=1)
    consent_accepted: bool
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

# After defining students collection
students.create_index("wha_id", unique=True)
