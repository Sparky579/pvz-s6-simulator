"""Render the two requested matches in independent verified native segments."""
from concurrent.futures import ThreadPoolExecutor, wait, FIRST_COMPLETED
from pathlib import Path
import json
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parent.parent
BASE = ROOT/'artifacts/five-lane-match-20261027'


def render_part(job):
    match, number, start, stop = job
    directory = BASE/'renders'/match/'parts'
    directory.mkdir(parents=True, exist_ok=True)
    output = directory/f'part-{number:02d}.mp4'
    args = [sys.executable, '-u', str(ROOT/'tools/render_match.py'),
            str(BASE/'local/matches'/match/'replay.json'), '-o', str(output),
            '--prefix', str(ROOT/f'.wine-s6-video-{match[:4]}-{number}'),
            '--start-frame', str(start)]
    if stop:
        args += ['--stop-frame', str(stop)]
    with open(directory/f'part-{number:02d}.log', 'w') as log:
        subprocess.run(args, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT, check=True)
    report = json.loads(output.with_suffix('.verification.json').read_text())
    if not all(item['matches'] for item in report['checkpoints']):
        raise ValueError(f'Checkpoint mismatch: {match} segment {number}')
    return match, number, output, report


def main():
    plans = {
        '0063-seed-20261089': [0, 44000, 88000, 132000, 0],
        '0115-seed-20261141': [0, 41000, 82000, 0],
    }
    jobs = [(match, i, start, stop)
            for match, edges in plans.items()
            for i, (start, stop) in enumerate(zip(edges, edges[1:]))]
    finished = {match: {} for match in plans}
    started = time.monotonic()
    with ThreadPoolExecutor(max_workers=7) as pool:
        pending = {pool.submit(render_part, job) for job in jobs}
        while pending:
            done, pending = wait(pending, timeout=45, return_when=FIRST_COMPLETED)
            for future in done:
                match, number, output, report = future.result()
                finished[match][number] = (output, report)
                print(f'Completed {match} segment {number+1}: '
                      f'{report["duration_seconds"]:.2f}s; verified', flush=True)
            if not done:
                print(f'Rendering {len(pending)} segments; '
                      f'{time.monotonic()-started:.0f}s elapsed', flush=True)
    for match, segments in finished.items():
        out = BASE/'renders'/match/f'match-{match[:4]}-runner-up-end.mp4'
        listing = out.parent/'parts/concat.txt'
        listing.write_text(''.join(f"file '{segments[i][0]}'\n" for i in sorted(segments)))
        temporary = out.with_suffix('.merging.mp4')
        subprocess.run(['ffmpeg', '-hide_banner', '-loglevel', 'warning', '-y',
                        '-f', 'concat', '-safe', '0', '-i', str(listing),
                        '-c', 'copy', '-movflags', '+faststart', str(temporary)], check=True)
        probe = json.loads(subprocess.check_output([
            'ffprobe', '-v', 'error', '-show_entries',
            'stream=codec_name,width,height,r_frame_rate,nb_frames:format=duration,size',
            '-of', 'json', str(temporary)]))
        ordered = [segments[i][1] for i in sorted(segments)]
        video_frames = sum(r['video_frames'] for r in ordered)
        if int(probe['streams'][0]['nb_frames']) != video_frames:
            raise ValueError('Merged frame count differs from verified segments')
        if not ordered[-1]['ended']:
            raise ValueError('Missing original CT runner-up ending')
        checkpoints = [c for r in ordered for c in r['checkpoints']]
        report = {**ordered[-1], 'segments': ordered, 'checkpoints': checkpoints,
                  'video_frames': video_frames, 'duration_seconds': video_frames/25,
                  'output': str(out), 'probe': probe,
                  'winning_lane': 4 if match.startswith('0063') else 2,
                  'wall_seconds': time.monotonic()-started}
        temporary.replace(out)
        out.with_suffix('.verification.json').write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n')
        print(f'Complete: {out} ({video_frames/25:.2f}s, '
              f'{out.stat().st_size/1024/1024:.1f} MiB)', flush=True)


if __name__ == '__main__':
    main()
