"""API do recomendador de cursos do IFS."""
import json
import logging
import os
import secrets
import hashlib
import hmac
import re
import time
from threading import Lock
import sqlite3
from datetime import datetime, timezone
from collections import Counter
from fastapi import Depends, Request, Response as FastAPIResponse, Cookie
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.responses import Response
from contextlib import asynccontextmanager
from pathlib import Path
from threading import BoundedSemaphore
from typing import Optional

import numpy as np
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .scoring import (FIELD_LABELS, DEFAULT_WEIGHTS, RIASEC_NAMES, RIASEC_TYPES, holland_code,
                      load_weights, parse_holland_text, profile_from_answers, profile_is_flat, rank_courses)
from .analytics import AnonymousMetrics

logging.basicConfig(level=os.getenv('LOG_LEVEL', 'INFO'))
logger = logging.getLogger('recomendador-ifs')
ROOT = Path(__file__).resolve().parent.parent
DATA_FILE = os.getenv('COURSES_JSON', str(ROOT / 'data' / 'cursos_ifs.json'))
MODEL_NAME = os.getenv('EMBEDDING_MODEL', 'paraphrase-multilingual-MiniLM-L12-v2')
WEIGHTS_FILE = os.getenv('WEIGHTS_FILE')
FIELD_WEIGHTS = load_weights(WEIGHTS_FILE)
RIASEC_ITEMS_FILE = os.getenv('RIASEC_ITEMS_FILE', str(ROOT / 'data' / 'riasec_itens.json'))
RIASEC_COURSES_FILE = os.getenv('RIASEC_COURSES_FILE', str(ROOT / 'data' / 'riasec_cursos.json'))
# Peso do perfil RIASEC no modo híbrido (0 = só texto, 1 = só perfil). Calibrar com scripts/evaluate.py.
RIASEC_WEIGHT = min(max(float(os.getenv('RIASEC_WEIGHT', '0.5')), 0.0), 1.0)
# Abaixo desta similaridade de texto, nenhum curso do catálogo é considerado próximo do que o estudante descreveu.
# Valor inicial observado com o modelo real (cursos pertinentes: 0,49 a 0,64; sem curso no catálogo, como
# saúde e moda: 0,27 e 0,37);
# deve ser recalibrado com os casos avaliados por especialistas.
LOW_AFFINITY_THRESHOLD = float(os.getenv('LOW_AFFINITY_THRESHOLD', '0.40'))
MAX_CONCURRENT_INFERENCES = max(1, int(os.getenv('MAX_CONCURRENT_INFERENCES', '2')))
inference_slots = BoundedSemaphore(MAX_CONCURRENT_INFERENCES)
courses = []
model = None
course_vectors = {}
institution_metadata = {}
metrics = None
# auto_error=False: a interface usa sessão por cookie; HTTP Basic segue aceito para scripts e testes.
security = HTTPBasic(auto_error=False)
MANAGEMENT_DB = os.getenv("MANAGEMENT_DB", str(ROOT / "runtime" / "management.sqlite3"))
MANAGER_SESSION_SECONDS = 60 * 60 * 8

def valid_manager_credentials(username, password):
    expected_user = os.getenv("GESTAO_USER", "gestao")
    expected_password = os.getenv("GESTAO_PASSWORD", "")
    if not expected_password:
        return False
    return (secrets.compare_digest(str(username).encode(), expected_user.encode())
            and secrets.compare_digest(str(password).encode(), expected_password.encode()))

def manager_from_session(request: Request):
    token = request.cookies.get('ifs_gestao', '')
    if not token:
        return None
    with management_connection() as db:
        row = db.execute('SELECT username FROM manager_sessions WHERE token_hash=? AND expires_at>?',
                         (session_digest(token), int(time.time()))).fetchone()
    return row['username'] if row else None

def management_auth(request: Request, credentials: Optional[HTTPBasicCredentials] = Depends(security)):
    if manager_from_session(request):
        return True
    if credentials and valid_manager_credentials(credentials.username, credentials.password):
        return True
    raise HTTPException(status_code=401, detail="Acesso restrito à gestão. Faça login como gestor.")

def management_connection():
    db = sqlite3.connect(MANAGEMENT_DB, timeout=10)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys=ON")
    return db

SESSION_SECONDS = 60 * 60 * 24 * 7
LOGIN_ATTEMPTS = {}
LOGIN_LOCK = Lock()

def hash_password(password, salt=None):
    salt = salt or secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac('sha256', password.encode(), salt, 310000)
    return salt.hex() + ':' + digest.hex()

def verify_password(password, stored):
    try:
        salt, expected = stored.split(':', 1)
        return hmac.compare_digest(hash_password(password, bytes.fromhex(salt)), stored)
    except (ValueError, TypeError):
        return False

def session_digest(token):
    return hashlib.sha256(token.encode()).hexdigest()

def require_student(request: Request):
    token = request.cookies.get('ifs_session', '')
    if not token:
        raise HTTPException(401, 'Faça login para continuar.')
    with management_connection() as db:
        row = db.execute('SELECT u.id, u.name, u.email FROM student_sessions s JOIN students u ON u.id=s.student_id WHERE s.token_hash=? AND s.expires_at>?', (session_digest(token), int(time.time()))).fetchone()
    if not row:
        raise HTTPException(401, 'Sessão expirada. Faça login novamente.')
    return dict(row)

def check_origin(request: Request):
    origin = request.headers.get('origin')
    if origin:
        from urllib.parse import urlsplit
        parsed = urlsplit(origin)
        expected = urlsplit(str(request.base_url))
        if (parsed.scheme, parsed.netloc) != (expected.scheme, expected.netloc):
            raise HTTPException(403, 'Origem não permitida.')

def set_session_cookie(response, token, request):
    response.set_cookie('ifs_session', token, httponly=True, secure=request.url.scheme == 'https', samesite='strict', max_age=SESSION_SECONDS, path='/')

def init_management():
    Path(MANAGEMENT_DB).parent.mkdir(parents=True, exist_ok=True)
    with management_connection() as db:
        db.execute("CREATE TABLE IF NOT EXISTS consultations (id INTEGER PRIMARY KEY AUTOINCREMENT, created_at TEXT NOT NULL, campus TEXT, nivel TEXT, interests TEXT NOT NULL, top_course TEXT, top_area TEXT, top_score REAL, results_json TEXT NOT NULL)")
        db.execute("CREATE INDEX IF NOT EXISTS ix_consultations_date ON consultations(created_at)")
        db.execute("CREATE TABLE IF NOT EXISTS students (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, email TEXT NOT NULL UNIQUE COLLATE NOCASE, password_hash TEXT NOT NULL, created_at TEXT NOT NULL, consent_at TEXT NOT NULL)")
        db.execute("CREATE TABLE IF NOT EXISTS student_sessions (token_hash TEXT PRIMARY KEY, student_id INTEGER NOT NULL REFERENCES students(id) ON DELETE CASCADE, expires_at INTEGER NOT NULL)")
        db.execute("CREATE INDEX IF NOT EXISTS ix_sessions_student ON student_sessions(student_id)")
        db.execute("CREATE TABLE IF NOT EXISTS manager_sessions (token_hash TEXT PRIMARY KEY, username TEXT NOT NULL, expires_at INTEGER NOT NULL)")
        # Sugestões de novos cursos feitas pelos estudantes ao IFS.
        db.execute("CREATE TABLE IF NOT EXISTS course_suggestions (id INTEGER PRIMARY KEY AUTOINCREMENT, student_id INTEGER NOT NULL REFERENCES students(id) ON DELETE CASCADE, created_at TEXT NOT NULL, course_name TEXT NOT NULL, area TEXT, campus TEXT, nivel TEXT, reason TEXT NOT NULL)")
        db.execute("CREATE INDEX IF NOT EXISTS ix_suggestions_student ON course_suggestions(student_id)")
        db.execute("CREATE INDEX IF NOT EXISTS ix_suggestions_date ON course_suggestions(created_at)")
        db.execute("CREATE TABLE IF NOT EXISTS riasec_profiles (student_id INTEGER PRIMARY KEY REFERENCES students(id) ON DELETE CASCADE, answers_json TEXT NOT NULL, scores_json TEXT NOT NULL, code TEXT, updated_at TEXT NOT NULL)")
        cols = {r[1] for r in db.execute('PRAGMA table_info(consultations)')}
        if 'student_id' not in cols:
            db.execute('ALTER TABLE consultations ADD COLUMN student_id INTEGER')
        if 'method' not in cols:
            db.execute('ALTER TABLE consultations ADD COLUMN method TEXT')
        if 'low_affinity' not in cols:
            db.execute('ALTER TABLE consultations ADD COLUMN low_affinity INTEGER NOT NULL DEFAULT 0')
        if 'riasec_code' not in cols:
            db.execute('ALTER TABLE consultations ADD COLUMN riasec_code TEXT')
        db.execute('CREATE INDEX IF NOT EXISTS ix_consultations_student ON consultations(student_id)')

def record_consultation(request, results, student_id, text, method='texto', riasec_code=None, low_affinity=False):
    # Histórico vinculado à conta autenticada. Não armazena IP nem identificador de dispositivo.
    top = results[0] if results else {}
    with management_connection() as db:
        db.execute("INSERT INTO consultations(created_at,campus,nivel,interests,top_course,top_area,top_score,results_json,student_id,method,riasec_code,low_affinity) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)", (datetime.now(timezone.utc).isoformat(), request.campus, request.nivel, text or '', top.get("nome"), top.get("area_principal"), top.get("score"), json.dumps(results[:10], ensure_ascii=False), student_id, method, riasec_code, int(bool(low_affinity))))

class RecommendationRequest(BaseModel):
    # Opcional quando o estudante já respondeu ao inventário RIASEC.
    interesses: Optional[str] = Field(default=None, max_length=2000)
    usar_riasec: bool = True
    campus: Optional[str] = None
    nivel: Optional[str] = None
    limite: int = Field(default=10, ge=1, le=46)

def load_courses():
    with open(DATA_FILE, encoding='utf-8') as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict):
        raise ValueError('O catálogo deve ser um objeto JSON.')
    items = payload.get('ofertas')
    if not isinstance(items, list) or not items:
        raise ValueError("O JSON precisa conter uma lista não vazia na chave 'ofertas'.")
    ids = set()
    for idx, course in enumerate(items):
        if not isinstance(course, dict):
            raise ValueError(f'Oferta {idx} não é um objeto.')
        for field in ('id_oferta', 'nome', 'campus', 'nivel'):
            if not isinstance(course.get(field), str) or not course[field].strip():
                raise ValueError(f'Oferta {idx}: campo {field} obrigatório.')
        if course['id_oferta'] in ids:
            raise ValueError(f"ID de oferta duplicado: {course['id_oferta']}")
        ids.add(course['id_oferta'])
    return payload, items

def initialize_model_and_embeddings():
    global courses, model, course_vectors, institution_metadata, metrics
    from sentence_transformers import SentenceTransformer
    metadata, loaded_courses = load_courses()
    logger.info('Carregando modelo %s em CPU...', MODEL_NAME)
    loaded_model = SentenceTransformer(MODEL_NAME, device='cpu')
    vectors = {}
    for field in FIELD_WEIGHTS:
        texts = [str(course.get(field) or course.get('nome') or '') for course in loaded_courses]
        encoded = loaded_model.encode(texts, batch_size=16, show_progress_bar=False,
                                      convert_to_numpy=True, normalize_embeddings=True)
        vectors[field] = np.asarray(encoded, dtype=np.float32)
    # Publicação atômica após inicialização completa.
    institution_metadata, courses, course_vectors, model = metadata, loaded_courses, vectors, loaded_model
    if os.getenv('ENABLE_ANONYMOUS_METRICS', 'false').lower() == 'true':
        metrics = AnonymousMetrics(os.getenv('METRICS_DB', str(ROOT / 'runtime' / 'metrics.sqlite3')))
    logger.info('Inicialização concluída: %d ofertas, %d perfis.', len(courses), len({c.get('id_perfil') for c in courses}))

@asynccontextmanager
async def lifespan(app: FastAPI):
    init_management()
    initialize_model_and_embeddings()
    yield

app = FastAPI(title='Recomendador de Cursos do IFS',
              description='Recomendação semântica de ofertas de cursos a partir de interesses em texto livre.',
              version='1.2.0', lifespan=lifespan)
app.mount('/static', StaticFiles(directory=Path(__file__).parent / 'static'), name='static')

@app.get('/', response_class=HTMLResponse)
def home():
    return (Path(__file__).parent / 'index.html').read_text(encoding='utf-8')

@app.get('/health')
def health():
    if model is None:
        raise HTTPException(status_code=503, detail='Modelo ainda não está pronto.')
    return {'status': 'ok', 'device': 'cpu', 'model': MODEL_NAME, 'total_ofertas': len(courses)}

@app.get('/metadata')
def metadata():
    if model is None:
        raise HTTPException(status_code=503, detail='Aplicação ainda inicializando.')
    return {'instituicao': institution_metadata.get('instituicao'),
            'total_ofertas': len(courses),
            'total_perfis': len({c.get('id_perfil') for c in courses}),
            'campi': sorted({c.get('campus') for c in courses if c.get('campus')}),
            'niveis': sorted({c.get('nivel') for c in courses if c.get('nivel')}),
            'modelo': MODEL_NAME, 'dispositivo': 'CPU'}

@app.post('/recommend')
def recommend(request: RecommendationRequest, student=Depends(require_student)):
    if model is None:
        raise HTTPException(status_code=503, detail='Modelo ainda não foi carregado.')
    query = (request.interesses or '').strip()
    if request.interesses is not None and query and len(query) < 5:
        raise HTTPException(status_code=422, detail='Informe uma descrição de interesses mais completa.')
    profile = load_student_profile(student['id']) if request.usar_riasec else None
    if profile and profile_is_flat(profile['pontuacoes']):
        profile = None  # respostas todas iguais não diferenciam cursos
    if not query and not profile:
        raise HTTPException(status_code=422, detail='Descreva seus interesses (pelo menos 5 caracteres) ou responda ao inventário de interesses.')
    if not inference_slots.acquire(blocking=False):
        raise HTTPException(status_code=503, detail='Sistema ocupado. Tente novamente em instantes.', headers={'Retry-After': '2'})
    try:
        query_vector = None
        if query:
            query_vector = np.asarray(model.encode([query], show_progress_bar=False,
                                      convert_to_numpy=True, normalize_embeddings=True)[0], dtype=np.float32)
        results = rank_courses(query_vector, courses, course_vectors, FIELD_WEIGHTS,
                               request.campus, request.nivel, request.limite,
                               riasec_user=profile['pontuacoes'] if profile else None,
                               riasec_courses=riasec_course_profiles() if profile else None,
                               riasec_weight=RIASEC_WEIGHT)
        # Melhor similaridade de TEXTO entre as ofertas filtradas (sem normalização), para saber
        # se algum curso realmente se parece com o que o estudante escreveu.
        best_text = None
        if query_vector is not None:
            best = rank_courses(query_vector, courses, course_vectors, FIELD_WEIGHTS,
                                request.campus, request.nivel, 1)
            best_text = best[0]['score'] if best else None
    except Exception:
        logger.exception('Erro durante a recomendação')
        raise HTTPException(status_code=500, detail='Não foi possível calcular as recomendações.')
    finally:
        inference_slots.release()
    mode = results[0]['metodo'] if results else ('hibrido' if query and profile else 'riasec' if profile else 'texto')
    low_affinity = best_text is not None and best_text < LOW_AFFINITY_THRESHOLD
    try:
        record_consultation(request, results, student["id"], query, mode, profile['codigo'] if profile else None, low_affinity)
    except Exception:
        logger.exception("Falha ao registrar consulta anônima")
    if metrics is not None:
        try:
            metrics.record_search()
        except Exception:
            logger.exception('Não foi possível registrar contador anônimo')
    descriptions = {'texto': 'similaridade de cosseno ponderada',
                    'riasec': 'congruência de perfis RIASEC (correlação)',
                    'hibrido': 'combinação de texto e perfil RIASEC'}
    return {'consulta': query, 'modelo': MODEL_NAME,
            'modo': mode, 'metodo': descriptions[mode],
            'peso_riasec': RIASEC_WEIGHT if mode == 'hibrido' else None,
            'perfil_riasec': {'codigo': profile['codigo'], 'pontuacoes': profile['pontuacoes']} if profile else None,
            'afinidade': {'baixa': low_affinity, 'limiar': LOW_AFFINITY_THRESHOLD,
                          'melhor_similaridade_texto': round(best_text, 4) if best_text is not None else None},
            'observacao': 'O score serve só para ordenar os resultados; não representa probabilidade nem percentual de compatibilidade.',
            'pesos': FIELD_WEIGHTS, 'total_retornado': len(results), 'resultados': results}

class RegisterRequest(BaseModel):
    name: str = Field(min_length=2, max_length=100)
    email: str = Field(min_length=5, max_length=254)
    password: str = Field(min_length=12, max_length=128)
    consent: bool

class LoginRequest(BaseModel):
    email: str
    password: str

@app.post('/api/alunos/cadastro', status_code=201)
def register(payload: RegisterRequest, request: Request, response: FastAPIResponse):
    check_origin(request)
    name, email = payload.name.strip(), payload.email.strip().lower()
    if not payload.consent:
        raise HTTPException(422, 'É necessário aceitar o aviso de privacidade.')
    if len(name) < 2 or not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+', email):
        raise HTTPException(422, 'Nome ou email inválido.')
    if len(payload.password) < 12:
        raise HTTPException(422, 'A senha deve ter pelo menos 12 caracteres.')
    with management_connection() as db:
        try:
            cursor = db.execute('INSERT INTO students(name,email,password_hash,created_at,consent_at) VALUES(?,?,?,?,?)', (name, email, hash_password(payload.password), datetime.now(timezone.utc).isoformat(), datetime.now(timezone.utc).isoformat()))
        except sqlite3.IntegrityError:
            raise HTTPException(409, 'Este email já está cadastrado.')
        token = secrets.token_urlsafe(32)
        db.execute('INSERT INTO student_sessions VALUES(?,?,?)', (session_digest(token), cursor.lastrowid, int(time.time()) + SESSION_SECONDS))
    set_session_cookie(response, token, request)
    return {'name': name, 'email': email}

@app.post('/api/alunos/login')
def login(payload: LoginRequest, request: Request, response: FastAPIResponse):
    check_origin(request)
    email = payload.email.strip().lower()
    key = (email, request.client.host if request.client else '')
    now = time.time()
    with LOGIN_LOCK:
        recent = [t for t in LOGIN_ATTEMPTS.get(key, []) if now - t < 900]
        if len(recent) >= 8:
            raise HTTPException(429, 'Muitas tentativas. Aguarde 15 minutos.')
        LOGIN_ATTEMPTS[key] = recent
    with management_connection() as db:
        row = db.execute('SELECT * FROM students WHERE email=?', (email,)).fetchone()
        if not row or not verify_password(payload.password, row['password_hash']):
            with LOGIN_LOCK:
                LOGIN_ATTEMPTS.setdefault(key, []).append(now)
            raise HTTPException(401, 'Email ou senha inválidos.')
        token = secrets.token_urlsafe(32)
        db.execute('INSERT INTO student_sessions VALUES(?,?,?)', (session_digest(token), row['id'], int(now) + SESSION_SECONDS))
    with LOGIN_LOCK:
        LOGIN_ATTEMPTS.pop(key, None)
    set_session_cookie(response, token, request)
    return {'name': row['name'], 'email': row['email']}

@app.get('/api/alunos/me')
def student_me(student=Depends(require_student)):
    return student

@app.get('/api/alunos/historico')
def student_history(student=Depends(require_student)):
    with management_connection() as db:
        rows = db.execute('SELECT id,created_at,campus,nivel,interests,top_course,top_area,top_score,results_json FROM consultations WHERE student_id=? ORDER BY id DESC LIMIT 100', (student['id'],)).fetchall()
    return [{'id':r['id'], 'data':r['created_at'], 'campus':r['campus'], 'nivel':r['nivel'], 'interesses':r['interests'], 'curso':r['top_course'], 'area':r['top_area'], 'score':r['top_score'], 'resultados':json.loads(r['results_json'])} for r in rows]

@app.post('/api/alunos/logout')
def student_logout(request: Request, response: FastAPIResponse):
    check_origin(request)
    token = request.cookies.get('ifs_session')
    if token:
        with management_connection() as db:
            db.execute('DELETE FROM student_sessions WHERE token_hash=?', (session_digest(token),))
    response.delete_cookie('ifs_session', path='/')
    return {'ok': True}

@app.delete('/api/alunos/conta')
def student_delete(request: Request, response: FastAPIResponse, student=Depends(require_student)):
    check_origin(request)
    with management_connection() as db:
        db.execute('DELETE FROM consultations WHERE student_id=?', (student['id'],))
        db.execute('DELETE FROM course_suggestions WHERE student_id=?', (student['id'],))
        db.execute('DELETE FROM riasec_profiles WHERE student_id=?', (student['id'],))
        db.execute('DELETE FROM student_sessions WHERE student_id=?', (student['id'],))
        db.execute('DELETE FROM students WHERE id=?', (student['id'],))
    response.delete_cookie('ifs_session', path='/')
    return {'ok': True}

def login_rate_limit(key):
    now = time.time()
    with LOGIN_LOCK:
        recent = [t for t in LOGIN_ATTEMPTS.get(key, []) if now - t < 900]
        if len(recent) >= 8:
            raise HTTPException(429, 'Muitas tentativas. Aguarde 15 minutos.')
        LOGIN_ATTEMPTS[key] = recent
    return now

class ManagerLoginRequest(BaseModel):
    username: str = Field(max_length=100)
    password: str = Field(max_length=256)

@app.post('/api/gestao/login')
def manager_login(payload: ManagerLoginRequest, request: Request, response: FastAPIResponse):
    check_origin(request)
    key = ('gestao:' + payload.username.strip().lower(), request.client.host if request.client else '')
    now = login_rate_limit(key)
    if not valid_manager_credentials(payload.username.strip(), payload.password):
        with LOGIN_LOCK:
            LOGIN_ATTEMPTS.setdefault(key, []).append(now)
        raise HTTPException(401, 'Usuário ou senha de gestor inválidos.')
    with LOGIN_LOCK:
        LOGIN_ATTEMPTS.pop(key, None)
    token = secrets.token_urlsafe(32)
    with management_connection() as db:
        db.execute('DELETE FROM manager_sessions WHERE expires_at<=?', (int(now),))
        db.execute('INSERT INTO manager_sessions VALUES(?,?,?)',
                   (session_digest(token), payload.username.strip(), int(now) + MANAGER_SESSION_SECONDS))
    response.set_cookie('ifs_gestao', token, httponly=True, secure=request.url.scheme == 'https',
                        samesite='strict', max_age=MANAGER_SESSION_SECONDS, path='/')
    return {'username': payload.username.strip()}

@app.get('/api/gestao/me')
def manager_me(request: Request):
    username = manager_from_session(request)
    if not username:
        raise HTTPException(401, 'Sessão de gestor inexistente ou expirada.')
    return {'username': username}

@app.post('/api/gestao/logout')
def manager_logout(request: Request, response: FastAPIResponse):
    check_origin(request)
    token = request.cookies.get('ifs_gestao')
    if token:
        with management_connection() as db:
            db.execute('DELETE FROM manager_sessions WHERE token_hash=?', (session_digest(token),))
    response.delete_cookie('ifs_gestao', path='/')
    return {'ok': True}

@app.get('/gestao')
def management_page():
    # A gestão agora é uma aba da interface única.
    return RedirectResponse('/#/gestao', status_code=307)

@app.get('/api/gestao/dashboard', dependencies=[Depends(management_auth)])
def management_dashboard(period: int = 0, campus: str = 'all', nivel: str = 'all', area: str = 'all', search: str = ''):
    if period not in (0, 7, 30, 90, 180, 365):
        raise HTTPException(422, 'Período inválido')
    with management_connection() as db:
        rows = [dict(r) for r in db.execute('SELECT c.*, s.name AS student_name, s.email AS student_email FROM consultations c LEFT JOIN students s ON s.id=c.student_id ORDER BY c.id DESC').fetchall()]
    from datetime import timedelta
    cutoff = (datetime.now(timezone.utc) - timedelta(days=period)).isoformat() if period else None
    if cutoff: rows = [r for r in rows if r['created_at'] >= cutoff]
    if campus != 'all': rows = [r for r in rows if r['campus'] == campus]
    if nivel != 'all': rows = [r for r in rows if r['nivel'] == nivel]
    if area != 'all': rows = [r for r in rows if r['top_area'] == area]
    if search: rows = [r for r in rows if search.casefold() in (r['interests'] + ' ' + (r['top_course'] or '')).casefold()]
    course_counts = Counter()
    for r in rows:
        for result in json.loads(r['results_json']):
            name = result.get('nome')
            if name: course_counts[(name, result.get('campus') or '')] += 1
    return {'total_consultas':len(rows), 'alunos_distintos':len({r['student_id'] for r in rows if r['student_id']}), 'campi':len({r['campus'] for r in rows if r['campus']}), 'cursos_sugeridos':len(course_counts), 'sem_curso_proximo':sum(1 for r in rows if r.get('low_affinity')), 'areas': [{'name':k or 'Não informado','count':v} for k,v in Counter(r['top_area'] for r in rows).most_common()], 'regioes':[{'name':k or 'Não informado','count':v} for k,v in Counter(r['campus'] for r in rows).most_common()], 'evolucao':[{'day':k,'count':v} for k,v in sorted(Counter(r['created_at'][:10] for r in rows).items())], 'cursos':[{'nome':k[0],'campus':k[1], 'count':v} for k,v in course_counts.most_common(30)], 'consultas':[{'id':r['id'],'aluno':r['student_name'] or 'Consulta anterior sem identificação','email':r['student_email'] or '', 'data':r['created_at'],'campus':r['campus'],'nivel':r['nivel'],'interesses':r['interests'],'curso':r['top_course'],'area':r['top_area'],'score':r['top_score'],'metodo':r.get('method') or 'texto','perfil':r.get('riasec_code'),'sem_curso_proximo':bool(r.get('low_affinity')),'resultados':json.loads(r['results_json'])} for r in rows], 'total_ofertas':len(courses), 'catalogo_campi':sorted({c['campus'] for c in courses}), 'catalogo_niveis':sorted({c['nivel'] for c in courses}), 'riasec': riasec_distribution()}

@app.get('/api/gestao/export', dependencies=[Depends(management_auth)])
def management_export(period: int = 0, campus: str = 'all', nivel: str = 'all', area: str = 'all', search: str = ''):
    import csv, io
    data = management_dashboard(period, campus, nivel, area, search)
    output = io.StringIO()
    writer = csv.writer(output, delimiter=';')
    writer.writerow(['ID consulta','Aluno','Email','Data UTC','Campus selecionado','Nível selecionado','Interesses declarados','Primeiro curso recomendado','Área','Score de similaridade'])
    for r in data['consultas']:
        writer.writerow(csv_safe([r['id'],r['aluno'],r['email'],r['data'],r['campus'],r['nivel'],r['interesses'],r['curso'],r['area'],r['score']]))
    return Response(content='\ufeff'+output.getvalue(),media_type='text/csv; charset=utf-8',headers={'Content-Disposition':'attachment; filename="relatorio_gestao_ifs.csv"'})


def csv_safe(values):
    """Evita que textos digitados por estudantes virem fórmulas ao abrir o CSV no Excel."""
    return [("'" + v) if isinstance(v, str) and v[:1] in ('=', '+', '-', '@', '\t', '\r') else v for v in values]


# ---------- Sugestões de novos cursos (estudante -> IFS) ----------

SUGGESTION_LEVELS = ('Técnico Integrado', 'Técnico Subsequente', 'Graduação', 'Pós-graduação', 'Curso livre / FIC', 'Não sei')
SUGGESTIONS_PER_DAY = 10

def normalize_name(text):
    import unicodedata
    plain = unicodedata.normalize('NFD', str(text or '')).encode('ascii', 'ignore').decode()
    return ' '.join(re.sub(r'[^a-z0-9 ]', ' ', plain.casefold()).split())

class SuggestionRequest(BaseModel):
    course_name: str = Field(min_length=3, max_length=120)
    area: Optional[str] = Field(default=None, max_length=80)
    campus: Optional[str] = Field(default=None, max_length=60)
    nivel: Optional[str] = Field(default=None, max_length=40)
    reason: str = Field(min_length=10, max_length=1000)

def suggestion_row(r):
    return {'id': r['id'], 'data': r['created_at'], 'curso': r['course_name'], 'area': r['area'],
            'campus': r['campus'], 'nivel': r['nivel'], 'motivo': r['reason']}

@app.post('/api/alunos/sugestoes', status_code=201)
def create_suggestion(payload: SuggestionRequest, request: Request, student=Depends(require_student)):
    check_origin(request)
    name, reason = ' '.join(payload.course_name.split()), payload.reason.strip()
    if len(name) < 3 or len(reason) < 10:
        raise HTTPException(422, 'Informe o nome do curso e explique em pelo menos 10 caracteres por que ele deveria existir.')
    valid_campi = {c.get('campus') for c in courses}
    campus = payload.campus if payload.campus in valid_campi else None
    nivel = payload.nivel if payload.nivel in SUGGESTION_LEVELS else None
    area = ' '.join((payload.area or '').split()) or None
    since = datetime.now(timezone.utc).date().isoformat()
    with management_connection() as db:
        today = db.execute('SELECT COUNT(*) FROM course_suggestions WHERE student_id=? AND created_at>=?', (student['id'], since)).fetchone()[0]
        if today >= SUGGESTIONS_PER_DAY:
            raise HTTPException(429, f'Você já enviou {SUGGESTIONS_PER_DAY} sugestões hoje. Tente novamente amanhã.')
        cur = db.execute('INSERT INTO course_suggestions(student_id,created_at,course_name,area,campus,nivel,reason) VALUES(?,?,?,?,?,?,?)',
                         (student['id'], datetime.now(timezone.utc).isoformat(), name, area, campus, nivel, reason))
        row = db.execute('SELECT * FROM course_suggestions WHERE id=?', (cur.lastrowid,)).fetchone()
    return suggestion_row(row)

@app.get('/api/alunos/sugestoes')
def list_own_suggestions(student=Depends(require_student)):
    with management_connection() as db:
        rows = db.execute('SELECT * FROM course_suggestions WHERE student_id=? ORDER BY id DESC LIMIT 100', (student['id'],)).fetchall()
    return [suggestion_row(r) for r in rows]

@app.delete('/api/alunos/sugestoes/{suggestion_id}')
def delete_own_suggestion(suggestion_id: int, request: Request, student=Depends(require_student)):
    check_origin(request)
    with management_connection() as db:
        deleted = db.execute('DELETE FROM course_suggestions WHERE id=? AND student_id=?', (suggestion_id, student['id'])).rowcount
    if not deleted:
        raise HTTPException(404, 'Sugestão não encontrada.')
    return {'ok': True}

@app.get('/api/gestao/sugestoes', dependencies=[Depends(management_auth)])
def management_suggestions(period: int = 0, campus: str = 'all', search: str = ''):
    if period not in (0, 7, 30, 90, 180, 365):
        raise HTTPException(422, 'Período inválido')
    from datetime import timedelta
    sql = ('SELECT g.*, s.name AS student_name, s.email AS student_email '
           'FROM course_suggestions g JOIN students s ON s.id=g.student_id WHERE 1=1')
    args = []
    if period:
        sql += ' AND g.created_at>=?'
        args.append((datetime.now(timezone.utc) - timedelta(days=period)).isoformat())
    if campus != 'all':
        sql += ' AND g.campus=?'
        args.append(campus)
    with management_connection() as db:
        rows = [dict(r) for r in db.execute(sql + ' ORDER BY g.id DESC', args).fetchall()]
    if search:
        needle = search.casefold()
        rows = [r for r in rows if needle in (r['course_name'] + ' ' + r['reason'] + ' ' + (r['area'] or '')).casefold()]
    # Agrupa grafias diferentes do mesmo curso ("Enfermagem", "enfermagem ") e indica se ele já existe no catálogo.
    catalog = {}
    for c in courses:
        catalog.setdefault(normalize_name(c.get('nome')), set()).add(c.get('campus'))
    groups = {}
    for r in rows:
        key = normalize_name(r['course_name'])
        g = groups.setdefault(key, {'names': Counter(), 'students': set(), 'campi': Counter(), 'areas': Counter(), 'total': 0})
        g['names'][r['course_name']] += 1
        g['students'].add(r['student_id'])
        g['total'] += 1
        if r['campus']:
            g['campi'][r['campus']] += 1
        if r['area']:
            g['areas'][r['area']] += 1
    ranking = sorted(({
        'curso': g['names'].most_common(1)[0][0],
        'estudantes': len(g['students']),
        'sugestoes': g['total'],
        'campi': [{'name': k, 'count': v} for k, v in g['campi'].most_common(3)],
        'area': g['areas'].most_common(1)[0][0] if g['areas'] else None,
        'ja_ofertado_em': sorted(catalog.get(key, [])),
    } for key, g in groups.items()), key=lambda x: (-x['estudantes'], -x['sugestoes'], x['curso']))
    return {'total_sugestoes': len(rows), 'estudantes': len({r['student_id'] for r in rows}),
            'cursos_distintos': len(groups), 'ranking': ranking[:50],
            'sugestoes': [{**suggestion_row(r), 'aluno': r['student_name'], 'email': r['student_email']} for r in rows]}

@app.get('/api/gestao/sugestoes/export', dependencies=[Depends(management_auth)])
def management_suggestions_export(period: int = 0, campus: str = 'all', search: str = ''):
    import csv, io
    data = management_suggestions(period, campus, search)
    output = io.StringIO()
    writer = csv.writer(output, delimiter=';')
    writer.writerow(['ID', 'Data UTC', 'Aluno', 'Email', 'Curso sugerido', 'Área', 'Campus desejado', 'Nível', 'Motivo'])
    for r in data['sugestoes']:
        writer.writerow(csv_safe([r['id'], r['data'], r['aluno'], r['email'], r['curso'], r['area'],
                                  r['campus'], r['nivel'], r['motivo']]))
    return Response(content='﻿' + output.getvalue(), media_type='text/csv; charset=utf-8',
                    headers={'Content-Disposition': 'attachment; filename="sugestoes_cursos_ifs.csv"'})


# ---------- Inventário de interesses RIASEC ----------

_riasec_cache = {}

def riasec_questionnaire():
    if 'items' not in _riasec_cache:
        with open(RIASEC_ITEMS_FILE, encoding='utf-8') as handle:
            data = json.load(handle)
        ids = [i['id'] for i in data['itens']]
        if len(ids) != len(set(ids)) or any(i['tipo'] not in RIASEC_TYPES for i in data['itens']):
            raise ValueError('Questionário RIASEC inválido: IDs repetidos ou tipo desconhecido.')
        _riasec_cache['items'] = data
    return _riasec_cache['items']

def riasec_course_profiles():
    """Perfil RIASEC por id_perfil. Usa data/riasec_cursos.json; se faltar, deriva do texto do catálogo."""
    if 'courses' not in _riasec_cache:
        profiles = {}
        if Path(RIASEC_COURSES_FILE).exists():
            with open(RIASEC_COURSES_FILE, encoding='utf-8') as handle:
                profiles = {k: v['vetor'] for k, v in json.load(handle)['perfis'].items()}
        for c in courses:
            profiles.setdefault(c.get('id_perfil'), parse_holland_text(c.get('dimensoes_vocacionais', '')))
        _riasec_cache['courses'] = profiles
    return _riasec_cache['courses']

def profile_payload(scores, updated_at):
    return {'pontuacoes': scores, 'codigo': holland_code(scores), 'atualizado_em': updated_at,
            'diferenciado': not profile_is_flat(scores),
            'tipos': {t: RIASEC_NAMES[t] for t in RIASEC_TYPES}}

def load_student_profile(student_id):
    with management_connection() as db:
        row = db.execute('SELECT scores_json, updated_at FROM riasec_profiles WHERE student_id=?', (student_id,)).fetchone()
    return profile_payload(json.loads(row['scores_json']), row['updated_at']) if row else None

def riasec_distribution():
    with management_connection() as db:
        codes = [r['code'] for r in db.execute('SELECT code FROM riasec_profiles').fetchall()]
    counts = Counter(c[0] for c in codes if c)
    return {'perfis': len(codes), 'predominante': [{'tipo': t, 'nome': RIASEC_NAMES[t], 'count': counts.get(t, 0)} for t in RIASEC_TYPES]}

@app.get('/api/riasec/questionario')
def riasec_questionnaire_endpoint():
    data = riasec_questionnaire()
    return {k: data[k] for k in ('versao', 'fonte', 'instrucao', 'escala', 'tipos', 'itens')}

class RiasecAnswers(BaseModel):
    respostas: dict[str, int]

@app.post('/api/alunos/riasec')
def save_riasec(payload: RiasecAnswers, request: Request, student=Depends(require_student)):
    check_origin(request)
    data = riasec_questionnaire()
    values = [e['valor'] for e in data['escala']]
    try:
        scores = profile_from_answers(data['itens'], payload.respostas, min(values), max(values))
    except ValueError as exc:
        raise HTTPException(422, str(exc))
    answers = {i['id']: payload.respostas[i['id']] for i in data['itens']}
    now = datetime.now(timezone.utc).isoformat()
    with management_connection() as db:
        db.execute('INSERT INTO riasec_profiles(student_id,answers_json,scores_json,code,updated_at) VALUES(?,?,?,?,?) '
                   'ON CONFLICT(student_id) DO UPDATE SET answers_json=excluded.answers_json, scores_json=excluded.scores_json, '
                   'code=excluded.code, updated_at=excluded.updated_at',
                   (student['id'], json.dumps(answers), json.dumps(scores), holland_code(scores), now))
    return profile_payload(scores, now)

@app.get('/api/alunos/riasec')
def get_riasec(student=Depends(require_student)):
    profile = load_student_profile(student['id'])
    if not profile:
        raise HTTPException(404, 'Você ainda não respondeu ao inventário de interesses.')
    return profile

@app.delete('/api/alunos/riasec')
def delete_riasec(request: Request, student=Depends(require_student)):
    check_origin(request)
    with management_connection() as db:
        db.execute('DELETE FROM riasec_profiles WHERE student_id=?', (student['id'],))
    return {'ok': True}
