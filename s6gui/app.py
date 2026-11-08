"""Tk front end: formation text + picture, threaded batch, result list, video export."""
from __future__ import annotations
import base64
import io
import json
import os
from pathlib import Path
import queue
import random
import statistics
import threading
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import tkinter.font as tkfont

from . import codes
from .batch import Brusher, load_record, summarize
from .capture import scene_names
from .platform import ROOT, WINDOWS, automatic_workers, requirements

MODES = [(1, '白天'), (2, '黑夜'), (5, '屋顶'), (6, '白天·困难'), (7, '黑夜·困难'), (10, '屋顶·困难')]
DEFAULT_FORMATION = '海魅窝高金\n小灯双爆草\n机魅火反仙\n狙飘卷玉曾\n胆阳叶魅嘴'
SETTINGS = ROOT/'artifacts/gui/settings.json'
PREVIEW_WIDTH = 340


def clock(seconds):
    if seconds is None:
        return '—'
    minutes, rest = divmod(seconds, 60)
    return f'{int(minutes)}:{rest:05.2f}'


def photo(image, width):
    """PIL image -> tk.PhotoImage without requiring PIL.ImageTk."""
    image = image.resize((width, round(image.height*width/image.width)))
    buffer = io.BytesIO()
    image.save(buffer, 'PNG')
    return tk.PhotoImage(data=base64.b64encode(buffer.getvalue()))


class App:
    def __init__(self, root):
        self.root = root
        self.events = queue.Queue()
        self.records = {}
        self.brusher = None
        self.preview = None
        self.preview_key = 0
        self.preview_after = None
        self.export_cancel = None
        self.export_thread = None
        root.title('S6 刷阵器')
        root.geometry('1360x820')
        families = set(tkfont.families())
        family = next((f for f in ('Microsoft YaHei UI', 'Microsoft YaHei', 'Noto Sans CJK SC',
                                   'WenQuanYi Micro Hei', 'Source Han Sans SC') if f in families), None)
        if family:
            for name in ('TkDefaultFont', 'TkTextFont', 'TkMenuFont', 'TkHeadingFont'):
                tkfont.nametofont(name).configure(family=family, size=10)
        self.big = tkfont.Font(family=family, size=20) if family else tkfont.Font(size=20)
        self._build()
        self._load_settings()
        root.protocol('WM_DELETE_WINDOW', self.close)
        root.after(100, self._poll)
        missing = requirements()
        if missing:
            messagebox.showwarning('运行环境', '\n'.join(missing))
        self.schedule_preview()

    # ---------------------------------------------------------------- layout
    def _build(self):
        left = ttk.Frame(self.root, padding=8)
        left.pack(side='left', fill='y')
        right = ttk.Frame(self.root, padding=(0, 8, 8, 8))
        right.pack(side='left', fill='both', expand=True)

        box = ttk.LabelFrame(left, text='阵容（上→下5路，左→右5格；空位写「空」）', padding=6)
        box.pack(fill='x')
        self.text = tk.Text(box, width=16, height=5, font=self.big, undo=True)
        self.text.pack(fill='x')
        self.text.insert('1.0', DEFAULT_FORMATION)
        self.text.bind('<<Modified>>', self._text_changed)
        line = ttk.Frame(box)
        line.pack(fill='x')
        self.parse_status = ttk.Label(line, text='', foreground='#a33')
        self.parse_status.pack(side='left')
        ttk.Button(line, text='简称表', command=self.show_codes).pack(side='right')

        pic = ttk.LabelFrame(left, text='阵容图（原包图片拼成，不启动游戏）', padding=6)
        pic.pack(fill='x', pady=(8, 0))
        self.canvas = tk.Canvas(pic, width=PREVIEW_WIDTH, height=round(PREVIEW_WIDTH*515/470),
                                highlightthickness=0, background='#2b3b2b')
        self.canvas.pack()
        self.preview_status = ttk.Label(pic, text='')
        self.preview_status.pack(anchor='w')

        conf = ttk.LabelFrame(right, text='条件', padding=6)
        conf.pack(fill='x')
        self.mode = tk.StringVar(value='1 白天')
        self.seed = tk.StringVar(value=str(random.randrange(1 << 31)))
        self.count = tk.StringVar(value='0')
        self.workers = tk.StringVar(value=str(automatic_workers()))
        self.speed = tk.StringVar(value='fast')
        self.reuse = tk.BooleanVar(value=True)
        self.easter = tk.StringVar(value='original')
        self.elite = tk.StringVar(value='original')
        self.elite_marker = tk.StringVar(value='0')
        self.giant = tk.StringVar(value='0')
        rows = [
            ('模式', ttk.Combobox(conf, textvariable=self.mode, state='readonly', width=12,
                                 values=[f'{m} {n}' for m, n in MODES])),
            ('起始种子', ttk.Entry(conf, textvariable=self.seed, width=14)),
            ('局数（0=不限）', ttk.Spinbox(conf, textvariable=self.count, from_=0, to=100000, width=8)),
            ('线程数', ttk.Spinbox(conf, textvariable=self.workers, from_=1, to=128, width=8)),
            ('速度模式', ttk.Combobox(conf, textvariable=self.speed, state='readonly', width=8,
                                   values=['fast', 'exact'])),
            ('彩蛋', ttk.Combobox(conf, textvariable=self.easter, state='readonly', width=10,
                                values=['original', 'disabled', 'forced'])),
            ('盲盒精英', ttk.Combobox(conf, textvariable=self.elite, state='readonly', width=10,
                                  values=['original', 'forced'])),
            ('精英标记', ttk.Combobox(conf, textvariable=self.elite_marker, state='readonly', width=4,
                                  values=['0', '1', '2'])),
            ('巨人标记', ttk.Combobox(conf, textvariable=self.giant, state='readonly', width=4,
                                  values=['0', '1'])),
        ]
        for i, (label, widget) in enumerate(rows):
            ttk.Label(conf, text=label).grid(row=i//5, column=(i % 5)*2, sticky='w', padx=(0, 4), pady=2)
            widget.grid(row=i//5, column=(i % 5)*2+1, sticky='w', padx=(0, 14), pady=2)
        ttk.Checkbutton(conf, text='线程内复用游戏进程（更快）', variable=self.reuse).grid(
            row=1, column=8, columnspan=2, sticky='w')
        self.mode.trace_add('write', lambda *_: self.schedule_preview())

        buttons = ttk.Frame(conf)
        buttons.grid(row=2, column=0, columnspan=10, sticky='w', pady=(6, 0))
        self.start_button = ttk.Button(buttons, text='开始刷', command=self.start)
        self.start_button.pack(side='left')
        self.stop_button = ttk.Button(buttons, text='停止', command=self.stop, state='disabled')
        self.stop_button.pack(side='left', padx=6)
        ttk.Button(buttons, text='随机种子', command=lambda: self.seed.set(str(random.randrange(1 << 31)))).pack(side='left')
        self.worker_status = ttk.Label(conf, text='', justify='left', foreground='#555')
        self.worker_status.grid(row=3, column=0, columnspan=10, sticky='w')

        top = ttk.Frame(right)
        top.pack(fill='x', pady=(8, 0))
        ttk.Button(top, text='打开记录…', command=self.open_records).pack(side='left')
        ttk.Button(top, text='清空列表', command=self.clear).pack(side='left', padx=6)
        self.summary = ttk.Label(top, text='', justify='left')
        self.summary.pack(side='left', padx=12, fill='x', expand=True)

        columns = ('index', 'seed', 'l1', 'l2', 'l3', 'l4', 'l5', 'duration', 'winner', 'status')
        heads = ('局', '种子', '第1路', '第2路', '第3路', '第4路', '第5路', '对局时长', '胜者', '状态')
        table = ttk.Frame(right)
        table.pack(fill='both', expand=True, pady=6)
        self.tree = ttk.Treeview(table, columns=columns, show='headings', selectmode='browse')
        for c, h in zip(columns, heads):
            self.tree.heading(c, text=h, command=lambda c=c: self.sort(c))
            self.tree.column(c, width=70 if c.startswith('l') or c in ('index', 'winner') else 100,
                             anchor='center')
        self.tree.column('status', width=150)
        scroll = ttk.Scrollbar(table, command=self.tree.yview)
        self.tree.configure(yscrollcommand=scroll.set)
        self.tree.pack(side='left', fill='both', expand=True)
        scroll.pack(side='left', fill='y')
        self.tree.tag_configure('invalid', foreground='#999')
        self.tree.tag_configure('best', background='#e8f4e8')
        self.tree.bind('<<TreeviewSelect>>', lambda _: self._selection_changed())

        export = ttk.LabelFrame(right, text='导出所选对局为视频', padding=6)
        export.pack(fill='x')
        self.scene = tk.StringVar(value=scene_names()[0])
        self.to_last = tk.BooleanVar(value=False)
        self.tail = tk.StringVar(value='3')
        self.sound_plant = tk.BooleanVar(value=True)
        self.sound_mower = tk.BooleanVar(value=False)
        self.sound_zombie = tk.BooleanVar(value=False)
        ttk.Label(export, text='场景').grid(row=0, column=0, sticky='w')
        scene = ttk.Combobox(export, textvariable=self.scene, values=scene_names(), state='readonly', width=14)
        scene.grid(row=0, column=1, sticky='w', padx=(4, 12))
        self.scene.trace_add('write', lambda *_: self.schedule_preview())
        ttk.Checkbutton(export, text='第二名失败后继续，直到第一名也失败', variable=self.to_last).grid(
            row=0, column=2, sticky='w')
        ttk.Label(export, text='  结尾保留(秒)').grid(row=0, column=3, sticky='w')
        ttk.Spinbox(export, textvariable=self.tail, from_=0, to=60, width=4).grid(row=0, column=4, sticky='w')
        self.export_button = ttk.Button(export, text='导出视频…', command=self.export, state='disabled')
        self.export_button.grid(row=0, column=5, padx=12)
        self.cancel_button = ttk.Button(export, text='取消导出', command=self.cancel_export, state='disabled')
        self.cancel_button.grid(row=0, column=6)
        sounds = ttk.Frame(export)
        sounds.grid(row=1, column=0, columnspan=7, sticky='w', pady=(4, 0))
        ttk.Label(sounds, text='音效（不含背景音乐）').pack(side='left')
        for text, var in (('植物', self.sound_plant), ('推车', self.sound_mower), ('僵尸/提示音', self.sound_zombie)):
            ttk.Checkbutton(sounds, text=text, variable=var).pack(side='left', padx=(8, 0))
        self.progress = ttk.Progressbar(export, maximum=1000)
        self.progress.grid(row=2, column=0, columnspan=7, sticky='ew', pady=(6, 0))
        export.columnconfigure(2, weight=1)
        ttk.Label(export, text='场景只改变画面背景；导出时逐检查点比对保存的状态摘要，分叉即中止。',
                  foreground='#666').grid(row=3, column=0, columnspan=7, sticky='w')

        self.log = tk.Text(right, height=7, state='disabled', foreground='#333')
        self.log.pack(fill='x')

    def show_codes(self):
        window = tk.Toplevel(self.root)
        window.title('植物简称表')
        text = tk.Text(window, width=46, height=24)
        text.pack(fill='both', expand=True)
        text.insert('end', '每格一个字；字后可接数字作为该株初始经验，例如「机3000」。\n'
                           '行之间换行或用 / 分隔；空位写「空」。\n\n')
        for code, entry in codes.plants().items():
            text.insert('end', f'{code}  {entry["id"]:>3}  {entry["name"]}\n')
        text.configure(state='disabled')

    # ------------------------------------------------------------ settings
    def _load_settings(self):
        try:
            data = json.loads(SETTINGS.read_text(encoding='utf-8'))
        except (OSError, ValueError):
            return
        if data.get('formation'):
            self.text.delete('1.0', 'end')
            self.text.insert('1.0', data['formation'])
        for name in ('mode', 'workers', 'speed', 'scene', 'easter', 'elite', 'elite_marker', 'giant', 'count'):
            if name in data:
                getattr(self, name).set(data[name])
        for name in ('reuse', 'to_last', 'sound_plant', 'sound_mower', 'sound_zombie'):
            if name in data:
                getattr(self, name).set(bool(data[name]))

    def _save_settings(self):
        data = {name: getattr(self, name).get() for name in
                ('mode', 'workers', 'speed', 'scene', 'easter', 'elite', 'elite_marker', 'giant', 'count',
                 'reuse', 'to_last', 'sound_plant', 'sound_mower', 'sound_zombie')}
        data['formation'] = self.text.get('1.0', 'end').strip()
        try:
            SETTINGS.parent.mkdir(parents=True, exist_ok=True)
            SETTINGS.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
        except OSError:
            pass

    # -------------------------------------------------------------- config
    def config_data(self):
        formation = codes.parse(self.text.get('1.0', 'end'))
        seed = int(self.seed.get())
        if not 0 <= seed <= 0xffffffff:
            raise ValueError('种子须在 0..4294967295')
        return {'version': 's6-bug', 'formation': formation, 'mode': int(self.mode.get().split()[0]),
                'seed': seed, 'speed_mode': self.speed.get(), 'max_frames': 3000000,
                'easter': self.easter.get(), 'elite': self.elite.get(),
                'elite_marker': int(self.elite_marker.get()), 'giant': int(self.giant.get())}

    # ------------------------------------------------------------- preview
    def _text_changed(self, _):
        if self.text.edit_modified():
            self.text.edit_modified(False)
            self.schedule_preview()

    def schedule_preview(self):
        if self.preview_after:
            self.root.after_cancel(self.preview_after)
        self.preview_after = self.root.after(500, self.request_preview)

    def draw_grid(self, formation):
        c = self.canvas
        c.delete('all')
        w, h = int(c['width']), int(c['height'])
        cw, ch = (w-40)/5, h/5
        for r, row in enumerate(formation):
            for col, cell in enumerate(row):
                x, y = 40+col*cw, r*ch
                c.create_rectangle(x+2, y+2, x+cw-2, y+ch-2, outline='#5a7a5a',
                                   fill='#3d5a3d' if (r+col) % 2 else '#456545')
                if cell is None:
                    continue
                p = cell if isinstance(cell, dict) else {'id': cell, 'xp': 0}
                entry = codes.by_id().get(p['id'], {'code': '?', 'name': str(p['id'])})
                c.create_text(x+cw/2, y+ch/2-8, text=entry['code'], fill='white', font=self.big)
                c.create_text(x+cw/2, y+ch/2+18, text=entry['name'][:6]+(f' {p["xp"]}' if p.get('xp') else ''),
                              fill='#ddd')

    def request_preview(self):
        self.preview_after = None
        try:
            data = self.config_data()
        except ValueError as exc:
            self.parse_status.configure(text=str(exc))
            return
        self.parse_status.configure(text='')
        self.draw_grid(data['formation'])
        if self.preview is False:
            return
        if self.preview is None:
            from .preview import PreviewService
            self.preview = PreviewService(lambda *a: self.events.put(('preview',)+a))
            self.preview_status.configure(text='载入植物图片…')
        self.preview_key += 1
        self.preview.submit(self.preview_key, data, self.scene.get())

    def show_preview(self, key, image, error):
        if key is None:
            self.preview_status.configure(text=error or '')
            if error and error.startswith('预览不可用'):
                self.preview = False
            return
        if key != self.preview_key:
            return
        if error:
            self.preview_status.configure(text=error)
        elif image is None:
            self.preview_status.configure(text='绘制中…')
        else:
            self.preview_image = photo(image, PREVIEW_WIDTH)
            self.canvas.delete('all')
            self.canvas.create_image(0, 0, image=self.preview_image, anchor='nw')
            self.preview_status.configure(text=f'模式 {self.mode.get()} · {self.scene.get()}')

    # --------------------------------------------------------------- batch
    def start(self):
        try:
            data = self.config_data()
            workers = max(1, int(self.workers.get()))
            count = max(0, int(self.count.get()))
        except ValueError as exc:
            messagebox.showerror('设置有误', str(exc))
            return
        if count:
            workers = min(workers, count)
        self._save_settings()
        self.brusher = Brusher(data, workers, count, self.reuse.get(), lambda *a: self.events.put(a))
        self.worker_lines = {}
        self.brusher.start()
        self.start_button.configure(state='disabled')
        self.stop_button.configure(state='normal')

    def stop(self):
        if self.brusher:
            self.brusher.stop()
            self.write_log('停止中：正在进行的对局将被放弃…')
            self.stop_button.configure(state='disabled')

    def add_record(self, path, record):
        trial = record['trials'][0]
        s = record.get('gui', {}).get('summary') or summarize(trial)
        index = record.get('gui', {}).get('index') or record.get('source_match_index') or Path(path).stem
        status = {'all_mowers_triggered': '完成', 'native_error': '原生异常（无效）',
                  'frame_limit': '达到帧数上限'}.get(trial['status'], trial['status'])
        values = (index, trial['seed'], *[clock(t) for t in s['lanes']], clock(s['duration']),
                  '、'.join(map(str, s['winners'])) or '—', status)
        iid = str(Path(path).resolve())
        if iid in self.records:
            self.tree.item(iid, values=values)
        else:
            self.tree.insert('', 'end', iid=iid, values=values, tags=() if s['valid'] else ('invalid',))
        self.records[iid] = (Path(path), record, s)
        self.update_summary()

    def update_summary(self):
        valid = [s for _, _, s in self.records.values() if s['valid']]
        if not valid:
            self.summary.configure(text=f'共 {len(self.records)} 局')
            return
        wins = [sum(lane in s['winners'] for s in valid) for lane in range(1, 6)]
        means = [statistics.mean(s['lanes'][lane] for s in valid) for lane in range(5)]
        self.summary.configure(text=(
            f'共 {len(self.records)} 局，有效 {len(valid)}，平均对局时长 {clock(statistics.mean(s["duration"] for s in valid))}\n'
            '胜场 ' + '  '.join(f'{i+1}路:{w}' for i, w in enumerate(wins)) +
            '　均时 ' + '  '.join(f'{i+1}路:{clock(m)}' for i, m in enumerate(means))))

    def sort(self, column):
        def key(iid):
            value = self.tree.set(iid, column)
            if ':' in value:
                m, s = value.split(':')
                return (0, int(m)*60+float(s))
            try:
                return (0, float(value))
            except ValueError:
                return (1, value)
        items = sorted(self.tree.get_children(), key=key, reverse=getattr(self, '_sorted', None) == column)
        self._sorted = None if getattr(self, '_sorted', None) == column else column
        for i, iid in enumerate(items):
            self.tree.move(iid, '', i)

    def clear(self):
        self.tree.delete(*self.tree.get_children())
        self.records.clear()
        self.update_summary()
        self._selection_changed()

    def open_records(self):
        paths = filedialog.askopenfilenames(title='选择对局记录（GUI 记录或 replay.json）',
                                            initialdir=ROOT/'artifacts', filetypes=[('JSON', '*.json')])
        for path in paths:
            try:
                record = load_record(path)
            except (OSError, ValueError, KeyError) as exc:
                self.write_log(f'{path}: {exc}')
                continue
            if len(record['trials']) == 1:
                self.add_record(path, record)
            else:
                self.write_log(f'{path}: 含 {len(record["trials"])} 局的汇总文件，请打开 matches/ 下的单局文件')

    # -------------------------------------------------------------- export
    def _selection_changed(self):
        selected = self.tree.selection()
        ok = bool(selected) and self.records[selected[0]][2]['valid'] and not self.export_running()
        self.export_button.configure(state='normal' if ok else 'disabled')

    def export_running(self):
        return self.export_thread is not None and self.export_thread.is_alive()

    def export(self):
        selected = self.tree.selection()
        if not selected:
            return
        path, record, _ = self.records[selected[0]]
        trial = record['trials'][0]
        suffix = 'to-last' if self.to_last.get() else 'runner-up'
        output = filedialog.asksaveasfilename(
            title='保存视频', defaultextension='.mp4', initialdir=ROOT/'artifacts',
            initialfile=f'seed-{trial["seed"]}-{suffix}.mp4', filetypes=[('MP4', '*.mp4')])
        if not output:
            return
        try:
            tail = float(self.tail.get())
        except ValueError:
            tail = 3.0
        self._save_settings()
        self.export_cancel = threading.Event()
        put = self.events.put
        sounds = tuple(name for name, var in (('plant', self.sound_plant), ('mower', self.sound_mower),
                                              ('zombie', self.sound_zombie)) if var.get())
        options = dict(scene=self.scene.get(), to_last=self.to_last.get(), tail_seconds=tail, sounds=sounds,
                       progress=lambda f, t: put(('export-progress', f, t)),
                       log=lambda text: put(('log', text)), cancel=self.export_cancel)

        def run():
            from .render import Cancelled, export
            try:
                export(record, output, **options)
                put(('export-done', output, None))
            except Cancelled:
                put(('export-done', None, '已取消导出'))
            except Exception as exc:
                put(('export-done', None, f'{type(exc).__name__}: {exc}'))
        self.write_log(f'导出种子 {trial["seed"]} → {output}')
        self.export_thread = threading.Thread(target=run, daemon=True)
        self.export_thread.start()
        self.export_button.configure(state='disabled')
        self.cancel_button.configure(state='normal')
        self.progress['value'] = 0

    def cancel_export(self):
        if self.export_cancel:
            self.export_cancel.set()

    # -------------------------------------------------------------- events
    def write_log(self, text):
        self.log.configure(state='normal')
        self.log.insert('end', text+'\n')
        self.log.see('end')
        self.log.configure(state='disabled')

    def _poll(self):
        try:
            while True:
                event = self.events.get_nowait()
                kind = event[0]
                if kind == 'preview':
                    self.show_preview(*event[1:])
                elif kind == 'result':
                    self.add_record(*event[1:])
                elif kind == 'log':
                    self.write_log(event[1])
                elif kind == 'error':
                    self.write_log('错误：'+event[1])
                    messagebox.showerror('刷阵出错', event[1])
                elif kind == 'worker':
                    self.worker_lines[event[1]] = event[2]
                    self.worker_status.configure(text='　'.join(
                        f'线程{w+1}: {t}' for w, t in sorted(self.worker_lines.items())))
                elif kind == 'done':
                    self.write_log(f'刷阵结束，用时 {event[1]:.0f} 秒')
                    self.start_button.configure(state='normal')
                    self.stop_button.configure(state='disabled')
                    self.worker_status.configure(text='')
                elif kind == 'export-progress':
                    self.progress['value'] = min(1000, 1000*event[1]/max(1, event[2]))
                elif kind == 'export-done':
                    output, error = event[1:]
                    self.cancel_button.configure(state='disabled')
                    if error:
                        self.write_log('导出失败：'+error)
                        if error != '已取消导出':
                            messagebox.showerror('导出失败', error)
                    else:
                        self.progress['value'] = 1000
                        if messagebox.askyesno('导出完成', f'{output}\n\n打开所在文件夹？'):
                            self.open_folder(Path(output).parent)
                    self._selection_changed()
        except queue.Empty:
            pass
        self.root.after(100, self._poll)

    @staticmethod
    def open_folder(path):
        import subprocess
        if WINDOWS:
            os.startfile(path)
        else:
            subprocess.Popen(['xdg-open', str(path)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def close(self):
        self._save_settings()
        if self.brusher and self.brusher.running():
            if not messagebox.askokcancel('退出', '正在刷阵，退出会放弃进行中的对局（已完成的已保存）。'):
                return
            self.brusher.stop()
        if self.export_cancel:
            self.export_cancel.set()
        self.root.withdraw()
        if self.preview:
            self.preview.close()
        if self.brusher:
            self.brusher.thread.join(30)
        if self.export_thread:
            self.export_thread.join(30)
        self.root.destroy()


def main():
    root = tk.Tk()
    App(root)
    root.mainloop()
