"""Minimal pool references; only the selected entry can authorize original IO."""
from dataclasses import dataclass
import json
import re

from .outlet import OutletError


class _Pairs(list):
    pass


@dataclass(frozen=True)
class OriginalSources:
    entries: tuple


def original_sources(text):
    try:
        size=len(text.encode('utf-8')) if isinstance(text,str) else 2*1024*1024+1
    except UnicodeError:
        raise OutletError('原素材目录JSON编码无效') from None
    if size>2*1024*1024:
        raise OutletError('原素材目录JSON必须在2 MiB运输安全预算内')
    try:
        # Keep duplicate fields until the pool/selected entry is examined. Task
        # constants and duplicate keys are irrelevant to original file selection.
        root=json.loads(text,object_pairs_hook=_Pairs,parse_constant=lambda value:None)
        pending=[(root,0)]
        while pending:
            value,depth=pending.pop()
            if depth>32:raise ValueError('depth')
            if isinstance(value,_Pairs):pending.extend((v,depth+1) for _,v in value)
            elif isinstance(value,list):pending.extend((v,depth+1) for v in value)
    except (ValueError,TypeError,RecursionError):
        raise OutletError('原素材目录JSON语法或32层运输安全深度无效') from None
    if not isinstance(root,_Pairs):raise OutletError('原素材目录需要工程JSON对象中的素材池')
    pools=[value for key,value in root if key=='assets']
    if len(pools)!=1:raise OutletError('原素材池缺失或assets字段重复，来源有歧义')
    pool=pools[0]
    if not isinstance(pool,list) or isinstance(pool,_Pairs) or len(pool)>128:
        raise OutletError('原素材池必须是最多128项的数组')
    return OriginalSources(tuple(tuple((k,v) for k,v in row if k in ('asset_id','kind','source_handle')) if isinstance(row,_Pairs) else () for row in pool))


def selected_source(sources,asset_id,kind):
    if not isinstance(sources,OriginalSources):raise OutletError('原素材来源线缺失或数据无效，请连接素材台的原素材来源口')
    if not isinstance(asset_id,str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,96}',asset_id):
        raise OutletError('原素材稳定资产ID无效')
    matches=[row for row in sources.entries if any(k=='asset_id' and v==asset_id for k,v in row)]
    if len(matches)!=1:raise OutletError('绑定原素材已从来源池移除或资产ID重复，不能确定来源')
    values={}
    for key in ('asset_id','kind','source_handle'):
        fields=[v for k,v in matches[0] if k==key]
        if len(fields)!=1 or not isinstance(fields[0],str):raise OutletError('绑定原素材引用字段无效或重复')
        values[key]=fields[0]
    if values['kind']!=kind:raise OutletError('绑定素材种类不匹配，请连接对应原素材出口')
    return values['source_handle']
