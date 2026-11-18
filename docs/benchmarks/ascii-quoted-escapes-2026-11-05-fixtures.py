from pathlib import Path
import csv,json,hashlib,sys,platform
p=Path(sys.argv[1]);sha=lambda f:hashlib.sha256(f.read_bytes()).hexdigest();meta={}
known={'plain':'37bb8e696a4aa01df8452adcc1b4fb14c11bec1f8064b4575152a62be738e1ae','rich':'c73a6e154bafab8a0d2ecf4e08b08e2f68587fb5287b145abc8082c44ec9cd64'}
assert not (p/'fixtures.json').exists()
for shape in ['plain','rich']:
 f=p/f'input-{shape}-4000000.csv'
 with f.open('x',encoding='utf8',newline='') as out:
  writer=csv.writer(out,lineterminator='\n');writer.writerow(['id','region','payload'])
  for row in range(4000000):
   ordinary='x'*(24+row%97)
   value=('note-'+str(row)+','+'界 '+ordinary+' says "hi"\r\nnext-'+str(row%7)) if shape=='rich' else ('note-'+str(row)+'-'+ordinary)
   writer.writerow([str(row),'R'+str(row%4),value])
   if row==999999:
    out.flush();assert sha(f)==known[shape];prefix_bytes=f.stat().st_size
 meta[f'{shape}-4000000']={'rows':4000000,'fields':3,'shape':shape,'bytes':f.stat().st_size,'sha256':sha(f),'encoding':'UTF8,LF,noBOM,minimalquoting; embeddedCRLF preserved','prefix1M_sha256':known[shape],'prefix1M_bytes':prefix_bytes,'generator':'generate-fixtures.py; Pythoncsv independent of Chopper'}
(p/'fixtures.json').write_text(json.dumps({'fixtures':meta,'generator_sha256':sha(Path(__file__)),'runtime':sys.version,'platform':platform.platform()},indent=2)+'\n')
