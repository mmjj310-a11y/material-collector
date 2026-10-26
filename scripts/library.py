#!/usr/bin/env python3
"""Portable, local material index. Network collection belongs to the host agent."""
import argparse
import hashlib
import json
import os
import shutil
import tempfile
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit


def now():
    return datetime.now(timezone.utc).isoformat()


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix='.pending-')
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            f.write(value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, indent=2) + '\n')
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def url(value):
    p = urlsplit(value)
    if p.scheme not in ('http', 'https') or not p.hostname or p.username or p.password:
        raise ValueError('来源必须是不带账号密码的 http/https URL')
    # Keep query parameters: distinct articles can share the same URL path.
    return urlunsplit((p.scheme.lower(), p.netloc.lower(), p.path or '/', p.query, ''))


def digest(path):
    h = hashlib.sha256()
    with path.open('rb') as f:
        for block in iter(lambda: f.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


@contextmanager
def lock(root):
    p = root / '.collector' / 'write.lock'
    fd = os.open(p, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    try:
        os.write(fd, str(os.getpid()).encode())
        os.close(fd)
        yield
    finally:
        p.unlink()


def index(root):
    return read(root / '.collector' / 'index.json')


def render(root, data):
    lines = ['# 素材知识库', '', '由索引生成；个人笔记请写在其他文件，避免重新生成时覆盖。', '']
    for item in data:
        lines.append(f"- [{item['id']}](items/{item['id']}.md) — {item['title'].replace(chr(10), ' ')}")
    write(root / 'INDEX.md', '\n'.join(lines) + '\n')


def init(root, config):
    cfg = read(config)
    if cfg.get('version') != 1:
        raise ValueError('配置 version 必须为 1')
    for source in cfg.get('sources', []):
        url(source['url'])
    if root.exists():
        raise ValueError('初始化只接受不存在的新目录；已有 Obsidian 库请在其下指定新子目录')
    root.mkdir(parents=True)
    write(root / '.collector' / 'config.json', cfg)
    write(root / '.collector' / 'index.json', [])
    write(root / 'HANDOFF.md', '# 接手说明\n\n先读 .collector/config.json 与 .collector/index.json，再核对当前机器的保存位置和连接能力。\n同步状态以逐条记录为准；pending/failed/unknown 均不代表成功。只补未完成部分。\n新机器不继承旧机器账号权限、绝对路径或定时任务。保留人工笔记，不重建整个库。\n')
    render(root, [])
    return {'root': str(root), 'status': 'initialized'}


def ingest(root, record_path):
    record = read(record_path)
    title = record['title'].strip()
    if not title:
        raise ValueError('标题不能为空')
    source = url(record['source_url'])
    files = []
    for value in record.get('files', []):
        p = Path(value).expanduser().resolve(strict=True)
        if not p.is_file() or p.stat().st_size == 0:
            raise ValueError(f'无效文件: {p}')
        files.append((p, digest(p)))
    with lock(root):
        data = index(root)
        old = next((x for x in data if x['source_url'] == source), None)
        ident = old['id'] if old else 'MC-' + hashlib.sha256(source.encode()).hexdigest()[:16]
        item = old or {'id': ident, 'title': title, 'source_url': source, 'created_at': now(),
                       'tags': record.get('tags', []), 'summary': record.get('summary', ''),
                       'analysis': record.get('analysis', ''), 'author': record.get('author', ''),
                       'published_at': record.get('published_at'), 'assets': [], 'sync': {}}
        changed = old is None
        for p, sha in files:
            if any(a['sha256'] == sha for a in item['assets']):
                continue
            known = next((a for x in data for a in x['assets'] if a['sha256'] == sha), None)
            rel = known['path'] if known else 'attachments/' + sha + p.suffix.lower()
            dest = root / rel
            if dest.exists() and digest(dest) != sha:
                raise ValueError('已有附件校验失败，停止覆盖: ' + rel)
            dest.parent.mkdir(parents=True, exist_ok=True)
            if not dest.exists():
                fd, tmp = tempfile.mkstemp(dir=dest.parent)
                os.close(fd)
                try:
                    shutil.copyfile(p, tmp)
                    if digest(Path(tmp)) != sha:
                        raise ValueError('复制期间文件变化')
                    os.replace(tmp, dest)
                finally:
                    if os.path.exists(tmp): os.unlink(tmp)
            item['assets'].append({'path': rel, 'sha256': sha})
            changed = True
        if not old:
            data.append(item)
        if changed:
            item['updated_at'] = now()
            cfg = read(root / '.collector' / 'config.json')
            for target in ('eagle', 'feishu'):
                if cfg.get('destinations', {}).get(target, {}).get('enabled'):
                    previous = item['sync'].get(target, {})
                    item['sync'][target] = {**previous, 'status': 'pending', 'updated_at': now()}
        # Index is authoritative; notes and INDEX can be rebuilt after an interrupted write.
        write(root / '.collector' / 'index.json', data)
        note = root / 'items' / (ident + '.md')
        if not note.exists():
            body = f"# {title}\n\n来源：<{source}>\n\n作者：{item['author'] or '未知'}\n\n## 摘要\n\n{item['summary']}\n\n## AI 分析（观点）\n\n{item['analysis']}\n\n## 附件\n\n"
            write(note, body)
        body = note.read_text(encoding='utf-8')
        for a in item['assets']:
            link = '../' + a['path']
            if link not in body:
                ext = Path(a['path']).suffix.lower()
                prefix = '!' if ext in ('.png', '.jpg', '.jpeg', '.webp', '.gif') else ''
                body += f"{prefix}[附件]({link})\n\n"
        write(note, body)
        render(root, data)
        return {'id': ident, 'changed': changed, 'asset_count': len(item['assets'])}


def sync(root, ident, target, status, evidence):
    proof = read(evidence)
    with lock(root):
        data = index(root)
        item = next(x for x in data if x['id'] == ident)
        if status == 'verified':
            if not proof.get('remote_refs') or not proof.get('readback_at'):
                raise ValueError('verified 需要真实远端标识与回读时间')
            if sorted(proof.get('asset_sha256', [])) != sorted(a['sha256'] for a in item['assets']):
                raise ValueError('回读证据未覆盖当前全部附件')
        item['sync'][target] = {'status': status, 'evidence': proof, 'updated_at': now()}
        write(root / '.collector' / 'index.json', data)
    return item['sync'][target]


def verify(root):
    data = index(root)
    errors = []
    for x in data:
        if not (root / 'items' / (x['id'] + '.md')).is_file(): errors.append(x['id'] + ': missing note')
        for a in x['assets']:
            p = (root / a['path']).resolve()
            if not p.is_relative_to(root.resolve()):
                errors.append(x['id'] + ': unsafe attachment path')
            elif not p.is_file() or digest(p) != a['sha256']:
                errors.append(x['id'] + ': invalid ' + a['path'])
    return {'items': len(data), 'errors': errors, 'ok': not errors}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('command', choices=['init', 'ingest', 'status', 'verify', 'sync'])
    p.add_argument('--root', required=True, type=Path)
    p.add_argument('--config', type=Path)
    p.add_argument('--record', type=Path)
    p.add_argument('--id')
    p.add_argument('--target', choices=['eagle', 'feishu'])
    p.add_argument('--status', choices=['pending', 'failed', 'unknown', 'verified'])
    p.add_argument('--evidence', type=Path)
    a = p.parse_args()
    try:
        if a.command == 'init': result = init(a.root, a.config)
        elif a.command == 'ingest': result = ingest(a.root, a.record)
        elif a.command == 'verify': result = verify(a.root)
        elif a.command == 'sync': result = sync(a.root, a.id, a.target, a.status, a.evidence)
        else: result = index(a.root)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        if a.command == 'verify' and not result['ok']: raise SystemExit(1)
    except (OSError, ValueError, KeyError, TypeError, StopIteration) as e:
        p.exit(2, f'未完成：{e}\n')


if __name__ == '__main__':
    main()
