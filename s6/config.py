from __future__ import annotations
from dataclasses import dataclass
import hashlib
import json


@dataclass(frozen=True)
class Config:
    data: dict

    @classmethod
    def parse(cls, data):
        if not isinstance(data,dict):raise ValueError('Configuration must be an object')
        allowed={'formation','version','mode','max_frames','seed','repetitions','easter','elite','elite_marker','giant','checkpoint_every','speed_mode'}
        if set(data)-allowed:raise ValueError(f'Unknown configuration fields: {sorted(set(data)-allowed)}')
        version=data.get('version','s6-bug')
        if version != 's6-bug':raise ValueError('version must be s6-bug (the unchanged supplied CT)')
        formation=data.get('formation')
        if not isinstance(formation,list) or len(formation)!=5 or any(not isinstance(r,list) or len(r)!=5 for r in formation):
            raise ValueError('formation must have exactly 5 rows of 5 cells, top to bottom / left to right')
        result=[]
        for row in formation:
            out=[]
            for cell in row:
                layers=cell if isinstance(cell,list) else [cell]
                parsed=[]
                for p in layers:
                    if p is None:continue
                    if type(p) is int:p={'id':p}
                    if not isinstance(p,dict) or set(p)-{'id','xp'}:raise ValueError('Plant must be an ID, null, or {id, xp}')
                    if type(p.get('id')) is not int or not (0<=p['id']<=79):raise ValueError('Plant ID must be 0..79')
                    if type(p.get('xp',0)) is not int or not (0<=p.get('xp',0)<=0x7fffffff):raise ValueError('xp must be a nonnegative int32')
                    parsed.append({'id':p['id'],'xp':p.get('xp',0)})
                out.append(parsed)
            result.append(out)
        mode=data.get('mode',1)
        if type(mode) is not int or mode not in (1,2,5,6,7,10):raise ValueError('Only five-lane survival modes 1, 2, 5, 6, 7, 10 are supported')
        normalized={**data,'formation':result,'version':version,'mode':mode,
                    'speed_mode':data.get('speed_mode','exact'),
                    'max_frames':data.get('max_frames',300000),'seed':data.get('seed',1),
                    'repetitions':data.get('repetitions',1),'easter':data.get('easter','original'),
                    'elite':data.get('elite','original'),'giant':data.get('giant',0),
                    'elite_marker':data.get('elite_marker',0),
                    'checkpoint_every':data.get('checkpoint_every',1000)}
        for field in ('max_frames','repetitions','checkpoint_every'):
            if type(normalized[field]) is not int or normalized[field]<1:raise ValueError(f'{field} must be a positive integer')
        if type(normalized['seed']) is not int or not (0<=normalized['seed']<=0xffffffff):raise ValueError('seed must be uint32')
        if normalized['easter'] not in ('original','disabled','forced'):raise ValueError('easter must be original, disabled, or forced')
        if normalized['elite'] not in ('original','forced'):raise ValueError('elite must be original or forced (blind-box elite flag)')
        if normalized['speed_mode'] not in ('exact','fast'):raise ValueError('speed_mode must be exact or fast')
        if type(normalized['elite_marker']) is not int or normalized['elite_marker'] not in (0,1,2):
            raise ValueError('elite_marker must be 0, 1, or 2 (original CT marker 701200)')
        if type(normalized['giant']) is not int or normalized['giant'] not in (0,1):raise ValueError('giant must be 0 or 1')
        return cls(normalized)

    @property
    def digest(self):
        return hashlib.sha256(json.dumps(self.data,sort_keys=True,separators=(',',':')).encode()).hexdigest()
