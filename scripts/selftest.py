"""Isolated tests: no network, no app writes, no personal materials."""
import json
import tempfile
from pathlib import Path
from library import init, ingest, index, sync, verify, write, lock


def run():
    with tempfile.TemporaryDirectory() as temp:
        p = Path(temp)
        root = p / '库'
        cfg = p / 'config.json'
        write(cfg, {'version': 1, 'sources': [], 'destinations': {'eagle': {'enabled': True}}})
        init(root, cfg)
        try:
            init(root, cfg)
            assert False, 'existing root overwritten'
        except ValueError:
            pass
        a = p / 'a.txt'
        a.write_text('test material', encoding='utf-8')
        record = p / 'record.json'
        r = {'title': '测试', 'source_url': 'https://example.org/a#top', 'files': [str(a)]}
        write(record, r)
        first = ingest(root, record)
        ident = first['id']
        assert first['changed']
        assert not ingest(root, record)['changed']
        assert len(index(root)) == 1
        note = root / 'items' / (ident + '.md')
        note.write_text(note.read_text() + '\n人工笔记保留\n')
        proof = p / 'proof.json'
        write(proof, {'remote_refs': ['test-id'], 'readback_at': 'test', 'asset_sha256': []})
        try:
            sync(root, ident, 'eagle', 'verified', proof)
            assert False, 'missing coverage accepted'
        except ValueError:
            pass
        write(proof, {'remote_refs': ['test-id'], 'readback_at': 'test', 'asset_sha256': [index(root)[0]['assets'][0]['sha256']]})
        sync(root, ident, 'eagle', 'verified', proof)
        assert index(root)[0]['sync']['eagle']['status'] == 'verified'
        b = p / 'b.txt'
        b.write_text('second material')
        r['files'].append(str(b))
        write(record, r)
        ingest(root, record)
        assert index(root)[0]['sync']['eagle']['status'] == 'pending'
        assert '人工笔记保留' in note.read_text()
        assert len(index(root)[0]['assets']) == 2
        r['source_url'] = 'https://example.org/b'
        write(record, r)
        ingest(root, record)
        assert len(index(root)) == 2
        assert len(list((root / 'attachments').iterdir())) == 2
        assert verify(root)['ok']
        with lock(root):
            try:
                ingest(root, record)
                assert False, 'concurrent writer accepted'
            except FileExistsError:
                pass
        note.unlink()
        assert not verify(root)['ok']
        ingest(root, p / 'record.json')
        # Re-ingest the missing note's source to recover its note.
        r['source_url'] = 'https://example.org/a'
        write(record, r)
        ingest(root, record)
        assert verify(root)['ok']
        (root / index(root)[0]['assets'][0]['path']).write_text('corrupt')
        assert not verify(root)['ok']
    print('PASS: init protection, URL dedup, hash reuse, append, manual notes, sync coverage/invalidation, lock, recovery, corruption detection')


if __name__ == '__main__':
    run()
