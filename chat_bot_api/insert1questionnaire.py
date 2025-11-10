"""Utility script to seed a random DASS-21 questionnaire for a given wa_id."""

from __future__ import annotations

import argparse
import os
import random
from datetime import datetime
from typing import Dict, Tuple

from pymongo import MongoClient

DEFAULT_MONGO_URI = os.environ.get("MONGO_URI", "mongodb://localhost:27017/")
DEFAULT_DB = os.environ.get("MONGO_DB", "chat_bot")
RESPONSES_COLLECTION = os.environ.get("MONGO_COLLECTION", "responses")
STUDENTS_COLLECTION = "students"

DEPRESSION_ITEMS = [3, 5, 10, 13, 16, 17, 21]
ANXIETY_ITEMS = [2, 4, 7, 9, 15, 19, 20]
STRESS_ITEMS = [1, 6, 8, 11, 12, 14, 18]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Insert a random questionnaire for the provided wa_id."
    )
    parser.add_argument("wha_id", help="WA ID (student identifier) to attach the questionnaire to.")
    parser.add_argument(
        "--mongo-uri",
        default=DEFAULT_MONGO_URI,
        help="MongoDB connection string (defaults to env MONGO_URI or localhost).",
    )
    parser.add_argument(
        "--database",
        default=DEFAULT_DB,
        help="MongoDB database name (defaults to env MONGO_DB or chat_bot).",
    )
    parser.add_argument(
        "--seed",
        type=int,
        help="Optional random seed for deterministic output.",
    )
    return parser.parse_args()


def ensure_student(collection, wa_id: str) -> None:
    existing = collection.find_one({"wha_id": wa_id})
    if existing:
        return
    now = datetime.utcnow()
    student_document = {
        "wha_id": wa_id,
        "consent_accepted": True,
        "age": random.randint(18, 30),
        "semester": random.choice(["Semestres 1 a 3", "Semestres 4 a 6", "Semestres 7 a 9"]),
        "career": random.choice(["Ingenieria", "Psicologia", "Administracion"]),
        "created_at": now,
        "updated_at": now,
    }
    collection.insert_one(student_document)


def random_answers() -> Tuple[Dict[str, Dict[str, int]], Dict[str, int]]:
    answers: Dict[str, Dict[str, int]] = {}
    scores = {"stress_score": 0, "anxiety_score": 0, "depression_score": 0}
    for index in range(1, 22):
        value = random.randint(0, 3)
        key = f"dass_q{index:02d}"
        answers[key] = {"value": value}
        if index in STRESS_ITEMS:
            scores["stress_score"] += value
        if index in ANXIETY_ITEMS:
            scores["anxiety_score"] += value
        if index in DEPRESSION_ITEMS:
            scores["depression_score"] += value
    scores["total_score"] = scores["stress_score"] + scores["anxiety_score"] + scores["depression_score"]
    return answers, scores


def next_questionnaire_id(collection) -> str:
    """Mimic the sequential identifier used by the API."""
    next_id = collection.count_documents({}) + 1
    candidate = str(next_id)
    while collection.find_one({"questionnaire_id": candidate}, {"_id": 1}):
        next_id += 1
        candidate = str(next_id)
    return candidate


def main() -> None:
    args = parse_args()
    if args.seed is not None:
        random.seed(args.seed)

    with MongoClient(args.mongo_uri) as client:
        database = client[args.database]
        students = database[STUDENTS_COLLECTION]
        responses = database[RESPONSES_COLLECTION]

        ensure_student(students, args.wha_id)

        questionnaire_id = next_questionnaire_id(responses)
        now = datetime.utcnow()
        answers, scores = random_answers()
        document = {
            "wha_id": args.wha_id,
            "questionnaire_id": questionnaire_id,
            "answer": answers,
            "stress_score": scores["stress_score"],
            "anxiety_score": scores["anxiety_score"],
            "depression_score": scores["depression_score"],
            "total_score": scores["total_score"],
            "response_date": now,
            "created_at": now,
            "updated_at": now,
        }
        responses.insert_one(document)
        print(
            f"Inserted questionnaire {questionnaire_id} for {args.wha_id} "
            f"(stress={scores['stress_score']}, anxiety={scores['anxiety_score']}, "
            f"depression={scores['depression_score']}, total={scores['total_score']})."
        )


if __name__ == "__main__":
    main()
