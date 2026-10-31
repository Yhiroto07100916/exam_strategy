from __future__ import annotations
import io, json, sqlite3, uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
import pandas as pd
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from pypdf import PdfReader
ROOT=Path(__file__).resolve().parents[1]
DATA=ROOT/'data'; WEB=ROOT/'web'
DB=DATA/'exam_strategy.sqlite3'
SUBJECTS=['国語','数学','英語','理科','社会']
app=FastAPI(title='Exam Strategy API',version='1.0.0')
def db():
 DATA.mkdir(exist_ok=True); c=sqlite3.connect(DB); c.row_factory=sqlite3.Row
 c.execute('CREATE TABLE IF NOT EXISTS scores(id TEXT PRIMARY KEY,date TEXT NOT NULL,exam_name TEXT NOT NULL,exam_type TEXT NOT NULL,subject TEXT NOT NULL,score REAL NOT NULL,max_score REAL NOT NULL,deviation REAL,rank INTEGER,examinees INTEGER,created_at TEXT NOT NULL)')
 c.execute('CREATE TABLE IF NOT EXISTS questions(id TEXT PRIMARY KEY,date TEXT,exam_name TEXT,subject TEXT NOT NULL,unit TEXT NOT NULL,correct INTEGER NOT NULL,points REAL,earned_points REAL)')
 c.execute('CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY,value TEXT NOT NULL)'); c.commit(); return c
class Score(BaseModel):
 date:str; exam_name:str=Field(min_length=1); exam_type:str='模試'; subject:str
 score:float=Field(ge=0); max_score:float=Field(gt=0); deviation:float|None=None; rank:int|None=None; examinees:int|None=None
class Question(BaseModel):
 date:str|None=None; exam_name:str|None=None; subject:str; unit:str; correct:bool; points:float|None=None; earned_points:float|None=None
class Settings(BaseModel): profile:dict[str,Any]={}; target:dict[str,Any]={}
@app.on_event('startup')
def startup():
 c=db(); c.close()
@app.get('/api/health')
def health(): return {'status':'ok','version':app.version}
@app.get('/api/scores')
def scores():
 c=db(); rows=c.execute('SELECT * FROM scores ORDER BY date DESC,created_at DESC').fetchall(); c.close(); return [dict(x) for x in rows]
@app.post('/api/scores',status_code=201)
def add_score(x:Score):
 if x.subject not in SUBJECTS or x.score>x.max_score: raise HTTPException(422,'科目または得点の範囲を確認してください')
 d=x.model_dump(); d['id']=str(uuid.uuid4()); d['created_at']=datetime.now(timezone.utc).isoformat()
 c=db(); c.execute('INSERT INTO scores VALUES(?,?,?,?,?,?,?,?,?,?,?)',tuple(d[k] for k in ['id','date','exam_name','exam_type','subject','score','max_score','deviation','rank','examinees','created_at'])); c.commit(); c.close(); return d
@app.delete('/api/scores/{item_id}',status_code=204)
def delete_score(item_id:str):
 c=db(); cur=c.execute('DELETE FROM scores WHERE id=?',(item_id,)); c.commit(); c.close()
 if not cur.rowcount: raise HTTPException(404,'成績が見つかりません')
@app.get('/api/questions')
def questions():
 c=db(); rows=c.execute('SELECT * FROM questions ORDER BY date DESC').fetchall(); c.close(); return [dict(x) for x in rows]
@app.post('/api/questions',status_code=201)
def add_question(x:Question):
 d=x.model_dump(); d['id']=str(uuid.uuid4()); d['correct']=int(d['correct']); c=db(); c.execute('INSERT INTO questions VALUES(?,?,?,?,?,?,?,?)',tuple(d[k] for k in ['id','date','exam_name','subject','unit','correct','points','earned_points'])); c.commit(); c.close(); return d
@app.get('/api/settings')
def get_settings():
 c=db(); rows=c.execute('SELECT key,value FROM settings').fetchall(); c.close(); d={x['key']:json.loads(x['value']) for x in rows}; return {'profile':d.get('profile',{}),'target':d.get('target',{})}
@app.put('/api/settings')
def put_settings(x:Settings):
 c=db()
 for k,v in x.model_dump().items(): c.execute('INSERT INTO settings VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value',(k,json.dumps(v,ensure_ascii=False)))
 c.commit(); c.close(); return x.model_dump()
@app.get('/api/analysis')
def analysis():
 c=db(); s=pd.read_sql_query('SELECT * FROM scores ORDER BY date,created_at',c); q=pd.read_sql_query('SELECT * FROM questions',c); rows=c.execute('SELECT key,value FROM settings').fetchall(); c.close(); cfg={r['key']:json.loads(r['value']) for r in rows}
 if s.empty:return {'summary':[],'weak_units':[],'latest_exam':None,'target_gaps':[]}
 s['rate']=s.score/s.max_score*100; summary=[]
 for subject,g in s.groupby('subject'):
  z=g.iloc[-1]; summary.append({'subject':subject,'count':len(g),'average_rate':round(g.rate.mean(),1),'latest_score':z.score,'latest_max':z.max_score,'latest_rate':round(z.rate,1),'latest_deviation':None if pd.isna(z.deviation) else z.deviation})
 last=s[s.date==s.date.max()]; latest={'date':str(last.iloc[-1].date),'name':str(last.iloc[-1].exam_name),'total':float(last.score.sum()),'max_total':float(last.max_score.sum()),'rate':round(float(last.score.sum()/last.max_score.sum()*100),1)}
 weak=[]
 if not q.empty:
  for (sub,unit),g in q.groupby(['subject','unit']):
   p=g.points.fillna(0).sum(); e=g.earned_points.fillna(0).sum(); rate=e/p*100 if p else g.correct.mean()*100; weak.append({'subject':sub,'unit':unit,'questions':len(g),'accuracy':round(float(rate),1)})
 weak.sort(key=lambda x:x['accuracy']); target=cfg.get('target',{}).get('subjects',{}); gaps=[]
 for x in summary:
  goal=target.get(x['subject'],{}).get('target_score')
  if goal is not None:gaps.append({'subject':x['subject'],'current':x['latest_score'],'target':goal,'gap':round(float(goal)-x['latest_score'],1)})
 return {'summary':summary,'weak_units':weak,'latest_exam':latest,'target_gaps':gaps}
@app.post('/api/import/table')
async def import_table(file:UploadFile=File(...)):
 b=await file.read(); n=(file.filename or '').lower()
 try:
  f=pd.read_excel(io.BytesIO(b)) if n.endswith(('.xlsx','.xls')) else pd.read_csv(io.BytesIO(b),encoding='utf-8-sig')
 except Exception as e: raise HTTPException(400,'ファイルを読み込めません: '+str(e))
 if not {'subject','score','max_score'}.issubset(f.columns):raise HTTPException(422,'subject, score, max_score列が必要です')
 count=0; errors=[]
 for i,r in f.iterrows():
  try:
   add_score(Score(date=str(r.get('date',datetime.now().date().isoformat()))[:10],exam_name=str(r.get('exam_name',Path(file.filename or '取り込み').stem)),exam_type=str(r.get('exam_type','模試')),subject=str(r.subject),score=float(r.score),max_score=float(r.max_score),deviation=None if pd.isna(r.get('deviation')) else float(r.deviation))) ; count+=1
  except Exception as e:errors.append({'row':int(i)+2,'error':str(e)})
 return {'imported':count,'errors':errors}
@app.post('/api/import/pdf')
async def import_pdf(file:UploadFile=File(...)):
 try: pages=PdfReader(io.BytesIO(await file.read())).pages; texts=[p.extract_text() or '' for p in pages]
 except Exception as e:raise HTTPException(400,'PDFを読み込めません: '+str(e))
 return {'pages':len(texts),'text':'\n\n'.join('--- '+str(i+1)+'ページ ---\n'+t for i,t in enumerate(texts)),'needs_ocr':not any(t.strip() for t in texts)}
@app.get('/api/reports/excel')
def report():
 c=db(); s=pd.read_sql_query('SELECT date,exam_name,exam_type,subject,score,max_score,deviation,rank,examinees FROM scores ORDER BY date',c); q=pd.read_sql_query('SELECT date,exam_name,subject,unit,correct,points,earned_points FROM questions',c); c.close(); out=io.BytesIO()
 with pd.ExcelWriter(out,engine='openpyxl') as w:
  s.to_excel(w,sheet_name='成績データ',index=False); q.to_excel(w,sheet_name='問題別データ',index=False)
  if not s.empty:
   s['得点率']=s.score/s.max_score*100; s.groupby('subject')['得点率'].agg(['count','mean','max','min']).round(1).to_excel(w,sheet_name='科目分析')
 out.seek(0); return StreamingResponse(out,media_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',headers={'Content-Disposition':'attachment; filename=exam_strategy_report.xlsx'})
if WEB.exists():app.mount('/',StaticFiles(directory=WEB,html=True),name='web')
