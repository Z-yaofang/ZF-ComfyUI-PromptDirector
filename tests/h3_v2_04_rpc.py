"""04 browser extension: actual desk runtime dimensions before node build."""
import copy
import json
from pathlib import Path
import runpy
import sys

B = runpy.run_path(str(Path(__file__).with_name('h3_v2_03_rpc.py')))
G = B['execute'].__globals__


def execute(request):
    if request['action'] == '04_preview_metadata':
        import av
        asset = G['matrix_assets']['video'][0]
        path = G['store'].preview(asset['source_handle'], 'proxy')
        with av.open(str(path)) as container:
            stream = container.streams.video[0]
            proxy = {'container_seconds': float(container.duration / av.time_base), 'stream_seconds': float(stream.duration * stream.time_base), 'frames': stream.frames, 'fps': float(stream.average_rate), 'start_seconds': float((stream.start_time or 0) * stream.time_base)}
        return {'source_probe': asset['probe'], 'proxy_metadata': proxy}
    if request['action'] == '04_project':
        M = G['M']; assets = G['matrix_assets']
        project = M['project'](assets, pictures=0 if request.get('empty') else 2, videos=0 if request.get('empty') else 1, audios=0 if request.get('empty') else 1, start=10)
        project.pop('output_canvas', None)
        for row in project['video_track']+project['audio_track']:
            row.update(source_in_seconds=.5, source_out_seconds=2.5)
        return {'project': M['C'].normalize_project(project), 'state': M['I'].empty_interview()}
    if request['action'] == '04_build':
        M = G['M']; prompt = G['last_value']['prompt']; raw = request['project']
        prepared = M['S']._planning_project(M['C'].normalize_project(raw), prompt, '172')
        desk = prompt['165']['inputs']; canvas = prepared.get('output_canvas')
        width, height = (canvas['width'], canvas['height']) if 'width' in desk or 'height' in desk else (None, None)
        current, _, _ = M['DESK'].ZVUniversalMediaEvidenceDesk().export_project(json.dumps(raw), width, height)
        built = M['V2']['N'].ZVH3InterviewFormV2().build(current, M['I'].dumps(request['state']), prompt=prompt, unique_id='172')
        return {'ready': built[5], 'tuple_count': len(built), 'canvas': current.get('output_canvas'), 'errors': built[6]['errors']}
    return B['execute'](request)


if __name__ == '__main__':
    sys.stdin.reconfigure(encoding='utf-8'); sys.stdout.reconfigure(encoding='utf-8')
    for line in sys.stdin:
        request = json.loads(line)
        try: print(json.dumps({'id': request['id'], 'result': execute(request)}, ensure_ascii=False), flush=True)
        except Exception as error: print(json.dumps({'id': request['id'], 'error': str(error)}, ensure_ascii=False), flush=True)
