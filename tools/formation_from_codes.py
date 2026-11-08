"""Convert five rows of single-character plant codes to an S6 configuration."""
from pathlib import Path
import argparse,json


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('rows',nargs=5,help='Top to bottom; five codes per row from left to right; 空 means empty')
    p.add_argument('--base',type=Path,help='Preserve conditions from an existing configuration')
    p.add_argument('-o','--output',type=Path,required=True)
    a=p.parse_args()
    mapping=json.loads((Path(__file__).resolve().parent.parent/'plant_codes.json').read_text())
    codes={entry['code']:entry['id'] for entry in mapping}
    if len(codes)!=len(mapping) or len({e['id'] for e in mapping})!=len(mapping) or any(len(c)!=1 for c in codes):
        raise ValueError('Plant codes and IDs must be unique, with one character per code')
    codes['空']=None
    formation=[]
    for index,row in enumerate(a.rows,1):
        row=''.join(row.split())
        if len(row)!=5:raise ValueError(f'Row {index} must contain exactly five characters')
        unknown=set(row)-codes.keys()
        if unknown:raise ValueError(f'Row {index}: unknown codes {sorted(unknown)}')
        formation.append([codes[c] for c in row])
    config=json.loads(a.base.read_text()) if a.base else {'version':'s6-bug','speed_mode':'fast'}
    config['formation']=formation
    a.output.parent.mkdir(parents=True,exist_ok=True)
    a.output.write_text(json.dumps(config,ensure_ascii=False,indent=2)+'\n')
    print(a.output)


if __name__=='__main__':main()
