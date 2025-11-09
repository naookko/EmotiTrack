import json, random

dataset = []
for i in range(1, 151):
    # Asignar grupo natural (bajo, medio, alto estrés)
    group = random.choice(["low", "medium", "high"])
    if group == "low":
        stress = random.randint(2, 6)
        anxiety = random.randint(2, 6)
        depression = random.randint(2, 6)
    elif group == "medium":
        stress = random.randint(7, 13)
        anxiety = random.randint(7, 13)
        depression = random.randint(7, 13)
    else:
        stress = random.randint(14, 21)
        anxiety = random.randint(14, 21)
        depression = random.randint(14, 21)

    dataset.append({
        "student_id": f"s{i:03}",
        "stress_score": stress,
        "anxiety_score": anxiety,
        "depression_score": depression,
        "total_score": stress + anxiety + depression
    })

with open("mock_scores.json", "w") as f:
    json.dump(dataset, f, indent=2)

print("✅ Dataset de 150 estudiantes generado: mock_scores.json")
