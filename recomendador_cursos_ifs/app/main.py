import os
import logging
from contextlib import asynccontextmanager
from typing import Optional

import numpy as np
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from sentence_transformers import SentenceTransformer

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
logger = logging.getLogger("recomendador-ifs")

DATA_FILE = os.getenv("COURSES_JSON", "/app/data/cursos_ifs.json")
MODEL_NAME = os.getenv(
    "EMBEDDING_MODEL",
    "paraphrase-multilingual-MiniLM-L12-v2"
)

# Pesos iniciais. Devem ser calibrados com avaliações de pessoas especialistas.
FIELD_WEIGHTS = {
    "interesses_relacionados": 0.35,
    "habilidades_relacionadas": 0.20,
    "objetivos_profissionais": 0.20,
    "areas_atuacao": 0.15,
    "descricao": 0.07,
    "dimensoes_vocacionais": 0.03,
}

FIELD_LABELS = {
    "interesses_relacionados": "Interesses relacionados",
    "habilidades_relacionadas": "Habilidades relacionadas",
    "objetivos_profissionais": "Objetivos profissionais",
    "areas_atuacao": "Áreas de atuação",
    "descricao": "Descrição do curso",
    "dimensoes_vocacionais": "Dimensões vocacionais",
}

courses = []
model = None
course_vectors = {}


class RecommendationRequest(BaseModel):
    interesses: str = Field(..., min_length=5, description="Descrição livre dos interesses")
    campus: Optional[str] = None
    nivel: Optional[str] = None
    limite: int = Field(default=10, ge=1, le=46)


def load_courses():
    import json
    if not os.path.isfile(DATA_FILE):
        raise FileNotFoundError(
            f"Arquivo de cursos não encontrado: {DATA_FILE}. "
            "Verifique o volume ou a cópia do cursos_ifs.json."
        )
    with open(DATA_FILE, "r", encoding="utf-8") as f:
        payload = json.load(f)
    items = payload.get("ofertas")
    if not isinstance(items, list) or not items:
        raise ValueError("O JSON precisa conter uma lista não vazia na chave 'ofertas'.")
    return payload, items


def initialize_model_and_embeddings():
    global courses, model, course_vectors, institution_metadata

    institution_metadata, courses = load_courses()
    logger.info("Carregando modelo %s em CPU...", MODEL_NAME)
    model = SentenceTransformer(MODEL_NAME, device="cpu")

    # Gera uma representação vetorial independente para cada dimensão de cada oferta.
    # Isso permite calcular e explicar a contribuição de cada campo.
    for field in FIELD_WEIGHTS:
        texts = [
            str(course.get(field) or course.get("nome") or "")
            for course in courses
        ]
        vectors = model.encode(
            texts,
            batch_size=16,
            show_progress_bar=False,
            convert_to_numpy=True,
            normalize_embeddings=True,
        )
        course_vectors[field] = np.asarray(vectors, dtype=np.float32)

    logger.info(
        "Inicialização concluída: %d ofertas, %d perfis e execução em CPU.",
        len(courses),
        len({c.get("id_perfil") for c in courses}),
    )


@asynccontextmanager
async def lifespan(app: FastAPI):
    initialize_model_and_embeddings()
    yield


app = FastAPI(
    title="Recomendador de Cursos do IFS",
    description="Recomendação semântica de ofertas de cursos a partir de interesses em texto livre.",
    version="1.0.0",
    lifespan=lifespan,
)


@app.get("/", response_class=HTMLResponse)
def home():
    html_path = os.path.join(os.path.dirname(__file__), "index.html")
    with open(html_path, "r", encoding="utf-8") as f:
        return f.read()


@app.get("/health")
def health():
    return {
        "status": "ok" if model is not None else "initializing",
        "device": "cpu",
        "model": MODEL_NAME,
        "total_ofertas": len(courses),
    }


@app.get("/metadata")
def metadata():
    if not courses:
        raise HTTPException(status_code=503, detail="Aplicação ainda inicializando.")
    return {
        "instituicao": institution_metadata.get("instituicao"),
        "total_ofertas": len(courses),
        "total_perfis": len({c.get("id_perfil") for c in courses}),
        "campi": sorted({c.get("campus") for c in courses if c.get("campus")}),
        "niveis": sorted({c.get("nivel") for c in courses if c.get("nivel")}),
        "modelo": MODEL_NAME,
        "dispositivo": "CPU",
    }


@app.post("/recommend")
def recommend(request: RecommendationRequest):
    if model is None:
        raise HTTPException(status_code=503, detail="Modelo ainda não foi carregado.")

    query = request.interesses.strip()
    if len(query) < 5:
        raise HTTPException(status_code=422, detail="Informe uma descrição de interesses mais completa.")

    query_vector = model.encode(
        [query],
        show_progress_bar=False,
        convert_to_numpy=True,
        normalize_embeddings=True,
    )[0].astype(np.float32)

    results = []
    for idx, course in enumerate(courses):
        if request.campus and request.campus != "Todos" and course.get("campus") != request.campus:
            continue
        if request.nivel and request.nivel != "Todos" and course.get("nivel") != request.nivel:
            continue

        breakdown = {}
        weighted_score = 0.0
        for field, weight in FIELD_WEIGHTS.items():
            similarity = float(np.dot(query_vector, course_vectors[field][idx]))
            breakdown[field] = {
                "label": FIELD_LABELS[field],
                "similaridade": round(similarity, 4),
                "peso": weight,
                "contribuicao": round(similarity * weight, 4),
            }
            weighted_score += similarity * weight

        strongest = max(breakdown.items(), key=lambda item: item[1]["similaridade"])
        results.append({
            "id_oferta": course.get("id_oferta"),
            "id_perfil": course.get("id_perfil"),
            "nome": course.get("nome"),
            "campus": course.get("campus"),
            "nivel": course.get("nivel"),
            "duracao": course.get("duracao"),
            "area_principal": course.get("area_principal"),
            "score": round(weighted_score, 4),
            "dimensao_mais_proxima": strongest[1]["label"],
            "detalhamento": breakdown,
            "descricao": course.get("descricao"),
            "interesses_relacionados": course.get("interesses_relacionados"),
            "habilidades_relacionadas": course.get("habilidades_relacionadas"),
            "objetivos_profissionais": course.get("objetivos_profissionais"),
            "areas_atuacao": course.get("areas_atuacao"),
            "dimensoes_vocacionais": course.get("dimensoes_vocacionais"),
        })

    results.sort(key=lambda item: item["score"], reverse=True)
    results = results[:request.limite]

    return {
        "consulta": query,
        "modelo": MODEL_NAME,
        "metodo": "similaridade de cosseno ponderada",
        "observacao": (
            "O score é uma medida de similaridade para ordenar os resultados; "
            "não representa probabilidade nem percentual de compatibilidade."
        ),
        "pesos": FIELD_WEIGHTS,
        "total_retornado": len(results),
        "resultados": results,
    }
