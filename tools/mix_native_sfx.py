"""Mix all observed native SFX from original PCM and DirectSound controls."""
from pathlib import Path
import argparse
import json
import struct
import wave
import numpy as np

RATE=44100
# Background music uses the separate BASS interface and is never captured.
# These two musical stingers can also be loaded as game sound instances.
MUSIC_SAMPLES={'losemusic','winmusic'}


def read_samples(directory):
    names={int(p[0]):p[2] for line in (directory/'sample-names.tsv').read_text(errors='replace').splitlines()
           if len(p:=line.split('\t'))==3}
    samples={};f=open(directory/'samples.bin','rb')
    while header:=f.read(32):
        sid,gid,rate,channels,bits,align,size,tag=struct.unpack('<8I',header)
        pcm=f.read(size)
        if len(pcm)!=size:raise ValueError('Truncated native PCM')
        data=(np.frombuffer(pcm,dtype='<i2').astype(np.float32)/32768 if bits==16 else
              (np.frombuffer(pcm,dtype=np.uint8).astype(np.float32)-128)/128)
        data=data.reshape(-1,channels)
        name=names[sid].replace('\\','/').rsplit('/',1)[-1].lower()
        samples[sid]={'data':data,'name':name,'rate':rate,'selected':name not in MUSIC_SAMPLES,'game_id':gid}
    f.close();return samples


def signed(value):return value if value<0x80000000 else value-0x100000000


def mix(directory,output,duration):
    samples=read_samples(directory)
    events=np.fromfile(directory/'events.bin',dtype='<u4').reshape(-1,8)
    length=round(duration*RATE)
    backing=output.with_suffix('.mix-f32')
    mix=np.memmap(backing,dtype=np.float32,mode='w+',shape=(length,2));mix[:]=0
    voices={};selected_events=0
    def render(v,tick):
        end=min(round(tick*RATE/100),length);start=v['time']
        n=end-start
        if n<=0:return
        if v['playing']:
            sample=samples[v['sample']]
            if sample['selected']:
                data=sample['data'];count=len(data)
                positions=v['position']+np.arange(n,dtype=np.float64)*(v['frequency']/RATE)
                if v['looping']:positions%=count
                else:positions=positions[positions<count]
                if len(positions):
                    i=positions.astype(np.int64);j=(i+1)%count if v['looping'] else np.minimum(i+1,count-1)
                    frac=(positions-i).astype(np.float32)[:,None]
                    pcm=data[i]*(1-frac)+data[j]*frac
                    if pcm.shape[1]==1:pcm=np.repeat(pcm,2,axis=1)
                    gain=10**(v['volume']/2000)
                    gains=np.array([gain*(10**(-max(v['pan'],0)/2000)),
                                    gain*(10**(min(v['pan'],0)/2000))],dtype=np.float32)
                    mix[start:start+len(pcm)]+=pcm*gains
            v['position']+=n*v['frequency']/RATE
        v['time']=end
    for tick,op,vid,sid,a,b,c,d in events.tolist():
        code=op&255
        v=voices.get(vid)
        if v is not None:render(v,tick)
        if code==1:
            voices[vid]={'sample':sid,'position':a/100,'frequency':b,'volume':signed(c),'pan':signed(d),
                         'time':min(round(tick*RATE/100),length),'playing':True,'looping':bool(op&256)}
            selected_events+=int(samples[sid]['selected'])
        elif v is not None:
            if code==2:v['playing']=False
            elif code==3:v['position']=a/100
            elif code==4:v['frequency']=a
            elif code==5:v['volume']=signed(a)
            elif code==6:v['pan']=signed(a)
    for v in voices.values():render(v,duration*100)
    peak=0.;clipped=0;energy=0.
    with wave.open(str(output),'wb') as wav:
        wav.setnchannels(2);wav.setsampwidth(2);wav.setframerate(RATE)
        for start in range(0,length,RATE*10):
            pcm=np.asarray(mix[start:start+RATE*10])
            peak=max(peak,float(np.max(np.abs(pcm))));clipped+=int(np.sum(np.abs(pcm)>1))
            energy+=float(np.sum(pcm.astype(np.float64)**2))
            wav.writeframes((np.clip(pcm,-1,32767/32768)*32768).astype('<i2').tobytes())
    del mix;backing.unlink()
    report={'duration_seconds':length/RATE,'sample_rate':RATE,'channels':2,'peak_before_saturation':peak,
            'rms_before_saturation':(energy/(length*2))**.5,'saturated_sample_fraction':clipped/(length*2),
            'event_count':len(events),'selected_play_events':selected_events,
            'included_samples':[{'id':sid,'name':s['name'],'game_id':s['game_id']} for sid,s in samples.items() if s['selected']],
            'excluded_samples':[{'id':sid,'name':s['name'],'game_id':s['game_id']} for sid,s in samples.items() if not s['selected']],
            'music':'none; all original game sound effects, including zombies, plants, impacts, mowers and ending',
            'source':'original DirectSound decoded PCM with recorded pitch, position, volume and pan'}
    output.with_suffix('.verification.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({k:v for k,v in report.items() if not isinstance(v,list)},ensure_ascii=False),flush=True)


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('capture',type=Path);p.add_argument('-o','--output',type=Path,required=True)
    p.add_argument('--duration',type=float,required=True)
    a=p.parse_args();mix(a.capture,a.output,a.duration)


if __name__=='__main__':main()
