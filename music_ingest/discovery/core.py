"""Provider-independent ranking, conservative matching and SQLite history."""
from contextlib import closing
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import sqlite3
from typing import Iterable, Protocol

from .. import identity, library
from ..history import import_lock

APPLICATION_ID = 0x484D4431  # HMD1; refuse to mutate an unrelated database.


class ProviderError(RuntimeError):
    """Only static, credential-free diagnostic messages may be passed here."""


@dataclass(frozen=True)
class Candidate:
    provider: str
    artist: str
    title: str
    score: float
    reason: str
    album: str | None = None
    recording_mbid: str | None = None
    isrc: str | None = None
    duration: float | None = None


class Provider(Protocol):
    name: str

    def candidates(self) -> Iterable[Candidate]: ...


def clean(candidate: Candidate) -> Candidate:
    values = asdict(candidate)
    for field in ('artist', 'title', 'provider', 'reason'):
        value = values[field]
        if not isinstance(value, str) or not value.strip() or len(value) > 2000:
            raise ValueError(f'Invalid candidate {field}')
        values[field] = value.strip()
    score = float(candidate.score)
    if not math.isfinite(score) or not 0 <= score <= 1:
        raise ValueError('Provider score must be between zero and one')
    values['score'] = score
    values['recording_mbid'] = identity.mbid(candidate.recording_mbid)
    values['isrc'] = identity.isrc(candidate.isrc)
    if candidate.duration is not None:
        duration = float(candidate.duration)
        if not math.isfinite(duration) or duration <= 0:
            raise ValueError('Invalid duration')
        values['duration'] = duration
    return Candidate(**values)


def same_recording(a: Candidate, b: Candidate) -> bool:
    for field in ('recording_mbid', 'isrc'):
        left, right = getattr(a, field), getattr(b, field)
        if left and right and left != right:
            return False
    if a.duration and b.duration and abs(a.duration - b.duration) > 4:
        return False
    if (a.recording_mbid and a.recording_mbid == b.recording_mbid) or (a.isrc and a.isrc == b.isrc):
        return True
    return (library.normalize_text(a.artist), library.normalize_text(a.title)) == (
        library.normalize_text(b.artist), library.normalize_text(b.title))


def collect(providers: list[Provider], index: dict, *, weights: dict | None = None,
            blocked_artists: list[str] = (), blocked_tracks: list[str] = (),
            limit: int = 25) -> dict:
    if not 1 <= limit <= 100:
        raise ValueError('limit must be between 1 and 100')
    weights = weights or {}
    if any(not math.isfinite(float(v)) or float(v) < 0 for v in weights.values()):
        raise ValueError('Weights must be finite and nonnegative')
    artists = {library.normalize_text(x) for x in blocked_artists}
    tracks = {library.normalize_text(x) for x in blocked_tracks}
    raw, errors, outcomes = [], [], {}
    for provider in providers:
        count = 0
        try:
            for candidate in provider.candidates():
                if count >= 1000:
                    raise ValueError('Provider candidate limit exceeded')
                count += 1
                candidate = clean(candidate)
                if candidate.provider != provider.name:
                    raise ValueError('Provider identity mismatch')
                if library.normalize_text(candidate.artist) in artists or library.normalize_text(
                    f'{candidate.artist} - {candidate.title}') in tracks:
                    continue
                raw.append(candidate)
            outcomes[provider.name] = 'ok' if count else 'empty'
        except Exception as exc:
            # Exception text may contain a URL/API credential. Never persist it.
            error = {'provider': provider.name, 'error': type(exc).__name__}
            if isinstance(exc, ProviderError):
                error['detail'] = str(exc)
            errors.append(error)
            outcomes[provider.name] = 'partial' if count else 'failed'
    groups = []
    # Stable ordering, prefer strong identifiers over text-only candidates.
    for candidate in sorted(raw, key=lambda c: (not bool(c.recording_mbid), not bool(c.isrc),
                                                c.artist.casefold(), c.title.casefold(), c.provider)):
        matches = [group for group in groups if all(same_recording(candidate, x) for x in group)]
        # Ambiguous text-only candidates must not bridge different recording IDs.
        if len(matches) == 1:
            matches[0].append(candidate)
        else:
            groups.append([candidate])
    results = []
    for group in groups:
        first = group[0]
        terms = {}
        for candidate in group:
            value = candidate.score * float(weights.get(candidate.provider, 1))
            terms[candidate.provider] = max(terms.get(candidate.provider, 0), value)
        duration = next((c.duration for c in group if c.duration), None)
        recording_mbid = next((c.recording_mbid for c in group if c.recording_mbid), None)
        isrc = next((c.isrc for c in group if c.isrc), None)
        match = library.find_existing_track(dict(title=first.title, artists=[{'name': first.artist}],
                                                duration_seconds=duration,
                                                recording_mbid=recording_mbid, isrc=isrc), index)
        key = recording_mbid or isrc or json.dumps([
            library.normalize_text(first.artist), library.normalize_text(first.title)])
        results.append(dict(key=hashlib.sha256(key.encode()).hexdigest(), artist=first.artist,
                            title=first.title, album=first.album, recording_mbid=recording_mbid,
                            isrc=isrc, duration=duration, score=round(sum(terms.values()), 6),
                            score_terms=terms, provenance=[asdict(c) for c in group],
                            status='available' if match else 'unavailable',
                            local_path=str(match['path']) if match else None))
    unique = {}
    for result in results:
        previous = unique.get(result['key'])
        if previous:
            # Contradictory durations or identifiers under one identity must not
            # become a false playable match or overwrite each other silently.
            previous.update(status='ambiguous', local_path=None)
            previous['provenance'].extend(result['provenance'])
            previous['score'] = max(previous['score'], result['score'])
        else:
            unique[result['key']] = result
    results = list(unique.values())
    results.sort(key=lambda c: (-c['score'], c['key']))
    return dict(candidates=results[:limit], errors=errors, providers=outcomes,
                generated_at=datetime.now(timezone.utc).isoformat(), acquisition_enabled=False)


def save(path: Path, report: dict) -> None:
    with import_lock(path), closing(sqlite3.connect(path)) as db:
        tables = db.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        if tables and db.execute('PRAGMA application_id').fetchone()[0] != APPLICATION_ID:
            raise ValueError('Refusing to write an unrelated database')
        db.execute(f'PRAGMA application_id={APPLICATION_ID}')
        db.executescript('''
            CREATE TABLE IF NOT EXISTS candidates (
                key TEXT PRIMARY KEY, payload TEXT NOT NULL,
                first_seen TEXT NOT NULL, last_seen TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS runs (
                id INTEGER PRIMARY KEY, created_at TEXT NOT NULL, report TEXT NOT NULL);
        ''')
        now = report['generated_at']
        with db:
            for candidate in report['candidates']:
                db.execute('''INSERT INTO candidates VALUES (?, ?, ?, ?)
                              ON CONFLICT(key) DO UPDATE SET payload=excluded.payload,
                              last_seen=excluded.last_seen''',
                           (candidate['key'], json.dumps(candidate), now, now))
            db.execute('INSERT INTO runs(created_at,report) VALUES (?,?)', (now, json.dumps(report)))


def latest(path: Path) -> dict:
    if not path.is_file():
        return dict(candidates=[], errors=[], providers={}, acquisition_enabled=False)
    with closing(sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True)) as db:
        if db.execute('PRAGMA application_id').fetchone()[0] != APPLICATION_ID:
            raise ValueError('Not a Discovery database')
        row = db.execute('SELECT report FROM runs ORDER BY id DESC LIMIT 1').fetchone()
    report = json.loads(row[0]) if row else dict(candidates=[])
    # Availability is checked again; reports must not keep deleted files playable.
    for candidate in report['candidates']:
        if candidate['local_path'] and not Path(candidate['local_path']).is_file():
            candidate.update(status='unavailable', local_path=None)
    return report
