import csv,json,subprocess,sys,tempfile,unittest
from pathlib import Path
from tools.match_records import winner,write_documents


class MatchRecordPolicyTests(unittest.TestCase):
    def test_last_lane_wins_with_ties_and_invalid_game_has_no_winner(self):
        trial={'mower_frames':[100,300,300,90,200],'valid_for_statistics':True}
        self.assertEqual(winner(trial),[2,3])
        trial['valid_for_statistics']=False
        self.assertEqual(winner(trial),[])

    def test_native_failure_invalidates_every_reported_lane_even_if_raw_times_exist(self):
        result={'config':{'seed':17,'repetitions':1},'trials':[
            {'seed':17,'mower_frames':[100,200,300,400,None],'valid_for_statistics':False,
             'status':'native_error','initial_conditions_file':'initial.json','replay_file':'replay.json'}]}
        with tempfile.TemporaryDirectory() as temporary:
            write_documents(temporary,result)
            root=Path(temporary)
            with (root/'matches.csv').open(encoding='utf-8-sig',newline='') as f:
                rows=list(csv.reader(f))
            self.assertEqual(rows[1][3:8],['']*5)
            self.assertEqual(rows[1][8],'无效')
            self.assertEqual((root/'matches.md').read_text().count('| 无效'),6)
            self.assertEqual(result['trials'][0]['mower_frames'],[100,200,300,400,None])

    def test_statistics_excludes_all_five_lanes_of_a_failed_match(self):
        data={'config':{'seed':17,'repetitions':2},'manifest':{},'trials':[
            {'seed':17,'frames':500,'mower_frames':[100,200,300,400,500],
             'status':'native_error','valid_for_statistics':False},
            {'seed':18,'frames':1000,'mower_frames':[600,700,800,900,1000],
             'status':'all_mowers_triggered','valid_for_statistics':True}]}
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);source=root/'results.json';source.write_text(json.dumps(data))
            subprocess.run([sys.executable,str(Path(__file__).resolve().parents[1]/'tools/lane_statistics.py'),
                            str(source),'--lanes','1','2','3','4','5','--allow-censored'],
                           check=True,stdout=subprocess.DEVNULL)
            summary=json.loads((root/'statistics.json').read_text())
            self.assertEqual(summary['overall']['count'],5)
            self.assertEqual(summary['overall']['mean_seconds'],8)
            self.assertEqual(summary['unobserved_lane_samples'],5)
            self.assertEqual(summary['invalid_matches'],1)


if __name__=='__main__':unittest.main()
