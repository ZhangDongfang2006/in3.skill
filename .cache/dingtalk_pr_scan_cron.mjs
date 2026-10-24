import fs from 'node:fs';
const ENV_PATH='/Users/zhangdongfang/.openclaw/secrets/dingtalk_in3_review.env';
const STATE_PATH='/Users/zhangdongfang/.openclaw/workspace-in3bot/IN3数据/dingtalk_pr_overdue_state.json';
const OUT_PATH="/Users/zhangdongfang/.openclaw/workspace-in3bot/.cache/dingtalk_pr_scan_result.json";
const PROCESS_CODE='PROC-2E68A3B4-3C43-4598-AB10-532CE9E8F5C4';
const EIGHT_H=8*3600*1000;
const waitms=ms=>new Promise(r=>setTimeout(r,ms));
function envGet(k){
  const lines=fs.readFileSync(ENV_PATH,'utf8').split(String.fromCharCode(10));
  for(const ln of lines){
    const i=ln.indexOf('=');
    if(i>0&&ln.slice(0,i).trim()===k){return ln.slice(i+1).trim().replace(/^["']|["']$/g,'');}
  }
  return null;
}
async function post(url,body){
  let last={errcode:-1,errmsg:'no-attempt'};
  for(let i=0;i<3;i++){
    try{
      const r=await fetch(url,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
      last=await r.json();
    }catch(e){last={errcode:-1,errmsg:String((e&&e.message)||e)};}
    if(last&&last.errcode===0){return last;}
    if(i<2){await waitms(800);}
  }
  return last;
}
function ctToMs(s){
  if(typeof s==='number')return s;
  const m=String(s||'').match(/(\d{4})-(\d{2})-(\d{2})[ T](\d{2}):(\d{2}):(\d{2})/);
  if(!m)return NaN;
  return Date.parse(m[1]+'-'+m[2]+'-'+m[3]+'T'+m[4]+':'+m[5]+':'+m[6]+'+08:00');
}
const fmtHM=new Intl.DateTimeFormat('en-GB',{timeZone:'Asia/Shanghai',hour:'2-digit',minute:'2-digit',hour12:false});
const fmtD=new Intl.DateTimeFormat('en-CA',{timeZone:'Asia/Shanghai'});
const now=Date.now();
const hm=fmtHM.format(new Date());
const hh=Number(hm.slice(0,2));
const mm=Number(hm.slice(3,5));
const quiet=(hh>=21)||(hh<7)||((hh===7)&&(mm<30));
let state={};
try{state=JSON.parse(fs.readFileSync(STATE_PATH,'utf8'));}catch(e){}
const out={scanAt:fmtD.format(new Date())+' '+hm,quiet:quiet,tokenOk:false,pages:0,ids:0,running:0,detailErr:0,detailErrors:[],listErr:null,overdue:[],candidates:[],runningList:[]};
try{
  const tk=await post('https://api.dingtalk.com/v1.0/oauth2/accessToken',{appKey:envGet('DINGTALK_APPKEY'),appSecret:envGet('DINGTALK_APPSECRET')});
  if(!tk||!tk.accessToken){out.tokenErr=tk;throw new Error('token failed');}
  out.tokenOk=true;
  const at=tk.accessToken;
  const start=now-7*24*3600*1000;
  let cursor=0;
  const ids=[];
  let more=true;
  while(more&&out.pages<50){
    out.pages++;
    const d=await post('https://oapi.dingtalk.com/topapi/processinstance/listids?access_token='+at,{process_code:PROCESS_CODE,start_time:start,size:20,cursor:cursor});
    if(d.errcode!==0){out.listErr={errcode:d.errcode,errmsg:d.errmsg};break;}
    const L=(d.result&&d.result.list)||[];
    ids.push.apply(ids,L);
    const nc=(d.result&&d.result.next_cursor!=null)?d.result.next_cursor:null;
    if(nc==null||nc===cursor){more=false;}else{cursor=nc;}
  }
  out.ids=ids.length;
  const running=[];
  for(const id of ids){
    const d=await post('https://oapi.dingtalk.com/topapi/processinstance/get?access_token='+at,{process_instance_id:id});
    if(d.errcode!==0||!d.process_instance){out.detailErr++;if(out.detailErrors.length<10){out.detailErrors.push({id:id,errcode:d.errcode,errmsg:d.errmsg});}continue;}
    const r=d.process_instance;
    if(r.status==='RUNNING'||!r.result){
      const form=JSON.stringify(r.form_component_values||[]);
      const m=(String(r.title||'')+' '+form).match(/PR[0-9]+/);
      let applicant='';
      const fvs=r.form_component_values||[];
      for(let i=0;i<fvs.length;i++){
        const fv=fvs[i];
        if(fv&&/申请人|发起人/.test(String(fv.name||''))){applicant=String(fv.value||'').split(',')[0].split('$')[0].trim();break;}
      }
      const ctm=ctToMs(r.create_time);
      running.push({id:id,pr:m?m[0]:'',title:String(r.title||''),applicant:applicant,createTimeRaw:r.create_time,createTime:ctm});
    }
  }
  out.running=running.length;
  for(const x of running){
    if(!isNaN(x.createTime)){x.hours=Math.round((now-x.createTime)/360000)/10;}
    if(!isNaN(x.createTime)&&(now-x.createTime)>EIGHT_H){
      out.overdue.push({id:x.id,pr:x.pr,title:x.title,applicant:x.applicant,createTimeRaw:x.createTimeRaw,hours:x.hours});
      const last=state[x.id];
      if(!last||((now-Number(last))>=EIGHT_H)){out.candidates.push({id:x.id,pr:x.pr,title:x.title,applicant:x.applicant,createTimeRaw:x.createTimeRaw,hours:x.hours});}
    }
  }
  out.runningList=running.map(x=>({id:x.id,pr:x.pr,applicant:x.applicant,createTimeRaw:x.createTimeRaw,hours:x.hours}));
}catch(e){out.fatal=String((e&&e.message)||e);}
fs.writeFileSync(OUT_PATH,JSON.stringify(out,null,1));
console.log(JSON.stringify(out));
