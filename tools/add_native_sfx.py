"""Add verified original game SFX to an existing rendered video, without BGM."""
from pathlib import Path
import argparse
import json
import os
import subprocess


def video_hash(path):
    return subprocess.check_output([
        'ffmpeg','-hide_banner','-v','error','-i',str(path),'-map','0:v:0',
        '-c:v','copy','-f','hash','-hash','sha256','-'],text=True).strip()


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('video',type=Path)
    a=p.parse_args();video=a.video.resolve()
    report_path=video.with_suffix('.verification.json')
    report=json.loads(report_path.read_text())
    directory=video.parent/'native-sfx'
    capture=json.loads((directory/'capture.verification.json').read_text())
    audio=json.loads((directory/'all-native-sfx.verification.json').read_text())
    if capture['end_frame']!=report['end_frame'] or capture['mower_frames']!=report['mower_frames']:
        raise ValueError('Captured audio ending differs from video')
    if not all(c['matches'] for c in capture['checkpoints']):
        raise ValueError('Audio capture has divergent gameplay checkpoints')
    if audio['selected_play_events']==0 or audio['rms_before_saturation']==0:
        raise ValueError('Audio capture is silent')
    duration=report['duration_seconds']
    if abs(audio['duration_seconds']-duration)>1/44100:
        raise ValueError('Sound track duration differs from video')
    temporary=video.with_suffix('.with-audio.mp4')
    original_hash=video_hash(video)
    subprocess.run([
        'ffmpeg','-hide_banner','-loglevel','warning','-y',
        '-i',str(video),'-i',str(directory/'all-native-sfx.wav'),
        '-map','0:v:0','-map','1:a:0','-c:v','copy','-c:a','aac','-b:a','192k',
        # The first video sample is game frame 1, presented at video time zero.
        '-af','atrim=start=0.01,asetpts=PTS-STARTPTS,apad',
        '-t',str(duration),'-metadata:s:a:0','title=Original game sound effects (no BGM)',
        '-movflags','+faststart',str(temporary)],check=True)
    probe=json.loads(subprocess.check_output([
        'ffprobe','-v','error','-show_entries',
        'stream=codec_type,codec_name,width,height,r_frame_rate,nb_frames,sample_rate,channels,duration:format=duration,size',
        '-of','json',str(temporary)]))
    streams=probe['streams']
    pictures=[s for s in streams if s['codec_type']=='video']
    sound=[s for s in streams if s['codec_type']=='audio']
    if len(pictures)!=1 or len(sound)!=1 or sound[0]['codec_name']!='aac':
        raise ValueError('Unexpected muxed streams')
    if int(pictures[0]['nb_frames'])!=report['video_frames'] or video_hash(temporary)!=original_hash:
        raise ValueError('Video bitstream changed during audio mux')
    subprocess.run(['ffmpeg','-hide_banner','-v','error','-i',str(temporary),
                    '-map','0:a:0','-f','null','-'],check=True)
    backup=video.with_suffix('.silent.mp4')
    if not backup.exists():os.link(video,backup)
    temporary.replace(video)
    report.update({'audio':'all native game sound effects; no background music',
                   'native_sfx_capture':capture,'native_sfx_mix':audio,
                   'audio_alignment_seconds':-0.01,'video_bitstream_hash':original_hash,
                   'video_bitstream_unchanged':True,'audio_decode_check':{'exit_code':0,'errors':[]},
                   'original_silent_video':str(backup),'probe':probe})
    report_path.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    print(f'Complete: {video}; original video stream retained; AAC stereo SFX, no BGM',flush=True)


if __name__=='__main__':main()
