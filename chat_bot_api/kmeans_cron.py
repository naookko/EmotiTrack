import polars as pl
import json, math, random, os, shutil
from datetime import datetime, timedelta, date
from pathlib import Path
import matplotlib.pyplot as plt
from pymongo import MongoClient

MONGO_URI = os.environ.get("MONGO_URI", "mongodb://localhost:27017")
MONGO_DB = os.environ.get("MONGO_DB", "chat_bot")
MONGO_COLLECTION = os.environ.get("MONGO_COLLECTION", "responses")
WEEK_RESULTS_COLLECTION = os.environ.get("WEEK_RESULTS_COLLECTION", "dass21weekresults")
SCRIPT_DIR = Path(__file__).resolve().parent
OUTPUT_BASE_PATH = SCRIPT_DIR / "kmeans_result_vault"
WEEK_HISTORY_PATH = OUTPUT_BASE_PATH / "week_history.txt"


def read_last_week_entry():
    if not os.path.exists(WEEK_HISTORY_PATH):
        return None, None
    with open(WEEK_HISTORY_PATH, "r", encoding="utf-8") as history_file:
        entries = [line.strip() for line in history_file if line.strip()]
    if not entries:
        return None, None
    last = entries[-1]
    try:
        parts = dict(piece.strip().split(": ") for piece in last.split(","))
        start = datetime.fromisoformat(parts["started_date"]).date()
        end = datetime.fromisoformat(parts["end_date"]).date()
        return start, end
    except Exception:
        return None, None

# -------------------------------
# 🧩 CARGA DE DATOS DESDE MONGODB
# -------------------------------
today = datetime.utcnow().date()
current_week_start = today - timedelta(days=today.weekday())
current_week_end = current_week_start + timedelta(days=6)

last_start, last_end = read_last_week_entry()
if last_start and last_start <= today <= last_end:
    week_start_date = last_start
else:
    if last_start:
        week_start_date = last_start + timedelta(days=7)
        while week_start_date + timedelta(days=6) < current_week_start:
            week_start_date += timedelta(days=7)
        if week_start_date > current_week_start:
            week_start_date = current_week_start
    else:
        week_start_date = current_week_start

week_end_date = week_start_date + timedelta(days=6)

start_dt = datetime.combine(week_start_date, datetime.min.time())
end_dt = datetime.combine(week_end_date + timedelta(days=1), datetime.min.time())

with MongoClient(MONGO_URI) as client:
    collection = client[MONGO_DB][MONGO_COLLECTION]
    cursor = collection.find(
        {"created_at": {"$gte": start_dt, "$lt": end_dt}}
    ).sort("created_at", 1)
    data = []
    for doc in cursor:
        cleaned = dict(doc)
        cleaned["_id"] = str(doc.get("_id"))
        created_at = cleaned.get("created_at")
        if isinstance(created_at, datetime):
            cleaned["created_at"] = created_at

        total_score = cleaned.get("total_score")
        stress = cleaned.get("stress_score")
        anxiety = cleaned.get("anxiety_score")
        depression = cleaned.get("depression_score")
        try:
            total_score_value = float(total_score)
        except (TypeError, ValueError):
            continue
        if (
            total_score_value < 0
            or stress is None
            or anxiety is None
            or depression is None
        ):
            continue
        cleaned["total_score"] = total_score_value
        data.append(cleaned)

run_datetime = datetime.utcnow()
OUTPUT_BASE_PATH.mkdir(parents=True, exist_ok=True)
run_output_dir = OUTPUT_BASE_PATH / f"{week_start_date}-{week_end_date}"
if run_output_dir.exists():
    shutil.rmtree(run_output_dir)
run_output_dir.mkdir(parents=True, exist_ok=True)

history_lines = []
if WEEK_HISTORY_PATH.exists():
    with WEEK_HISTORY_PATH.open("r", encoding="utf-8") as history_file:
        history_lines = [
            line.strip() for line in history_file
            if line.strip() and not line.startswith(f"started_date: {week_start_date}")
        ]
with WEEK_HISTORY_PATH.open("w", encoding="utf-8") as history_file:
    for line in history_lines:
        history_file.write(line + "\n")
    history_file.write(f"started_date: {week_start_date}, end_date: {week_end_date}\n")

if not data:
    print(f"WARNING: No se encontraron cuestionarios completos (total_score >= 0) en MongoDB para la semana {week_start_date} - {week_end_date}.")
    print(f"INFO: Carpeta vacia creada en {run_output_dir}.")
    raise SystemExit(0)

# Crear DataFrame Polars
df = pl.DataFrame(data)
print(f"✅ Datos cargados desde MongoDB para la semana {week_start_date} - {week_end_date}:")
print(df)

def parse_record_timestamp(record):
    for key in ("created_at", "response_date", "run_date", "timestamp"):
        if key in record and record[key] is not None:
            value = record[key]
            if isinstance(value, dict):
                value = value.get("$date") or value.get("date")
            if isinstance(value, str):
                ts = value.rstrip("Z")
                if ts != value:
                    ts = ts + "+00:00"
                return datetime.fromisoformat(ts)
            if isinstance(value, datetime):
                return value
    raise ValueError("❌ No se encontró un campo de fecha válido en el registro.")

timestamps = [parse_record_timestamp(row) for row in data]
reference_date = min(timestamps)
week_start_date = (reference_date - timedelta(days=reference_date.weekday())).date()
week_end_date = (week_start_date + timedelta(days=6))
for ts in timestamps:
    if ts.date() < week_start_date or ts.date() > week_end_date:
        raise ValueError("❌ El archivo semanal debe contener datos dentro de una sola semana.")

if "wha_id" in df.columns:
    identifier_column = "wha_id"
    result_identifier_key = "wha_id"
elif "_id" in df.columns:
    df = df.with_columns(pl.col("_id").struct.field("$oid").alias("unique_id"))
    identifier_column = "unique_id"
    result_identifier_key = "_id"
else:
    identifier_column = "student_id"
    result_identifier_key = "student_id"

# Convertir los datos a listas numéricas
vectors = [
    [row["stress_score"], row["anxiety_score"], row["depression_score"]]
    for row in df.iter_rows(named=True)
]

# -----------------------------------------------------
# 🧮 IMPLEMENTACIÓN MANUAL DE K-MEANS Y ELBOW METHOD
# -----------------------------------------------------
def kmeans_clustering(data, k=3, max_iterations=10):
    """Algoritmo K-Means sin librerías"""
    centroids = random.sample(data, k)
    for _ in range(max_iterations):
        clusters = {i: [] for i in range(k)}
        # Asignar cada punto al centroide más cercano
        for vector in data:
            distances = [math.sqrt(sum((a - b)**2 for a, b in zip(vector, c))) for c in centroids]
            cluster_idx = distances.index(min(distances))
            clusters[cluster_idx].append(vector)
        # Recalcular centroides
        new_centroids = []
        for idx, points in clusters.items():
            if points:
                mean = [sum(vec[i] for vec in points) / len(points) for i in range(len(points[0]))]
                new_centroids.append(mean)
            else:
                new_centroids.append(centroids[idx])
        if new_centroids == centroids:
            break
        centroids = new_centroids

    # Calcular SSE
    sse = 0
    for idx, points in clusters.items():
        for vec in points:
            sse += sum((a - b)**2 for a, b in zip(vec, centroids[idx]))

    return clusters, centroids, sse


def elbow_method(data, max_k=6):
    """Calcula el SSE para varios k para identificar el codo"""
    sse_results = []
    for k in range(1, max_k + 1):
        _, _, sse = kmeans_clustering(data, k)
        sse_results.append((k, sse))
        print(f"k={k}, SSE={sse}")
    return sse_results


# -------------------------------
# 📉 MÉTODO DEL CODO (ELBOW)
# -------------------------------
print("\n📊 Calculando Método del Codo...")
sse_values = elbow_method(vectors, max_k=6)

# Convertir resultados SSE a DataFrame Polars
elbow_df = pl.DataFrame({"k": [k for k, _ in sse_values], "SSE": [s for _, s in sse_values]})
print("\n📈 Resultados del método del codo:")
print(elbow_df)

# -------------------------------
# 📊 GRAFICAR MÉTODO DEL CODO
# -------------------------------
plt.figure(figsize=(8, 5))
plt.plot(elbow_df["k"], elbow_df["SSE"], marker='o', linestyle='-', color='royalblue')
plt.title("Método del Codo (Elbow Method)")
plt.xlabel("Número de Clusters (k)")
plt.ylabel("SSE (Suma de Errores Cuadrados)")
plt.grid(True)
plt.tight_layout()
elbow_path = run_output_dir / "elbow_method.png"
plt.savefig(elbow_path, dpi=200)
plt.close()
print(f"💾 Gráfico guardado en {elbow_path}")

# Elegir manualmente el k óptimo después de ver la gráfica
optimal_k = 3  # Ajusta según el 'codo'

# -------------------------------
# 🧩 APLICAR K-MEANS FINAL
# -------------------------------
clusters, centroids, _ = kmeans_clustering(vectors, k=optimal_k)

cluster_data = []
for cluster_id, members in clusters.items():
    for vector in members:
        # Buscar el estudiante asociado
        match = df.filter(
            (pl.col("stress_score") == vector[0]) &
            (pl.col("anxiety_score") == vector[1]) &
            (pl.col("depression_score") == vector[2])
        ).select(identifier_column).to_series()
        if len(match) > 0:
            cluster_entry = {
                "cluster_label": f"cluster_{cluster_id}",
                "stress": vector[0],
                "anxiety": vector[1],
                "depression": vector[2]
            }
            cluster_entry[identifier_column] = match[0]
            cluster_data.append(cluster_entry)

clusters_df = pl.DataFrame(cluster_data)
print("\n✅ Resultados del clustering:")
print(clusters_df)

# -------------------------------
# 📊 GRAFICAR CLUSTERS (3D)
# -------------------------------
from mpl_toolkits.mplot3d import Axes3D

fig = plt.figure(figsize=(8, 6))
ax = fig.add_subplot(111, projection="3d")

colors = ["royalblue", "darkorange", "green", "purple", "red", "cyan"]
for cluster_id, members in clusters.items():
    xs = [v[0] for v in members]
    ys = [v[1] for v in members]
    zs = [v[2] for v in members]
    ax.scatter(xs, ys, zs, color=colors[cluster_id % len(colors)], label=f"Cluster {cluster_id}")

# Añadir centroides
for i, centroid in enumerate(centroids):
    ax.scatter(centroid[0], centroid[1], centroid[2], s=200, color="black", marker="X", edgecolors="white")

ax.set_xlabel("Estrés")
ax.set_ylabel("Ansiedad")
ax.set_zlabel("Depresión")
ax.set_title("Visualización 3D de Clusters (K-Means)")
ax.legend()
plt.tight_layout()
clusters_3d_path = run_output_dir / "clusters_3D.png"
plt.savefig(clusters_3d_path, dpi=200)
plt.close(fig)
print(f"💾 Gráfico 3D guardado en {clusters_3d_path}")

# -------------------------------
# 📊 DISTRIBUCIÓN DE ESTUDIANTES POR CLUSTER
# -------------------------------
counts_df = clusters_df.group_by("cluster_label").count()
plt.figure(figsize=(7, 5))
plt.bar(counts_df["cluster_label"], counts_df["count"], color="cornflowerblue")
plt.title("Distribución de Estudiantes por Cluster")
plt.xlabel("Cluster")
plt.ylabel("Cantidad de Estudiantes")
plt.tight_layout()
distribution_path = run_output_dir / "cluster_distribution.png"
plt.savefig(distribution_path, dpi=200)
plt.close()
print(f"💾 Gráfico guardado en {distribution_path}")

# -------------------------------
# 💾 GUARDAR RESULTADOS A JSON
# -------------------------------
result = []
for row in clusters_df.iter_rows(named=True):
    identifier_value = row[identifier_column]
    result.append({
        result_identifier_key: identifier_value,
        "method": "K-Means",
        "cluster_label": row["cluster_label"],
        "run_date": run_datetime.isoformat(),
        "scores": {
            "stress": row["stress"],
            "anxiety": row["anxiety"],
            "depression": row["depression"]
        }
    })

result_path = run_output_dir / "analytics_results.json"
with open(result_path, "w") as f:
    json.dump(result, f, indent=2)

print(f"\n🎯 Resultados guardados en '{result_path}'")

week_document = {
    "week_start_date": week_start_date.isoformat(),
    "week_end_date": week_end_date.isoformat(),
    "run_date": run_datetime,
    "is_active_week": week_start_date <= today <= week_end_date,
    "optimal_k": optimal_k,
    "sse_values": [{"k": int(k), "sse": float(s)} for k, s in sse_values],
    "centroids": centroids,
    "clusters": result,
    "outputs": {
        "elbow_chart": str(elbow_path),
        "clusters_chart": str(clusters_3d_path),
        "distribution_chart": str(distribution_path),
        "analytics_json": str(result_path),
    },
}

with MongoClient(MONGO_URI) as client:
    week_results = client[MONGO_DB][WEEK_RESULTS_COLLECTION]
    week_filter = {"week_start_date": week_document["week_start_date"]}
    existing_week = week_results.find_one(week_filter)
    is_active_week = week_document["is_active_week"]
    if existing_week and not is_active_week:
        print("INFO: Semana ya cerrada; se conservan resultados previos en MongoDB.")
    else:
        week_results.replace_one(week_filter, week_document, upsert=True)
        action = "actualizados" if existing_week else "insertados"
        print(f"📊 Resultados {action} en MongoDB (colección '{WEEK_RESULTS_COLLECTION}').")
