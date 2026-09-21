import {spawn} from "node:child_process";

export async function startUiServer(executable, args, {timeoutMs=30000}={}) {
    const child=spawn(executable,args,{windowsHide:true,stdio:["ignore","pipe","pipe"]});
    let stdout="",stderr="",closed=false;
    const closing=new Promise(resolve=>child.once("close",()=>{closed=true;resolve();}));
    child.stdout.setEncoding("utf8");child.stderr.setEncoding("utf8");
    child.stderr.on("data",data=>{stderr=(stderr+data).slice(-32768);});
    const stop=async()=>{if(!closed)child.kill();await closing;};
    try {
        const url=await new Promise((resolve,reject)=>{
            const finish=(error,url)=>{clearTimeout(timer);child.stdout.off("data",onData);error?reject(error):resolve(url);};
            const failure=message=>finish(new Error(`${message}${stderr.trim()?`\n${stderr.trim()}`:""}`));
            const onData=data=>{
                stdout+=data;
                const match=stdout.match(/(?:^|\r?\n)(http:\/\/127\.0\.0\.1:\d+\/?)(?:\r?\n)/);
                if(match)finish(null,match[1]);
            };
            const timer=setTimeout(()=>failure(`UI harness did not start within ${timeoutMs} ms`),timeoutMs);
            child.stdout.on("data",onData);
            child.once("error",error=>failure(`UI harness could not start: ${error.message}`));
            child.once("close",(code,signal)=>failure(`UI harness exited before startup (code ${code}, signal ${signal})`));
        });
        return {url,stop};
    } catch(error) {
        await stop();
        throw error;
    }
}
