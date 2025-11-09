import polars as pl
import json, math, random
from datetime import datetime
import matplotlib.pyplot as plt

# -------------------------------
# 🧩 CARGA DE MOCK DATA DESDE JSON
# -------------------------------
with open("mock_scores.json", "r") as f:
    data = json.load(f)

if not data:
    raise ValueError("❌ No hay registros en mock_scores.json")

# Crear DataFrame Polars
df = pl.DataFrame(data)
print("✅ Datos cargados desde mock_scores.json:")
print(df)

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
plt.savefig("elbow_method.png", dpi=200)
plt.show()
print("💾 Gráfico guardado como elbow_method.png")

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
        ).select("student_id").to_series()
        if len(match) > 0:
            cluster_data.append({
                "student_id": match[0],
                "cluster_label": f"cluster_{cluster_id}",
                "stress": vector[0],
                "anxiety": vector[1],
                "depression": vector[2]
            })

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
plt.savefig("clusters_3D.png", dpi=200)
plt.show()
print("💾 Gráfico 3D guardado como clusters_3D.png")

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
plt.savefig("cluster_distribution.png", dpi=200)
plt.show()
print("💾 Gráfico guardado como cluster_distribution.png")

# -------------------------------
# 💾 GUARDAR RESULTADOS A JSON
# -------------------------------
result = []
for row in clusters_df.iter_rows(named=True):
    result.append({
        "student_id": row["student_id"],
        "method": "K-Means",
        "cluster_label": row["cluster_label"],
        "run_date": datetime.utcnow().isoformat(),
        "scores": {
            "stress": row["stress"],
            "anxiety": row["anxiety"],
            "depression": row["depression"]
        }
    })

with open("analytics_results.json", "w") as f:
    json.dump(result, f, indent=2)

print("\n🎯 Resultados guardados en 'analytics_results.json'")