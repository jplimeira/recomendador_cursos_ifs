import json,re,unicodedata,sqlite3
from collections import defaultdict
from pathlib import Path
from django.conf import settings
from django.contrib.auth.models import User
from django.db import transaction
from django.http import FileResponse
from rest_framework.decorators import api_view,permission_classes
from rest_framework.permissions import AllowAny,IsAuthenticated
from rest_framework.response import Response
from rest_framework.authtoken.models import Token

DB=Path(settings.DATABASES['default']['NAME'])
def conn():
 c=sqlite3.connect(DB);c.row_factory=sqlite3.Row;c.execute('PRAGMA foreign_keys=ON');return c
def student_page(request):return FileResponse(open(settings.BASE_DIR/'site'/'index.html','rb'),content_type='text/html')
def management_page(request):return FileResponse(open(settings.BASE_DIR/'site'/'gestao.html','rb'),content_type='text/html')
def normalize(t):return ''.join(c for c in unicodedata.normalize('NFD',str(t or '').lower()) if unicodedata.category(c)!='Mn')
def score(text,terms):
 if not text.strip() or not terms:return 0
 u=normalize(text);tokens=set(re.findall(r'[a-z0-9]{4,}',u));hits=0
 for term in terms:
  t=normalize(term);words=re.findall(r'[a-z0-9]{4,}',t)
  if t in u or any(w in tokens for w in words):hits+=1
 return min(100,round(hits/max(1,min(len(terms),8))*100))
@api_view(['POST'])
@permission_classes([AllowAny])
def register(request):
 username=str(request.data.get('username','')).strip();password=str(request.data.get('password',''))
 if len(username)<3 or len(password)<8:return Response({'erro':'Usuário deve ter 3 caracteres e senha pelo menos 8.'},status=400)
 if User.objects.filter(username=username).exists():return Response({'erro':'Usuário já cadastrado.'},status=400)
 u=User.objects.create_user(username=username,password=password,first_name=str(request.data.get('nome',''))[:150]);return Response({'token':Token.objects.create(user=u).key,'usuario':u.username},status=201)
@api_view(['POST'])
@permission_classes([AllowAny])
def login(request):
 from django.contrib.auth import authenticate
 u=authenticate(username=request.data.get('username'),password=request.data.get('password'))
 if not u:return Response({'erro':'Credenciais inválidas.'},status=401)
 return Response({'token':Token.objects.get_or_create(user=u)[0].key,'usuario':u.username,'gestor':u.is_staff})
@api_view(['GET'])
def me(request):return Response({'usuario':request.user.username,'nome':request.user.first_name,'gestor':request.user.is_staff})
@api_view(['GET'])
@permission_classes([AllowAny])
def catalog(request):
 with conn() as c:
  courses=[dict(r) for r in c.execute('SELECT o.id_oferta,p.nome_curso,p.descricao,p.area_principal,ca.nome campus,n.nome nivel,o.duracao FROM curso_oferta o JOIN curso_perfil p ON p.id_perfil=o.id_perfil JOIN campus ca ON ca.id_campus=o.id_campus JOIN nivel_ensino n ON n.id_nivel=o.id_nivel')]
 return Response({'cursos':courses})
@api_view(['POST'])
def recommend(request):
 data=request.data;fields=['interests','skills','goals']
 if any(not str(data.get(f,'')).strip() for f in fields):return Response({'erro':'Preencha interesses, habilidades e objetivos.'},status=400)
 with conn() as c:
  c.execute('BEGIN IMMEDIATE')
  # Mapeamento persistente do usuário Django para o cadastro de estudante legado.
  c.execute('CREATE TABLE IF NOT EXISTS conta_estudante (id_usuario INTEGER PRIMARY KEY,id_estudante INTEGER NOT NULL UNIQUE REFERENCES estudante(id_estudante))')
  row=c.execute('SELECT id_estudante FROM conta_estudante WHERE id_usuario=?',(request.user.id,)).fetchone()
  if row:student=row['id_estudante'];c.execute('UPDATE estudante SET nome=?,idade=?,cidade=? WHERE id_estudante=?',(request.user.first_name or request.user.username,data.get('age') or None,data.get('city',''),student))
  else:
   student=c.execute('INSERT INTO estudante(nome,idade,cidade) VALUES(?,?,?)',(request.user.first_name or request.user.username,data.get('age') or None,data.get('city',''))).lastrowid
   c.execute('INSERT INTO conta_estudante VALUES(?,?)',(request.user.id,student))
  evaluation=c.execute('INSERT INTO avaliacao_perfil(id_estudante,idade_informada,cidade_informada,hobbies_texto) VALUES(?,?,?,?)',(student,data.get('age') or None,data.get('city',''),data['interests'])).lastrowid
  for dimension,field in [('interesse','interests'),('habilidade','skills'),('objetivo_profissional','goals')]:c.execute('INSERT INTO avaliacao_resposta(id_avaliacao,dimensao,resposta) VALUES(?,?,?)',(evaluation,dimension,data[field]))
  characteristics=defaultdict(lambda:defaultdict(list))
  for r in c.execute('SELECT cc.id_perfil,ch.tipo,ch.nome FROM curso_caracteristica cc JOIN caracteristica ch ON ch.id_caracteristica=cc.id_caracteristica'):
   characteristics[r['id_perfil']][r['tipo']].append(r['nome'])
  courses=c.execute('SELECT o.id_oferta,o.id_perfil,p.nome_curso,p.descricao,p.area_principal,ca.nome campus,n.nome nivel,o.duracao FROM curso_oferta o JOIN curso_perfil p ON p.id_perfil=o.id_perfil JOIN campus ca ON ca.id_campus=o.id_campus JOIN nivel_ensino n ON n.id_nivel=o.id_nivel').fetchall()
  results=[]
  for r in courses:
   item=dict(r)
   if data.get('level') and item['nivel']!=data['level']:continue
   if data.get('campus') and item['campus']!=data['campus']:continue
   ch=characteristics[item['id_perfil']];a=score(data['interests'],ch['interesse']);b=score(data['skills'],ch['habilidade']);d=score(data['goals'],ch['objetivo_profissional'])
   item.update(a=a,b=b,d=d,score=round(.4*a+.3*b+.3*d),caracteristicas=dict(ch));results.append(item)
  results.sort(key=lambda x:(-x['score'],x['nome_curso'],x['campus']))
  for i,item in enumerate(results,1):
   rid=c.execute('INSERT INTO recomendacao(id_avaliacao,id_oferta,posicao,pontuacao_final,justificativa,modelo_ia) VALUES(?,?,?,?,?,?)',(evaluation,item['id_oferta'],i,item['score'],'Correspondência textual ponderada de interesses, habilidades e objetivos.','matching-v1')).lastrowid
   c.execute('INSERT INTO recomendacao_componente VALUES(?,?,?,?)',(rid,item['a'],item['b'],item['d']))
 return Response({'avaliacao_id':evaluation,'resultados':results[:6]})
@api_view(['GET'])
def history(request):
 with conn() as c:
  try:rows=[dict(r) for r in c.execute('SELECT a.id_avaliacao,a.criado_em,r.posicao,r.pontuacao_final,p.nome_curso FROM conta_estudante ce JOIN avaliacao_perfil a ON a.id_estudante=ce.id_estudante JOIN recomendacao r ON r.id_avaliacao=a.id_avaliacao JOIN curso_oferta o ON o.id_oferta=r.id_oferta JOIN curso_perfil p ON p.id_perfil=o.id_perfil WHERE ce.id_usuario=? AND r.posicao<=6 ORDER BY a.id_avaliacao DESC,r.posicao',(request.user.id,))]
  except sqlite3.OperationalError:rows=[]
 return Response({'historico':rows})
@api_view(['GET'])
def summary(request):
 if not request.user.is_staff:return Response({'erro':'Acesso restrito à gestão.'},status=403)
 with conn() as c:
  metrics={'estudantes':c.execute('SELECT count(*) FROM estudante').fetchone()[0],'avaliacoes':c.execute('SELECT count(*) FROM avaliacao_perfil').fetchone()[0],'recomendacoes':c.execute('SELECT count(*) FROM recomendacao').fetchone()[0]}
  top=[dict(r) for r in c.execute('SELECT p.nome_curso,COUNT(*) total FROM recomendacao r JOIN curso_oferta o ON o.id_oferta=r.id_oferta JOIN curso_perfil p ON p.id_perfil=o.id_perfil WHERE r.posicao<=6 GROUP BY p.nome_curso ORDER BY total DESC LIMIT 10')]
  campus=[dict(r) for r in c.execute('SELECT ca.nome campus,COUNT(*) total FROM recomendacao r JOIN curso_oferta o ON o.id_oferta=r.id_oferta JOIN campus ca ON ca.id_campus=o.id_campus WHERE r.posicao<=6 GROUP BY ca.nome ORDER BY total DESC')]
  recentes=[dict(r) for r in c.execute('SELECT e.nome,a.criado_em,COUNT(r.id_recomendacao) recomendacoes FROM avaliacao_perfil a JOIN estudante e ON e.id_estudante=a.id_estudante LEFT JOIN recomendacao r ON r.id_avaliacao=a.id_avaliacao AND r.posicao<=6 GROUP BY a.id_avaliacao ORDER BY a.id_avaliacao DESC LIMIT 20')]
 return Response({'metricas':metrics,'cursos':top,'campi':campus,'recentes':recentes})

@api_view(['GET'])
def management_analysis(request):
 if not request.user.is_staff:return Response({'erro':'Acesso restrito à gestão.'},status=403)
 from datetime import datetime,timedelta
 period=str(request.query_params.get('period','365'))
 period=int(period) if period in ('0','30','90','365') else 365
 area=str(request.query_params.get('area',''))[:150]
 city=str(request.query_params.get('city',''))[:150]
 level=str(request.query_params.get('level',''))[:150]
 with conn() as c:
  # Contagens de estudantes e avaliações são distintas das recomendações.
  filters=[];args=[]
  if period:
   filters.append('date(a.criado_em)>=date(?)');args.append((datetime.now()-timedelta(days=period)).date().isoformat())
  if city:filters.append('a.cidade_informada=?');args.append(city)
  where=(' WHERE '+' AND '.join(filters)) if filters else ''
  evaluations=[dict(r) for r in c.execute('SELECT a.id_avaliacao,a.id_estudante,a.criado_em,a.cidade_informada FROM avaliacao_perfil a'+where,args)]
  evaluation_ids=[x['id_avaliacao'] for x in evaluations]
  allowed=set(evaluation_ids)
  raw=[dict(r) for r in c.execute('''SELECT r.id_avaliacao,r.posicao,p.nome_curso,p.area_principal area,n.nome nivel,ca.nome campus FROM recomendacao r JOIN curso_oferta o ON o.id_oferta=r.id_oferta JOIN curso_perfil p ON p.id_perfil=o.id_perfil JOIN nivel_ensino n ON n.id_nivel=o.id_nivel JOIN campus ca ON ca.id_campus=o.id_campus WHERE r.posicao<=6''')]
  recs=[r for r in raw if r['id_avaliacao'] in allowed and (not area or r['area']==area) and (not level or r['nivel']==level)]
  selected_ids={r['id_avaliacao'] for r in recs} if (area or level) else allowed
  selected=[e for e in evaluations if e['id_avaliacao'] in selected_ids]
  from collections import Counter
  course_counts=Counter((r['nome_curso'],r['area'] or 'Não informada',r['nivel'],r['campus']) for r in recs)
  courses=[{'nome_curso':k[0],'area':k[1],'nivel':k[2],'campus':k[3],'total':v} for k,v in course_counts.most_common(25)]
  areas=Counter(r['area'] or 'Não informada' for r in recs)
  cities=Counter((e['cidade_informada'] or '').strip() for e in selected if (e['cidade_informada'] or '').strip())
  month_counts=Counter(e['criado_em'][:7] for e in selected)
  now=datetime.now();months=[]
  for offset in range(11,-1,-1):
   y=now.year; m=now.month-offset
   while m<=0:y-=1;m+=12
   months.append({'mes':f'{y:04d}-{m:02d}','total':month_counts[f'{y:04d}-{m:02d}']})
  filters_available={'areas':[r[0] for r in c.execute('SELECT DISTINCT area_principal FROM curso_perfil WHERE area_principal IS NOT NULL AND area_principal != "" ORDER BY 1')], 'cidades':[r[0] for r in c.execute('SELECT DISTINCT cidade_informada FROM avaliacao_perfil WHERE cidade_informada IS NOT NULL AND cidade_informada != "" ORDER BY 1')], 'niveis':[r[0] for r in c.execute('SELECT nome FROM nivel_ensino ORDER BY nome')]}
 return Response({'metricas':{'estudantes':len({e['id_estudante'] for e in selected}),'avaliacoes':len(selected),'areas':len(areas),'cidades':len(cities),'recomendacoes':len(recs)},'areas':[{'area':k,'total':v} for k,v in areas.most_common(15)],'cidades':[{'cidade':k,'total':v} for k,v in cities.most_common(30)],'evolucao':months,'cursos':courses,'filtros':filters_available})

@api_view(['GET'])
def demo_page(request):
 if not request.user.is_staff:
  return Response({'erro':'Acesso restrito à gestão.'},status=403)
 return FileResponse(open(settings.BASE_DIR / 'site' / 'gestao_demo.html','rb'),content_type='text/html; charset=utf-8')

@api_view(['GET'])
def management_students(request):
 if not request.user.is_staff:return Response({'erro':'Acesso restrito à gestão.'},status=403)
 with conn() as c:
  rows=[dict(r) for r in c.execute('''SELECT e.id_estudante,e.nome,e.idade,e.cidade,a.id_avaliacao,a.criado_em,a.hobbies_texto,
   (SELECT resposta FROM avaliacao_resposta WHERE id_avaliacao=a.id_avaliacao AND dimensao='habilidade' LIMIT 1) habilidades,
   (SELECT resposta FROM avaliacao_resposta WHERE id_avaliacao=a.id_avaliacao AND dimensao='objetivo_profissional' LIMIT 1) objetivos,
   (SELECT p.nome_curso FROM recomendacao r JOIN curso_oferta o ON o.id_oferta=r.id_oferta JOIN curso_perfil p ON p.id_perfil=o.id_perfil WHERE r.id_avaliacao=a.id_avaliacao ORDER BY r.posicao LIMIT 1) curso,
   (SELECT pontuacao_final FROM recomendacao r WHERE r.id_avaliacao=a.id_avaliacao ORDER BY r.posicao LIMIT 1) pontuacao
   FROM estudante e LEFT JOIN avaliacao_perfil a ON a.id_estudante=e.id_estudante ORDER BY e.nome,a.id_avaliacao DESC''')]
 return Response({'alunos':rows})


# Ponte HTTP: a interface Django utiliza o motor semântico FastAPI.
# O navegador nunca precisa acessar diretamente o contêiner da IA.
import os
import urllib.request
import urllib.error
from rest_framework.exceptions import ValidationError

IA_API_URL = os.environ.get('IFS_IA_API_URL', 'http://127.0.0.1:8000').rstrip('/')

def ia_request(path, payload=None):
    headers = {'Accept': 'application/json'}
    data = None
    if payload is not None:
        data = json.dumps(payload, ensure_ascii=False).encode('utf-8')
        headers['Content-Type'] = 'application/json'
    request = urllib.request.Request(IA_API_URL + path, data=data, headers=headers,
                                     method='POST' if payload is not None else 'GET')
    try:
        with urllib.request.urlopen(request, timeout=90) as response:
            return json.load(response)
    except urllib.error.HTTPError as exc:
        try:
            detail = json.loads(exc.read().decode('utf-8')).get('detail', 'Erro na API de IA.')
        except (ValueError, UnicodeDecodeError):
            detail = 'Erro na API de IA.'
        raise ValidationError({'erro': str(detail)})
    except (urllib.error.URLError, TimeoutError) as exc:
        raise ConnectionError('A API de inteligência artificial está indisponível. Verifique se o serviço está em execução.') from exc

@api_view(['GET'])
@permission_classes([AllowAny])
def ia_metadata(request):
    try:
        return Response(ia_request('/metadata'))
    except ConnectionError as exc:
        return Response({'erro': str(exc)}, status=503)

@api_view(['POST'])
@permission_classes([AllowAny])
def ia_recommend(request):
    data = request.data
    # A interface simplificada envia um texto livre, exatamente como a API de IA espera.
    # Os três campos antigos continuam aceitos para não quebrar consumidores existentes.
    description = str(data.get('description') or '').strip()
    interests = str(data.get('interests') or '').strip()
    skills = str(data.get('skills') or '').strip()
    goals = str(data.get('goals') or '').strip()
    if description:
        text = description
    elif all((interests, skills, goals)):
        text = f'Interesses e hobbies: {interests}. Habilidades: {skills}. Objetivos profissionais: {goals}.'
    else:
        return Response({'erro': 'Descreva seus interesses, habilidades e objetivos.'}, status=400)
    if len(text) < 5:
        return Response({'erro': 'A descrição deve ter pelo menos 5 caracteres.'}, status=400)
    if len(text) > 12000:
        return Response({'erro': 'A descrição é longa demais (máximo 12.000 caracteres).'}, status=400)
    query = {'interesses': text, 'campus': data.get('campus') or None,
             'nivel': data.get('level') or None, 'limite': 6}
    try:
        result = ia_request('/recommend', query)
    except ConnectionError as exc:
        return Response({'erro': str(exc)}, status=503)
    # Salva as recomendações reais para que a gestão possa acompanhar os resultados.
    # A coluna legada aceita 0..100: registramos o cosseno * 100 para armazenamento,
    # sem interpretar esse número como probabilidade ou compatibilidade validada.
    with conn() as c:
        c.execute('BEGIN IMMEDIATE')
        name = str(data.get('name') or '').strip()[:150] or 'Visitante'
        city = str(data.get('city') or '').strip()[:150]
        raw_age = str(data.get('age') or '').strip()
        age = int(raw_age) if raw_age.isdigit() and 0 <= int(raw_age) <= 120 else None
        student = c.execute('INSERT INTO estudante(nome,idade,cidade) VALUES(?,?,?)',
                            (name, age, city)).lastrowid
        evaluation = c.execute('INSERT INTO avaliacao_perfil(id_estudante,idade_informada,cidade_informada,hobbies_texto) VALUES(?,?,?,?)',
                               (student, age, city, text)).lastrowid
        respostas = (('interesse', text),) if description else (('interesse', interests), ('habilidade', skills), ('objetivo_profissional', goals))
        for dimension, text_value in respostas:
            c.execute('INSERT INTO avaliacao_resposta(id_avaliacao,dimensao,resposta) VALUES(?,?,?)',
                      (evaluation, dimension, text_value))
        for i, item in enumerate(result.get('resultados', []), 1):
            match = c.execute('SELECT 1 FROM curso_oferta WHERE id_oferta=?',(item.get('id_oferta'),)).fetchone()
            if not match:
                continue
            value = max(0.0, min(100.0, float(item.get('score') or 0) * 100))
            recid = c.execute('INSERT INTO recomendacao(id_avaliacao,id_oferta,posicao,pontuacao_final,justificativa,modelo_ia) VALUES(?,?,?,?,?,?)',
                              (evaluation,item['id_oferta'],i,value,
                               'Similaridade semântica ponderada; valor armazenado em escala 0 a 100, não é probabilidade.',
                               result.get('modelo','sentence-transformers'))).lastrowid
            c.execute('INSERT INTO recomendacao_componente(id_recomendacao,pontuacao_interesses,pontuacao_habilidades,pontuacao_objetivos) VALUES(?,?,?,?)',
                      (recid,0,0,0))
    result['avaliacao_id'] = evaluation
    return Response(result)
