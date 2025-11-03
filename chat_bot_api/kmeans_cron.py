import polars as pl
import json, math, random, os, shutil
from datetime import datetime, timedelta
import matplotlib.pyplot as plt

# -------------------------------
# 🧩 CARGA DE MOCK DATA DESDE JSON
# -------------------------------
data_file = "mook_weekly_data/responses_week_8.ndjson"
with open(data_file, "r") as f:
    first_char = f.read(1)
    f.seek(0)
    if first_char == "[":
        data = json.load(f)
    else:
        data = [json.loads(line) for line in f if line.strip()]

if not data:
    raise ValueError(f"❌ No hay registros en {data_file}")

# Crear DataFrame Polars
df = pl.DataFrame(data)
print(f"✅ Datos cargados desde {data_file}:")
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
run_datetime = datetime.utcnow()
output_base_path = os.path.join("kmeans_result_vault")
os.makedirs(output_base_path, exist_ok=True)
run_output_dir = os.path.join(output_base_path, f"{week_start_date}-{week_end_date}")
if os.path.isdir(run_output_dir):
    shutil.rmtree(run_output_dir)
os.makedirs(run_output_dir, exist_ok=True)
with open(os.path.join(output_base_path, "week_history.txt"), "a") as history_file:
    history_file.write(f"started_date: {week_start_date}, end_date: {week_end_date}\n")

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
elbow_path = os.path.join(run_output_dir, "elbow_method.png")
plt.savefig(elbow_path, dpi=200)
plt.show()
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
clusters_3d_path = os.path.join(run_output_dir, "clusters_3D.png")
plt.savefig(clusters_3d_path, dpi=200)
plt.show()
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
distribution_path = os.path.join(run_output_dir, "cluster_distribution.png")
plt.savefig(distribution_path, dpi=200)
plt.show()
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

result_path = os.path.join(run_output_dir, "analytics_results.json")
with open(result_path, "w") as f:
    json.dump(result, f, indent=2)

print(f"\n🎯 Resultados guardados en '{result_path}'")
