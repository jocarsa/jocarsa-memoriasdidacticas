#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import argparse, hashlib, re, sqlite3, unicodedata
from pathlib import Path
import pandas as pd

def norm(v):
    if v is None: return ''
    try:
        if pd.isna(v): return ''
    except Exception: pass
    return re.sub(r'\s+',' ',str(v).strip())
def strip(s): return ''.join(c for c in unicodedata.normalize('NFKD',s) if not unicodedata.combining(c))
def key(v): return re.sub(r'\s+',' ',re.sub(r'[^a-z0-9]+',' ',strip(norm(v).lower()))).strip()
def slug(v): return re.sub(r'-+','-',re.sub(r'[^a-z0-9]+','-',strip(v).lower())).strip('-') or 'sin-nombre'
def skey(name): return hashlib.sha1(key(name).encode()).hexdigest()
def sha(p): return 'sha256$'+hashlib.sha256(p.encode()).hexdigest()

def parse_grade(v):
    t=norm(v).upper().replace(',','.')
    if t=='': return None
    if t in {'NP','N/P','NO PRESENTADO','NO PRESENTADA','NC','N/C','NO CALIFICADO','NO CALIFICADA'}: return 0.0
    if t in {'NE','N.E.','-'}: return None
    if isinstance(v,(int,float)) and not isinstance(v,bool):
        n=float(v); return round(n,2) if 0<=n<=10 else None
    m=re.search(r'[-+]?\d+(?:\.\d+)?',t)
    if not m: return None
    n=float(m.group(0)); return round(n,2) if 0<=n<=10 else None

def read(path):
    if path.suffix.lower()=='.xls': return pd.read_excel(path,sheet_name=None,header=None,engine='xlrd')
    if path.suffix.lower()=='.xlsx': return pd.read_excel(path,sheet_name=None,header=None,engine='openpyxl')
    return {f'table_{i+1}':df for i,df in enumerate(pd.read_html(path))}
def sheet(sheets,wanted):
    for n,df in sheets.items():
        if key(n)==key(wanted): return df
    for n,df in sheets.items():
        if key(wanted) in key(n): return df
    return None
def data_sheet(sheets):
    e=sheet(sheets,'Extra')
    return ('Extra',e) if e is not None else max(sheets.items(),key=lambda x:x[1].shape[0]*x[1].shape[1])
def full_name(sheets):
    info=sheet(sheets,'Info')
    if info is None: return ''
    for _,row in info.iterrows():
        cells=[norm(x) for x in row.tolist()]; keys=[key(x) for x in cells]
        for i,k in enumerate(keys):
            if 'materia' in k or 'modulo' in k or 'asignatura' in k:
                for j in range(i+1,len(cells)):
                    if cells[j]: return cells[j]
    return ''
def headers(df):
    rg=rc=rd=sc=-1
    for r in range(min(15,len(df))):
        vals=[key(v) for v in df.iloc[r].tolist()]
        if 'nombre' in vals: sc=vals.index('nombre')
        joined=' '.join(vals)
        if any(x in joined for x in ['primera evaluacion','segunda evaluacion','tercera evaluacion','evaluacion final','notas finales']): rg=r
        if any(x in vals for x in ['fna','nta','fn']): rc=r
        if ('final' in vals or 'nota' in vals or 'recuperacion' in vals) and r>rc: rd=r
    if sc<0: raise RuntimeError('No se encontró columna Nombre')
    if rg<0 or rc<0: raise RuntimeError('No se encontraron cabeceras de evaluación')
    return rg,rc,rd if rd>=0 else rc,sc
def groups(df,rg):
    cur=''; out={}
    for c in range(df.shape[1]):
        x=norm(df.iat[rg,c])
        if x: cur=x
        out[c]=cur
    return out
def score(group,code,desc,target):
    g,c,d=key(group),key(code),key(desc); s=0
    if target=='I' and 'primera evaluacion' in g: s+=100
    if target=='II' and 'segunda evaluacion' in g: s+=100
    if target=='III' and 'tercera evaluacion' in g: s+=100
    if target=='F' and 'evaluacion final' in g: s+=100
    elif target=='F' and 'notas finales' in g: s+=80
    if target=='E' and 'notas finales' in g: s+=100
    if c in {'fna','fn'}: s+=40
    elif d.startswith('final'): s+=35
    elif c=='nta' or d=='nota': s+=10
    elif c=='rca' or 'recuperacion' in d: s-=30
    return s
def detect(df):
    rg,rc,rd,sc=headers(df); gs=groups(df,rg); cols={}
    for target in ['I','II','III','F','E']:
        best=(-999,None)
        for c in range(df.shape[1]):
            ss=score(gs.get(c,''),norm(df.iat[rc,c]),norm(df.iat[rd,c]),target)
            if ss>best[0]: best=(ss,c)
        cols[target]=best[1] if best[0]>0 else None
    if cols['F'] is None: cols['F']=cols['III'] or cols['II'] or cols['I']
    return sc,cols,rd
def first_row(df,sc,after):
    for r in range(after,len(df)):
        name=norm(df.iat[r,sc])
        if len(name)>=3 and key(name) not in {'nombre','alumno','nan'} and any(ch.isalpha() for ch in name): return r
    return len(df)
def extract(path):
    sheets=read(path); _,df=data_sheet(sheets); sc,cols,rd=detect(df); start=first_row(df,sc,rd); rows=[]
    for r in range(start,len(df)):
        name=norm(df.iat[r,sc])
        if not name or key(name) in {'nan','nombre','total','media','promedio'}: continue
        row={'student_fullname':name,'student_key':skey(name)}
        for ev in ['I','II','III','F','E']: row[ev]=parse_grade(df.iat[r,cols[ev]]) if cols.get(ev) is not None else None
        row['O']=row['F']
        if not all(row[ev] is None for ev in ['I','II','III','F','O','E']): rows.append(row)
    return slug(path.stem),full_name(sheets),rows,cols

def conn(db):
    c=sqlite3.connect(db); c.row_factory=sqlite3.Row; c.execute('PRAGMA foreign_keys=ON'); return c
def init(c):
    c.executescript('''
    CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY AUTOINCREMENT,username TEXT NOT NULL UNIQUE,display_name TEXT,password_hash TEXT,role TEXT NOT NULL DEFAULT 'teacher',is_active INTEGER NOT NULL DEFAULT 1,created_at TEXT DEFAULT CURRENT_TIMESTAMP,updated_at TEXT DEFAULT CURRENT_TIMESTAMP);
    CREATE TABLE IF NOT EXISTS subjects(id INTEGER PRIMARY KEY AUTOINCREMENT,teacher_id INTEGER NOT NULL,slug TEXT NOT NULL UNIQUE,full_name TEXT,source_filename TEXT,created_at TEXT DEFAULT CURRENT_TIMESTAMP,updated_at TEXT DEFAULT CURRENT_TIMESTAMP,FOREIGN KEY(teacher_id) REFERENCES users(id) ON DELETE CASCADE);
    CREATE TABLE IF NOT EXISTS students(id INTEGER PRIMARY KEY AUTOINCREMENT,student_key TEXT NOT NULL UNIQUE,full_name TEXT NOT NULL,created_at TEXT DEFAULT CURRENT_TIMESTAMP,updated_at TEXT DEFAULT CURRENT_TIMESTAMP);
    CREATE TABLE IF NOT EXISTS grades(id INTEGER PRIMARY KEY AUTOINCREMENT,student_id INTEGER NOT NULL,subject_id INTEGER NOT NULL,I REAL,II REAL,III REAL,F REAL,O REAL,E REAL,created_at TEXT DEFAULT CURRENT_TIMESTAMP,updated_at TEXT DEFAULT CURRENT_TIMESTAMP,UNIQUE(student_id,subject_id),FOREIGN KEY(student_id) REFERENCES students(id) ON DELETE CASCADE,FOREIGN KEY(subject_id) REFERENCES subjects(id) ON DELETE CASCADE);
    CREATE TABLE IF NOT EXISTS import_log(id INTEGER PRIMARY KEY AUTOINCREMENT,source_filename TEXT NOT NULL UNIQUE,subject_slug TEXT,rows_imported INTEGER DEFAULT 0,status TEXT NOT NULL,message TEXT,imported_at TEXT DEFAULT CURRENT_TIMESTAMP);
    CREATE TABLE IF NOT EXISTS teaching_memory(id INTEGER PRIMARY KEY AUTOINCREMENT,subject_id INTEGER NOT NULL UNIQUE,cycle TEXT,professional_module TEXT,academic_year TEXT,responsible_teacher TEXT,programming_units TEXT,planned_timing TEXT,actual_timing TEXT,timing_modifications TEXT,developed_activities TEXT,used_resources TEXT,first_evaluation TEXT,second_evaluation TEXT,third_evaluation TEXT,ordinary_evaluation TEXT,extraordinary_evaluation TEXT,detected_difficulties TEXT,relevant_incidents TEXT,diversity_measures TEXT,teaching_practice_assessment TEXT,improvement_proposals TEXT,complementary_activities TEXT,closing_text TEXT,created_at TEXT DEFAULT CURRENT_TIMESTAMP,updated_at TEXT DEFAULT CURRENT_TIMESTAMP,FOREIGN KEY(subject_id) REFERENCES subjects(id) ON DELETE CASCADE);
    ''')
    c.execute("INSERT INTO users(username,display_name,password_hash,role,is_active) VALUES('jocarsa','Jocarsa',?,'admin',1) ON CONFLICT(username) DO UPDATE SET role='admin',is_active=1,password_hash=COALESCE(users.password_hash,excluded.password_hash)",(sha('jocarsa'),))
def choose_user(c,arg):
    if arg:
        u=c.execute('SELECT id FROM users WHERE username=?',(arg,)).fetchone()
        if not u: raise RuntimeError(f'No existe usuario {arg}')
        return int(u['id'])
    users=c.execute('SELECT id,username,display_name,role FROM users WHERE is_active=1 ORDER BY username').fetchall()
    print('\nUsuarios disponibles:')
    for i,u in enumerate(users,1): print(f"{i}. {u['username']} ({u['display_name'] or ''}) [{u['role']}]")
    return int(users[int(input('Selecciona usuario para adjuntar asignaturas: '))-1]['id'])
def import_file(c,teacher,path):
    sl,fn,rows,cols=extract(path)
    c.execute('INSERT INTO subjects(teacher_id,slug,full_name,source_filename) VALUES(?,?,?,?) ON CONFLICT(slug) DO UPDATE SET teacher_id=excluded.teacher_id,full_name=excluded.full_name,source_filename=excluded.source_filename,updated_at=CURRENT_TIMESTAMP',(teacher,sl,fn,path.name))
    sid=c.execute('SELECT id FROM subjects WHERE slug=?',(sl,)).fetchone()['id']
    for r in rows:
        c.execute('INSERT INTO students(student_key,full_name) VALUES(?,?) ON CONFLICT(student_key) DO UPDATE SET full_name=excluded.full_name,updated_at=CURRENT_TIMESTAMP',(r['student_key'],r['student_fullname']))
        st=c.execute('SELECT id FROM students WHERE student_key=?',(r['student_key'],)).fetchone()['id']
        c.execute('INSERT INTO grades(student_id,subject_id,I,II,III,F,O,E) VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(student_id,subject_id) DO UPDATE SET I=excluded.I,II=excluded.II,III=excluded.III,F=excluded.F,O=excluded.O,E=excluded.E,updated_at=CURRENT_TIMESTAMP',(st,sid,r['I'],r['II'],r['III'],r['F'],r['O'],r['E']))
    c.execute("INSERT INTO import_log(source_filename,subject_slug,rows_imported,status,message) VALUES(?,?,?,'ok','') ON CONFLICT(source_filename) DO UPDATE SET subject_slug=excluded.subject_slug,rows_imported=excluded.rows_imported,status='ok',message='',imported_at=CURRENT_TIMESTAMP",(path.name,sl,len(rows)))
    print(f'{path.name}: {len(rows)} filas -> {sl}')
def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--input-dir',default='.'); ap.add_argument('--db',default='grades.sqlite'); ap.add_argument('--user'); ap.add_argument('--reset',action='store_true'); args=ap.parse_args()
    db=Path(args.db).resolve()
    if args.reset and db.exists(): db.unlink()
    c=conn(db); init(c); teacher=choose_user(c,args.user)
    files=[p for p in sorted(Path(args.input_dir).iterdir()) if p.suffix.lower() in {'.xls','.xlsx','.html','.htm'} and not p.name.startswith('~$')]
    for p in files:
        with c: import_file(c,teacher,p)
    print('\nOK');
    for t in ['users','subjects','students','grades']: print(t,c.execute(f'SELECT COUNT(*) n FROM {t}').fetchone()['n'])
if __name__=='__main__': raise SystemExit(main())
