import {MAX_PHYSICAL_STEPS} from './physical-history';
export const DAG_NODE_WIDTH=300,DAG_NODE_HEIGHT=148,DAG_COLUMN_GAP=64,DAG_ROW_GAP=56,DAG_PADDING=28;
export const MAX_DAG_NODES=MAX_PHYSICAL_STEPS+4,MAX_DAG_EDGES=MAX_DAG_NODES*4;
export type DagInput={id:number;sources:readonly number[];stage?:number;height?:number};
export type DagPosition={column:number;row:number;x:number;y:number;height:number};
export type DagEdge={source:number;target:number};
export type DagFrame={positions:ReadonlyMap<number,DagPosition>;edges:DagEdge[];width:number;height:number;missing:number;cycles:number;revision:number};

function order(ids:number[],edges:DagEdge[]){
 const degree=new Map(ids.map(id=>[id,0])),children=new Map<number,number[]>();
 for(const edge of edges){degree.set(edge.target,degree.get(edge.target)!+1);const list=children.get(edge.source)||[];list.push(edge.target);children.set(edge.source,list);}
 const queue=ids.filter(id=>degree.get(id)===0);
 for(let i=0;i<queue.length;i++)for(const child of children.get(queue[i])||[]){degree.set(child,degree.get(child)!-1);if(degree.get(child)===0)queue.push(child);}
 return queue;
}

// First placement uses dependency layers. New observations append slots; existing
// dependency order is repaired when a late producer arrives; rows only grow.
export class ExecutionDag {
 private positions=new Map<number,DagPosition>();
 private rows=new Map<number,number>();
 private heights=new Map<number,number>();
 private key='';private revision=0;
 private frame:DagFrame={positions:this.positions,edges:[],width:320,height:204,missing:0,cycles:0,revision:0};
 update(input:DagInput[]):DagFrame{
  const nodes=input.slice(0,MAX_DAG_NODES),key=nodes.map(node=>`${node.id}@${node.stage??''}/${node.height??DAG_NODE_HEIGHT}:${node.sources.slice(0,4).join(',')}`).join(';');
  if(key===this.key)return this.frame;this.key=key;
  const ids=nodes.map(node=>node.id),known=new Set(ids),edges:DagEdge[]=[],seen=new Set<string>();let missing=0,cycles=0;
  for(const node of nodes)for(const source of node.sources.slice(0,4)){
   const edgeKey=`${source}:${node.id}`;
   if(seen.has(edgeKey))continue;seen.add(edgeKey);
   if(!known.has(source)){missing++;continue;}
   if(source===node.id){cycles++;continue;}
   if(edges.length<MAX_DAG_EDGES)edges.push({source,target:node.id});
  }
  let sorted=order(ids,edges),accepted=edges;
  if(sorted.length!==ids.length){
   accepted=[];const children=new Map<number,number[]>();
   for(const edge of edges){
    const stack=[edge.target],visited=new Set<number>();let cyclic=false;
    while(stack.length){const id=stack.pop()!;if(id===edge.source){cyclic=true;break;}if(visited.has(id))continue;visited.add(id);stack.push(...children.get(id)||[]);}
    if(cyclic){cycles++;continue;}
    accepted.push(edge);const list=children.get(edge.source)||[];list.push(edge.target);children.set(edge.source,list);
   }
   sorted=order(ids,accepted);
  }
  const stages=new Map(nodes.map(node=>[node.id,node.stage]));
  const parents=new Map<number,number[]>();
  for(const edge of accepted){const list=parents.get(edge.target)||[];list.push(edge.source);parents.set(edge.target,list);}
  for(const id of sorted){
   if(this.positions.has(id)||this.positions.size===MAX_DAG_NODES)continue;
   const stage=stages.get(id);
   const column=stage!=null&&Number.isInteger(stage)&&stage>=0&&stage<MAX_DAG_NODES?stage:Math.max(0,...(parents.get(id)||[]).map(parent=>(this.positions.get(parent)?.column??-1)+1));
   const parentRow=Math.max(-1,...(parents.get(id)||[]).map(parent=>{const p=this.positions.get(parent);return p?.column===column?p.row:-1;}));
   const row=Math.max(this.rows.get(column)||0,parentRow+1);this.rows.set(column,row+1);
   this.positions.set(id,{column,row,x:DAG_PADDING+row*(DAG_NODE_WIDTH+DAG_COLUMN_GAP),y:DAG_PADDING+column*(DAG_NODE_HEIGHT+DAG_ROW_GAP),height:DAG_NODE_HEIGHT});
  }
  this.rows.clear();
  for(const id of sorted){const position=this.positions.get(id);if(!position)continue;position.row=this.rows.get(position.column)||0;this.rows.set(position.column,position.row+1);position.x=DAG_PADDING+position.row*(DAG_NODE_WIDTH+DAG_COLUMN_GAP);}
  for(const node of nodes){
   const position=this.positions.get(node.id);if(!position)continue;
   position.height=Math.max(position.height,DAG_NODE_HEIGHT,Number.isFinite(node.height)?node.height!:0);
   this.heights.set(position.column,Math.max(this.heights.get(position.column)||DAG_NODE_HEIGHT,position.height));
  }
  const offsets=new Map<number,number>();let offset=DAG_PADDING;
  const last=Math.max(0,...[...this.positions.values()].map(p=>p.column));
  for(let column=0;column<=last;column++){offsets.set(column,offset);offset+=(this.heights.get(column)||DAG_NODE_HEIGHT)+DAG_ROW_GAP;}
  for(const position of this.positions.values()){position.y=offsets.get(position.column)!;position.height=this.heights.get(position.column)!;}
  let width=320,height=204;
  for(const position of this.positions.values()){width=Math.max(width,position.x+DAG_NODE_WIDTH+DAG_PADDING);height=Math.max(height,position.y+position.height+DAG_PADDING);}
  const outgoing=new Map<number,DagEdge[]>();for(const edge of accepted){const list=outgoing.get(edge.source)||[];list.push(edge);outgoing.set(edge.source,list);}
  const visible=accepted.filter(edge=>{
   const column=this.positions.get(edge.source)!.column;if(column!==this.positions.get(edge.target)!.column)return true;
   const pending=[edge.source],visited=new Set<number>();
   while(pending.length){const id=pending.pop()!;if(visited.has(id))continue;visited.add(id);
    for(const other of outgoing.get(id)||[]){if(other===edge||this.positions.get(other.target)!.column!==column)continue;if(other.target===edge.target)return false;pending.push(other.target);}
   }return true;
  });
  this.frame={positions:this.positions,edges:visible,width,height,missing,cycles,revision:++this.revision};return this.frame;
 }
}
export function edgePath(source:DagPosition,target:DagPosition){
 if(source.column===target.column){
  const x=source.x+DAG_NODE_WIDTH,y=source.y+source.height/2,endX=target.x,endY=target.y+target.height/2;
  return `M ${x} ${y} L ${endX-3} ${endY}`;
 }
 const x=source.x+DAG_NODE_WIDTH/2,y=source.y+source.height,endX=target.x+DAG_NODE_WIDTH/2,endY=target.y;
 const bend=Math.max(22,Math.abs(endY-y)/2);
 return `M ${x} ${y} L ${x} ${y+12} C ${x} ${y+bend}, ${endX} ${endY-bend}, ${endX} ${endY-12} L ${endX} ${endY-3}`;
}
