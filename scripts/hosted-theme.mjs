import {createHash} from 'node:crypto';
// The exact bytes are shared by the early bootstrap and both hosted CSPs.
export const themeBootstrap="try{var t=localStorage.getItem('chopper-color-scheme');if(t==='light'||t==='dark')document.querySelector('meta[name=\"color-scheme\"]').content=t}catch{}";
export const hostedCsp=`default-src 'self'; script-src 'self' 'wasm-unsafe-eval' 'sha256-${createHash('sha256').update(themeBootstrap).digest('base64')}'; worker-src 'self'; style-src 'self'; connect-src 'self'; img-src 'self' data:; frame-ancestors 'none'; base-uri 'none'`;
