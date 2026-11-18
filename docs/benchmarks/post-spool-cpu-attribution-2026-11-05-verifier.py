def payload(row,shape):
    ordinary='x'*(24+row%97)
    return f'note-{row},界 {ordinary} says "hi"\r\nnext-{row%7}' if shape=='rich' else f'note-{row}-{ordinary}'

def verify(output,job,n,analysis,recipe,shape):
    rows=0;seen=bytearray(n);files={}
    outputs=[r for line in (output/'manifest.jsonl').read_text().splitlines() if (r:=json.loads(line)).get('type')=='output']
    assert len(outputs)==analysis['output_files']
    for item in outputs:
        f=output/item['path'];length=f.stat().st_size
        assert length==item['csv_bytes'] and length<=job['limits']['bytes'];count=0
        with f.open(encoding='utf8',newline='') as stream:
            reader=csv.reader(stream,strict=True);assert next(reader)==['id','region','payload']
            for fields in reader:
                assert len(fields)==3
                row=int(fields[0]);assert 0<=row<n and not seen[row];seen[row]=1
                assert fields==[str(row),f'R{row%4}',payload(row,shape)]
                if recipe=='ordered':assert row==rows
                else:assert item['lineage'][0]['values']==[f'R{row%4}'] and item['lineage'][1]['allocation'] in ['treatment','control']
                rows+=1;count+=1
        assert count==item['rows'] and count<=job['limits']['rows'];files[f.name]=sha(f)
    assert rows==n==analysis['rows'] and all(seen)
    assert analysis['groups']==(1 if recipe=='ordered' else 12)
    assert {f.name for f in output.iterdir()}==set(files)|{'manifest.jsonl'}
    assert sum((output/name).stat().st_size for name in files)==analysis['output_csv_bytes']
    if recipe=='ordered':assert len(files)==1 and next(iter(files.values()))==fixtures[f'{shape}-{n}']['sha256']
    return {'files_sha256':files,'output_records':outputs,'logical_analysis':{k:analysis[k] for k in logical}}
