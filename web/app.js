const $=s=>document.querySelector(s),queryAll=s=>[...document.querySelectorAll(s)],examMode=localStorage.getItem('examMode')==='university'?'university':'high_school';let subjects=examMode==='university'?['国語','英語','英語リーディング','英語リスニング','数学IA','数学IIBC','数学III','物理','化学','生物','地学','地理総合・地理探究','歴史総合・日本史探究','歴史総合・世界史探究','公共・政治経済','情報I','小論文','面接']:['国語','数学','英語','理科','社会'];let scores=[],questions=[],analysis={},settings={profile:{},target:{}},ocrCandidates=[],activeSchoolAllocation=null,importPreview=null,importPage=0;const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));function allocationFields(){const bySubject=Object.fromEntries((analysis.summary||[]).map(x=>[x.subject,x]));const configuredTargets=Object.entries(settings.target?.subjects||{}).filter(([,value])=>value?.target_score!==null&&value?.target_score!==undefined&&value?.target_score!=='').map(([subject])=>subject);const configured=new Set([...configuredTargets,...Object.keys(bySubject)]);$('#allocation-subjects').innerHTML=subjects.map(s=>{const x=bySubject[s]||{};const enabled=examMode==='high_school'||configured.has(s);return '<div class="allocation-row"><label class="allocation-toggle"><input type="checkbox" data-alloc-enabled="'+esc(s)+'" '+(enabled?'checked':'')+'> 配分対象</label><label>現在点<input type="number" min="0" step="0.1" data-alloc-current="'+esc(s)+'" value="'+(x.latest_score??0)+'"></label><label>満点<input type="number" min="0.1" step="0.1" data-alloc-max="'+esc(s)+'" value="'+(x.latest_max??100)+'"></label><label>優先度<input type="number" min="0.1" max="10" step="0.1" data-alloc-weight="'+esc(s)+'" value="1"></label></div>'}).join('')}function renderSchools(){$('#school-list').innerHTML=schools.map(s=>'<div class="panel school-card"><div class="school-head"><div><strong>'+esc(s.name)+'</strong><p>'+esc(s.prefecture)+' / '+esc(s.school_type)+'</p></div><div><button type="button" data-add-rule="'+esc(s.id)+'">選抜情報を追加</button> <button type="button" class="delete" data-delete-school="'+esc(s.id)+'">学校を削除</button></div></div>'+(s.rules||[]).map(r=>'<div class="rule-card"><div><strong>'+esc(r.admission_year+'年度・'+(r.course||'コース未指定')+'・'+r.selection_type)+'</strong><span class="rule-status">'+esc(r.verification_status)+'</span></div><p>'+esc(r.notes||'')+'</p>'+(r.official_source_url?'<p><a href="'+esc(r.official_source_url)+'" target="_blank" rel="noopener noreferrer">公式資料を開く</a></p>':'<p class="note">公式資料URL未登録</p>')+'<button type="button" data-edit-rule="'+esc(r.id)+'">編集</button> '+(r.verification_status==='確認済み'&&r.rule_data?.scoring_model?'<button type="button" data-allocate-school-rule="'+esc(s.id)+'|'+esc(r.id)+'">この選抜方式で目標点を計算</button>':'')+' <button type="button" class="delete" data-delete-rule="'+esc(r.id)+'">削除</button></div>').join('')+'</div>').join('')||'<p class="note">学校データがまだ登録されていません。</p>'}function renderOfficialSources(){const items=officialSources.official_sources||[];$('#official-source-list').innerHTML=items.map(x=>'<div class="source-row"><strong>'+esc(x.prefecture)+' / '+esc(x.category)+'</strong><a href="'+esc(x.url)+'" target="_blank" rel="noopener noreferrer">'+esc(x.note)+'</a></div>').join('')||'<p class="note">公式資料一覧がありません。</p>'}async function api(p,o={}){let r=await fetch('/api'+p,{...o,headers:{...(o.headers||{}),'X-Exam-Mode':examMode}});if(!r.ok){let d={};try{d=await r.json()}catch{}throw Error(d.detail||r.statusText)}if(r.status===204)return null;return r.json()}queryAll('#score-form select[name="subject"],#question-form select[name="subject"]').forEach(select=>{select.innerHTML=subjects.map(subject=>'<option value="'+esc(subject)+'">'+esc(subject)+'</option>').join('')});$('#exam-mode').value=examMode;$('#exam-mode').onchange=e=>{localStorage.setItem('examMode',e.target.value);location.reload()};if(examMode==='university'){queryAll('[data-high-school-only]').forEach(el=>el.hidden=true);$('#subtitle').textContent='大学受験・学習分析';$('#target-school-label').textContent='志望大学・学部・学科';$('#target-school-name').placeholder='大学・学部・学科';$('#target-school-name').parentElement.hidden=true;$('#target-prefecture-field').hidden=true;$('#university-target-fields').hidden=false;const typeSelect=$('#score-form').elements.exam_type;typeSelect.innerHTML=['模試','共通テスト','個別試験','過去問','定期試験','その他'].map(x=>'<option>'+x+'</option>').join('');$('#title').textContent='大学受験ダッシュボード';}function toast(s){let n=$('#toast');n.textContent=s;n.classList.add('show');setTimeout(()=>n.classList.remove('show'),2500)}async function refresh(){[scores,questions,analysis,settings,schools,officialSources]=await Promise.all([api('/scores'),api('/questions'),api('/analysis'),api('/settings'),api('/schools'),api('/schools/official-sources')]);render()}function renderUnitTrends(){
const groups=new Map();
for(const item of analysis.unit_trends||[]){
const key=JSON.stringify([item.subject,item.unit,item.exam_type||"模試"]);
if(!groups.has(key))groups.set(key,[]);
groups.get(key).push(item);
}
const rows=[...groups.values()].map(items=>{
items.sort((a,b)=>String(a.date).localeCompare(String(b.date))||String(a.exam_name).localeCompare(String(b.exam_name)));
const byDate=new Map();
for(const item of items){if(!byDate.has(item.date))byDate.set(item.date,[]);byDate.get(item.date).push(item)}
const dateGroups=[...byDate.entries()].sort((a,b)=>String(a[0]).localeCompare(String(b[0])));
const latestGroup=dateGroups[dateGroups.length-1][1];
const previousGroup=dateGroups.length>1?dateGroups[dateGroups.length-2][1]:null;
const latest=latestGroup[latestGroup.length-1];
const previous=previousGroup?previousGroup[previousGroup.length-1]:null;
const latestDateAmbiguous=latestGroup.length>1;
const previousDateAmbiguous=Boolean(previousGroup&&previousGroup.length>1);
const comparisonAmbiguous=latestDateAmbiguous||previousDateAmbiguous;
const delta=previous&&!comparisonAmbiguous?Number(latest.accuracy)-Number(previous.accuracy):null;
const comparison=comparisonAmbiguous?'同日複数試験のため比較保留':previous?(delta>=0?'+':'')+delta.toFixed(1)+'pt':'比較データなし';
return {latest,delta,comparison,count:items.length,latestDateAmbiguous};
}).sort((a,b)=>String(b.latest.date).localeCompare(String(a.latest.date))||Number(a.latest.accuracy)-Number(b.latest.accuracy)).slice(0,12);
$('#unit-trends').innerHTML=rows.length?'<div class="table"><table><thead><tr><th>科目・単元</th><th>最新試験</th><th>得点率</th><th>前回との差</th><th>記録数</th></tr></thead><tbody>'+rows.map(row=>'<tr><td>'+esc(row.latest.subject+'・'+row.latest.unit+'（'+(row.latest.exam_type||'模試')+'）')+'</td><td>'+esc(row.latest.date+' / '+(row.latestDateAmbiguous?'同日複数試験（順序不明）':row.latest.exam_name+' / '+row.latest.exam_type))+'</td><td>'+(row.latestDateAmbiguous?'—':Number(row.latest.accuracy).toFixed(1)+'%')+'</td><td>'+esc(row.comparison)+'</td><td>'+row.count+'回</td></tr>').join('')+'</tbody></table></div><p class="note">同じ日付に複数の試験がある場合、試験の実施順を特定できないため得点率や前回との差の表示を保留します。試験ごとの難易度は補正していないため、学習状況を振り返る参考値として使用してください。表示は最新12単元です。</p>':'<p class="note">日付と試験名の両方を登録した問題データがありません。問題データの登録時に両方を入力すると、試験別の推移を確認できます。</p>';
}
function render(){let l=analysis.latest_exam;const examTypeRows=analysis.exam_type_summary||[];$('#exam-type-panel').hidden=examMode!=='university';$('#exam-type-analysis').innerHTML=examTypeRows.length?'<div class="table"><table><thead><tr><th>試験種別</th><th>科目</th><th>平均得点率</th><th>最新得点率</th><th>記録数</th><th>最新試験</th></tr></thead><tbody>'+examTypeRows.map(x=>'<tr><td>'+esc(x.exam_type)+'</td><td>'+esc(x.subject)+'</td><td>'+x.average_rate+'%</td><td>'+x.latest_rate+'%</td><td>'+x.count+'件</td><td>'+esc(x.latest_date+' '+x.latest_exam_name)+'</td></tr>').join('')+'</tbody></table></div>':'試験種別ごとの成績を登録すると、ここに表示されます。';$('#metrics').innerHTML=[['最新試験',l?esc(l.name)+'（'+esc(l.exam_type||'種別未設定')+'）':'—'],['総合得点率',l?l.rate+'%':'—'],['登録済み成績',scores.length+'件'],['分析単元',(analysis.weak_units||[]).length+'件']].map(x=>'<div class="metric"><span>'+x[0]+'</span><strong>'+x[1]+'</strong></div>').join('');$('#bars').innerHTML=(analysis.summary||[]).map(x=>'<div class="bar"><b>'+esc(x.subject)+'</b><div class="track"><div class="fill" style="width:'+x.latest_rate+'%"></div></div><span>'+x.latest_rate+'%</span></div>').join('')||'成績データを登録してください。';let weak=(analysis.weak_units||[]).slice(0,4);$('#actions').innerHTML=weak.map(x=>{const count=Number(x.questions||0);const sampleNote=count>0&&count<5?' ※記録数が少ないため暫定的な目安です。':'';const guidance=Number(x.accuracy)<100?'間違えた問題の解法を確認しましょう。':'正答できた問題も、解法を説明できるか確認しましょう。';return '<p>'+esc(x.subject+'・'+x.unit+'（'+(x.exam_type||'模試')+'）')+'：正答率 '+x.accuracy+'%（'+count+'問）'+sampleNote+' '+guidance+'</p>'}).join('')||'問題別データがありません。';$('#gaps').innerHTML=(analysis.target_gaps||[]).map(x=>'<p>'+esc(x.subject)+'：現在 '+x.comparable_current+'/'+x.target_max_score+'点 → 目標 '+x.target+'点（'+(x.gap<=0?'目標達成':'あと '+x.gap+'点')+'）</p>').join('')||'目標点を設定してください。';renderUnitTrends();$('#question-rows').innerHTML=questions.map(x=>'<tr><td>'+esc(x.date||'—')+'</td><td>'+esc(x.exam_type||'模試')+'</td><td>'+esc(x.subject)+'</td><td>'+esc(x.unit)+'</td><td>'+(x.correct?'正解':'不正解')+'</td><td>'+(x.earned_points??'—')+'/'+(x.points??'—')+'</td><td><button type="button" data-edit-question-id="'+esc(x.id)+'">編集</button> <button class="delete" data-question-id="'+esc(x.id)+'">削除</button></td></tr>').join('');$('#score-rows').innerHTML=scores.map(x=>'<tr><td>'+esc(x.date)+'</td><td>'+esc(x.exam_name)+'</td><td>'+esc(x.exam_type||'種別未設定')+'</td><td>'+esc(x.subject)+'</td><td>'+x.score+'/'+x.max_score+'</td><td>'+ (x.deviation??'—')+'</td><td><button type="button" data-edit-id="'+esc(x.id)+'">編集</button> <button class="delete" data-id="'+esc(x.id)+'">削除</button></td></tr>').join('');let t=settings.target||{};$('#target-form').elements.school_name.value=t.school_name||'';$('#target-form').elements.prefecture.value=t.prefecture||'';if(examMode==='university'){const u=t.university||{};['university_name','faculty','department','admission_method'].forEach(k=>$('#target-form').elements[k].value=u[k]||'');}$('#target-form').elements.admission_year.value=t.admission_year||2027;$('#target-form').elements.source_note.value=t.source_note||'';$('#subject-targets').innerHTML=subjects.map(s=>'<label>'+s+'<div class="target-score-fields"><input type="number" min="0" data-sub="'+s+'" value="'+(t.subjects?.[s]?.target_score??'')+'" placeholder="目標点"><input type="number" min="0.1" step="0.1" data-sub-max="'+s+'" value="'+(t.subjects?.[s]?.max_score??100)+'" aria-label="'+esc(s)+'の満点" title="満点"></div></label>').join('');allocationFields();renderSchools();renderOfficialSources()}queryAll('nav button').forEach(b=>b.onclick=()=>{queryAll('.page').forEach(p=>p.classList.add('hidden'));$('#'+b.dataset.page).classList.remove('hidden');queryAll('nav button').forEach(x=>x.classList.toggle('active',x===b));$('#title').textContent=b.textContent});$('#refresh').onclick=()=>refresh().then(()=>toast('更新しました')).catch(e=>toast(e.message));$('#score-form').onsubmit=async e=>{e.preventDefault();const form=e.target;let d=Object.fromEntries(new FormData(form));const id=d.id;delete d.id;['score','max_score','deviation','rank','examinees'].forEach(k=>d[k]=d[k]===''?null:Number(d[k]));try{await api(id?'/scores/'+id:'/scores',{method:id?'PUT':'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(d)});form.reset();$('#score-submit').textContent='成績を追加';$('#score-cancel').hidden=true;await refresh();toast(id?'成績を更新しました':'成績を保存しました')}catch(x){toast(x.message)}};$('#score-rows').onclick=async e=>{const editId=e.target.dataset.editId;if(editId){const item=scores.find(x=>x.id===editId);if(!item)return;const form=$('#score-form');['date','exam_name','exam_type','subject','score','max_score','deviation','rank','examinees'].forEach(k=>form.elements[k].value=item[k]??'');form.elements.id.value=item.id;$('#score-submit').textContent='変更を保存';$('#score-cancel').hidden=false;return}const id=e.target.dataset.id;if(!id)return;if(confirm('この成績を削除しますか？')){try{await api('/scores/'+id,{method:'DELETE'});await refresh()}catch(x){toast(x.message)}}};$('#score-cancel').onclick=()=>{$('#score-form').reset();$('#score-submit').textContent='成績を追加';$('#score-cancel').hidden=true};$('#target-form').onsubmit=async e=>{e.preventDefault();let d=Object.fromEntries(new FormData(e.target)),target={school_name:examMode==='university'?[d.university_name,d.faculty,d.department].filter(Boolean).join(' / '):d.school_name,prefecture:d.prefecture,admission_year:Number(d.admission_year),source_note:d.source_note,subjects:{}};if(examMode==='university')target.university={university_name:d.university_name||'',faculty:d.faculty||'',department:d.department||'',admission_method:d.admission_method||''};const invalidTargets=[];
subjects.forEach(s=>{
const targetRaw=$('[data-sub="'+s+'"]').value;
const maxScore=Number($('[data-sub-max="'+s+'"]').value||100);
const targetScore=targetRaw===''?null:Number(targetRaw);
if(!Number.isFinite(maxScore)||maxScore<=0||(targetScore!==null&&(!Number.isFinite(targetScore)||targetScore<0||targetScore>maxScore)))invalidTargets.push(s);
target.subjects[s]={target_score:targetScore,max_score:maxScore,weight:1};
});
if(invalidTargets.length)return toast('目標点・満点を確認してください：'+invalidTargets.join('、'));
try{await api('/settings',{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify({profile:settings.profile||{},target})});await refresh();toast('目標を保存しました')}catch(x){toast(x.message)}};function renderImportPreview(){
const container=$('#import-preview');
if(!importPreview){container.innerHTML='';$('#import-confirm').disabled=true;return}
const records=importPreview.records||[];
const pageSize=50;
const pageCount=Math.max(1,Math.ceil(records.length/pageSize));
importPage=Math.min(Math.max(importPage,0),pageCount-1);
const start=importPage*pageSize;
const visible=records.slice(start,start+pageSize);
const selectedCount=records.filter(item=>item.selected&&!item.duplicate).length;
const validCount=records.filter(item=>!item.duplicate).length;
const warningCount=records.filter(item=>(item.warnings||[]).length>0).length;
let html='<p class="note">'+importPreview.total_rows+'行中、有効な登録候補 '+validCount+'件 / 重複 '+importPreview.duplicates+'件 / 自動補完の確認 '+warningCount+'件 / 入力エラー '+importPreview.errors.length+'件。重複行は選択できず、自動補完した行は確認後に選択してください。</p>';
if(records.length){
html+='<div class="table import-table"><table><thead><tr><th>登録</th><th>行</th><th>試験日</th><th>試験名</th><th>試験種別</th><th>科目</th><th>得点</th><th>偏差値</th><th>順位</th><th>受験者数</th><th>状態・確認事項</th></tr></thead><tbody>';
html+=visible.map((item,offset)=>{
const index=start+offset,data=item.data;
return '<tr><td><input type="checkbox" data-import-index="'+index+'" '+(item.selected?'checked ':'')+(item.duplicate?'disabled':'')+' aria-label="行 '+item.row+'を登録"></td><td>'+item.row+'</td><td>'+esc(data.date)+'</td><td>'+esc(data.exam_name)+'</td><td>'+esc(data.exam_type)+'</td><td>'+esc(data.subject)+'</td><td>'+esc(data.score)+' / '+esc(data.max_score)+'</td><td>'+esc(data.deviation??'')+'</td><td>'+esc(data.rank??'')+'</td><td>'+esc(data.examinees??'')+'</td><td>'+(item.duplicate?'重複':(item.warnings||[]).length?'要確認':'登録候補')+((item.warnings||[]).length?'<br><span class="note">'+esc(item.warnings.join(' / '))+'</span>':'')+'</td></tr>';
}).join('');
html+='</tbody></table></div>';
html+='<div class="import-pagination"><button type="button" data-import-page="-1" '+(importPage===0?'disabled':'')+'>前へ</button><span>ページ '+(importPage+1)+' / '+pageCount+'・選択 '+selectedCount+'件</span><button type="button" data-import-page="1" '+(importPage>=pageCount-1?'disabled':'')+'>次へ</button></div>';
}else{
html+='<p class="note">登録できる行がありません。下のエラー内容を確認してください。</p>';
}
if(importPreview.errors.length){
html+='<details><summary>入力エラー '+importPreview.errors.length+'件を確認</summary><ul>';
html+=importPreview.errors.slice(0,20).map(item=>'<li>行 '+item.row+'：'+esc(item.error)+'</li>').join('');
if(importPreview.errors.length>20)html+='<li>ほか '+(importPreview.errors.length-20)+'件</li>';
html+='</ul></details>';
}
container.innerHTML=html;
$('#import-confirm').disabled=selectedCount===0;
}
$('#import-preview').onclick=e=>{
const input=e.target.closest('[data-import-index]');
if(input&&importPreview){
importPreview.records[Number(input.dataset.importIndex)].selected=input.checked;
renderImportPreview();
return;
}
const page=e.target.closest('[data-import-page]');
if(page){importPage+=Number(page.dataset.importPage);renderImportPreview()}
};
$('#table-file').onchange=()=>{
importPreview=null;importPage=0;renderImportPreview();$('#upload-result').textContent='';
};
$('#upload').onclick=async()=>{
const file=$('#table-file').files[0];
if(!file)return toast('ファイルを選択してください');
const data=new FormData();data.append('file',file);
$('#upload').disabled=true;$('#upload-result').textContent='プレビューを作成中...';
importPreview=null;renderImportPreview();
try{
const result=await api('/import/table/preview',{method:'POST',body:data});
importPreview={...result,records:result.records.map(item=>({...item,selected:!item.duplicate&&!(item.warnings||[]).length}))};
importPage=0;renderImportPreview();
$('#upload-result').textContent='登録する行を確認してください。自動補完された行は未選択なので、内容を確認してから選択してください。';
}catch(error){
$('#upload-result').textContent=error.message;
}finally{$('#upload').disabled=false}
};
$('#import-confirm').onclick=async()=>{
if(!importPreview)return;
const selected=importPreview.records.filter(item=>item.selected&&!item.duplicate).map(item=>item.data);
if(!selected.length)return toast('登録する行を選択してください');
$('#import-confirm').disabled=true;
try{
const result=await api('/import/table/confirm',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({scores:selected})});
importPreview=null;renderImportPreview();
$('#upload-result').textContent=selected.length+'件を確認し、'+result.imported+'件登録 / 重複 '+result.duplicates+'件';
try{await refresh()}catch(error){toast('登録は完了しましたが、画面更新に失敗しました：'+error.message)}
}catch(error){
$('#upload-result').textContent=error.message;
if(importPreview)renderImportPreview();
}
};
$('#pdf').onclick=async()=>{let f=$('#pdf-file').files[0];if(!f)return toast('PDFを選択してください');let d=new FormData();d.append('file',f);try{let r=await api('/import/pdf',{method:'POST',body:d});$('#pdf-text').value=r.text;toast(r.needs_ocr?'画像PDFです。OCRが必要です。':'読み取りました')}catch(x){toast(x.message)}};refresh().catch(e=>toast('API接続エラー：'+e.message));
$('#question-form').onsubmit=async e=>{e.preventDefault();const form=e.target;let d=Object.fromEntries(new FormData(form));const id=d.id;delete d.id;d.correct=d.correct==='true';['points','earned_points'].forEach(k=>d[k]=d[k]===''?null:Number(d[k]));try{await api(id?'/questions/'+id:'/questions',{method:id?'PUT':'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(d)});form.reset();$('#question-submit').textContent='問題データを追加';$('#question-cancel').hidden=true;await refresh();toast(id?'問題データを更新しました':'問題データを保存しました')}catch(x){toast(x.message)}};$('#question-rows').onclick=async e=>{const editId=e.target.dataset.editQuestionId;if(editId){const item=questions.find(x=>x.id===editId);if(!item)return;const form=$('#question-form');['date','exam_name','exam_type','subject','unit','points','earned_points'].forEach(k=>form.elements[k].value=item[k]??(k==='exam_type'?'模試':''));form.elements.correct.value=String(Boolean(item.correct));form.elements.id.value=item.id;$('#question-submit').textContent='変更を保存';$('#question-cancel').hidden=false;return}const id=e.target.dataset.questionId;if(!id)return;if(confirm('この問題データを削除しますか？')){try{await api('/questions/'+id,{method:'DELETE'});await refresh()}catch(x){toast(x.message)}}};$('#question-cancel').onclick=()=>{$('#question-form').reset();$('#question-submit').textContent='問題データを追加';$('#question-cancel').hidden=true};

$('#allocation-form').onsubmit=async e=>{
e.preventDefault();
const targetTotal=Number(new FormData(e.target).get('target_total'));
const selected=subjects.filter(subject=>$('[data-alloc-enabled="'+subject+'"]')?.checked);
if(selected.length<2)return toast('配分対象の科目を2つ以上選択してください');
if(!Number.isFinite(targetTotal)||targetTotal<0)return toast('総合目標点を正しく入力してください');
const allocationSubjects=selected.map(subject=>({subject,current_score:Number($('[data-alloc-current="'+subject+'"]').value),max_score:Number($('[data-alloc-max="'+subject+'"]').value),weight:Number($('[data-alloc-weight="'+subject+'"]').value)}));
const invalid=allocationSubjects.filter(x=>!Number.isFinite(x.current_score)||x.current_score<0||!Number.isFinite(x.max_score)||x.max_score<=0||x.current_score>x.max_score||!Number.isFinite(x.weight)||x.weight<=0||x.weight>10);
if(invalid.length)return toast('現在点・満点・優先度を確認してください：'+invalid.map(x=>x.subject).join('、'));
if(targetTotal>allocationSubjects.reduce((sum,x)=>sum+x.max_score,0))return toast('総合目標点は選択科目の満点合計以下にしてください');
try{
const result=await api('/targets/allocate',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({target_total:targetTotal,subjects:allocationSubjects})});
$('#allocation-result').innerHTML='<h3>科目別の目標点</h3><p>対象 '+result.subjects.length+'科目 / 現在 '+result.current_total+'点 → 計画 '+result.planned_total+'点 / 目標 '+result.requested_total+'点</p><div class="table"><table><thead><tr><th>科目</th><th>現在点</th><th>目標点</th><th>必要な上積み</th><th>目標得点率</th></tr></thead><tbody>'+result.subjects.map(x=>'<tr><td>'+esc(x.subject)+'</td><td>'+x.current_score+'</td><td>'+x.target_score+'</td><td>+'+x.increase+'</td><td>'+x.target_rate+'%</td></tr>').join('')+'</tbody></table></div><p class="note">'+esc(result.notice)+'</p>'+(result.already_at_or_above_goal?'<p>現在点がすでに総合目標点以上です。</p>':'');
}catch(x){toast(x.message)}
};

function localDateValue(){const d=new Date();return d.getFullYear()+'-'+String(d.getMonth()+1).padStart(2,'0')+'-'+String(d.getDate()).padStart(2,'0')}
$('#ocr-preview').onclick=async()=>{
const file=$('#pdf-file').files[0];if(!file)return toast('PDFを選択してください');
const form=new FormData();form.append('file',file);
try{
const result=await api('/import/pdf/ocr-preview',{method:'POST',body:form});
$('#pdf-text').value=result.text;ocrCandidates=result.candidates||[];
const today=localDateValue(),examName=file.name.replace(/\.pdf$/i,'');
$('#ocr-candidates').innerHTML=ocrCandidates.map((x,i)=>'<div class="ocr-row"><p>ページ '+x.page+' / 行 '+x.line+'：'+esc(x.ocr_text)+'</p><div class="ocr-fields"><label>実施日<input type="date" data-ocr-date value="'+today+'" required></label><label>模試名<input data-ocr-name value="'+esc(examName)+'" required></label><label>試験種別<select data-ocr-exam-type>'+['模試','定期試験','共通テスト','個別試験','過去問','その他'].map(t=>'<option value="'+t+'" '+(t===(examMode==='university'?'共通テスト':'模試')?'selected':'')+'>'+t+'</option>').join('')+'</select></label><label>科目<select data-ocr-subject>'+subjects.map(s=>'<option value="'+s+'" '+(s===x.subject?'selected':'')+'>'+s+'</option>').join('')+'</select></label><label>得点<input type="number" min="0" data-ocr-score value="'+x.score_candidate+'" required></label><label>満点<input type="number" min="1" data-ocr-max value="'+x.max_score_candidate+'" required></label></div><button type="button" data-ocr-remove>この候補を除外</button></div>').join('')||'<p class="note">得点候補が見つかりませんでした。OCRテキストを確認し、必要なら成績管理から手入力してください。</p>';
$('#ocr-confirm').disabled=ocrCandidates.length===0;toast('OCR候補を抽出しました。内容を確認してください');
}catch(x){toast(x.message)}
};
$('#ocr-candidates').onclick=e=>{if(!e.target.matches('[data-ocr-remove]'))return;e.target.closest('.ocr-row').remove();$('#ocr-confirm').disabled=queryAll('.ocr-row').length===0};
$('#ocr-confirm').onclick=async()=>{
const rows=queryAll('.ocr-row');if(!rows.length)return toast('登録する候補がありません');
for(const row of rows){
const controls=[...row.querySelectorAll('input,select')];
const invalid=controls.find(control=>!control.checkValidity());
if(invalid){invalid.reportValidity();return}
const score=Number(row.querySelector('[data-ocr-score]').value),maximum=Number(row.querySelector('[data-ocr-max]').value);
if(!Number.isFinite(score)||!Number.isFinite(maximum)||maximum<=0||score>maximum)return toast('得点は0以上、満点以下になるように確認してください');
}
const confirmed=rows.map(row=>({date:row.querySelector('[data-ocr-date]').value,exam_name:row.querySelector('[data-ocr-name]').value,exam_type:row.querySelector('[data-ocr-exam-type]').value,subject:row.querySelector('[data-ocr-subject]').value,score:Number(row.querySelector('[data-ocr-score]').value),max_score:Number(row.querySelector('[data-ocr-max]').value)}));
const button=$('#ocr-confirm');button.disabled=true;
try{const result=await api('/import/ocr-confirm',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({scores:confirmed})});$('#ocr-candidates').innerHTML='';toast(result.imported+'件登録 / 重複 '+result.duplicates+'件');await refresh()}catch(x){toast(x.message);button.disabled=queryAll('.ocr-row').length===0?true:false}
};

$('#school-form').onsubmit=async e=>{e.preventDefault();const data=Object.fromEntries(new FormData(e.target));try{await api('/schools',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(data)});e.target.reset();await refresh();toast('学校を登録しました')}catch(x){toast(x.message)}};
$('#school-list').onclick=async e=>{
const addId=e.target.dataset.addRule;if(addId){const form=$('#school-rule-form');form.reset();form.elements.id.value='';form.elements.school_id.value=addId;form.elements.admission_year.value=2027;form.elements.rule_data.value='{}';$('#school-rule-submit').textContent='選抜情報を保存';$('#school-rule-panel').hidden=false;return}
const editId=e.target.dataset.editRule;if(editId){const school=schools.find(s=>(s.rules||[]).some(r=>r.id===editId));const rule=school?.rules.find(r=>r.id===editId);if(!rule)return;const form=$('#school-rule-form');form.elements.id.value=rule.id;form.elements.school_id.value=rule.school_id;['admission_year','course','selection_type','verification_status','official_source_url','verified_on','notes'].forEach(k=>form.elements[k].value=rule[k]??'');form.elements.rule_data.value=JSON.stringify(rule.rule_data||{},null,2);$('#school-rule-submit').textContent='変更を保存';$('#school-rule-panel').hidden=false;return}
const deleteRule=e.target.dataset.deleteRule;if(deleteRule&&confirm('この選抜情報を削除しますか？')){try{await api('/school-rules/'+deleteRule,{method:'DELETE'});await refresh()}catch(x){toast(x.message)}return}
const deleteSchool=e.target.dataset.deleteSchool;if(deleteSchool&&confirm('学校と登録済みの選抜情報を削除しますか？')){try{await api('/schools/'+deleteSchool,{method:'DELETE'});await refresh()}catch(x){toast(x.message)}}
};
$('#school-rule-form').onsubmit=async e=>{e.preventDefault();const form=e.target;const raw=Object.fromEntries(new FormData(form));const id=raw.id,schoolId=raw.school_id;let ruleData;try{ruleData=JSON.parse(raw.rule_data||'{}');if(!ruleData||Array.isArray(ruleData)||typeof ruleData!=='object')throw Error('JSONはオブジェクト形式で入力してください')}catch(x){toast('選抜データJSONを確認してください：'+x.message);return}const data={admission_year:Number(raw.admission_year),course:raw.course||'',selection_type:raw.selection_type,verification_status:raw.verification_status,official_source_url:raw.official_source_url||null,verified_on:raw.verified_on||null,rule_data:ruleData,notes:raw.notes||''};try{await api(id?'/school-rules/'+id:'/schools/'+schoolId+'/rules',{method:id?'PUT':'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(data)});form.reset();$('#school-rule-panel').hidden=true;await refresh();toast(id?'選抜情報を更新しました':'選抜情報を登録しました')}catch(x){toast(x.message)}};
$('#school-rule-cancel').onclick=()=>{$('#school-rule-form').reset();$('#school-rule-panel').hidden=true};


$('#school-list').addEventListener('click',e=>{
const key=e.target.dataset.allocateSchoolRule;if(!key)return;
const [schoolId,ruleId]=key.split('|');
const school=schools.find(x=>x.id===schoolId),rule=school?.rules?.find(x=>x.id===ruleId);
const model=rule?.rule_data?.scoring_model;if(!school||!rule||!model)return;
activeSchoolAllocation={schoolId,ruleId,model};
$('#school-allocation-title').textContent=school.name+' / '+rule.admission_year+'年度 '+rule.selection_type+' の目標点計算';
const latest=Object.fromEntries((analysis.summary||[]).map(x=>[x.subject,x]));
const subjectFields=model.exam_subjects.map(x=>{
const s=latest[x.subject],converted=s&&s.latest_max>0?Math.min(x.raw_max_score,Math.max(0,s.latest_score/s.latest_max*x.raw_max_score)):0;
return '<div class="allocation-row"><strong>'+esc(x.subject)+'（満点 '+x.raw_max_score+'）</strong><label>現在点<input type="number" min="0" max="'+x.raw_max_score+'" step="0.1" required data-school-current="'+esc(x.subject)+'" value="'+converted.toFixed(1)+'"></label><label>学習優先度<input type="number" min="0.1" max="10" step="0.1" required data-school-priority="'+esc(x.subject)+'" value="1"></label><span class="note">選抜換算上限 '+x.contribution_max_score+'点 / 出典 p.'+x.source_page+'</span></div>'
}).join('');
const fixedFields=[{label:model.method_label||'基本方式',items:model.fixed_components||[]},...(model.alternatives||[]).map(x=>({label:x.label,items:x.fixed_components||[]}))].map(method=>method.items.map(x=>'<div class="allocation-row"><strong>'+esc(method.label)+' / '+esc(x.name)+'（満点 '+x.max_score+'）</strong><label>現在の評価点<input type="number" min="0" max="'+x.max_score+'" step="0.1" required data-school-fixed-method="'+esc(method.label)+'" data-school-fixed-name="'+esc(x.name)+'" value="0"></label><span class="note">出典 p.'+x.source_page+'</span></div>').join('')).join('');
$('#school-allocation-fields').innerHTML=subjectFields+fixedFields;
$('#school-allocation-result').innerHTML='';
$('#school-allocation-panel').hidden=false;
$('#school-allocation-panel').scrollIntoView({behavior:'smooth',block:'start'});
});
$('#school-allocation-form').onsubmit=async e=>{
e.preventDefault();if(!activeSchoolAllocation)return;
const model=activeSchoolAllocation.model;
const subjects=model.exam_subjects.map(x=>({subject:x.subject,current_score:Number($('[data-school-current="'+x.subject+'"]').value),priority:Number($('[data-school-priority="'+x.subject+'"]').value)}));
const fixedValues=items=>Object.fromEntries((items||[]).map(x=>[x.name,Number(queryAll('[data-school-fixed-method]').find(el=>el.dataset.schoolFixedMethod===(activeSchoolAllocation.model.method_label||'基本方式')&&el.dataset.schoolFixedName===x.name)?.value)]));
const fixed_component_scores=fixedValues(model.fixed_components);
const alternative_fixed_component_scores=Object.fromEntries((model.alternatives||[]).map(x=>[x.label,Object.fromEntries((x.fixed_components||[]).map(item=>[item.name,Number(queryAll('[data-school-fixed-method]').find(el=>el.dataset.schoolFixedMethod===x.label&&el.dataset.schoolFixedName===item.name)?.value)]))]));
const target_total=Number(new FormData(e.target).get('target_total'));
try{
const result=await api('/schools/'+activeSchoolAllocation.schoolId+'/rules/'+activeSchoolAllocation.ruleId+'/allocate',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({target_total,subjects,fixed_component_scores,alternative_fixed_component_scores})});
const methodCards=result.method_results.map(method=>'<div class="panel"><h4>'+esc(method.method_label)+(method.method_label===result.best_current_method?'（現在点が最も高い方式）':'')+'</h4>'+(method.error?'<p class="note">この方式では計算できません：'+esc(method.error)+'</p>':'<p>現在 '+method.current_total+'点 → 計画 '+method.planned_total+'点 / 目標 '+method.requested_total+'点</p><div class="table"><table><thead><tr><th>科目</th><th>現在の素点</th><th>目標素点</th><th>必要な上積み</th><th>選抜換算点</th></tr></thead><tbody>'+method.subjects.map(x=>'<tr><td>'+esc(x.subject)+'</td><td>'+x.current_score+'/'+x.raw_max_score+'</td><td>'+x.target_score+'/'+x.raw_max_score+'</td><td>+'+x.increase+'</td><td>'+x.target_contribution+'/'+x.contribution_max_score+'</td></tr>').join('')+'</tbody></table></div>')+'</div>').join('');
$('#school-allocation-result').innerHTML='<h3>方式別の科目目標</h3>'+methodCards+'<p class="note">'+esc(result.notice)+'</p>';
}catch(x){toast(x.message)}
};



$('#backup-download').onclick=async()=>{
try{
const response=await fetch('/api/backup',{headers:{'X-Exam-Mode':examMode}});
if(!response.ok){let detail='バックアップを作成できませんでした';try{detail=(await response.json()).detail||detail}catch{}throw Error(detail)}
const blob=await response.blob();
const url=URL.createObjectURL(blob);
const link=document.createElement('a');
link.href=url;
link.download='exam_strategy_'+examMode+'_'+new Date().toISOString().slice(0,10)+'.json';
document.body.appendChild(link);
link.click();
link.remove();
URL.revokeObjectURL(url);
toast('バックアップをダウンロードしました');
}catch(error){toast(error.message)}
};

$('#backup-restore').onclick=async()=>{
const file=$('#backup-file').files[0];
if(!file)return toast('復元するJSONファイルを選択してください');
if(!$('#backup-confirm').checked)return toast('既存データを置き換える確認にチェックしてください');
if(!confirm('現在の'+(examMode==='university'?'大学受験':'高校受験')+'データをバックアップ内容で置き換えます。続行しますか？'))return;
try{
const backup=JSON.parse(await file.text());
backup.confirm_replace=true;
const result=await api('/backup/restore',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(backup)});
$('#backup-file').value='';
$('#backup-confirm').checked=false;
toast('復元しました：成績 '+result.restored.scores+'件 / 問題 '+result.restored.questions+'件');
await refresh();
}catch(error){toast(error.message)}
};


$('#excel-report-download').onclick=async()=>{
try{
const response=await fetch('/api/reports/excel',{headers:{'X-Exam-Mode':examMode}});
if(!response.ok){let detail='Excelレポートを作成できませんでした';try{detail=(await response.json()).detail||detail}catch{}throw Error(detail)}
const blob=await response.blob();
const url=URL.createObjectURL(blob);
const link=document.createElement('a');
link.href=url;
link.download='exam_strategy_report_'+examMode+'.xlsx';
document.body.appendChild(link);
link.click();
link.remove();
URL.revokeObjectURL(url);
toast('Excelレポートをダウンロードしました');
}catch(error){toast(error.message)}
};
