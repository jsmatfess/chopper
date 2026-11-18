import http from 'node:http';
import {hostedCsp} from './hosted-theme.mjs';
import {readFile} from 'node:fs/promises';
import {fileURLToPath} from 'node:url';
const root=fileURLToPath(new URL('../ui/dist/',import.meta.url));
const port=Number(process.env.PORT||8421);
const types={'.html':'text/html; charset=utf-8','.js':'text/javascript','.css':'text/css','.wasm':'application/wasm','.json':'application/json'};
http.createServer(async(req,res)=>{
  res.setHeader('Cross-Origin-Opener-Policy','same-origin');res.setHeader('Cross-Origin-Embedder-Policy','require-corp');res.setHeader('Cache-Control','no-store');
  res.setHeader('X-Content-Type-Options','nosniff');
  res.setHeader('Content-Security-Policy',hostedCsp);
  try {
    if(req.method!=='GET')throw new Error('GET only');
    const path=new URL(req.url,'http://localhost').pathname;
    // Serve only build-root files. No file upload or processing endpoints exist.
    const name=path==='/'?'index.html':path.slice(1);
    if(!/^[a-zA-Z0-9_.-]+$/.test(name)||name.startsWith('.'))throw new Error('Not found');
    const bytes=await readFile(root+name);
    res.setHeader('Content-Type',types[name.slice(name.lastIndexOf('.'))]||'application/octet-stream');res.end(bytes);
  } catch {res.statusCode=404;res.end('Not found');}
}).listen(port,'127.0.0.1',()=>console.log(`Chopper browser engine: http://127.0.0.1:${port}/`));
