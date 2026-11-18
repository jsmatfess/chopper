"""In-memory test data. These layouts cannot qualify an installed browser."""
def layout(mode):
    if mode == 'input':
        nodes = [dict(parentIndex=-1, **{'class':'ComboBoxEx32'}, id=1148),
                 dict(parentIndex=0, **{'class':'ComboBox'}, id=1148),
                 dict(parentIndex=1, **{'class':'Edit'}, id=1148)]
        count = 50
    else:
        nodes = [dict(parentIndex=-1, **{'class':'Edit'}, id=1152)]
        count = 44
    nodes += [dict(parentIndex=-1, **{'class':'Button'}, id=i) for i in (1,2)]
    while len(nodes) < count:
        nodes.append(dict(parentIndex=-1, **{'class':'Static'}, id=100+len(nodes)))
    return dict(nodes=nodes)


def job():
    csv = dict(encoding='utf-8',headers=True,delimiter=',',quote='"',escape=None,
               line_ending='crlf',bom=False,skip_empty_lines=False)
    return dict(version=1,input='tiny.csv',output='export',zip_member=None,
                input_csv=csv,output_csv=csv.copy(),compression='none',operations=[],
                limits=dict(rows=None,bytes=40,compressed_bytes=None),
                resources=dict(memory_mb=32,workers=1,temp_dir=None,temp_bytes=8388608,
                               max_files=32,max_record_bytes=1048576,grouping='auto'),
                seed='issue105-6069cef-tiny-v1')
