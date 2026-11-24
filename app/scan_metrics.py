"""Scan history and latency read from PostgreSQL instead of process memory.

Azure Container Apps can run two replicas. The linked lists of ``ScanPipeline``
live inside one process, so before this module half of the requests saw the
history and latencies of one replica and the other half saw the other one (or
nothing). Persisted analyses are the same for every replica.

A scan with several detections stores one analysis per detection, all with the
same frame hash and duration; they are folded back into one scan here.
"""
import os
import socket
from sqlalchemy import select
from . import schema as s


def percentile(values: list[int], rank: int) -> int | None:
    """Nearest-rank percentile, the same rule used by ScanPipeline.stats."""
    if not values:
        return None
    ordered = sorted(values)
    return ordered[max(0, (rank * len(ordered) + 99) // 100 - 1)]


def instance_id() -> str:
    """Name of this replica: Azure sets CONTAINER_APP_REPLICA_NAME; locally the host name."""
    return os.environ.get('CONTAINER_APP_REPLICA_NAME') or os.environ.get('HOSTNAME') or socket.gethostname()


class ScanMetrics:
    WINDOW = 100

    def __init__(self, engine):
        self.engine = engine

    def _rows(self, limit: int, session_id: str | None = None):
        query = (select(s.analyses.c.id, s.analyses.c.created_at, s.analyses.c.duration_ms, s.analyses.c.result,
                        s.frames.c.sha256, s.frames.c.scan_session_id, s.ai_models.c.provider, s.reports.c.id.label('report_id'))
                 .select_from(s.analyses.join(s.frames, s.analyses.c.frame_id == s.frames.c.id)
                              .join(s.scan_sessions, s.frames.c.scan_session_id == s.scan_sessions.c.id)
                              .join(s.ai_models, s.analyses.c.model_id == s.ai_models.c.id)
                              .outerjoin(s.detections, s.detections.c.analysis_id == s.analyses.c.id)
                              .outerjoin(s.reports, s.reports.c.detection_id == s.detections.c.id))
                 .order_by(s.analyses.c.created_at.desc(), s.analyses.c.id.desc()).limit(limit))
        if session_id is not None:
            query = query.where(s.scan_sessions.c.session_id == session_id)
        with self.engine.connect() as conn:
            return conn.execute(query).mappings().all()

    def scans(self, limit: int, session_id: str | None = None) -> list[dict]:
        """Most recent scans first; detections saved by the same scan become one entry.

        Rows of one scan share frame hash and duration and are written a few
        milliseconds apart, after the analysis finished. A second scan of the same
        frame needs another full analysis first, so a gap of at least half the
        duration means a new scan even when the duration is identical.
        """
        # Up to 20 detections per frame are stored, so read enough rows to fill ``limit`` scans.
        rows = sorted(self._rows(limit * 20, session_id), key=lambda row: (row['created_at'], row['id']))
        scans: list[dict] = []
        open_scans: dict[tuple, dict] = {}
        for row in rows:
            key = (row['scan_session_id'], row['sha256'], row['duration_ms'])
            scan = open_scans.get(key)
            if scan is None or row['created_at'] - scan['lastAt'] > max(1, row['duration_ms'] // 2):
                scan = open_scans[key] = {'analysisId': row['id'], 'provider': row['provider'], 'isPothole': False,
                                          'reportId': None, 'timestamp': row['created_at'], 'durationMs': row['duration_ms']}
                scans.append(scan)
            scan['lastAt'] = row['created_at']
            scan['isPothole'] = scan['isPothole'] or bool((row['result'] or {}).get('isPothole'))
            scan['reportId'] = scan['reportId'] or row['report_id']
        newest = sorted(scans, key=lambda scan: (-scan['timestamp'], scan['analysisId']))[:limit]
        return [{key: value for key, value in scan.items() if key != 'lastAt'} for scan in newest]

    def history(self, session_id: str, newest_first: bool = True) -> list[dict]:
        events = self.scans(self.WINDOW, session_id)
        return events if newest_first else events[::-1]

    def latency(self) -> dict:
        values = [scan['durationMs'] for scan in self.scans(self.WINDOW)]
        return {'samples': len(values), 'p50': percentile(values, 50), 'p95': percentile(values, 95), 'scope': 'all-replicas'}
