// Product labels shared by the editor, plan links and observed execution views.
const names:Record<string,string>={partition:'Partition by column',shuffle:'Shuffle row order',assign:'Assign exact groups',assign_probabilistic:'Assign approximate groups',balanced:'Split into consecutive parts',interleaved:'Split into alternating parts'};
const colors:Record<string,string>={partition:'blue',shuffle:'amber',assign:'purple',assign_probabilistic:'purple',balanced:'teal',interleaved:'teal'};
export const operationName=(type:string)=>Object.hasOwn(names,type)?names[type]:'Pipeline step';
export const operationColor=(type:string)=>Object.hasOwn(colors,type)?colors[type]:'slate';
export const configuredLabel=(label:string)=>label.replace(/^(\d+\. )([a-z_]+)/,(_,index,type)=>index+operationName(type));
export const statusLabel=(status:string)=>({active:'In Progress',in_progress:'In Progress',completed:'Completed',failed:'Failed',interrupted:'Interrupted',handed_off:'Handed Off',unknown:'Unknown'} as Record<string,string>)[status]??status.replaceAll('_',' ');
